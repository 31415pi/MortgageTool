"""
example_usage.py
================
Mortgage analysis for:
  - Original loan:  $375,888  @ 6.875%  opened 2025-01-01
  - Refinance:      $369,956  @ 6.05%   opened 2026-03-01  (month 14 of original)
  - Shadow:         original loan run to full term with NO refi (for comparison)

Run:
    pip install pandas numpy python-dateutil matplotlib
    python example_usage.py
"""

from datetime import date
import pandas as pd
pd.set_option("display.max_columns", None)
pd.set_option("display.width", 200)
pd.set_option("display.float_format", "{:,.2f}".format)

from mortgage_tool import (
    Loan, ExtraPayment, AnnualItem, ExtendedCosts,
    MortgageAnalyzer, plot_scenarios, plot_extended_costs
)

# ─────────────────────────────────────────────────────────────────────────────
# LOANS
# ─────────────────────────────────────────────────────────────────────────────

original_loan = Loan(
    principal     = 375_888,
    annual_rate   = 0.06875,
    term_months   = 360,
    start_date    = date(2025, 1, 1),
    label         = "Original 6.875%",
    closing_costs = 0,
    extra_payments = [
        # Uncomment to add extra principal payments:
        # ExtraPayment(amount=300, start_month=1,  end_month=12),
        # ExtraPayment(amount=150, start_month=25, end_month=None),
    ]
)

refi_loan = Loan(
    principal     = 369_956,
    annual_rate   = 0.0605,
    term_months   = 360,
    start_date    = date(2026, 3, 1),
    label         = "Refi 6.05%",
    closing_costs = 7_479.28,
    extra_payments = [
        ExtraPayment(amount=200, start_month=1, end_month=None),
    ]
)

# Shadow = original loan run to FULL 360-month completion, no refi.
# Used only for visual comparison in plots. Does not affect any calculations.
shadow_no_refi = Loan(
    principal     = 375_888,
    annual_rate   = 0.06875,
    term_months   = 360,
    start_date    = date(2025, 1, 1),
    label         = "Original 6.875% (no refi)",
    closing_costs = 0,
)

# ─────────────────────────────────────────────────────────────────────────────
# EXTENDED COSTS
# ─────────────────────────────────────────────────────────────────────────────

extended = ExtendedCosts(items=[
    AnnualItem("Tax",       {2025: 5_820}),
    AnnualItem("Insurance", {2025: 1_950}),
    AnnualItem("Warranty",  {2025:   600}),
    AnnualItem("Electric",  {2025: 2_040}),
    AnnualItem("Gas",       {2025:   900}),
    AnnualItem("Water",     {2025:   480}),
    AnnualItem("Sewer",     {2025:   300}),
    AnnualItem("Other",     {2025:   600}),
])

# ─────────────────────────────────────────────────────────────────────────────
# BUILD THE ANALYZER
# ─────────────────────────────────────────────────────────────────────────────

analyzer = MortgageAnalyzer(
    loans          = [original_loan, refi_loan],
    refi_month     = 13,
    extended_costs = extended,
    shadow_loans   = [shadow_no_refi],
)

# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────────────────────

analyzer.print_summary()

# ─────────────────────────────────────────────────────────────────────────────
# AMORTIZATION TABLE
# ─────────────────────────────────────────────────────────────────────────────

print("\n─── COMBINED AMORTIZATION TABLE (first 20 months) ───")
print(analyzer.mortgage_table(end_month=20).to_string(index=False))

print("\n─── CUSTOM: PI detail both loans ───")
print(analyzer.mortgage_table(
    columns=[
        "months_elapsed", "date",
        "remaining_start_L1", "monthly_payment_L1", "interest_L1",
        "interest_to_date_L1", "principal_L1", "principal_to_date_L1",
        "remaining_start_L2", "monthly_payment_L2", "interest_L2",
        "interest_to_date_L2", "principal_L2", "principal_to_date_L2",
    ],
    end_month=20
).to_string(index=False))

# ─────────────────────────────────────────────────────────────────────────────
# EXTENDED COST TABLE
# ─────────────────────────────────────────────────────────────────────────────

print("\n─── EXTENDED COSTS TABLE (first 18 months) ───")
print(analyzer.extended_table(
    columns=[
        "months_elapsed", "date",
        "Tax", "Tax_sum_yr", "Tax_to_date",
        "Insurance", "Insurance_sum_yr",
        "Electric", "Gas",
        "all_items_monthly", "all_items_sum_yr", "all_items_to_date",
    ],
    max_rows=18
).to_string(index=False))

print("\n─── PITI TABLE (first 24 months) ───")
print(analyzer.piti_table().head(24).to_string(index=False))

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
# FILTER TO A SINGLE YEAR
# ─────────────────────────────────────────────────────────────────────────────

print("\n─── EXTENDED COSTS FOR 2025 ONLY ───")
print(analyzer.extended_table(
    year=2025,
    columns=["months_elapsed","date","Tax","Insurance","Electric","Gas","Water","Sewer","all_items_monthly"]
).to_string(index=False))

# ─────────────────────────────────────────────────────────────────────────────
# PLOTS
# ─────────────────────────────────────────────────────────────────────────────

# Add cumulative P+I as a single combined column
df = analyzer.amortization
df["pi_to_date_L1"] = df["interest_to_date_L1"].fillna(0) + df["principal_to_date_L1"].fillna(0)
df["pi_to_date_L2"] = df["interest_to_date_L2"].fillna(0) + df["principal_to_date_L2"].fillna(0)

# Shadow df — referenced by index (0 = first shadow loan, no string matching needed)
shadow_df = analyzer.shadow(0)
shadow_df["pi_to_date"] = shadow_df["interest_to_date"] + shadow_df["principal_to_date"]

plot_scenarios(
    analyzer,
    groups=[
        {
            "label":      "Original 6.875%",
            "loan_idx":   1,
            "metrics":    ["remaining_start", "interest_to_date", "principal_to_date", "pi_to_date"],
            "base_color": "#1f6090",
        },
        {
            "label":      "Refi 6.05%",
            "loan_idx":   2,
            "metrics":    ["remaining_start", "interest_to_date", "principal_to_date", "pi_to_date"],
            "base_color": "#b04010",
        },
        {
            "label":      "Original 6.875% (no refi)",
            "shadow_idx": 0,        # ← integer index, no string matching required
            "metrics":    ["remaining_start", "interest_to_date", "principal_to_date", "pi_to_date"],
            "base_color": "#555599",
        },
    ],
    save_path="mortgage_scenario_plot.png",
)

plot_extended_costs(analyzer, mode="monthly",    save_path="extended_monthly.png")
plot_extended_costs(analyzer, mode="cumulative", save_path="extended_cumulative.png")
plot_extended_costs(analyzer, mode="annual",     save_path="extended_annual.png")

print("\nDone. Charts saved to disk.")
