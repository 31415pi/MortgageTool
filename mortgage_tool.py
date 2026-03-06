# Copyright (c) 2026. Private use unrestricted.
# Commercial use requires a license — contact hellomoto1123@gmail.com
# See LICENSE.md for full terms.
"""
mortgage_tool.py
================
A comprehensive mortgage amortization, refinancing, and true-cost-of-ownership tool.

Usage:
    from mortgage_tool import Loan, RefinanceScenario, ExtendedCosts, MortgageAnalyzer, plot_scenarios
"""

import pandas as pd
import numpy as np
from datetime import date
from dateutil.relativedelta import relativedelta
from dataclasses import dataclass, field
from typing import Optional
import warnings
warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────────────────────
# DATA CLASSES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ExtraPayment:
    """
    Specifies a principal-only extra payment for a date range.

    Parameters
    ----------
    amount : float
        Extra principal payment per month.
    start_month : int
        1-based month number (relative to the *loan* start) to begin extra payments.
    end_month : int | None
        Last month (inclusive) to apply the extra payment.
        None means "apply forever (until loan is paid off)".

    Examples
    --------
    # Pay an extra $200/mo from month 13 through month 36
    ExtraPayment(amount=200, start_month=13, end_month=36)

    # Pay an extra $500/mo starting month 1, indefinitely
    ExtraPayment(amount=500, start_month=1, end_month=None)
    """
    amount: float
    start_month: int = 1
    end_month: Optional[int] = None


@dataclass
class Loan:
    """
    Describes a single mortgage instrument.

    Parameters
    ----------
    principal : float
        Original loan amount (after down payment).
    annual_rate : float
        Annual interest rate as a decimal (e.g. 0.065 for 6.5%).
    term_months : int
        Total scheduled term (e.g. 360 for a 30-year mortgage).
    start_date : date
        First payment date.
    label : str
        Human-readable label used in tables and plots.
    extra_payments : list[ExtraPayment]
        Zero or more extra principal-only payment rules.
    closing_costs : float
        Up-front closing / origination costs for THIS loan
        (used in break-even calculations).

    Notes
    -----
    For a refinance, pass the *remaining balance* of the prior loan as `principal`.
    The analyzer will track the true elapsed months across instruments.
    """
    principal: float
    annual_rate: float
    term_months: int
    start_date: date
    label: str = "Loan"
    extra_payments: list = field(default_factory=list)
    closing_costs: float = 0.0


@dataclass
class AnnualItem:
    """
    A recurring annual cost (tax, insurance, warranty, electric, gas, etc.).

    Parameters
    ----------
    name : str          Column label used everywhere.
    history : dict      {year: amount} – known historical values used to fit
                        the linear regression for future projection.
                        At minimum supply {start_year: first_annual_amount}.
    """
    name: str
    history: dict  # {year: amount}


@dataclass
class ExtendedCosts:
    """
    Container for all recurring non-PI costs.

    Parameters
    ----------
    items : list[AnnualItem]
        Any number of annual cost items.

    Example
    -------
    ec = ExtendedCosts(items=[
        AnnualItem("Tax",       {2020: 3600, 2021: 3750, 2022: 3900}),
        AnnualItem("Insurance", {2020: 1200, 2021: 1240}),
        AnnualItem("Electric",  {2020: 1800}),
        AnnualItem("Gas",       {2020:  600}),
        AnnualItem("Water",     {2020:  480}),
        AnnualItem("Sewer",     {2020:  240}),
        AnnualItem("Warranty",  {2020:  600}),
        AnnualItem("Other",     {2020:  300}),
    ])
    """
    items: list = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# CORE AMORTIZATION ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def _monthly_payment(principal: float, monthly_rate: float, term_months: int) -> float:
    """Standard amortization payment formula."""
    if monthly_rate == 0:
        return principal / term_months
    return principal * (monthly_rate * (1 + monthly_rate) ** term_months) / \
           ((1 + monthly_rate) ** term_months - 1)


