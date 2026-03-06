# mortgage_tool.py

A Python toolkit for mortgage amortization, refinancing analysis, and true cost of homeownership. Built around pandas DataFrames so every table is directly sliceable, filterable, and exportable.

---

## What it does

- Builds a full amortization schedule for any fixed-rate mortgage
- Supports principal-only extra payments, specifiable by month range
- Models a refinance as two sequential loan instruments in one combined table — the original loan truncates at the refi month, the new loan picks up from there, and a global `months_elapsed` counter runs continuously across both
- Computes the true refi break-even point: the month at which cumulative interest savings exceed closing costs
- Projects recurring homeownership costs (tax, insurance, utilities, warranty, etc.) forward using linear regression fitted to your historical data
- Produces PITI tables, annual summaries, and cumulative running totals for any cost item
- Plots scenarios with grouped color families and gradient shading per metric, including a "shadow" counterfactual line showing what the original loan would have cost if you never refinanced

---

## Installation

```bash
pip install pandas numpy python-dateutil matplotlib
```

Both files go in the same directory:

```
your_project/
├── mortgage_tool.py
└── example_usage.py
```

---

## Core concepts

### Loan

The fundamental building block. One `Loan` = one mortgage instrument.

```python
from mortgage_tool import Loan

my_loan = Loan(
    principal     = 375888,       # loan amount after down payment
    annual_rate   = 0.06875,      # 6.875% as a decimal
    term_months   = 360,          # 30 years
    start_date    = date(2025, 1, 1),
    label         = "anything you want",   # cosmetic only, no functional role
    closing_costs = 0,            # used in break-even calc
)
```

`label` is purely display text. It appears in the summary printout and plot legends. It is never used as a lookup key and does not need to be unique or match anything else.

### ExtraPayment

Specifies a principal-only extra payment active during a month range, relative to that loan's start.

```python
from mortgage_tool import ExtraPayment

ExtraPayment(amount=300, start_month=1,  end_month=12)   # extra $300/mo for year 1
ExtraPayment(amount=150, start_month=25, end_month=None) # extra $150/mo from month 25, forever
```

Multiple `ExtraPayment` rules can be stacked on a single loan — they add together in any month where ranges overlap.

### AnnualItem + ExtendedCosts

Any recurring annual homeownership cost. Supply one or more historical years; the tool fits a linear regression and projects forward for the life of the loan. One data point means flat/no-growth.

```python
from mortgage_tool import AnnualItem, ExtendedCosts

extended = ExtendedCosts(items=[
    AnnualItem("Tax",       {2023: 5400, 2024: 5600, 2025: 5820}),  # growing ~$200/yr
    AnnualItem("Insurance", {2025: 1950}),                           # flat, one data point
    AnnualItem("Electric",  {2024: 1920, 2025: 2040}),
    AnnualItem("Gas",       {2025: 900}),
    AnnualItem("Water",     {2025: 480}),
    AnnualItem("Sewer",     {2025: 300}),
    AnnualItem("Warranty",  {2025: 600}),
    AnnualItem("Other",     {2025: 600}),
])
```

Item names are arbitrary — use whatever makes sense to you.

### MortgageAnalyzer

The main engine. Pass it one loan for a simple schedule, or two loans + a `refi_month` for a refinance scenario.

```python
from mortgage_tool import MortgageAnalyzer

analyzer = MortgageAnalyzer(
    loans          = [original_loan, refi_loan],
    refi_month     = 13,           # refi takes effect after month 13 of the original
    extended_costs = extended,     # optional
    shadow_loans   = [shadow_loan] # optional, see below
)
```

**Shadow loans** are full-term counterfactual loans used only for plotting — they let you draw "what would have happened without the refi" as a comparison line. They have no effect on tables or calculations.

```python
shadow_no_refi = Loan(
    principal   = 375888,
    annual_rate = 0.06875,
    term_months = 360,
    start_date  = date(2025, 1, 1),
    label       = "whatever",
)
```

---

## Tables

### Amortization table

```python
analyzer.mortgage_table()                        # all columns, all months
analyzer.mortgage_table(end_month=24)            # first 2 years
analyzer.mortgage_table(start_month=10, end_month=20)
```

**Column naming convention:**

