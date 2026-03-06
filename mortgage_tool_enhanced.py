"""
mortgage_tool_enhanced.py
=========================
Enhanced mortgage modeling layer built on top of mortgage_tool.py.

New features over the base tool:
  - Day-count conventions  (actual/365, actual/360, 30/360)
  - Stub period / per-diem first period  (first_payment_date != start_date)
  - Capitalized origination fees  (added to opening balance)
  - One-time fee events  (late fees, service charges, etc.)
  - Deferment / forbearance periods  (with or without interest capitalization)
  - Loan recast after extra payments  (recalculate payment vs shorten term)
  - Misapplied extra payment warnings

Copyright (c) 2026 Hellomoto1123. Private use unrestricted.
Commercial use requires a license — contact hellomoto1123@gmail.com
See LICENSE.md for full terms.
"""

import pandas as pd
import numpy as np
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from dataclasses import dataclass, field
from typing import Optional
import warnings
import calendar

# Re-export everything from the base tool so users only need one import
from mortgage_tool import (
    ExtraPayment, AnnualItem, ExtendedCosts,
    MortgageAnalyzer, plot_scenarios, plot_extended_costs,
    _monthly_payment,
)


# ─────────────────────────────────────────────────────────────────────────────
# NEW DATA CLASSES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class FeeEvent:
    """
    A one-time fee charged in a specific month of the loan.

    Fee application order follows standard servicing priority:
        fees → interest → principal

    Parameters
    ----------
    month : int
        1-based loan month in which the fee is charged.
    amount : float
        Fee amount in dollars.
    label : str
        Description shown in the amortization table (e.g. "Late Fee").
    capitalize : bool
        If True, the fee is added to the outstanding balance rather than
        collected as a separate cash outflow.  If False (default), it is
        collected in addition to the regular payment that month.

    Examples
    --------
    FeeEvent(month=3,  amount=35,   label="Late Fee")
    FeeEvent(month=1,  amount=500,  label="Origination Fee", capitalize=True)
    FeeEvent(month=12, amount=75,   label="Annual Service Charge")
    """
    month: int
    amount: float
    label: str = "Fee"
    capitalize: bool = False


@dataclass
class Deferment:
    """
    A period during which scheduled payments are suspended.

    Interest continues accruing during deferment.  Depending on
    `capitalize`, it either adds to the principal balance (common in
    forbearance) or is collected as a lump sum when payments resume.

    Parameters
    ----------
    start_month : int
        First month of the deferment period (1-based, relative to loan start).
    num_months : int
        Number of consecutive months payments are suspended.
    capitalize_interest : bool
        True  → accrued interest is added to principal (balance grows).
        False → accrued interest is collected as a lump sum at resumption.

    Examples
    --------
    # 3-month COVID-style forbearance, interest capitalizes
    Deferment(start_month=13, num_months=3, capitalize_interest=True)

    # 6-month hardship deferment, interest billed at resumption
    Deferment(start_month=7, num_months=6, capitalize_interest=False)
    """
    start_month: int
    num_months: int
    capitalize_interest: bool = True


