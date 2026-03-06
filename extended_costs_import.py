"""
extended_costs_import.py
========================
Import recurring homeownership cost data from CSV, XLSX, or ODS files
and return an ExtendedCosts object ready to pass to MortgageAnalyzer.

Supported formats
-----------------
CSV  — one row per entry: {COST_TYPE},{DATE},{AMOUNT}
XLSX — one sheet per cost type; columns: DATE, COST  (row 1 = header)
ODS  — same structure as XLSX  (requires: pip install odfpy)

Special sheet/format "ALL" or "Data" (XLSX/ODS only):
    A single flat sheet with three columns: COST_TYPE, DATE, AMOUNT
    Mirrors the CSV format inside a spreadsheet.

Date formats accepted
---------------------
    YYYY         — annual total, averaged across 12 months
    YYYYMM       — monthly entry
    YYYYMMDD     — daily entry collapsed to month (warn if month duplicated)
    YYYY-MM      — accepted and normalized
    YYYY-MM-DD   — accepted and normalized
    MM/YYYY      — accepted and normalized

Usage
-----
    from extended_costs_import import load_extended_costs
    from mortgage_tool import MortgageAnalyzer

    ec = load_extended_costs("my_costs.csv")
    ec = load_extended_costs("my_costs.xlsx")
    ec = load_extended_costs("my_costs.ods")

    analyzer = MortgageAnalyzer(loans=[...], extended_costs=ec)

Copyright (c) 2026 Hellomoto1123. Private use unrestricted.
Commercial use requires a license — contact hellomoto1123@gmail.com
"""

import re
import warnings
from pathlib import Path
from collections import defaultdict
from typing import Union

import pandas as pd

from mortgage_tool import AnnualItem, ExtendedCosts


# ─────────────────────────────────────────────────────────────────────────────
# DATE NORMALIZATION
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_date(raw: str, source_label: str = "") -> tuple:
    """
    Parse a date string into (year, month_or_None).

    Returns
    -------
    (year: int, month: int | None)
        month is None when the entry represents an annual total.

    Raises
    ------
    ValueError if the string cannot be parsed.
    """
    s = str(raw).strip().replace(" ", "")

    # YYYY-MM-DD or YYYYMMDD
    m = re.fullmatch(r"(\d{4})[-/]?(\d{2})[-/]?(\d{2})", s)
    if m:
        return int(m.group(1)), int(m.group(2))

    # YYYY-MM or YYYYMM
    m = re.fullmatch(r"(\d{4})[-/](\d{2})", s)
    if m:
        return int(m.group(1)), int(m.group(2))

    m = re.fullmatch(r"(\d{4})(\d{2})", s)
    if m:
        yr, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            return yr, mo

    # MM/YYYY
    m = re.fullmatch(r"(\d{1,2})/(\d{4})", s)
    if m:
        return int(m.group(2)), int(m.group(1))

    # YYYY only
    m = re.fullmatch(r"(\d{4})", s)
    if m:
        return int(m.group(1)), None

    raise ValueError(
        f"Unrecognized date format '{raw}'"
        + (f" in {source_label}" if source_label else "")
        + ". Accepted: YYYY, YYYYMM, YYYYMMDD, YYYY-MM, YYYY-MM-DD, MM/YYYY"
    )


# ─────────────────────────────────────────────────────────────────────────────
# AGGREGATION HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _aggregate_to_annual(entries: list, cost_type: str) -> dict:
    """
    Convert a list of (year, month_or_None, amount) tuples into
    {year: annual_total} for use in AnnualItem.

    Rules
    -----
    - YYYY entries: amount is already the annual total.
    - YYYYMM entries: summed per year across all months present.
    - Duplicate YYYYMM: warn and sum (do not drop).

    Parameters
    ----------
    entries : list of (year, month|None, amount)
    cost_type : str  — used in warning messages

    Returns
    -------
    dict {year: annual_float}
    """
    # Separate annual vs monthly
    annual_direct: dict = {}   # {year: amount}
    monthly_raw: dict = {}     # {(year, month): [amounts]}

    for year, month, amount in entries:
        if month is None:
            # Annual entry — add to any existing monthly data for that year
            annual_direct[year] = annual_direct.get(year, 0.0) + float(amount)
        else:
            key = (year, month)
            monthly_raw.setdefault(key, []).append(float(amount))

    # Warn on duplicate YYYYMM
    for (yr, mo), vals in monthly_raw.items():
        if len(vals) > 1:
            warnings.warn(
                f"[{cost_type}] Duplicate entries for {yr}-{mo:02d}: "
                f"{vals} — summing them. Verify your data.",
                UserWarning, stacklevel=4
            )

    # Sum monthly entries per year
    yearly_from_monthly: dict = defaultdict(float)
    for (yr, mo), vals in monthly_raw.items():
        yearly_from_monthly[yr] += sum(vals)

    # Merge: annual_direct wins if there are no monthly entries for that year
    all_years = set(annual_direct) | set(yearly_from_monthly)
    result = {}
    for yr in sorted(all_years):
        if yr in yearly_from_monthly:
            result[yr] = round(yearly_from_monthly[yr], 2)
            if yr in annual_direct:
                warnings.warn(
                    f"[{cost_type}] Both annual and monthly entries found for {yr}. "
                    "Using the summed monthly entries.",
                    UserWarning, stacklevel=4
                )
        else:
            result[yr] = round(annual_direct[yr], 2)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# PER-FORMAT READERS
