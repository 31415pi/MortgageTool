"""
example_usage.py
================
Mortgage analysis for:
  - Original loan:  $675,420  @ 7.99%  opened 2024-01-01
    with $140/mo extra principal from day one
  - Refinance:      $666,080  @ 4.33%  opened 2025-05-01  (month 16 of original)
    with half the monthly savings ($821.65/mo) applied as extra principal
  - Shadow:         original loan run to full term with NO refi (for comparison)

Run:
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
    principal     = 675_420,
    annual_rate   = 0.0799,
    term_months   = 360,
    start_date    = date(2024, 1, 1),
    label         = "Original 7.99%",
    closing_costs = 0,
    extra_payments = [
        ExtraPayment(amount=140, start_month=1, end_month=None),
    ]
)

# Remaining balance at month 16 = $666,080.71
# Original payment: $4,951.29 | Refi payment: $3,307.99 | Difference: $1,643.30
# Half the difference applied as extra principal: $821.65/mo
refi_loan = Loan(
    principal     = 666_081,
    annual_rate   = 0.0433,
    term_months   = 360,
    start_date    = date(2025, 5, 1),
    label         = "Refi 4.33%",
    closing_costs = 8_500,
    extra_payments = [
        ExtraPayment(amount=821.65, start_month=1, end_month=None),
    ]
)

# Shadow = original loan run to full completion, no refi, for comparison plots
shadow_no_refi = Loan(
    principal     = 675_420,
    annual_rate   = 0.0799,
    term_months   = 360,
    start_date    = date(2024, 1, 1),
    label         = "Original 7.99% (no refi)",
    closing_costs = 0,
    extra_payments = [
        ExtraPayment(amount=140, start_month=1, end_month=None),
    ]
)

# ─────────────────────────────────────────────────────────────────────────────
# EXTENDED COSTS
# Supply known historical years; linear regression projects the rest forward.
# One data point = flat/no-growth assumption.
# ─────────────────────────────────────────────────────────────────────────────

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
# BUILD THE ANALYZER
# ─────────────────────────────────────────────────────────────────────────────

analyzer = MortgageAnalyzer(
    loans          = [original_loan, refi_loan],
    refi_month     = 16,
    extended_costs = extended,
    shadow_loans   = [shadow_no_refi],
)

# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────────────────────

analyzer.print_summary()

# ─────────────────────────────────────────────────────────────────────────────
# AMORTIZATION TABLE — first 20 months (straddles the refi at month 16)
# Months 1-16:  L1 columns populated, L2 empty
# Months 17+:   L2 columns populated, L1 empty
# ─────────────────────────────────────────────────────────────────────────────

print("\n─── COMBINED AMORTIZATION TABLE (first 20 months) ───")
print(analyzer.mortgage_table(end_month=20).to_string(index=False))

# ─────────────────────────────────────────────────────────────────────────────
# CUSTOM COLUMNS
# ─────────────────────────────────────────────────────────────────────────────

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

# ─────────────────────────────────────────────────────────────────────────────
# PITI TABLE
# ─────────────────────────────────────────────────────────────────────────────

print("\n─── PITI TABLE (first 24 months) ───")
print(analyzer.piti_table().head(24).to_string(index=False))

# ─────────────────────────────────────────────────────────────────────────────
# ANNUAL SUMMARY
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
# FILTER TO A SINGLE YEAR
# ─────────────────────────────────────────────────────────────────────────────

print("\n─── EXTENDED COSTS FOR 2024 ONLY ───")
print(analyzer.extended_table(
    year=2024,
    columns=["months_elapsed","date","Tax","Insurance","Electric","Gas","Water","Sewer","all_items_monthly"]
).to_string(index=False))

# ─────────────────────────────────────────────────────────────────────────────
# PLOTS
# ─────────────────────────────────────────────────────────────────────────────

# Add combined cumulative P+I column (drop fillna so line stops cleanly at refi)
df = analyzer.amortization
df["pi_to_date_L1"] = df["interest_to_date_L1"] + df["principal_to_date_L1"]
df["pi_to_date_L2"] = df["interest_to_date_L2"] + df["principal_to_date_L2"]

shadow_df = analyzer.shadow(0)
shadow_df["pi_to_date"] = shadow_df["interest_to_date"] + shadow_df["principal_to_date"]

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
    save_path="mortgageScenario.png",
)

plot_extended_costs(analyzer, mode="monthly",    save_path="extCostsMonthly.png")
plot_extended_costs(analyzer, mode="cumulative", save_path="extCostsCumul.png")
plot_extended_costs(analyzer, mode="annual",     save_path="extCostsAnnual.png")

print("\nDone. Charts saved to disk.")