def build_amortization(loan: Loan, global_month_offset: int = 0) -> pd.DataFrame:
    """
    Build a full amortization schedule for a single Loan.

    Returns a DataFrame with columns:
        months_elapsed, date, remaining_start, monthly_payment,
        extra_payment, total_payment, interest, interest_to_date,
        principal, principal_to_date, label
    """
    r = loan.annual_rate / 12
    pmt = _monthly_payment(loan.principal, r, loan.term_months)

    rows = []
    balance = loan.principal
    i2d = 0.0
    p2d = 0.0
    cur_date = loan.start_date

    for m in range(1, loan.term_months + 1):
        if balance <= 0:
            break

        # Extra payments applicable this month?
        extra = 0.0
        for ep in loan.extra_payments:
            if ep.start_month <= m and (ep.end_month is None or m <= ep.end_month):
                extra += ep.amount

        interest = balance * r
        principal_portion = min(pmt - interest, balance)
        # Cap extra so we don't overpay
        extra = min(extra, balance - principal_portion)
        total_principal = principal_portion + extra
        total_pmt = interest + total_principal

        i2d += interest
        p2d += total_principal
        remaining_after = max(balance - total_principal, 0)

        rows.append({
            "months_elapsed":   global_month_offset + m,
            "date":             cur_date,
            "remaining_start":  round(balance, 2),
            "monthly_payment":  round(pmt, 2),
            "extra_payment":    round(extra, 2),
            "total_payment":    round(total_pmt, 2),
            "interest":         round(interest, 2),
            "interest_to_date": round(i2d, 2),
            "principal":        round(total_principal, 2),
            "principal_to_date":round(p2d, 2),
            "label":            loan.label,
        })

        balance = remaining_after
        cur_date = cur_date + relativedelta(months=1)
        if balance == 0:
            break

    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# LINEAR REGRESSION PROJECTOR
# ─────────────────────────────────────────────────────────────────────────────

def _project_annual_costs(item: AnnualItem, years: list) -> dict:
    """
    Given an AnnualItem with historical data, fit a linear regression and
    return projected annual cost for each year in `years`.
    If only one data point exists, assume flat (no growth).
    """
    hist_years = np.array(sorted(item.history.keys()), dtype=float)
    hist_vals  = np.array([item.history[y] for y in hist_years.astype(int)])

    if len(hist_years) >= 2:
        coeffs = np.polyfit(hist_years, hist_vals, 1)
        slope, intercept = coeffs
    else:
        slope, intercept = 0.0, hist_vals[0]
        # anchor intercept so projection(hist_years[0]) == hist_vals[0]
        intercept = hist_vals[0] - slope * hist_years[0]

    result = {}
    for y in years:
        projected = slope * y + intercept
        result[int(y)] = max(projected, 0.0)  # costs can't be negative
    return result


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ANALYZER
# ─────────────────────────────────────────────────────────────────────────────

