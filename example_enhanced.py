"""
example_enhanced.py
===================
Demonstrates the enhanced mortgage modeling features:
  - Stub period (46-day first period, loan funded mid-month)
  - Day-count convention comparison (actual/365 vs actual/360 vs 30/360)
  - Capitalized origination fee rolled into balance
  - One-time fee events (late charges)
  - Deferment / forbearance with interest capitalization
  - Loan recast after extra payments
  - Refinance with all enhanced features on the new loan

Run:
    python example_enhanced.py
"""

from datetime import date
import warnings
import pandas as pd
pd.set_option("display.max_columns", None)
pd.set_option("display.width", 200)
pd.set_option("display.float_format", "{:,.2f}".format)

from mortgage_tool_enhanced import (
    EnhancedLoan, FeeEvent, Deferment, ExtraPayment,
    AnnualItem, ExtendedCosts,
    EnhancedMortgageAnalyzer, plot_scenarios, plot_extended_costs,
)

# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO OVERVIEW
#
#  Original loan: $675,420 @ 7.99%, funded Jan 15 2024
#    - First payment pushed to March 1 (46-day stub period)
#    - $1,200 origination fee capitalized into balance
#    - actual/365 day-count
#    - $140/mo extra principal from month 1
#    - Late fee of $35 in month 5
#    - 3-month forbearance starting month 13 (interest capitalizes)
#
#  Refinance: after month 16, remaining balance @ 4.33%
#    - Standard first payment (no stub)
#    - actual/360 day-count (common in commercial/refi products)
#    - $821.65/mo extra (half the monthly savings)
#    - Recast enabled: extra payments lower future required payment
#    - $8,500 closing costs
#
#  Shadow: original loan, no refi, no deferment, for comparison
# ─────────────────────────────────────────────────────────────────────────────

# ── Original loan ─────────────────────────────────────────────────────────────

original_loan = EnhancedLoan(
    principal          = 675_420,
    annual_rate        = 0.0799,
    term_months        = 360,
    start_date         = date(2024, 1, 15),      # funded Jan 15
    first_payment_date = date(2024, 3, 1),        # first payment Mar 1 → 46-day stub
    day_count          = "actual/365",
    capitalized_fees   = 1_200,                   # origination fee rolled into balance
    fee_events         = [
        FeeEvent(month=5, amount=35, label="Late Fee"),
    ],
    deferments         = [
        Deferment(start_month=13, num_months=3, capitalize_interest=True),
    ],
    extra_payments     = [
        ExtraPayment(amount=140, start_month=1, end_month=None),
    ],
    reamortize_on_extra = False,                  # extra payments shorten term
    closing_costs      = 0,
    label              = "Original 7.99%",
)

# ── Refi loan ─────────────────────────────────────────────────────────────────

refi_loan = EnhancedLoan(
    principal          = 666_081,                 # remaining balance at month 16
    annual_rate        = 0.0433,
    term_months        = 360,
    start_date         = date(2025, 5, 1),
    first_payment_date = None,                    # standard: 1 month after start
    day_count          = "actual/360",            # common in refi products
    capitalized_fees   = 0,
    fee_events         = [],
    deferments         = [],
    extra_payments     = [
        ExtraPayment(amount=821.65, start_month=1, end_month=None),
    ],
    reamortize_on_extra = True,                   # extra payments lower future payment
    closing_costs      = 8_500,
    label              = "Refi 4.33%",
)

# ── Shadow: original loan, no refi, no deferment, no fees ────────────────────

shadow_plain = EnhancedLoan(
    principal          = 675_420,
    annual_rate        = 0.0799,
    term_months        = 360,
    start_date         = date(2024, 1, 1),        # standard start
    first_payment_date = None,
    day_count          = "actual/365",
    capitalized_fees   = 0,
    fee_events         = [],
    deferments         = [],
    extra_payments     = [ExtraPayment(amount=140, start_month=1, end_month=None)],
    reamortize_on_extra = False,
    closing_costs      = 0,
    label              = "Original 7.99% (no refi)",
)

# ── Extended costs ─────────────────────────────────────────────────────────────

extended = ExtendedCosts(items=[
    AnnualItem("Tax",       {2022: 5_400, 2023: 5_600, 2024: 5_820}),
    AnnualItem("Insurance", {2024: 1_950}),
    AnnualItem("Warranty",  {2024:   600}),
    AnnualItem("Electric",  {2023: 1_920, 2024: 2_040}),
    AnnualItem("Gas",       {2023:   840, 2024:   900}),
    AnnualItem("Water",     {2024:   480}),
    AnnualItem("Sewer",     {2024:   300}),
    AnnualItem("Other",     {2024:   600}),
])

# ─────────────────────────────────────────────────────────────────────────────
# BUILD ANALYZER
# ─────────────────────────────────────────────────────────────────────────────

# Suppress the extra-payment servicer warning for this demo
# (in production you want to see it — remove the filter)
warnings.filterwarnings("ignore", category=UserWarning)

analyzer = EnhancedMortgageAnalyzer(
    loans          = [original_loan, refi_loan],
    refi_month     = 16,
    extended_costs = extended,
    shadow_loans   = [shadow_plain],
)

# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────────────────────