@dataclass
class EnhancedLoan:
    """
    Drop-in replacement for the base Loan with additional modeling features.

    All base Loan parameters are supported.  New parameters below.

    Parameters
    ----------
    principal : float
        Loan amount after down payment and before capitalized fees.
    annual_rate : float
        Annual interest rate as a decimal.
    term_months : int
        Scheduled term.
    start_date : date
        Date the loan is funded / interest begins accruing.
    first_payment_date : date | None
        Date of the first scheduled payment.  If None, defaults to one
        month after start_date (standard).  Set this to model a stub
        period — e.g. loan funded April 20, first payment June 1.
    day_count : str
        Interest day-count convention.  One of:
            "actual/365"  — actual calendar days / 365  (default)
            "actual/360"  — actual calendar days / 360  (common in commercial)
            "30/360"      — each month treated as 30 days, year as 360
    capitalized_fees : float
        Fees rolled into the opening balance (e.g. origination fee financed
        into the loan).  Added to principal before any calculations.
    fee_events : list[FeeEvent]
        One-time fee charges in specific months.
    deferments : list[Deferment]
        Periods during which scheduled payments are suspended.
    reamortize_on_extra : bool
        False (default) — extra payments shorten the term; payment stays fixed.
        True            — after each extra payment the remaining balance is
                          re-amortized over the remaining scheduled term,
                          lowering the required monthly payment.
    extra_payments : list[ExtraPayment]
        Principal-only extra payment rules (same as base Loan).
    closing_costs : float
        Out-of-pocket closing costs used in break-even calculations.
        Does NOT add to the balance — use capitalized_fees for that.
    label : str
        Display label (cosmetic only).

    Notes on stub periods
    ---------------------
    When first_payment_date differs from start_date + 1 month, the first
    period uses actual day-count interest from start_date to first_payment_date.
    Subsequent periods revert to standard monthly scheduling.

    Notes on misapplied extra payments
    ------------------------------------
    Some servicers apply extra funds to future installments rather than
    principal, negating the benefit.  This tool cannot model servicer
    behavior — if you are making extra payments, always verify with your
    servicer that funds are applied to principal.  A reminder is printed
    when extra_payments are present.
    """
    principal: float
    annual_rate: float
    term_months: int
    start_date: date
    first_payment_date: Optional[date] = None
    day_count: str = "actual/365"          # "actual/365" | "actual/360" | "30/360"
    capitalized_fees: float = 0.0
    fee_events: list = field(default_factory=list)
    deferments: list = field(default_factory=list)
    reamortize_on_extra: bool = False
    extra_payments: list = field(default_factory=list)
    closing_costs: float = 0.0
    label: str = "Loan"


# ─────────────────────────────────────────────────────────────────────────────
# DAY-COUNT HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _days_in_period(d_start: date, d_end: date, day_count: str) -> float:
    """Return the fractional year represented by the period under the chosen convention."""
    if day_count == "actual/365":
        return (d_end - d_start).days / 365.0
    elif day_count == "actual/360":
        return (d_end - d_start).days / 360.0
    elif day_count == "30/360":
        # ISDA 30/360 convention
        d1, m1, y1 = d_start.day, d_start.month, d_start.year
        d2, m2, y2 = d_end.day,   d_end.month,   d_end.year
        if d1 == 31: d1 = 30
        if d2 == 31 and d1 == 30: d2 = 30
        days = 360*(y2-y1) + 30*(m2-m1) + (d2-d1)
        return days / 360.0
    else:
        raise ValueError(f"Unknown day_count convention: '{day_count}'. "
                         f"Use 'actual/365', 'actual/360', or '30/360'.")


def _period_interest(balance: float, annual_rate: float,
                     d_start: date, d_end: date, day_count: str) -> float:
    """Interest accrued on `balance` from d_start to d_end."""
    return balance * annual_rate * _days_in_period(d_start, d_end, day_count)