| Column | Description |
|---|---|
| `months_elapsed` | Global month counter across all loans |
| `date` | Calendar date of that payment |
| `remaining_start_L1` | Balance at start of month (original loan) |
| `monthly_payment_L1` | Scheduled PI payment |
| `extra_payment_L1` | Extra principal-only payment |
| `total_payment_L1` | monthly_payment + extra_payment |
| `interest_L1` | Interest portion |
| `interest_to_date_L1` | Cumulative interest for this loan |
| `principal_L1` | Principal portion (including extra) |
| `principal_to_date_L1` | Cumulative principal for this loan |
| `label_L1` | The loan's label string |

`_L1` = original loan, `_L2` = refi loan, `_L3` = a third loan if you ever add one. Months where a loan is not active have `NaN` in its columns — this is intentional and expected. Months 1–13 fill L1; month 14 onward fills L2.

**Custom column selection:**

```python
analyzer.mortgage_table(columns=[
    "months_elapsed", "date",
    "remaining_start_L1", "interest_L1", "principal_L1",
    "remaining_start_L2", "interest_L2", "principal_L2",
])
```

### Extended cost table

```python
analyzer.extended_table()                        # all columns
analyzer.extended_table(year=2025)               # single calendar year
analyzer.extended_table(columns=["date","Tax","Tax_sum_yr","Tax_to_date","all_items_monthly"])
```

| Column pattern | Description |
|---|---|
| `{Item}` | Monthly cost (e.g. `Tax`, `Electric`) |
| `{Item}_sum_yr` | Running year-to-date total |
| `{Item}_to_date` | Life-of-loan cumulative total |
| `all_items_monthly` | Sum of all items this month |
| `all_items_sum_yr` | Sum of all items year-to-date |
| `all_items_to_date` | Sum of all items life-to-date |

### PITI table

Principal + Interest + Tax + Insurance with running totals.

```python
analyzer.piti_table()
```

### Annual summary

```python
analyzer.annual_summary()                        # all items
analyzer.annual_summary(items=["Tax","Electric"]) # specific items
```

### Raw DataFrames

All tables are plain pandas DataFrames. Access them directly for full pandas power:

```python
df  = analyzer.amortization    # combined amort table
ec  = analyzer.extended        # extended costs table
s0  = analyzer.shadow(0)       # first shadow loan (by index)

# Total interest paid across both loans
total = df["interest_L1"].fillna(0).sum() + df["interest_L2"].fillna(0).sum()

# Pivot extended costs by year
ec["year"] = pd.to_datetime(ec["date"]).dt.year
pivot = ec.pivot_table(index="year",
    values=["Tax","Insurance","Electric"], aggfunc="sum")

# Add a combined cumulative P+I column
df["pi_to_date_L1"] = df["interest_to_date_L1"].fillna(0) + df["principal_to_date_L1"].fillna(0)
df["pi_to_date_L2"] = df["interest_to_date_L2"].fillna(0) + df["principal_to_date_L2"].fillna(0)
```

---

## Summary and break-even

```python
analyzer.print_summary()
# Prints: true lifetime months/years, total interest per loan,
#         total paid per loan, closing costs, refi break-even month and date

be = analyzer.refi_breakeven_month   # months_elapsed integer, or None
```

The break-even is calculated by comparing cumulative interest savings on the refi vs. the closing costs. The month where savings >= closing costs is the break-even.

---

## Plots

### Scenario plot

```python
from mortgage_tool import plot_scenarios

plot_scenarios(analyzer)   # auto-generates one group per loan
```

Custom groups with full color and metric control:

```python
# First add any derived columns you want to plot
df = analyzer.amortization
df["pi_to_date_L1"] = df["interest_to_date_L1"].fillna(0) + df["principal_to_date_L1"].fillna(0)
df["pi_to_date_L2"] = df["interest_to_date_L2"].fillna(0) + df["principal_to_date_L2"].fillna(0)

shadow_df = analyzer.shadow(0)
shadow_df["pi_to_date"] = shadow_df["interest_to_date"] + shadow_df["principal_to_date"]

plot_scenarios(
    analyzer,
    groups=[
        {
            "label":      "Original 6.875%",
            "loan_idx":   1,                  # references L1 columns
            "metrics":    ["remaining_start", "interest_to_date", "principal_to_date", "pi_to_date"],
            "base_color": "#1f6090",          # any matplotlib color string
        },
        {
            "label":      "Refi 6.05%",
            "loan_idx":   2,                  # references L2 columns
            "metrics":    ["remaining_start", "interest_to_date", "principal_to_date", "pi_to_date"],
            "base_color": "#b04010",
        },
        {
            "label":      "Original (no refi)",
            "shadow_idx": 0,                  # 0-based index into shadow_loans list
            "metrics":    ["remaining_start", "interest_to_date", "principal_to_date", "pi_to_date"],
            "base_color": "#555599",
        },
    ],
    save_path="my_plot.png",   # optional
    figsize=(18, 10),          # optional
)
```

Each group gets a distinct base color. Metrics within a group get gradient shades of that color plus different line styles and markers so they're distinguishable. Shadow loan lines are automatically rendered thinner, dashed, and slightly faded so they recede visually behind the real scenario lines.

`loan_idx` is 1-based (L1, L2, ...). `shadow_idx` is 0-based (first shadow loan = 0).

Any column that exists in the DataFrame can be a metric — including custom ones you add yourself.

### Extended cost plots

```python
from mortgage_tool import plot_extended_costs

plot_extended_costs(analyzer, mode="monthly")     # monthly cost per item
plot_extended_costs(analyzer, mode="cumulative")  # running totals
plot_extended_costs(analyzer, mode="annual")      # stacked bar by year

plot_extended_costs(analyzer, mode="annual",
    items=["Tax", "Insurance", "Electric"],       # subset of items
    save_path="costs.png")
```

---

## Example walkthrough

`example_usage.py` models this scenario:

- **Original loan:** $375,888 at 6.875%, opened January 2025, 30-year term, no extra payments
- **Refinance:** $369,956 at 6.05% (the remaining balance after 13 months), opened March 2026, 30-year term, with $200/month extra principal from day one
- **Shadow loan:** The same original loan run to full 360-month completion with no refi — used only as a comparison line in plots
- **Extended costs:** Tax, insurance, electric, gas, water, sewer, warranty, and other — all anchored to 2025 values with flat projection (single data point each)

The script in order:

1. Defines the three loans and extended costs
2. Builds the analyzer with `refi_month=13`
3. Prints the summary — true lifetime, total interest per loan, closing costs, break-even
4. Prints the combined amortization table for the first 20 months — you can see L1 columns active for months 1–13, then L2 columns take over at month 14
5. Prints a custom column selection showing just the core PI metrics for both loans side by side
6. Prints the extended cost table for the first 18 months
7. Prints the PITI table (PI + tax + insurance) for the first 24 months
8. Prints the annual cost summary
9. Reports the break-even month
10. Filters extended costs to 2025 only
11. Adds `pi_to_date` columns (cumulative P+I combined) to the amortization DataFrame and shadow DataFrame
12. Generates the main scenario plot with all three groups
13. Generates monthly, cumulative, and annual extended cost plots

The $200/month extra payment on the refi is why the true lifetime is ~304 months instead of 373 (13 + 360) — extra principal payments accelerate payoff. Remove the `ExtraPayment` from `refi_loan` to see the unaccelerated full term.

---

## Quick reference

```python
# Key numbers
analyzer.refi_breakeven_month        # int: months_elapsed at break-even
analyzer.summary()                   # dict of all key metrics
analyzer.print_summary()             # formatted printout

# Tables
analyzer.mortgage_table(...)         # amortization (L1, L2 columns)
analyzer.extended_table(...)         # extended costs
analyzer.piti_table()                # PI + Tax + Insurance
analyzer.annual_summary(items=[...]) # year-by-year cost totals

# Raw DataFrames
analyzer.amortization                # full combined amort table
analyzer.extended                    # full extended cost table
analyzer.shadow(0)                   # first shadow loan DataFrame
analyzer.shadow_schedules            # dict keyed by index or label string

# Plots
plot_scenarios(analyzer, groups=[...], save_path="...", figsize=(...))
plot_extended_costs(analyzer, mode="monthly"|"cumulative"|"annual", items=[...])
```
