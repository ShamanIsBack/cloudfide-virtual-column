"""Clean sales.csv, add revenue with add_virtual_column, write revenue by region.

Usage:
    python pipeline.py
    python pipeline.py --input sales.csv --output revenue_by_region.csv

Each cleaning step fixes one problem found in notebooks/explore_sales.ipynb and
reports how many rows it changed. If the file contains a kind of problem the
steps do not know about, it raises a ValueError naming the values.
"""

import argparse

import pandas as pd

from solution import add_virtual_column

ORDER_ID = r"SO-[0-9]{5}"
HEADER_ORDER_ID = "Order ID"  # the header line repeated inside the data
LARGE_QUANTITY = 1000


def read_raw(path: str) -> pd.DataFrame:
    """Read every value as text and keep empty cells as "", so pandas converts nothing on its own."""
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def normalise_headers(df: pd.DataFrame) -> pd.DataFrame:
    """'Quantity ' -> 'quantity', 'Unit Price' -> 'unit_price': letters and underscores, as Part 1 requires."""
    df = df.copy()
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_", regex=False)
    return df


def split_off_non_orders(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Separate real order lines from the two known kinds of other line: a repeated header, the TOTAL line.

    Any other line with an unexpected order ID (for example "so-10001") stops the
    pipeline, because it may be a real order that should be fixed, not dropped.
    """
    is_order = df["order_id"].str.fullmatch(ORDER_ID)
    is_known_other = df["order_id"].isin([HEADER_ORDER_ID, "TOTAL"])
    unknown = ~is_order & ~is_known_other
    if unknown.any():
        raise ValueError(f"order IDs not understood: {df.loc[unknown, 'order_id'].tolist()}")
    return df[is_order].copy(), df[~is_order].copy()


def drop_duplicate_rows(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Lines identical to another line (same ID, same content) are export errors: keep the first."""
    copies = df.duplicated()
    return df[~copies].copy(), int(copies.sum())


def clean_region(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """' South', 'EAST', 'west  ' -> 'South', 'East', 'West'."""
    df = df.copy()
    cleaned = df["region"].str.strip().str.title()
    if (cleaned == "").any():
        raise ValueError(f"empty region in orders: {df.loc[cleaned == '', 'order_id'].tolist()}")
    changed = int((cleaned != df["region"]).sum())
    df["region"] = cleaned
    return df, changed


def clean_quantity(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """'1 762' -> 1762: a space used as a thousands separator."""
    df = df.copy()
    text = df["quantity"].str.strip()
    has_separator = text.str.contains(" ", regex=False)
    text = text.str.replace(" ", "", regex=False)
    bad = ~text.str.fullmatch(r"-?[0-9]+")
    if bad.any():
        raise ValueError(f"quantity values not understood: {df.loc[bad, 'quantity'].tolist()}")
    df["quantity"] = text.astype("int64")
    return df, int(has_separator.sum())


def clean_unit_price(df: pd.DataFrame) -> tuple[pd.DataFrame, int, int]:
    """'39,90' -> 39.90, and a missing price is filled with the product's price.

    Filling is only safe because every product has exactly one price in the
    file. If a product ever has two prices, it raises.
    """
    df = df.copy()
    text = df["unit_price"].str.strip()
    has_comma = text.str.contains(",", regex=False)
    text = text.str.replace(",", ".", regex=False)
    missing = text == ""
    bad = ~missing & ~text.str.fullmatch(r"[0-9]+(\.[0-9]+)?")
    if bad.any():
        raise ValueError(f"unit price values not understood: {df.loc[bad, 'unit_price'].tolist()}")

    price = pd.to_numeric(text.where(~missing))
    prices_per_product = price.groupby(df["product"]).nunique()
    if (prices_per_product > 1).any():
        raise ValueError(f"products with more than one price: {prices_per_product[prices_per_product > 1].to_dict()}")
    known_price = price.groupby(df["product"]).transform("first")
    if known_price[missing].isna().any():
        raise ValueError("a missing price belongs to a product with no known price")

    df["unit_price"] = price.fillna(known_price)
    return df, int(has_comma.sum()), int(missing.sum())


def clean_discount(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """An empty discount means no discount: 0."""
    df = df.copy()
    text = df["discount"].str.strip()
    empty = text == ""
    bad = ~empty & ~text.str.fullmatch(r"[0-9]+(\.[0-9]+)?")
    if bad.any():
        raise ValueError(f"discount values not understood: {df.loc[bad, 'discount'].tolist()}")
    df["discount"] = pd.to_numeric(text.where(~empty, "0"))
    return df, int(empty.sum())


def clean_order_date(df: pd.DataFrame) -> pd.DataFrame:
    """All dates are YYYY-MM-DD; anything else stops the pipeline."""
    df = df.copy()
    dates = pd.to_datetime(df["order_date"], format="%Y-%m-%d", errors="coerce")
    if dates.isna().any():
        raise ValueError(f"order dates not understood: {df.loc[dates.isna(), 'order_date'].tolist()}")
    df["order_date"] = dates
    return df


def check_product(df: pd.DataFrame) -> None:
    """Product names had no problems; an empty one would make a price impossible to fill, so it stops the pipeline."""
    empty = df["product"].str.strip() == ""
    if empty.any():
        raise ValueError(f"empty product in orders: {df.loc[empty, 'order_id'].tolist()}")


def check_against_total_line(orders: pd.DataFrame, non_orders: pd.DataFrame) -> bool:
    """Compare our sums with the export's own TOTAL line (taken before duplicates are removed).

    Returns False if the file has no TOTAL line. A TOTAL line that does not match
    means we read some numbers differently from the source system, so it stops.
    """
    total = non_orders[non_orders["order_id"] == "TOTAL"]
    if total.empty:
        return False
    expected = (int(total["quantity"].iloc[0].replace(" ", "")), round(float(total["discount"].iloc[0]), 2))
    ours = (int(orders["quantity"].sum()), round(float(orders["discount"].sum()), 2))
    if ours != expected:
        raise ValueError(f"sums do not match the TOTAL line: (quantity, discount) ours {ours}, TOTAL {expected}")
    return True


def clean(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Run every cleaning step in order. Returns the clean order lines and the number of rows each step changed."""
    df = normalise_headers(raw)
    orders, non_orders = split_off_non_orders(df)

    check_product(orders)
    orders, regions_fixed = clean_region(orders)
    orders, separators = clean_quantity(orders)
    orders, commas, prices_filled = clean_unit_price(orders)
    orders, empty_discounts = clean_discount(orders)
    orders = clean_order_date(orders)
    matches_total = check_against_total_line(orders, non_orders)
    orders, copies = drop_duplicate_rows(orders)

    counts = {
        "headers renamed": len(df.columns),
        "non-order lines removed": len(non_orders),
        "duplicate lines removed": copies,
        "regions fixed": regions_fixed,
        "thousands separators removed": separators,
        "decimal commas fixed": commas,
        "missing prices filled": prices_filled,
        "empty discounts set to 0": empty_discounts,
        "matches TOTAL line": matches_total,
        "negative quantities kept": int((orders["quantity"] < 0).sum()),
        "large quantities kept": int((orders["quantity"] >= LARGE_QUANTITY).sum()),
    }
    return orders.reset_index(drop=True), counts


def format_report(orders: pd.DataFrame, counts: dict) -> list[str]:
    negative = orders.loc[orders["quantity"] < 0, "order_id"].tolist()
    large = orders.loc[orders["quantity"] >= LARGE_QUANTITY, "order_id"].tolist()
    return [
        f"headers renamed to snake_case:            {counts['headers renamed']} columns",
        f"non-order lines removed:                  {counts['non-order lines removed']}",
        f"exact duplicate lines removed:            {counts['duplicate lines removed']}",
        f"regions with extra spaces or wrong case:  {counts['regions fixed']}",
        f"quantities with a thousands separator:    {counts['thousands separators removed']}",
        f"unit prices with a decimal comma:         {counts['decimal commas fixed']}",
        f"missing unit prices filled from product:  {counts['missing prices filled']}",
        f"empty discounts set to 0:                 {counts['empty discounts set to 0']}",
        f"sums checked against the TOTAL line:      {'match' if counts['matches TOTAL line'] else 'no TOTAL line'}",
        f"kept, flagged: negative quantity:         {negative}",
        f"kept, flagged: quantity of {LARGE_QUANTITY} or more:  {large}",
    ]


def add_revenue(orders: pd.DataFrame) -> pd.DataFrame:
    """Revenue = quantity x unit price - discount, computed with the Part 1 function."""
    result = add_virtual_column(orders, "quantity * unit_price - discount", "revenue")
    if result.empty and not orders.empty:
        raise ValueError("add_virtual_column rejected the revenue expression")
    return result


def revenue_by_region(orders: pd.DataFrame) -> pd.DataFrame:
    totals = orders.groupby("region", as_index=False)["revenue"].sum()
    totals["revenue"] = totals["revenue"].round(2)
    return totals.sort_values("region").reset_index(drop=True)


def run(input_path: str, output_path: str) -> list[str]:
    orders, counts = clean(read_raw(input_path))
    totals = revenue_by_region(add_revenue(orders))
    totals.to_csv(output_path, index=False)
    report = format_report(orders, counts)
    report.append(f"order lines used:                         {len(orders)}")
    report.append(f"total revenue:                            {totals['revenue'].sum():.2f}")
    report.append(f"written:                                  {output_path}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", default="sales.csv", help="raw sales export (default: sales.csv)")
    parser.add_argument("--output", default="revenue_by_region.csv", help="where to write the totals")
    args = parser.parse_args()
    for line in run(args.input, args.output):
        print(line)


if __name__ == "__main__":
    main()