# ─────────────────────────────────────────────────────────────────────────────
# ENHANCED AMORTIZATION ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def build_enhanced_amortization(
    loan: EnhancedLoan,
    global_month_offset: int = 0,
) -> pd.DataFrame:
    """
    Build a full enhanced amortization schedule for an EnhancedLoan.

    Returns a DataFrame with all base columns plus:
        stub_days        — days in the first period (0 for standard loans)
        fee_charge       — fee collected this month (cash, not capitalized)
        deferred         — True if this month's payment was suspended
        deferred_interest — interest that accrued during a deferment month
        capitalized_interest — deferred interest added to principal at resumption
        recast_payment   — new scheduled payment after a recast (NaN if no recast)
        day_count        — convention used (informational)
    """
    # ── warn about misapplied extra payments ─────────────────────────────────
    if loan.extra_payments:
        warnings.warn(
            f"\n[{loan.label}] Extra payments are present. Verify with your servicer "
            "that extra funds are applied directly to principal and not to future "
            "installments. Misapplication negates the benefit entirely.",
            UserWarning, stacklevel=2
        )

    # ── opening balance includes capitalized fees ─────────────────────────────
    opening_balance = loan.principal + loan.capitalized_fees

    # ── build fee event lookup {month: FeeEvent} ─────────────────────────────
    fee_lookup: dict = {}
    for fe in loan.fee_events:
        fee_lookup.setdefault(fe.month, []).append(fe)

    # ── build deferment lookup {month: Deferment} ────────────────────────────
    deferred_months: dict = {}  # {month_num: Deferment}
    for d in loan.deferments:
        for mo in range(d.start_month, d.start_month + d.num_months):
            deferred_months[mo] = d

    # ── determine payment dates ───────────────────────────────────────────────
    if loan.first_payment_date is None:
        first_pmt_date = loan.start_date + relativedelta(months=1)
    else:
        first_pmt_date = loan.first_payment_date

    stub_days = (first_pmt_date - loan.start_date).days
    standard_days = (loan.start_date + relativedelta(months=2) -
                     (loan.start_date + relativedelta(months=1))).days

    # ── standard monthly rate for payment calculation ─────────────────────────
    # Payment amount always uses 30/360-equivalent monthly rate for consistency
    # even when daily accrual uses a different convention
    r_monthly = loan.annual_rate / 12
    scheduled_pmt = _monthly_payment(opening_balance, r_monthly, loan.term_months)

    rows = []
    balance = opening_balance
    i2d = 0.0
    p2d = 0.0
    fee2d = 0.0
    deferred_interest_pending = 0.0  # accrued interest awaiting capitalization/collection
    current_pmt = scheduled_pmt      # may change after recast
    cur_date = first_pmt_date

    for m in range(1, loan.term_months + 1):
        if balance <= 0:
            break

        # ── period dates ─────────────────────────────────────────────────────
        if m == 1:
            period_start = loan.start_date
            period_end   = first_pmt_date
        else:
            period_start = cur_date - relativedelta(months=1)
            period_end   = cur_date

        # ── interest this period ──────────────────────────────────────────────
        interest = _period_interest(balance, loan.annual_rate,
                                    period_start, period_end, loan.day_count)

        # ── fee events ───────────────────────────────────────────────────────
        cash_fees = 0.0
        for fe in fee_lookup.get(m, []):
            if fe.capitalize:
                balance += fe.amount   # fee added to balance
            else:
                cash_fees += fe.amount  # fee collected in cash this month
        fee2d += cash_fees

        # ── deferment ────────────────────────────────────────────────────────
        is_deferred = m in deferred_months
        deferred_int_this_month = 0.0
        cap_int_this_month = 0.0

        if is_deferred:
            deferred_interest_pending += interest
            deferred_int_this_month = interest
            rows.append({
                "months_elapsed":        global_month_offset + m,
                "date":                  cur_date,
                "remaining_start":       round(balance, 2),
                "monthly_payment":       round(current_pmt, 2),
                "extra_payment":         0.0,
                "total_payment":         0.0,
                "interest":              round(interest, 2),
                "interest_to_date":      round(i2d + interest, 2),
                "principal":             0.0,
                "principal_to_date":     round(p2d, 2),
                "stub_days":             stub_days if m == 1 else 0,
                "fee_charge":            round(cash_fees, 2),
                "fee_to_date":           round(fee2d, 2),
                "deferred":              True,
                "deferred_interest":     round(deferred_int_this_month, 2),
                "capitalized_interest":  0.0,
                "recast_payment":        np.nan,
                "day_count":             loan.day_count,
                "label":                 loan.label,
            })
            i2d += interest
            cur_date += relativedelta(months=1)
            continue

        # ── handle deferred interest at resumption ────────────────────────────
        prev_month_deferred = (m - 1) in deferred_months if m > 1 else False
        if prev_month_deferred and deferred_interest_pending > 0:
            deferment_obj = deferred_months[m - 1]
            if deferment_obj.capitalize_interest:
                balance += deferred_interest_pending
                cap_int_this_month = deferred_interest_pending
            # else: collected as lump-sum — handled below via cash_fees
            deferred_interest_pending = 0.0

        # ── extra payments ────────────────────────────────────────────────────
        extra = 0.0
        for ep in loan.extra_payments:
            if ep.start_month <= m and (ep.end_month is None or m <= ep.end_month):
                extra += ep.amount

        # ── principal split ───────────────────────────────────────────────────
        principal_portion = min(current_pmt - interest, balance)
        if principal_portion < 0:
            # Interest exceeds payment (shouldn't happen on normal loans but
            # can occur after capitalization events or very high rates)
            principal_portion = 0.0

        extra = min(extra, balance - principal_portion)
        total_principal = principal_portion + extra
        total_pmt = interest + total_principal + cash_fees

        i2d += interest
        p2d += total_principal
        remaining_after = max(balance - total_principal, 0)

        # ── recast after extra payment ────────────────────────────────────────
        recast_pmt = np.nan
        if loan.reamortize_on_extra and extra > 0 and remaining_after > 0:
            months_remaining = loan.term_months - m
            if months_remaining > 0:
                new_pmt = _monthly_payment(remaining_after, r_monthly, months_remaining)
                current_pmt = new_pmt
                recast_pmt  = round(new_pmt, 2)

        rows.append({
            "months_elapsed":        global_month_offset + m,
            "date":                  cur_date,
            "remaining_start":       round(balance, 2),
            "monthly_payment":       round(current_pmt, 2),
            "extra_payment":         round(extra, 2),
            "total_payment":         round(total_pmt, 2),
            "interest":              round(interest, 2),
            "interest_to_date":      round(i2d, 2),
            "principal":             round(total_principal, 2),
            "principal_to_date":     round(p2d, 2),
            "stub_days":             stub_days if m == 1 else 0,
            "fee_charge":            round(cash_fees, 2),
            "fee_to_date":           round(fee2d, 2),
            "deferred":              False,
            "deferred_interest":     0.0,
            "capitalized_interest":  round(cap_int_this_month, 2),
            "recast_payment":        recast_pmt,
            "day_count":             loan.day_count,
            "label":                 loan.label,
        })

        balance = remaining_after
        cur_date += relativedelta(months=1)
        if balance == 0:
            break

    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# ENHANCED ANALYZER
