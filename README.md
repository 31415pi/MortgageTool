# MortgageTool

**Full-lifecycle mortgage analysis in Python.** Amortization schedules, refinance modeling, true cost of ownership, break-even analysis, and publication-quality plots — all in a single script built on pandas DataFrames.

Built by [Hellomoto1123](https://github.com/31415pi)

---

## Quickstart

```bash
git clone https://github.com/31415pi/MortgageTool.git
cd MortgageTool
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python example_usage.py
```

That's it. Four charts will be saved to your working directory and a full summary will print to the terminal.

---

## What it does

- Builds a complete amortization schedule for any fixed-rate mortgage
- Models principal-only extra payments, specifiable by month range — pay extra for a year, stop, restart later
- Handles refinancing as two sequential loan instruments in one unified table: the original loan truncates at the refi month, the new loan picks up, and a single `months_elapsed` counter runs across both — so the true lifetime is always visible
- Calculates the refi break-even point: the exact month where cumulative interest savings exceed closing costs
- Projects any recurring homeownership cost (tax, insurance, utilities, warranty, etc.) forward using linear regression fitted to your historical data
- Produces PITI tables, year-by-year cost summaries, and life-to-date running totals
- Plots multiple scenarios in grouped color families with a "shadow" counterfactual line showing what the original loan would have cost without a refinance

---

## For experienced users

If you know what an amortization schedule is and just want to get oriented fast:

```python
from mortgage_tool import Loan, ExtraPayment, AnnualItem, ExtendedCosts, MortgageAnalyzer, plot_scenarios

analyzer = MortgageAnalyzer(
    loans=[original_loan, refi_loan],   # sequential instruments
    refi_month=16,                       # original truncates here
    extended_costs=extended,             # tax, insurance, utilities, etc.
    shadow_loans=[shadow_no_refi],       # counterfactual for plots
)

analyzer.print_summary()
analyzer.mortgage_table(end_month=24)   # pandas DataFrame, slice freely
analyzer.refi_breakeven_month           # int: months_elapsed at break-even
```

Column naming convention — `_L1` = first loan, `_L2` = refi loan:

| Column | Description |
|---|---|
| `remaining_start_L{n}` | Balance at start of month |
| `monthly_payment_L{n}` | Scheduled PI payment |
| `extra_payment_L{n}` | Extra principal-only payment |
| `total_payment_L{n}` | monthly + extra |
| `interest_L{n}` / `interest_to_date_L{n}` | Monthly / cumulative interest |
| `principal_L{n}` / `principal_to_date_L{n}` | Monthly / cumulative principal |

Extended cost columns follow the same pattern: `Tax`, `Tax_sum_yr`, `Tax_to_date`, `all_items_monthly`, `all_items_to_date`.

Jump to [Plotting](#plotting) or [Full API Reference](#full-api-reference) below.

---

## Installation

### Requirements

```
pandas
numpy
python-dateutil
matplotlib
```

### Setup

```bash
# 1. Clone the repo
git clone https://github.com/31415pi/MortgageTool.git
cd MortgageTool

# 2. Create and activate a virtual environment
python -m venv .venv

# macOS / Linux
source .venv/bin/activate

# Windows
.venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the example
python example_usage.py
```

> **💡 What's a virtual environment?**
> It's an isolated Python installation just for this project — keeps dependencies from conflicting with anything else on your machine. The `deactivate` command exits it when you're done.

---

## The example explained

`example_usage.py` walks through a realistic scenario end-to-end:

- **Original loan:** $675,420 at 7.99%, opened January 2024, 30-year term, with $140/month extra principal from day one
- **Refinance:** after 16 months, the remaining balance ($666,081) is refinanced to 4.33%, new 30-year term, $8,500 closing costs — and half the monthly savings ($821.65/mo) is applied as extra principal
- **Shadow loan:** the original 7.99% loan run to full completion with no refinance, used only as a visual comparison in plots

### Defining loans

```python
from datetime import date
from mortgage_tool import Loan, ExtraPayment

original_loan = Loan(
    principal     = 675_420,      # underscores are optional — purely visual
    annual_rate   = 0.0799,       # 7.99% as a decimal
    term_months   = 360,
    start_date    = date(2024, 1, 1),
    label         = "Original 7.99%",   # cosmetic only — no functional role
    closing_costs = 0,
    extra_payments = [
        ExtraPayment(amount=140, start_month=1, end_month=None),  # $140/mo forever
    ]
)

refi_loan = Loan(
    principal     = 666_081,      # remaining balance from amortization table at month 16
    annual_rate   = 0.0433,
    term_months   = 360,
    start_date    = date(2025, 5, 1),
    label         = "Refi 4.33%",
    closing_costs = 8_500,
    extra_payments = [
        ExtraPayment(amount=821.65, start_month=1, end_month=None),
    ]
)
```

> **💡 Finding the refi principal**
> Run the original loan alone first with `analyzer.mortgage_table()`, find the `remaining_start_L1` value at your refi month, and use that as the refi `principal`.

`label` is purely display text for legends and summary printouts. It is never used as a lookup key and does not need to match anything else.

`ExtraPayment` month numbers are relative to that loan's start — month 1 of the refi is the first payment on the new loan, not month 17 of the overall timeline.

Multiple `ExtraPayment` rules can be stacked and will add together in overlapping months:

```python
extra_payments = [
    ExtraPayment(amount=500, start_month=1,  end_month=12),   # aggressive year 1
    ExtraPayment(amount=200, start_month=13, end_month=None),  # steady thereafter
]
```

### Extended costs

Supply one or more historical annual values per cost item. The tool fits a linear regression and projects forward for the life of the loan. One data point means flat/no-growth.

```python
from mortgage_tool import AnnualItem, ExtendedCosts

extended = ExtendedCosts(items=[
    AnnualItem("Tax",       {2022: 5_400, 2023: 5_600, 2024: 5_820}),  # 3 years → regression
    AnnualItem("Insurance", {2024: 1_950}),                              # 1 year → flat
    AnnualItem("Electric",  {2023: 1_920, 2024: 2_040}),
    AnnualItem("Gas",       {2023:   840, 2024:   900}),
    AnnualItem("Water",     {2024:   480}),
    AnnualItem("Sewer",     {2024:   300}),
    AnnualItem("Warranty",  {2024:   600}),
    AnnualItem("Other",     {2024:   600}),
])
```

> **⚠️ One `AnnualItem` per category.** Put all historical years for a single cost in one dict. If you create two `AnnualItem("Tax", ...)` entries, "Tax" will appear twice in your charts.

Item names are arbitrary — name them whatever makes sense to you.

### Building the analyzer

```python
from mortgage_tool import MortgageAnalyzer

analyzer = MortgageAnalyzer(
    loans          = [original_loan, refi_loan],
    refi_month     = 16,            # original loan truncates after this month
    extended_costs = extended,
    shadow_loans   = [shadow_no_refi],
)
```

For a single loan with no refinance, just pass `loans=[my_loan]` and omit `refi_month`.

**Shadow loans** are full-term counterfactual loans. They do not affect any calculations or tables — they exist only to draw a "what-if" comparison line on plots. Reference them by 0-based index: `shadow_idx: 0`.

### Summary output

```
analyzer.print_summary()
```

```
============================================================
  MORTGAGE ANALYSIS SUMMARY
============================================================
  True Lifetime Months                       259
  True Lifetime Years                        21.58
  Total Interest Original 7.99%              71,464.98
  Total Paid Original 7.99%                  81,460.64
  Closing Costs Original 7.99%               0
  Total Interest Refi 4.33%                  334,008.66
  Total Paid Refi 4.33%                      1,008,589.97
  Closing Costs Refi 4.33%                   8,500
  Refi Breakeven Months Elapsed              21
  Refi Breakeven Date                        2025-09-01
  Total Extended Costs                       360,497.48
============================================================
```

True lifetime of 259 months (21.6 years) vs the theoretical 376 (16 + 360) — entirely due to the $821.65/mo extra principal on the refi accelerating payoff.

---

## Tables

### Amortization table

```python
analyzer.mortgage_table()                         # all columns, full life
analyzer.mortgage_table(end_month=24)             # first 2 years
analyzer.mortgage_table(start_month=10, end_month=20)

# Pick exactly the columns you want
analyzer.mortgage_table(columns=[
    "months_elapsed", "date",
    "remaining_start_L1", "interest_L1", "principal_L1",
    "remaining_start_L2", "interest_L2", "principal_L2",
])
```

Months where a loan is not active show `NaN` — this is expected. Months 1–16 fill L1 columns; month 17 onward fills L2.

### Extended cost table

```python
analyzer.extended_table(max_rows=18)
analyzer.extended_table(year=2024)    # single calendar year
analyzer.extended_table(columns=["date","Tax","Tax_sum_yr","Tax_to_date","all_items_monthly"])
```

### PITI table

Principal + Interest + Tax + Insurance with running totals in one view.

```python
analyzer.piti_table()
```

### Annual summary

```python
analyzer.annual_summary()                          # all items, every year
analyzer.annual_summary(items=["Tax","Electric"])  # subset
```

### Raw DataFrames

Every table is a plain pandas DataFrame. Access them directly for full pandas power:

```python
df  = analyzer.amortization   # full combined amortization table
ec  = analyzer.extended        # full extended costs table
s0  = analyzer.shadow(0)       # first shadow loan schedule

# Add a combined cumulative P+I column
df["pi_to_date_L1"] = df["interest_to_date_L1"] + df["principal_to_date_L1"]
df["pi_to_date_L2"] = df["interest_to_date_L2"] + df["principal_to_date_L2"]

# Total interest across both loans
total = df["interest_L1"].fillna(0).sum() + df["interest_L2"].fillna(0).sum()

# Pivot extended costs by year
import pandas as pd
ec["year"] = pd.to_datetime(ec["date"]).dt.year
pivot = ec.pivot_table(index="year",
    values=["Tax","Insurance","Electric"], aggfunc="sum")
```

---

## Plotting

### Scenario plot

![Mortgage Scenario Analysis](https://github.com/31415pi/MortgageTool/blob/main/IMG/mortgageScenario.png)

Each loan instrument gets a distinct **color family**. Metrics within a group share that family with gradient shading and different line styles so they're distinguishable at a glance. Shadow loan lines are thinner, dashed, and slightly faded so they recede visually behind the real scenarios.

**What to look for:**

| Element | What it tells you |
|---|---|
| **Remaining balance lines** (solid, top-left to bottom-right) | How fast principal is being paid down — steeper = faster |
| **Interest to date** (rising curve) | Total interest cost accumulated — the gap between the original and refi versions is money saved |
| **Principal to date** (rising curve) | Equity built — where this crosses interest-to-date is the crossover point |
| **PI to date** (combined cumulative) | Total cash out the door for principal + interest together |
| **Dashed gold vertical line** | Refi break-even — the month where interest savings have covered closing costs |
| **Shadow lines** (faded, runs full term) | What the original loan would have cost with no refinance |

```python
# Add the combined PI column first
df = analyzer.amortization
df["pi_to_date_L1"] = df["interest_to_date_L1"] + df["principal_to_date_L1"]
df["pi_to_date_L2"] = df["interest_to_date_L2"] + df["principal_to_date_L2"]
analyzer.shadow(0)["pi_to_date"] = (analyzer.shadow(0)["interest_to_date"]
                                  + analyzer.shadow(0)["principal_to_date"])

plot_scenarios(
    analyzer,
    groups=[
        {
            "label":      "Original 7.99%",
            "loan_idx":   1,              # references _L1 columns
            "metrics":    ["remaining_start", "interest_to_date",
                           "principal_to_date", "pi_to_date"],
            "base_color": "#1f6090",      # any matplotlib color string
        },
        {
            "label":      "Refi 4.33%",
            "loan_idx":   2,              # references _L2 columns
            "metrics":    ["remaining_start", "interest_to_date",
                           "principal_to_date", "pi_to_date"],
            "base_color": "#b04010",
        },
        {
            "label":      "Original 7.99% (no refi)",
            "shadow_idx": 0,              # 0-based index into shadow_loans
            "metrics":    ["remaining_start", "interest_to_date",
                           "principal_to_date", "pi_to_date"],
            "base_color": "#555599",
        },
    ],
    save_path="mortgageScenario.png",
    figsize=(18, 10),
)
```

Any column that exists in the DataFrame — including custom ones you compute yourself — can be added to `metrics`.

### Extended cost plots

Three modes, one function:

```python
from mortgage_tool import plot_extended_costs

plot_extended_costs(analyzer, mode="monthly")     # monthly cost per item
plot_extended_costs(analyzer, mode="cumulative")  # running life-to-date totals
plot_extended_costs(analyzer, mode="annual")      # stacked bar chart by year

# Subset of items only
plot_extended_costs(analyzer, mode="annual",
    items=["Tax", "Insurance", "Electric"],
    save_path="costs.png")
```

**Monthly** — ![Monthly Extended Costs](https://github.com/31415pi/MortgageTool/blob/main/IMG/extCostsMonthly.png)

Shows each cost item as a separate line across the life of the loan. Flat lines are items with one historical data point (no-growth assumption). Rising lines are items where the regression found an upward trend.

**Cumulative** — ![Cumulative Extended Costs](https://github.com/31415pi/MortgageTool/blob/main/IMG/extCostsCumul.png)

Running totals over the loan lifetime. Useful for seeing total tax paid to date, total utilities, total true cost of ownership.

**Annual** — ![Annual Extended Costs](https://github.com/31415pi/MortgageTool/blob/main/IMG/extCostsAnnual.png)

Stacked bar chart by calendar year. The last bar is shorter because the loan pays off mid-year. Each color segment is one cost category — the total bar height is your total non-PI homeownership spend for that year.

---

## Full API reference

### Quick reference card

```python
# Key numbers
analyzer.refi_breakeven_month         # int: months_elapsed at break-even, or None
analyzer.summary()                    # dict of all key metrics
analyzer.print_summary()              # formatted printout to terminal

# Tables — all return pandas DataFrames
analyzer.mortgage_table(              # full amortization (L1/L2 columns)
    columns=[...],                    # optional column subset
    start_month=1, end_month=None,    # optional month range filter
    max_rows=None                     # optional row cap
)
analyzer.extended_table(              # extended costs
    columns=[...], year=None, max_rows=None
)
analyzer.piti_table()                 # PI + Tax + Insurance + running totals
analyzer.annual_summary(items=[...])  # year-by-year cost totals

# Raw DataFrames
analyzer.amortization                 # full combined amort table
analyzer.extended                     # full extended costs table
analyzer.shadow(0)                    # shadow loan by 0-based index
analyzer.shadow_schedules             # dict keyed by index or label string

# Plots
plot_scenarios(analyzer,
    groups=[...],                     # list of group dicts (see above)
    save_path="file.png",             # optional
    figsize=(18, 10)                  # optional
)
plot_extended_costs(analyzer,
    mode="monthly"|"cumulative"|"annual",
    items=[...],                      # optional subset
    save_path="file.png"              # optional
)
```

### All columns reference

**Amortization** (`_L1` = original, `_L2` = refi, `_L3` = third loan if applicable):

| Column | Description |
|---|---|
| `months_elapsed` | Global month counter across all loans |
| `date` | Calendar date of that payment |
| `remaining_start_L{n}` | Balance at start of month |
| `monthly_payment_L{n}` | Scheduled PI payment (fixed) |
| `extra_payment_L{n}` | Extra principal-only payment |
| `total_payment_L{n}` | monthly_payment + extra_payment |
| `interest_L{n}` | Interest portion this month |
| `interest_to_date_L{n}` | Cumulative interest for this loan |
| `principal_L{n}` | Principal portion this month (incl. extra) |
| `principal_to_date_L{n}` | Cumulative principal for this loan |
| `label_L{n}` | The loan's label string |

**Extended costs:**

| Column | Description |
|---|---|
| `{Item}` | Monthly cost (e.g. `Tax`, `Electric`) |
| `{Item}_sum_yr` | Running year-to-date total |
| `{Item}_to_date` | Life-of-loan cumulative total |
| `all_items_monthly` | Sum of all items this month |
| `all_items_sum_yr` | Sum of all items year-to-date |
| `all_items_to_date` | Sum of all items life-to-date |

---

## License

Private use is unrestricted. Commercial use requires a license.
Contact **hellomoto1123@gmail.com** — see [LICENSE.md](LICENSE.md) for full terms.

---

---

# Enhanced Features

`mortgage_tool_enhanced.py` adds a second modeling layer for users who need real-world precision beyond rate, term, and principal. All base tool features carry over — the enhanced analyzer produces identical tables, plots, and summary output. You only configure the features you need; everything else defaults to standard behavior.

```bash
# Same setup — both files live in the same directory
python example_enhanced.py
```

```python
# One import replaces the base import entirely
from mortgage_tool_enhanced import (
    EnhancedLoan, FeeEvent, Deferment, ExtraPayment,
    AnnualItem, ExtendedCosts,
    EnhancedMortgageAnalyzer, plot_scenarios, plot_extended_costs,
)
```

---

## Enhanced features overview

### 1. Stub period — per-diem first payment

When a loan is funded mid-month, the first payment period covers more (or fewer) than 30 days. Interest accrues daily from the funding date to the first payment date. Every subsequent period uses standard monthly scheduling.

```python
EnhancedLoan(
    start_date         = date(2024, 1, 15),   # funded Jan 15
    first_payment_date = date(2024, 3, 1),    # first payment Mar 1 → 46-day stub
    ...
)
```

The `stub_days` column in the amortization table shows the actual day count for month 1. In the example scenario this produces **$6,813 in first-period interest** versus the ~$4,500 a standard 30-day period would generate — a $2,300 difference on the very first payment.

> **💡 Why do lenders offer this?**
> An extended first period is often presented as "skip a payment" relief. In reality, interest accrues the entire time. You pay more first-period interest, not less.

### 2. Day-count convention

Controls how daily interest is calculated. The difference is real money over a 30-year loan.

```python
EnhancedLoan(
    day_count = "actual/365",   # default — calendar days / 365
    day_count = "actual/360",   # calendar days / 360 — slightly higher daily rate
    day_count = "30/360",       # each month treated as 30 days
    ...
)
```

Use `compare_day_counts()` to see the dollar impact across all three conventions for your specific loan:

```python
print(analyzer.compare_day_counts())
```

Example output for a $675,420 loan at 7.99%:

```
   day_count  total_interest  total_payments  payoff_months  vs_actual365
  actual/365    1,120,510.20    1,787,482.01            360          0.00
  actual/360    1,200,134.52    1,787,576.63            360     79,624.32
      30/360    1,115,884.49    1,787,576.63            360     -4,625.71
```

> **⚠️ actual/360 costs $79,624 more** over 30 years than actual/365 at the same nominal rate. This convention is common in commercial lending and some refi products. Check your note.

### 3. Capitalized origination fees

Fees rolled into the loan balance rather than paid at closing. Increases the opening principal and therefore every interest calculation for the life of the loan.

```python
EnhancedLoan(
    principal        = 675_420,
    capitalized_fees = 1_200,    # opening balance becomes $676,620
    ...
)
```

Separate from `closing_costs`, which represents out-of-pocket costs used only in the break-even calculation and does not affect the balance.

### 4. One-time fee events

Single charges applied in a specific month — late fees, annual service charges, etc. Standard payment application priority applies: fees collected first, then interest, then principal.

```python
EnhancedLoan(
    fee_events = [
        FeeEvent(month=5,  amount=35,  label="Late Fee"),
        FeeEvent(month=12, amount=75,  label="Annual Service Charge"),
        FeeEvent(month=1,  amount=500, label="Processing Fee", capitalize=True),
    ],
    ...
)
```

`capitalize=True` adds the fee to the balance. `capitalize=False` (default) collects it as additional cash that month.

The `fee_charge` and `fee_to_date` columns track these in the amortization table:

```
 months_elapsed  fee_charge_L1  fee_to_date_L1  total_payment_L1
              4           0.00            0.00          5,100.08
              5          35.00           35.00          5,135.08
              6           0.00           35.00          5,100.08
```

### 5. Deferment and forbearance

Suspends scheduled payments for a defined window. Interest continues accruing. At resumption, deferred interest either capitalizes into the balance or is collected as a lump sum.

```python
EnhancedLoan(
    deferments = [
        # 3-month forbearance, interest capitalizes (common in hardship programs)
        Deferment(start_month=13, num_months=3, capitalize_interest=True),

        # 6-month deferment, interest billed at resumption
        Deferment(start_month=7, num_months=6, capitalize_interest=False),
    ],
    ...
)
```

Deferred months appear in the table with `deferred=True` and zero principal reduction. The month payments resume shows `capitalized_interest` — the amount added to the balance:

```
 months_elapsed  deferred_L1  deferred_interest_L1  capitalized_interest_L1  remaining_start_L1
             13         True              4,107.07                      0.00          670,069.17
             14         True              4,547.11                      0.00          670,069.17
             15         True              4,400.43                      0.00          670,069.17
             16        False                  0.00                 13,054.60          683,123.77
```

In this example, three months of forbearance added **$13,054 to the balance** — money that now accrues interest for the remaining life of the loan.

> **⚠️ Forbearance is not forgiveness.** Balance grew from $670,069 to $683,123 during the deferment. That $13,054 will generate additional interest for the rest of the loan term.

### 6. Loan recast

When `reamortize_on_extra=True`, each extra principal payment triggers a recalculation of the required monthly payment over the remaining scheduled term. The payment goes down instead of the term shortening.

```python
EnhancedLoan(
    reamortize_on_extra = True,   # lower payment after each extra payment
    reamortize_on_extra = False,  # shorten term (default)
    ...
)
```

The `recast_payment` column shows the new required payment effective the following month:

```
 months_elapsed  monthly_payment_L2  extra_payment_L2  recast_payment_L2
             17        3,304.30            821.65           3,304.30
             18        3,300.21            821.65           3,300.21
             19        3,296.13            821.65           3,296.13
```

> **💡 Recast vs standard extra payments**
> With recast off, extra payments compress the timeline — you own the home sooner.
> With recast on, the required payment gradually decreases — useful if cash flow is uncertain and you want the option to pay less in a tight month.

### 7. Misapplied extra payment warning

When extra payments are present, the tool prints a one-time warning:

```
UserWarning: [Original 7.99%] Extra payments are present. Verify with your servicer
that extra funds are applied directly to principal and not to future installments.
Misapplication negates the benefit entirely.
```

This cannot be modeled computationally — it depends entirely on your servicer's processing rules. Always confirm in writing how extra funds are applied.

---

## Enhanced example walkthrough

`example_enhanced.py` combines all features into one scenario:

- Original loan funded Jan 15 with a **46-day stub period** to March 1 first payment
- **$1,200 capitalized origination fee** added to opening balance
- **actual/365 day-count** on the original
- **$35 late fee** in month 5
- **3-month forbearance** starting month 13, interest capitalizes ($13,054 added to balance)
- Refinance at month 16 to 4.33% using **actual/360** day-count
- Refi uses **loan recast** — extra payments lower future required payment

The enhanced plot uses the same `plot_scenarios()` call as the base tool:

![Enhanced Scenario](https://github.com/31415pi/MortgageTool/blob/main/IMG/mortgageEnhanced.png)

---

## New columns reference

These columns are added to the amortization table by the enhanced engine:

| Column | Description |
|---|---|
| `stub_days_L{n}` | Actual days in the first payment period (0 for standard) |
| `fee_charge_L{n}` | Cash fees collected this month |
| `fee_to_date_L{n}` | Cumulative cash fees paid |
| `deferred_L{n}` | True if this month's payment was suspended |
| `deferred_interest_L{n}` | Interest that accrued during a deferment month |
| `capitalized_interest_L{n}` | Deferred interest added to balance at resumption |
| `recast_payment_L{n}` | New scheduled payment after a recast (NaN if no recast) |
| `day_count_L{n}` | Convention used for this loan (informational) |

---

## Enhanced quick reference

```python
# New data classes
EnhancedLoan(
    principal, annual_rate, term_months, start_date,
    first_payment_date = None,       # stub period if set
    day_count          = "actual/365",
    capitalized_fees   = 0.0,
    fee_events         = [],
    deferments         = [],
    reamortize_on_extra = False,
    extra_payments     = [],
    closing_costs      = 0.0,
    label              = "Loan",
)

FeeEvent(month, amount, label="Fee", capitalize=False)

Deferment(start_month, num_months, capitalize_interest=True)

# Analyzer — identical interface to MortgageAnalyzer
EnhancedMortgageAnalyzer(loans, refi_month, extended_costs, shadow_loans)

# New method
analyzer.compare_day_counts()   # DataFrame: interest cost under all 3 conventions
```

---

---

# Importing Extended Costs from Files

`extended_costs_import.py` lets you load recurring cost data from a CSV, XLSX, or ODS file instead of defining `AnnualItem` entries by hand. The function returns an `ExtendedCosts` object ready to pass directly to either analyzer.

```bash
# Additional dependency for XLSX (already in requirements.txt)
pip install openpyxl

# Optional: only needed for .ods files
pip install odfpy
```

```python
from extended_costs_import import load_extended_costs, preview_extended_costs

ec = load_extended_costs("my_costs.csv")
ec = load_extended_costs("my_costs.xlsx")
ec = load_extended_costs("my_costs.ods")

analyzer = MortgageAnalyzer(loans=[...], extended_costs=ec)
```

---

## CSV format

One row per entry. Three required columns in this order: `COST_TYPE`, `DATE`, `AMOUNT`. Extra columns are ignored.

```csv
Tax, 2022, 5400
Tax, 2023, 5600
Tax, 2024, 5820
Insurance, 2024, 1950
Electric, 202301, 160
Electric, 202302, 155
Water, 20240501, 122
Water, 20240601, 115
Warranty, 2024, 600
```

---

## XLSX / ODS format — per-sheet

One sheet per cost type. Sheet name becomes the category name. Row 1 must be a header with at least `DATE` and `COST` (or `AMOUNT`) columns. Extra columns are silently ignored.

```
Sheet: "Tax"          Sheet: "Electric"       Sheet: "Water"
┌──────────┬───────┐  ┌──────────┬───────┐    ┌──────────┬───────┬──────────────┐
│ DATE     │ COST  │  │ DATE     │ COST  │    │ DATE     │ COST  │ NOTES        │
├──────────┼───────┤  ├──────────┼───────┤    ├──────────┼───────┼──────────────┤
│ 2022     │ 5400  │  │ 2023     │ 1920  │    │ 20240501 │ 122   │ (ignored)    │
│ 2023     │ 5600  │  │ 2024     │ 2040  │    │ 20240601 │ 115   │ (ignored)    │
│ 2024     │ 5820  │  └──────────┴───────┘    └──────────┴───────┴──────────────┘
└──────────┴───────┘
```

## XLSX / ODS format — flat sheet

A single sheet named `ALL`, `DATA`, `COSTS`, `EXTENDED`, or `IMPORT` is treated as a flat three-column table — same structure as the CSV format inside a spreadsheet:

```
Sheet: "ALL"
┌────────────┬──────────┬────────┐
│ COST_TYPE  │ DATE     │ AMOUNT │
├────────────┼──────────┼────────┤
│ Tax        │ 2022     │ 5400   │
│ Tax        │ 2023     │ 5600   │
│ Insurance  │ 2024     │ 1950   │
│ Electric   │ 2023     │ 1920   │
└────────────┴──────────┴────────┘
```

---

## Date formats accepted

| Format | Example | Interpretation |
|---|---|---|
| `YYYY` | `2024` | Annual total — averaged across 12 months |
| `YYYYMM` | `202404` | Monthly entry for April 2024 |
| `YYYYMMDD` | `20240415` | Collapsed to month (April 2024) |
| `YYYY-MM` | `2024-04` | Monthly entry |
| `YYYY-MM-DD` | `2024-04-15` | Collapsed to month |
| `MM/YYYY` | `04/2024` | Monthly entry |

> **⚠️ YYYYMMDD entries:** If two rows for the same cost type share the same YYYYMM (e.g. `20240104` and `20240128` are both January 2024), a warning is raised and the amounts are **summed**. This is usually a data prep error — one monthly entry per cost type per month is the intent.

---

## Warnings and data quality

The importer raises `UserWarning` (never crashes) in these situations — check your terminal output after loading:

| Situation | Warning |
|---|---|
| Missing DATE or COST column on a sheet | Sheet treated as zero for that category |
| Duplicate YYYYMM entries | Amounts summed, data preserved |
| Both annual and monthly entries for same year | Monthly entries used, annual ignored |
| Unrecognized date string | Row skipped |
| Non-numeric amount | Row skipped |
| Empty file | Empty ExtendedCosts returned |

---

## Preview before analyzing

`preview_extended_costs()` loads and summarizes the file without building the full object — useful for a quick sanity check:

```python
from extended_costs_import import preview_extended_costs

print(preview_extended_costs("my_costs.csv"))
```

```
cost_type  year  annual_total
 Electric  2023        1920.0
 Electric  2024        2040.0
      Gas  2023         840.0
      Tax  2022        5400.0
      Tax  2023        5600.0
      Tax  2024        5820.0
     ...
```

---

## Using the import with either analyzer

```python
from extended_costs_import import load_extended_costs
from mortgage_tool import Loan, MortgageAnalyzer
# or:
from mortgage_tool_enhanced import EnhancedLoan, EnhancedMortgageAnalyzer

ec = load_extended_costs("costs.xlsx")

analyzer = MortgageAnalyzer(
    loans=[my_loan],
    extended_costs=ec,       # ← drop-in replacement for manual ExtendedCosts(...)
)
```