# ─────────────────────────────────────────────────────────────────────────────

def _read_csv(path: Path) -> dict:
    """
    Read a CSV file. Expected row format: COST_TYPE, DATE, AMOUNT
    Extra columns are ignored. Returns {cost_type: [(year, month, amount), ...]}
    """
    try:
        df = pd.read_csv(path, header=None, skipinitialspace=True,
                         names=["cost_type", "date", "amount"],
                         usecols=[0, 1, 2])
    except Exception as e:
        raise ValueError(f"Could not read CSV '{path}': {e}")

    # Drop header row if someone included one
    df = df[~df["cost_type"].astype(str).str.lower().isin(["cost_type", "type", "category"])]
    df = df.dropna(subset=["cost_type", "date", "amount"])

    buckets: dict = defaultdict(list)
    for _, row in df.iterrows():
        ct   = str(row["cost_type"]).strip().title()
        raw  = str(row["date"]).strip()
        try:
            amt = float(str(row["amount"]).replace(",", "").replace("$", ""))
        except ValueError:
            warnings.warn(
                f"[CSV] Non-numeric amount '{row['amount']}' for {ct} on {raw} — skipping row.",
                UserWarning, stacklevel=3
            )
            continue
        try:
            year, month = _normalize_date(raw, source_label=f"CSV row {ct}")
        except ValueError as e:
            warnings.warn(str(e) + " — skipping row.", UserWarning, stacklevel=3)
            continue
        buckets[ct].append((year, month, amt))

    return dict(buckets)


def _read_sheet_pair(df_sheet: pd.DataFrame, cost_type: str) -> list:
    """
    Parse a DATE/COST two-column sheet (or similar).
    Returns [(year, month, amount), ...]
    """
    cols = [c.strip().upper() for c in df_sheet.columns]

    date_col = next((i for i, c in enumerate(cols) if "DATE" in c), None)
    cost_col = next((i for i, c in enumerate(cols)
                     if c in ("COST", "AMOUNT", "AMT", "VALUE")), None)

    if date_col is None or cost_col is None:
        warnings.warn(
            f"[{cost_type}] Sheet is missing a DATE or COST/AMOUNT column — "
            "treating this cost type as zero. Check column headers.",
            UserWarning, stacklevel=4
        )
        return []

    entries = []
    for _, row in df_sheet.iterrows():
        raw = str(row.iloc[date_col]).strip()
        if raw.lower() in ("nan", "", "date"):
            continue
        try:
            amt = float(str(row.iloc[cost_col]).replace(",", "").replace("$", ""))
        except ValueError:
            continue
        try:
            year, month = _normalize_date(raw, source_label=cost_type)
        except ValueError as e:
            warnings.warn(str(e) + " — skipping row.", UserWarning, stacklevel=4)
            continue
        entries.append((year, month, amt))
    return entries


def _read_flat_sheet(df_sheet: pd.DataFrame) -> dict:
    """
    Parse a flat ALL/Data sheet with COST_TYPE, DATE, AMOUNT columns.
    Returns {cost_type: [(year, month, amount), ...]}
    """
    cols = [c.strip().upper() for c in df_sheet.columns]
    ct_col   = next((i for i, c in enumerate(cols) if c in ("COST_TYPE","TYPE","CATEGORY","COST TYPE")), None)
    date_col = next((i for i, c in enumerate(cols) if "DATE" in c), None)
    amt_col  = next((i for i, c in enumerate(cols) if c in ("AMOUNT","AMT","COST","VALUE")), None)

    if ct_col is None or date_col is None or amt_col is None:
        warnings.warn(
            "Flat sheet missing COST_TYPE, DATE, or AMOUNT column — sheet skipped.",
            UserWarning, stacklevel=4
        )
        return {}

    buckets: dict = defaultdict(list)
    for _, row in df_sheet.iterrows():
        ct  = str(row.iloc[ct_col]).strip().title()
        raw = str(row.iloc[date_col]).strip()
        if ct.lower() in ("nan", "") or raw.lower() in ("nan", ""):
            continue
        try:
            amt = float(str(row.iloc[amt_col]).replace(",","").replace("$",""))
        except ValueError:
            continue
        try:
            year, month = _normalize_date(raw, source_label=ct)
        except ValueError as e:
            warnings.warn(str(e) + " — skipping.", UserWarning, stacklevel=4)
            continue
        buckets[ct].append((year, month, amt))
    return dict(buckets)