class MortgageAnalyzer:
    """
    Full-lifecycle mortgage analyzer supporting sequential loans (refinances).

    Parameters
    ----------
    loans : list[Loan]
        Ordered list of loan instruments.  The first is the original loan;
        subsequent entries represent refinances.  Each refinance `principal`
        should equal the remaining balance from the prior loan at the
        refinance month.
    refi_month : int | None
        The 1-based month (of the *original* loan) at which the refinance
        takes effect.  Required when len(loans) > 1.
    extended_costs : ExtendedCosts | None
        Optional recurring cost items.

    Example
    -------
    orig = Loan(principal=400_000, annual_rate=0.07, term_months=360,
                start_date=date(2022, 1, 1), label="Original 7%",
                closing_costs=8_000)

    refi = Loan(principal=385_000, annual_rate=0.055, term_months=360,
                start_date=date(2023, 3, 1), label="Refi 5.5%",
                closing_costs=6_500)

    analyzer = MortgageAnalyzer(loans=[orig, refi], refi_month=15)
    """

    def __init__(
        self,
        loans: list,
        refi_month: Optional[int] = None,
        extended_costs: Optional[ExtendedCosts] = None,
        shadow_loans: Optional[list] = None,
    ):
        self.loans          = loans
        self.refi_month     = refi_month
        self.extended_costs = extended_costs
        # shadow_loans: list of Loan objects run to FULL completion for
        # counterfactual "what-if" plotting. They do NOT affect cost
        # calculations or the combined amortization table.
        self.shadow_loans   = shadow_loans or []

        self._amort_dfs: list[pd.DataFrame] = []
        self._combined_df: Optional[pd.DataFrame] = None
        self._extended_df: Optional[pd.DataFrame] = None
        self._breakeven_refi: Optional[int] = None
        self._shadow_dfs: dict = {}   # {label: DataFrame}

        self._build()

    # ── build ─────────────────────────────────────────────────────────────────

    def _build(self):
        """Construct amortization schedules and extended cost table."""
        offset = 0
        for i, loan in enumerate(self.loans):
            if i == 0:
                if len(self.loans) > 1 and self.refi_month:
                    df = build_amortization(loan, global_month_offset=0)
                    # Only keep rows UP TO refi_month
                    df = df[df["months_elapsed"] <= self.refi_month].copy()
                else:
                    df = build_amortization(loan, global_month_offset=0)
                self._amort_dfs.append(df)
                offset = df["months_elapsed"].max()
            else:
                df = build_amortization(loan, global_month_offset=offset)
                self._amort_dfs.append(df)
                offset = df["months_elapsed"].max()

        self._combined_df = self._merge_schedules()

        if self.extended_costs:
            self._extended_df = self._build_extended()

        if len(self.loans) > 1:
            self._breakeven_refi = self._calc_refi_breakeven()

        # Build full-term shadow schedules for counterfactual comparison
        # Stored by BOTH label and 0-based index so users can reference either way.
        for si, sl in enumerate(self.shadow_loans):
            sdf = build_amortization(sl, global_month_offset=0)
            self._shadow_dfs[sl.label] = sdf   # by label
            self._shadow_dfs[si]       = sdf   # by 0-based int index

    def _merge_schedules(self) -> pd.DataFrame:
        """
        Produce the combined side-by-side table.
        Original loan columns get suffix _L1, refi loan columns get suffix _L2, etc.
        """
        if len(self._amort_dfs) == 1:
            df = self._amort_dfs[0].copy()
            df = df.rename(columns={c: c + "_L1" for c in df.columns
                                    if c not in ("months_elapsed", "date")})
            return df

        # Build a full month spine
        all_months = pd.concat([d[["months_elapsed", "date"]] for d in self._amort_dfs])
        all_months = all_months.drop_duplicates("months_elapsed").sort_values("months_elapsed")

        result = all_months.reset_index(drop=True)
        for idx, df in enumerate(self._amort_dfs, start=1):
            suffix = f"_L{idx}"
            cols_to_keep = [c for c in df.columns if c not in ("months_elapsed", "date")]
            renamed = df[["months_elapsed"] + cols_to_keep].rename(
                columns={c: c + suffix for c in cols_to_keep}
            )
            result = result.merge(renamed, on="months_elapsed", how="left")

        return result

    def _build_extended(self) -> pd.DataFrame:
        """Build month-by-month extended cost table with projections."""
        base = self._combined_df[["months_elapsed", "date"]].copy()
        all_years = sorted({d.year for d in base["date"]})
        extended_years = list(range(min(all_years), max(all_years) + 2))

        # Project each item
        item_annual: dict = {}
        for item in self.extended_costs.items:
            item_annual[item.name] = _project_annual_costs(item, extended_years)

        rows = []
        ytd_tracker: dict = {}  # {(year, name): cumulative}
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
                month_row[f"{name}_sum_yr"]  = round(ytd_tracker[yr][name], 2)

            rows.append(month_row)

        ext = pd.DataFrame(rows)

        # Compute running totals across entire life
        for name in item_annual:
            ext[f"{name}_to_date"] = ext[name].cumsum().round(2)

        # Sum all items columns for "all items this month"
        item_cols = list(item_annual.keys())
        ext["all_items_monthly"] = ext[item_cols].sum(axis=1).round(2)
        ext["all_items_sum_yr"]  = ext[[f"{n}_sum_yr" for n in item_cols]].sum(axis=1).round(2)
        ext["all_items_to_date"] = ext["all_items_monthly"].cumsum().round(2)

        return ext

    def _calc_refi_breakeven(self) -> Optional[int]:
        """
        Calculate the break-even month (relative to refi date) where
        cumulative savings in interest >= closing costs of the new loan.
        Returns months_elapsed value at break-even, or None if never.
        """
        if len(self._amort_dfs) < 2:
            return None

        refi_loan    = self.loans[1]
        closing_cost = refi_loan.closing_costs
        refi_offset  = self._amort_dfs[0]["months_elapsed"].max()

        orig_full = build_amortization(self.loans[0], global_month_offset=0)
        # hypothetical: what would orig loan cost from refi_month onward?
        orig_remaining = orig_full[orig_full["months_elapsed"] > self.refi_month].copy()
        refi_df = self._amort_dfs[1].copy()

        cum_savings = 0.0
        for (_, or_), (_, re_) in zip(orig_remaining.iterrows(), refi_df.iterrows()):
            cum_savings += (or_["interest"] - re_["interest"])
            if cum_savings >= closing_cost:
                return int(re_["months_elapsed"])
        return None

    # ── public helpers ─────────────────────────────────────────────────────────

    @property
    def amortization(self) -> pd.DataFrame:
        """Combined amortization schedule (all loans, sequential)."""
        return self._combined_df

    @property
    def extended(self) -> Optional[pd.DataFrame]:
        """Extended cost table (if extended_costs were supplied)."""
        return self._extended_df

    @property
    def refi_breakeven_month(self) -> Optional[int]:
        """months_elapsed value at which the refi pays for itself."""
        return self._breakeven_refi

    @property
    def shadow_schedules(self) -> dict:
        """
        Dict of shadow loan DataFrames, keyed by EITHER:
          - the Loan's label string  (e.g. analyzer.shadow_schedules["My Label"])
          - 0-based integer index    (e.g. analyzer.shadow_schedules[0])
        Both keys point to the same DataFrame.
        """
        return self._shadow_dfs

    def shadow(self, idx: int) -> pd.DataFrame:
        """
        Convenience: get shadow schedule by 0-based index.
        analyzer.shadow(0)  →  first shadow loan DataFrame
        """
        return self._shadow_dfs[idx]

    def summary(self) -> dict:
        """Return a dict of key metrics."""
        out = {}
        total_months = self._combined_df["months_elapsed"].max()
        out["true_lifetime_months"] = int(total_months)
        out["true_lifetime_years"]  = round(total_months / 12, 2)

        for idx, (loan, df) in enumerate(zip(self.loans, self._amort_dfs), start=1):
            sfx = f"_L{idx}"
            if f"interest{sfx}" in self._combined_df.columns:
                total_interest = self._combined_df[f"interest{sfx}"].sum()
                total_paid     = self._combined_df[f"total_payment{sfx}"].sum()
            elif "interest_L1" in self._combined_df.columns:
                # single-loan case – column was already suffixed
                total_interest = self._combined_df["interest_L1"].sum()
                total_paid     = self._combined_df["total_payment_L1"].sum()
            else:
                total_interest = df["interest"].sum()
                total_paid     = df["total_payment"].sum()

            out[f"total_interest_{loan.label}"] = round(total_interest, 2)
            out[f"total_paid_{loan.label}"]     = round(total_paid + loan.closing_costs, 2)
            out[f"closing_costs_{loan.label}"]  = loan.closing_costs

        if self._breakeven_refi:
            out["refi_breakeven_months_elapsed"] = self._breakeven_refi
            bedate = self._combined_df.loc[
                self._combined_df["months_elapsed"] == self._breakeven_refi, "date"
            ]
            if not bedate.empty:
                out["refi_breakeven_date"] = bedate.iloc[0]

        if self._extended_df is not None:
            out["total_extended_costs"] = round(
                self._extended_df["all_items_to_date"].iloc[-1], 2)

        return out

    def print_summary(self):
        """Pretty-print the summary."""
        s = self.summary()
        print("\n" + "=" * 60)
        print("  MORTGAGE ANALYSIS SUMMARY")
        print("=" * 60)
        for k, v in s.items():
            label = k.replace("_", " ").title()
            print(f"  {label:<42} {v}")
        print("=" * 60 + "\n")

    # ── table views ────────────────────────────────────────────────────────────

    def mortgage_table(
        self,
        columns: Optional[list] = None,
        max_rows: Optional[int] = None,
        start_month: int = 1,
        end_month: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Return the amortization table, optionally filtered/sliced.

        Parameters
        ----------
        columns : list | None
            Subset of column names to return. None = all columns.
        max_rows : int | None
            Cap number of rows returned.
        start_month, end_month : int
            Filter by months_elapsed range.

        Examples
        --------
        # All columns, first 24 months
        analyzer.mortgage_table(end_month=24)

        # Specific columns
        analyzer.mortgage_table(columns=["months_elapsed","date",
                                          "monthly_payment_L1","interest_L1",
                                          "principal_L1"])
        """
        df = self._combined_df.copy()
        df = df[df["months_elapsed"] >= start_month]
        if end_month:
            df = df[df["months_elapsed"] <= end_month]
        if columns:
            df = df[columns]
        if max_rows:
            df = df.head(max_rows)
        return df.reset_index(drop=True)

    def extended_table(
        self,
        columns: Optional[list] = None,
        year: Optional[int] = None,
        max_rows: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Return the extended cost table.

        Parameters
        ----------
        columns : list | None  – subset of columns
        year : int | None      – filter to a single calendar year
        max_rows : int | None  – cap rows

        Examples
        --------
        # PITI monthly + running totals
        analyzer.extended_table(columns=[
            "date","Tax","Insurance",
            "all_items_monthly","all_items_to_date"
        ])
        """
        if self._extended_df is None:
            raise ValueError("No extended costs were configured.")
        df = self._extended_df.copy()
        df["date"] = pd.to_datetime(df["date"])
        if year:
            df = df[df["date"].dt.year == year]
        if columns:
            df = df[columns]
        if max_rows:
            df = df.head(max_rows)
        return df.reset_index(drop=True)

    def piti_table(self, extra_cols: Optional[list] = None) -> pd.DataFrame:
        """
        Convenience table: PI + Tax + Insurance columns plus running totals.
        Pass extra_cols to add more extended cost columns.
        """
        if self._extended_df is None:
            raise ValueError("No extended costs were configured.")

        base = self._combined_df[["months_elapsed", "date"]].copy()
        ext  = self._extended_df.copy()

        # Find PI columns from first active loan each month
        pmt_col = next(
            (c for c in self._combined_df.columns if c.startswith("monthly_payment")), None
        )

        if pmt_col:
            base["PI"] = self._combined_df[pmt_col].fillna(0)
            # Add extra-payment contribution
            extra_col = pmt_col.replace("monthly_payment", "extra_payment")
            if extra_col in self._combined_df.columns:
                base["PI"] += self._combined_df[extra_col].fillna(0)

        merge = base.merge(
            ext[["months_elapsed", "Tax", "Insurance",
                 "all_items_monthly", "all_items_to_date"]
                if "Tax" in ext.columns and "Insurance" in ext.columns
                else ["months_elapsed"]],
            on="months_elapsed", how="left"
        )

        if "Tax" in merge.columns and "Insurance" in merge.columns and "PI" in merge.columns:
            merge["PITI"] = (merge["PI"] + merge["Tax"] + merge["Insurance"]).round(2)
            merge["PITI_to_date"] = merge["PITI"].cumsum().round(2)

        if extra_cols:
            merge = merge.merge(
                ext[["months_elapsed"] + extra_cols], on="months_elapsed", how="left"
            )

        return merge.reset_index(drop=True)

    def annual_summary(self, items: Optional[list] = None) -> pd.DataFrame:
        """
        Return a year-by-year aggregated summary.

        Parameters
        ----------
        items : list of extended cost names to include (None = all)
        """
        if self._extended_df is None:
            raise ValueError("No extended costs were configured.")

        ext = self._extended_df.copy()
        ext["date"] = pd.to_datetime(ext["date"])
        ext["year"] = ext["date"].dt.year

        agg_dict = {"all_items_monthly": "sum"}
        if items:
            for it in items:
                agg_dict[it] = "sum"
        else:
            for item in self.extended_costs.items:
                agg_dict[item.name] = "sum"

        return ext.groupby("year").agg(agg_dict).round(2).reset_index()


# ─────────────────────────────────────────────────────────────────────────────
# PLOTTING ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def plot_scenarios(
    analyzer: MortgageAnalyzer,
    groups: Optional[list] = None,
    save_path: Optional[str] = None,
    figsize: tuple = (18, 10),
):
    """
    Plot amortization metrics grouped by loan instrument with distinct base colors
    and differentiating line styles / markers per metric.

    Parameters
    ----------
    analyzer : MortgageAnalyzer
    groups : list of dicts | None
        Each dict defines one group:
          {
            "label":   "Original Loan",     # legend group title
            "loan_idx": 1,                   # 1-based loan index (L1, L2, ...)
            "metrics": ["remaining_start", "interest_to_date", "principal_to_date"],
            "base_color": "#1f77b4",         # any matplotlib color string
          }
        If None, auto-generate one group per loan.

    save_path : str | None   – if given, save figure to this path
    figsize   : tuple

    Examples
    --------
    plot_scenarios(analyzer, groups=[
        {
            "label": "Original 7% Loan",
            "loan_idx": 1,
            "metrics": ["remaining_start", "interest_to_date", "principal_to_date"],
            "base_color": "#1f6090",
        },
        {
            "label": "Refinanced 5.5% Loan",
            "loan_idx": 2,
            "metrics": ["remaining_start", "interest_to_date", "principal_to_date"],
            "base_color": "#c0390c",
        },
    ])
    """
    try:
        import matplotlib.pyplot as plt
        import matplotlib.colors as mcolors
        from matplotlib.lines import Line2D
    except ImportError:
        raise ImportError("matplotlib is required for plotting. pip install matplotlib")

    df = analyzer.amortization

    # Auto-generate groups if not provided
    if groups is None:
        palette = ["#1f6090", "#c0390c", "#1a7a4a", "#7b3fa0", "#b07d1a"]
        shadow_palette = ["#888888", "#aa7722", "#337755", "#775599"]
        groups = []
        for idx, loan in enumerate(analyzer.loans, start=1):
            groups.append({
                "label":      loan.label,
                "loan_idx":   idx,
                "metrics":    ["remaining_start", "interest_to_date", "principal_to_date"],
                "base_color": palette[(idx - 1) % len(palette)],
            })
        for si, sl in enumerate(analyzer.shadow_loans):
            groups.append({
                "label":      sl.label,
                "shadow_idx": si,          # index-based — no string matching needed
                "metrics":    ["remaining_start", "interest_to_date", "principal_to_date"],
                "base_color": shadow_palette[si % len(shadow_palette)],
            })

    # Style cycle for metrics within a group
    LINE_STYLES = ["-", "--", "-.", ":"]
    MARKERS     = ["", "o", "s", "^", "D", "v"]

    fig, ax = plt.subplots(figsize=figsize)
    legend_handles = []

    def lighten(rgb, factor):
        return tuple(min(1.0, c + (1 - c) * factor) for c in rgb)

    for g in groups:
        base_hex  = g["base_color"]
        metrics   = g.get("metrics", ["remaining_start"])
        base_rgb  = mcolors.to_rgb(base_hex)
        is_shadow = "shadow_label" in g or "shadow_idx" in g

        shades = [lighten(base_rgb, i / max(len(metrics), 1) * 0.55)
                  for i in range(len(metrics))]

        # Group header in legend
        prefix = "· · " if is_shadow else "── "
        suffix = " (no refi)" if is_shadow else " ──"
        legend_handles.append(
            Line2D([0], [0], color="none", label=f"{prefix}{g['label']}{suffix}")
        )

        # Resolve the data source: real combined df or shadow df
        if is_shadow:
            key = g.get("shadow_idx", g.get("shadow_label"))
            src_df = analyzer.shadow_schedules.get(key)
            if src_df is None:
                print(f"  [warn] shadow key '{key}' not found. "
                      f"Available keys: {list(analyzer.shadow_schedules.keys())}")
                continue
        else:
            src_df = df
            lidx = g["loan_idx"]

        for mi, metric in enumerate(metrics):
            if is_shadow:
                col = metric   # shadow dfs use plain column names
            else:
                col = f"{metric}_L{lidx}"

            if col not in src_df.columns:
                print(f"  [warn] column '{col}' not found, skipping.")
                continue

            series = src_df[col].dropna()
            xvals  = src_df.loc[series.index, "months_elapsed"]

            color  = shades[mi]
            # Shadow lines are dashed + thinner to visually recede
            if is_shadow:
                ls     = ["--", ":", "-."][mi % 3]
                lw     = 1.2
                alpha  = 0.65
            else:
                ls     = LINE_STYLES[mi % len(LINE_STYLES)]
                lw     = 1.8
                alpha  = 1.0
            marker = MARKERS[mi % len(MARKERS)]
            mevery = max(1, len(xvals) // 20)

            ax.plot(
                xvals, series,
                color=color, linestyle=ls, linewidth=lw, alpha=alpha,
                marker=marker if marker else None,
                markevery=mevery, markersize=4,
                label=f"{g['label']} – {metric.replace('_', ' ').title()}"
            )
            legend_handles.append(
                Line2D([0], [0], color=color, linestyle=ls, linewidth=lw,
                       alpha=alpha,
                       marker=marker if marker else None, markersize=4,
                       label=f"  {metric.replace('_', ' ').title()}")
            )

    # Mark refi break-even
    be = analyzer.refi_breakeven_month
    if be:
        ax.axvline(x=be, color="gold", linestyle="--", linewidth=1.5)
        ax.annotate(
            f"Refi Break-Even\nMonth {be}",
            xy=(be, ax.get_ylim()[1] * 0.9),
            fontsize=8, color="goldenrod",
            ha="center",
            bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="gold", alpha=0.8),
        )

    ax.set_xlabel("Months Elapsed", fontsize=11)
    ax.set_ylabel("Amount ($)", fontsize=11)
    ax.set_title("Mortgage Scenario Analysis", fontsize=14, fontweight="bold")
    ax.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda x, _: f"${x:,.0f}")
    )
    ax.legend(handles=legend_handles, fontsize=8, loc="upper right",
              framealpha=0.9, ncol=max(1, len(groups)))
    ax.grid(True, linestyle="--", alpha=0.4)
    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches="tight")
        print(f"  Figure saved → {save_path}")

    plt.show()
    return fig, ax