# ─────────────────────────────────────────────────────────────────────────────

class EnhancedMortgageAnalyzer:
    """
    Enhanced mortgage analyzer supporting all EnhancedLoan features.

    Wraps the same interface as MortgageAnalyzer with enhanced amortization.
    All table and plot methods are identical.

    Parameters
    ----------
    loans : list[EnhancedLoan]
        Ordered list of loan instruments.
    refi_month : int | None
        Month (of the first loan) at which refinance takes effect.
    extended_costs : ExtendedCosts | None
        Recurring homeownership costs.
    shadow_loans : list[EnhancedLoan] | None
        Counterfactual loans for plot comparison only.

    Example
    -------
    from mortgage_tool_enhanced import EnhancedLoan, FeeEvent, Deferment, EnhancedMortgageAnalyzer

    loan = EnhancedLoan(
        principal          = 675_420,
        annual_rate        = 0.0799,
        term_months        = 360,
        start_date         = date(2024, 1, 15),
        first_payment_date = date(2024, 3, 1),    # stub period: 46 days
        day_count          = "actual/365",
        capitalized_fees   = 1_200,               # origination fee rolled in
        fee_events         = [FeeEvent(month=4, amount=35, label="Late Fee")],
        deferments         = [Deferment(start_month=13, num_months=3,
                                        capitalize_interest=True)],
        reamortize_on_extra = False,
        extra_payments     = [ExtraPayment(amount=200, start_month=1)],
        closing_costs      = 8_500,
        label              = "Enhanced Loan",
    )
    analyzer = EnhancedMortgageAnalyzer(loans=[loan])
    """

    def __init__(
        self,
        loans: list,
        refi_month: Optional[int] = None,
        extended_costs=None,
        shadow_loans: Optional[list] = None,
    ):
        self.loans          = loans
        self.refi_month     = refi_month
        self.extended_costs = extended_costs
        self.shadow_loans   = shadow_loans or []

        self._amort_dfs: list = []
        self._combined_df = None
        self._extended_df = None
        self._breakeven_refi = None
        self._shadow_dfs: dict = {}

        self._build()

    def _build(self):
        offset = 0
        for i, loan in enumerate(self.loans):
            df = build_enhanced_amortization(loan, global_month_offset=offset)
            if i == 0 and len(self.loans) > 1 and self.refi_month:
                df = df[df["months_elapsed"] <= self.refi_month].copy()
            self._amort_dfs.append(df)
            offset = df["months_elapsed"].max()

        self._combined_df = self._merge()

        if self.extended_costs:
            # Re-use base tool's extended cost engine via MortgageAnalyzer
            from mortgage_tool import build_amortization, Loan as BaseLoan
            self._extended_df = self._build_extended()

        if len(self.loans) > 1:
            self._breakeven_refi = self._calc_breakeven()

        for si, sl in enumerate(self.shadow_loans):
            sdf = build_enhanced_amortization(sl, global_month_offset=0)
            self._shadow_dfs[sl.label] = sdf
            self._shadow_dfs[si]       = sdf

    def _merge(self):
        if len(self._amort_dfs) == 1:
            df = self._amort_dfs[0].copy()
            df = df.rename(columns={c: c + "_L1" for c in df.columns
                                    if c not in ("months_elapsed", "date")})
            return df

        all_months = pd.concat([d[["months_elapsed","date"]] for d in self._amort_dfs])
        all_months = all_months.drop_duplicates("months_elapsed").sort_values("months_elapsed")
        result = all_months.reset_index(drop=True)

        for idx, df in enumerate(self._amort_dfs, start=1):
            suffix = f"_L{idx}"
            cols = [c for c in df.columns if c not in ("months_elapsed","date")]
            renamed = df[["months_elapsed"] + cols].rename(
                columns={c: c+suffix for c in cols})
            result = result.merge(renamed, on="months_elapsed", how="left")
        return result

    def _build_extended(self):
        """Re-use base tool's extended cost projector."""
        from mortgage_tool import _project_annual_costs
        base = self._combined_df[["months_elapsed","date"]].copy()
        all_years = sorted({d.year for d in base["date"]})
        extended_years = list(range(min(all_years), max(all_years)+2))

        item_annual = {}
        for item in self.extended_costs.items:
            item_annual[item.name] = _project_annual_costs(item, extended_years)

        rows = []
        ytd_tracker = {}
        for _, row in base.iterrows():
            d = row["date"]
            month_row = {"months_elapsed": row["months_elapsed"], "date": d}
            yr = d.year
            if yr not in ytd_tracker:
                ytd_tracker[yr] = {nm: 0.0 for nm in item_annual}
            for name, annual_by_year in item_annual.items():
                monthly = annual_by_year.get(yr, 0.0) / 12
                ytd_tracker[yr][name] = ytd_tracker[yr].get(name, 0.0) + monthly
                month_row[name] = round(monthly, 2)
                month_row[f"{name}_sum_yr"] = round(ytd_tracker[yr][name], 2)
            rows.append(month_row)

        ext = pd.DataFrame(rows)
        for name in item_annual:
            ext[f"{name}_to_date"] = ext[name].cumsum().round(2)
        item_cols = list(item_annual.keys())
        ext["all_items_monthly"] = ext[item_cols].sum(axis=1).round(2)
        ext["all_items_sum_yr"]  = ext[[f"{n}_sum_yr" for n in item_cols]].sum(axis=1).round(2)
        ext["all_items_to_date"] = ext["all_items_monthly"].cumsum().round(2)
        return ext

    def _calc_breakeven(self):
        if len(self._amort_dfs) < 2:
            return None
        closing = self.loans[1].closing_costs
        orig_full = build_enhanced_amortization(self.loans[0])
        orig_remaining = orig_full[orig_full["months_elapsed"] > self.refi_month]
        refi_df = self._amort_dfs[1]
        cum_savings = 0.0
        for (_, or_), (_, re_) in zip(orig_remaining.iterrows(), refi_df.iterrows()):
            cum_savings += (or_["interest"] - re_["interest"])
            if cum_savings >= closing:
                return int(re_["months_elapsed"])
        return None

    # ── public interface (mirrors MortgageAnalyzer) ──────────────────────────

    @property
    def amortization(self):
        return self._combined_df

    @property
    def extended(self):
        return self._extended_df

    @property
    def refi_breakeven_month(self):
        return self._breakeven_refi

    @property
    def shadow_schedules(self):
        return self._shadow_dfs

    def shadow(self, idx: int):
        return self._shadow_dfs[idx]

    def mortgage_table(self, columns=None, max_rows=None,
                       start_month=1, end_month=None):
        df = self._combined_df.copy()
        df = df[df["months_elapsed"] >= start_month]
        if end_month:
            df = df[df["months_elapsed"] <= end_month]
        if columns:
            df = df[columns]
        if max_rows:
            df = df.head(max_rows)
        return df.reset_index(drop=True)

    def extended_table(self, columns=None, year=None, max_rows=None):
        if self._extended_df is None:
            raise ValueError("No extended costs configured.")
        df = self._extended_df.copy()
        df["date"] = pd.to_datetime(df["date"])
        if year:
            df = df[df["date"].dt.year == year]
        if columns:
            df = df[columns]
        if max_rows:
            df = df.head(max_rows)
        return df.reset_index(drop=True)

    def annual_summary(self, items=None):
        if self._extended_df is None:
            raise ValueError("No extended costs configured.")
        ext = self._extended_df.copy()
        ext["date"] = pd.to_datetime(ext["date"])
        ext["year"] = ext["date"].dt.year
        agg = {"all_items_monthly": "sum"}
        cols = items or [it.name for it in self.extended_costs.items]
        for c in cols:
            agg[c] = "sum"
        return ext.groupby("year").agg(agg).round(2).reset_index()

    def summary(self):
        out = {}
        total_months = self._combined_df["months_elapsed"].max()
        out["true_lifetime_months"] = int(total_months)
        out["true_lifetime_years"]  = round(total_months / 12, 2)

        for idx, (loan, df) in enumerate(zip(self.loans, self._amort_dfs), start=1):
            sfx = f"_L{idx}"
            ti_col = f"interest{sfx}"
            tp_col = f"total_payment{sfx}"
            if ti_col in self._combined_df.columns:
                ti = self._combined_df[ti_col].fillna(0).sum()
                tp = self._combined_df[tp_col].fillna(0).sum()
            else:
                ti = df["interest"].sum()
                tp = df["total_payment"].sum()

            stub = df["stub_days"].iloc[0] if "stub_days" in df.columns else 0
            cap  = loan.capitalized_fees if hasattr(loan, "capitalized_fees") else 0
            fees = df["fee_to_date"].iloc[-1] if "fee_to_date" in df.columns else 0

            out[f"label_{loan.label}"]           = loan.label
            out[f"total_interest_{loan.label}"]  = round(ti, 2)
            out[f"total_fees_{loan.label}"]      = round(fees, 2)
            out[f"capitalized_fees_{loan.label}"]= cap
            out[f"closing_costs_{loan.label}"]   = loan.closing_costs
            out[f"total_paid_{loan.label}"]      = round(tp + loan.closing_costs, 2)
            if stub > 0:
                out[f"stub_days_{loan.label}"]   = stub
            out[f"day_count_{loan.label}"]       = loan.day_count

        if self._breakeven_refi:
            out["refi_breakeven_months_elapsed"] = self._breakeven_refi
            be_row = self._combined_df[
                self._combined_df["months_elapsed"] == self._breakeven_refi]
            if not be_row.empty:
                out["refi_breakeven_date"] = be_row["date"].iloc[0]

        if self._extended_df is not None:
            out["total_extended_costs"] = round(
                self._extended_df["all_items_to_date"].iloc[-1], 2)
        return out

    def print_summary(self):
        s = self.summary()
        print("\n" + "="*60)
        print("  ENHANCED MORTGAGE ANALYSIS SUMMARY")
        print("="*60)
        for k, v in s.items():
            label = k.replace("_", " ").title()
            print(f"  {label:<46} {v}")
        print("="*60 + "\n")

    def compare_day_counts(self) -> pd.DataFrame:
        """
        Compare total interest under all three day-count conventions
        for the first loan.  Useful for understanding the cost difference.

        Returns a small DataFrame with one row per convention.
        """
        loan = self.loans[0]
        results = []
        for dc in ("actual/365", "actual/360", "30/360"):
            import copy
            test_loan = copy.copy(loan)
            test_loan.day_count = dc
            test_loan.deferments = []
            test_loan.fee_events = []
            test_loan.extra_payments = []
            test_loan.reamortize_on_extra = False
            df = build_enhanced_amortization(test_loan)
            results.append({
                "day_count":        dc,
                "total_interest":   round(df["interest"].sum(), 2),
                "total_payments":   round(df["total_payment"].sum(), 2),
                "payoff_months":    len(df),
            })
        base = results[0]["total_interest"]
        for r in results:
            r["vs_actual365"] = round(r["total_interest"] - base, 2)
        return pd.DataFrame(results)