analyzer.print_summary()

# ─────────────────────────────────────────────────────────────────────────────
# DAY-COUNT COMPARISON
# Shows total interest cost under all three conventions for the original loan.
# ─────────────────────────────────────────────────────────────────────────────

print("\n─── DAY-COUNT CONVENTION COMPARISON (Original Loan) ───")
print(analyzer.compare_day_counts().to_string(index=False))

# ─────────────────────────────────────────────────────────────────────────────
# STUB PERIOD — first 3 months
# Notice month 1 has more interest than a standard first payment would,
# because it covers 46 days instead of ~31.
# ─────────────────────────────────────────────────────────────────────────────

print("\n─── STUB PERIOD: First 3 Months ───")
print(analyzer.mortgage_table(
    columns=[
        "months_elapsed", "date",
        "remaining_start_L1", "stub_days_L1",
        "monthly_payment_L1", "interest_L1", "principal_L1",
        "fee_charge_L1", "deferred_L1",
    ],
    end_month=3
).to_string(index=False))

# ─────────────────────────────────────────────────────────────────────────────
# DEFERMENT PERIOD — months 11-18
# Months 13-15 show deferred=True, zero principal reduction.
# Month 16: capitalized interest added to balance before refi.
# ─────────────────────────────────────────────────────────────────────────────

print("\n─── DEFERMENT WINDOW: Months 11–18 ───")
print(analyzer.mortgage_table(
    columns=[
        "months_elapsed", "date",
        "remaining_start_L1", "interest_L1", "principal_L1",
        "deferred_L1", "deferred_interest_L1", "capitalized_interest_L1",
        "remaining_start_L2", "monthly_payment_L2", "interest_L2", "principal_L2",
        "recast_payment_L2",
    ],
    start_month=11, end_month=18
).to_string(index=False))

# ─────────────────────────────────────────────────────────────────────────────
# RECAST IN ACTION — refi loan, first 6 months
# Each month with extra principal shows a lower recast_payment for next month.
# ─────────────────────────────────────────────────────────────────────────────

print("\n─── RECAST: Refi Loan First 12 Months ───")
print(analyzer.mortgage_table(
    columns=[
        "months_elapsed", "date",
        "remaining_start_L2", "monthly_payment_L2",
        "extra_payment_L2", "interest_L2", "principal_L2",
        "recast_payment_L2",
    ],
    start_month=17, end_month=28
).to_string(index=False))

# ─────────────────────────────────────────────────────────────────────────────
# FEE EVENTS — show around month 5 where the late fee appeared
# ─────────────────────────────────────────────────────────────────────────────

print("\n─── FEE EVENTS: Months 4–7 ───")
print(analyzer.mortgage_table(
    columns=[
        "months_elapsed", "date",
        "remaining_start_L1", "monthly_payment_L1",
        "fee_charge_L1", "fee_to_date_L1",
        "interest_L1", "principal_L1",
        "total_payment_L1",
    ],
    start_month=4, end_month=7
).to_string(index=False))

# ─────────────────────────────────────────────────────────────────────────────
# EXTENDED COSTS
# ─────────────────────────────────────────────────────────────────────────────

print("\n─── ANNUAL EXTENDED COST SUMMARY ───")
print(analyzer.annual_summary().to_string(index=False))

# ─────────────────────────────────────────────────────────────────────────────
# BREAK-EVEN
# ─────────────────────────────────────────────────────────────────────────────

be = analyzer.refi_breakeven_month
if be:
    be_row = analyzer.amortization[analyzer.amortization["months_elapsed"] == be]
    be_date = be_row["date"].iloc[0].strftime("%b %Y") if not be_row.empty else "N/A"
    print(f"\n  Refi break-even at months_elapsed = {be}  ({be_date})")
else:
    print("\n  Refi never breaks even within loan term.")

# ─────────────────────────────────────────────────────────────────────────────
# PLOTS
# ─────────────────────────────────────────────────────────────────────────────

df = analyzer.amortization
df["pi_to_date_L1"] = df["interest_to_date_L1"] + df["principal_to_date_L1"]
df["pi_to_date_L2"] = df["interest_to_date_L2"] + df["principal_to_date_L2"]
s0 = analyzer.shadow(0)
s0["pi_to_date"] = s0["interest_to_date"] + s0["principal_to_date"]

plot_scenarios(
    analyzer,
    groups=[
        {
            "label":      "Original 7.99%",
            "loan_idx":   1,
            "metrics":    ["remaining_start", "interest_to_date", "principal_to_date", "pi_to_date"],
            "base_color": "#1f6090",
        },
        {
            "label":      "Refi 4.33%",
            "loan_idx":   2,
            "metrics":    ["remaining_start", "interest_to_date", "principal_to_date", "pi_to_date"],
            "base_color": "#b04010",
        },
        {
            "label":      "Original 7.99% (no refi)",
            "shadow_idx": 0,
            "metrics":    ["remaining_start", "interest_to_date", "principal_to_date", "pi_to_date"],
            "base_color": "#555599",
        },
    ],
    save_path="mortgageEnhanced.png",
)

plot_extended_costs(analyzer, mode="annual", save_path="extCostsEnhanced.png")

print("\nDone.")