def plot_extended_costs(
    analyzer: MortgageAnalyzer,
    items: Optional[list] = None,
    mode: str = "monthly",   # "monthly" | "cumulative" | "annual"
    save_path: Optional[str] = None,
    figsize: tuple = (16, 7),
):
    """
    Bar/line chart of extended costs over time.

    Parameters
    ----------
    items : list of item names to include (None = all)
    mode : "monthly" | "cumulative" | "annual"
    save_path : str | None
    """
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        raise ImportError("matplotlib is required. pip install matplotlib")

    if analyzer.extended is None:
        raise ValueError("No extended costs configured.")

    ext = analyzer.extended.copy()

    palette = plt.cm.tab10.colors

    if mode == "annual":
        data = analyzer.annual_summary(items)
        item_names = items or [it.name for it in analyzer.extended_costs.items]
        x = data["year"].astype(str)
        fig, ax = plt.subplots(figsize=figsize)
        bottom = np.zeros(len(data))
        for ci, name in enumerate(item_names):
            if name in data.columns:
                ax.bar(x, data[name], bottom=bottom,
                       label=name, color=palette[ci % len(palette)], alpha=0.85)
                bottom += data[name].values
        ax.set_title("Annual Extended Costs", fontsize=13, fontweight="bold")
        ax.set_xlabel("Year")
        ax.set_ylabel("Cost ($)")
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"${v:,.0f}"))
        ax.legend(fontsize=9)
        ax.grid(axis="y", linestyle="--", alpha=0.4)
    else:
        item_names = items or [it.name for it in analyzer.extended_costs.items]
        fig, ax = plt.subplots(figsize=figsize)
        for ci, name in enumerate(item_names):
            if mode == "cumulative":
                col = f"{name}_to_date"
            else:
                col = name
            if col in ext.columns:
                ax.plot(ext["months_elapsed"], ext[col],
                        label=name, color=palette[ci % len(palette)],
                        linewidth=1.8)
        ax.set_title(
            f"Extended Costs – {'Cumulative' if mode == 'cumulative' else 'Monthly'}",
            fontsize=13, fontweight="bold"
        )
        ax.set_xlabel("Months Elapsed")
        ax.set_ylabel("Amount ($)")
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"${v:,.0f}"))
        ax.legend(fontsize=9)
        ax.grid(linestyle="--", alpha=0.4)

    plt.tight_layout()
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches="tight")
        print(f"  Figure saved → {save_path}")
    plt.show()
    return fig, ax