def _read_spreadsheet(path: Path, engine: str) -> dict:
    """
    Read an XLSX or ODS workbook.
    Each sheet name is treated as a cost type, UNLESS the sheet is named
    ALL, DATA, COSTS, or EXTENDED — those are treated as flat three-column sheets.
    Returns {cost_type: [(year, month, amount), ...]}
    """
    try:
        xl = pd.ExcelFile(path, engine=engine)
    except Exception as e:
        raise ValueError(f"Could not open '{path}': {e}")

    FLAT_SHEET_NAMES = {"ALL", "DATA", "COSTS", "EXTENDED", "IMPORT"}
    buckets: dict = defaultdict(list)

    for sheet_name in xl.sheet_names:
        df = xl.parse(sheet_name)
        if df.empty:
            continue

        if sheet_name.strip().upper() in FLAT_SHEET_NAMES:
            flat = _read_flat_sheet(df)
            for ct, entries in flat.items():
                buckets[ct].extend(entries)
        else:
            ct = sheet_name.strip().title()
            entries = _read_sheet_pair(df, ct)
            buckets[ct].extend(entries)

    return dict(buckets)


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def load_extended_costs(path: Union[str, Path]) -> ExtendedCosts:
    """
    Load recurring homeownership cost data from a file and return an
    ExtendedCosts object ready to pass to MortgageAnalyzer or
    EnhancedMortgageAnalyzer.

    Parameters
    ----------
    path : str or Path
        Path to a .csv, .xlsx, or .ods file.

    Returns
    -------
    ExtendedCosts

    Raises
    ------
    ValueError  — unrecognized file format or unreadable file.
    ImportError — .ods file but odfpy is not installed.

    Examples
    --------
    ec = load_extended_costs("costs.csv")
    ec = load_extended_costs("costs.xlsx")
    ec = load_extended_costs("costs.ods")

    analyzer = MortgageAnalyzer(loans=[...], extended_costs=ec)

    CSV format (one row per entry):
        Tax, 2025, 9533
        Water, 202504, 232
        Water, 20250501, 122
        Warranty, 202601, 144

    XLSX/ODS format:
        Sheet name  = cost type  (e.g. sheet "Tax", sheet "Water")
        Column 1    = DATE header
        Column 2    = COST header
        Extra columns are ignored.

        OR: one sheet named ALL / DATA / COSTS with columns:
        COST_TYPE, DATE, AMOUNT
    """
    path = Path(path)
    suffix = path.suffix.lower()

    if not path.exists():
        raise FileNotFoundError(f"File not found: '{path}'")

    if suffix == ".csv":
        raw_buckets = _read_csv(path)

    elif suffix == ".xlsx":
        raw_buckets = _read_spreadsheet(path, engine="openpyxl")

    elif suffix == ".ods":
        try:
            import odf  # noqa: F401
        except ImportError:
            raise ImportError(
                "Reading .ods files requires odfpy. Install it with:\n"
                "    pip install odfpy"
            )
        raw_buckets = _read_spreadsheet(path, engine="odf")

    else:
        raise ValueError(
            f"Unsupported file format '{suffix}'. "
            "Supported: .csv, .xlsx, .ods"
        )

    if not raw_buckets:
        warnings.warn(
            f"No cost data found in '{path.name}'. "
            "Returning empty ExtendedCosts.",
            UserWarning, stacklevel=2
        )
        return ExtendedCosts(items=[])

    items = []
    for cost_type, entries in sorted(raw_buckets.items()):
        if not entries:
            warnings.warn(
                f"[{cost_type}] No valid entries found — skipping.",
                UserWarning, stacklevel=2
            )
            continue
        history = _aggregate_to_annual(entries, cost_type)
        items.append(AnnualItem(name=cost_type, history=history))

    print(f"  Loaded {len(items)} cost categories from '{path.name}':")
    for item in items:
        yrs = sorted(item.history.keys())
        total = sum(item.history.values())
        print(f"    {item.name:<18} {len(yrs)} year(s) "
              f"[{yrs[0]}–{yrs[-1]}]  total: ${total:,.0f}")

    return ExtendedCosts(items=items)


def preview_extended_costs(path: Union[str, Path]) -> pd.DataFrame:
    """
    Load cost data and return a summary DataFrame without building the
    ExtendedCosts object.  Useful for verifying data before running the
    full analysis.

    Returns
    -------
    DataFrame with columns: cost_type, year, annual_total
    """
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix == ".csv":
        raw_buckets = _read_csv(path)
    elif suffix == ".xlsx":
        raw_buckets = _read_spreadsheet(path, engine="openpyxl")
    elif suffix == ".ods":
        raw_buckets = _read_spreadsheet(path, engine="odf")
    else:
        raise ValueError(f"Unsupported format '{suffix}'")

    rows = []
    for ct, entries in sorted(raw_buckets.items()):
        history = _aggregate_to_annual(entries, ct)
        for yr, amt in sorted(history.items()):
            rows.append({"cost_type": ct, "year": yr, "annual_total": amt})

    return pd.DataFrame(rows)
