"""Tests for pipeline.py (Part 2).

Small hand-made frames test one cleaning step each; the last tests run the
whole pipeline on sales.csv and check the counts written in the README.
"""

from pathlib import Path

import pandas as pd
import pytest

import pipeline

HERE = Path(__file__).parent
SALES = str(HERE / "sales.csv")


def frame(**columns):
    """A small all-text frame, as read_raw would return it."""
    return pd.DataFrame({name: pd.Series(values, dtype="str") for name, values in columns.items()})


def test_headers_become_snake_case():
    raw = frame(**{"Order ID": ["SO-10001"], "Quantity ": ["1"], "Unit Price": ["2.00"]})
    assert list(pipeline.normalise_headers(raw).columns) == ["order_id", "quantity", "unit_price"]


def test_non_order_lines_are_split_off():
    df = frame(order_id=["SO-10001", "Order ID", "SO-10002", "TOTAL"])
    orders, other = pipeline.split_off_non_orders(df)
    assert orders["order_id"].tolist() == ["SO-10001", "SO-10002"]
    assert other["order_id"].tolist() == ["Order ID", "TOTAL"]


def test_unknown_order_id_stops_the_pipeline():
    # It could be a real order with a typo in its ID: stop rather than drop it.
    df = frame(order_id=["SO-10001", "so-10002"])
    with pytest.raises(ValueError, match="order IDs"):
        pipeline.split_off_non_orders(df)


def test_empty_region_stops_the_pipeline():
    with pytest.raises(ValueError, match="empty region"):
        pipeline.clean_region(frame(order_id=["SO-1", "SO-2"], region=["North", "  "]))


def test_empty_product_stops_the_pipeline():
    with pytest.raises(ValueError, match="empty product"):
        pipeline.check_product(frame(order_id=["SO-1"], product=[""]))


def test_total_line_mismatch_stops_the_pipeline():
    orders = pd.DataFrame({"quantity": [1, 2], "discount": [0.0, 1.0]})
    total = frame(order_id=["TOTAL"], quantity=["4"], discount=["1.00"])
    with pytest.raises(ValueError, match="TOTAL"):
        pipeline.check_against_total_line(orders, total)


def test_no_total_line_is_allowed():
    orders = pd.DataFrame({"quantity": [1], "discount": [0.0]})
    assert pipeline.check_against_total_line(orders, frame(order_id=[])) is False


@pytest.mark.parametrize("value", ["٣", "１２"])  # Arabic-Indic and fullwidth digits
def test_only_ascii_digits_in_quantities(value):
    with pytest.raises(ValueError, match="quantity"):
        pipeline.clean_quantity(frame(quantity=[value]))


def test_exact_duplicates_are_removed_but_same_id_with_other_content_is_kept():
    df = frame(order_id=["SO-1", "SO-1", "SO-2", "SO-2"], quantity=["5", "5", "1", "2"])
    deduplicated, removed = pipeline.drop_duplicate_rows(df)
    assert removed == 1
    assert deduplicated["quantity"].tolist() == ["5", "1", "2"]


def test_region_spaces_and_case():
    df = frame(region=[" South", "EAST", "west  ", "North"])
    cleaned, changed = pipeline.clean_region(df)
    assert cleaned["region"].tolist() == ["South", "East", "West", "North"]
    assert changed == 3


def test_quantity_thousands_separator_and_negatives():
    df = frame(quantity=["1 762", "12", "-3"])
    cleaned, separators = pipeline.clean_quantity(df)
    assert cleaned["quantity"].tolist() == [1762, 12, -3]
    assert cleaned["quantity"].dtype == "int64"
    assert separators == 1


@pytest.mark.parametrize("value", ["12.5", "abc", "", "1,5"])
def test_quantity_not_understood_stops_the_pipeline(value):
    with pytest.raises(ValueError, match="quantity"):
        pipeline.clean_quantity(frame(quantity=["1", value]))


def test_unit_price_comma_and_fill_from_product():
    df = frame(product=["Mouse", "Mouse", "Lamp", "Mouse"], unit_price=["29,50", "", "39.90", "29.50"])
    cleaned, commas, filled = pipeline.clean_unit_price(df)
    assert cleaned["unit_price"].tolist() == [29.5, 29.5, 39.9, 29.5]
    assert (commas, filled) == (1, 1)


def test_unit_price_cannot_be_filled_when_product_has_two_prices():
    df = frame(product=["Mouse", "Mouse", "Mouse"], unit_price=["29.50", "30.00", ""])
    with pytest.raises(ValueError, match="more than one price"):
        pipeline.clean_unit_price(df)


def test_unit_price_cannot_be_filled_when_product_has_no_price():
    df = frame(product=["Mouse", "Lamp"], unit_price=["29.50", ""])
    with pytest.raises(ValueError, match="no known price"):
        pipeline.clean_unit_price(df)


def test_empty_discount_is_zero():
    cleaned, empty = pipeline.clean_discount(frame(discount=["", "10.50", " "]))
    assert cleaned["discount"].tolist() == [0.0, 10.5, 0.0]
    assert empty == 2


def test_bad_date_stops_the_pipeline():
    with pytest.raises(ValueError, match="order dates"):
        pipeline.clean_order_date(frame(order_date=["2026-01-02", "02/01/2026"]))


def test_revenue_is_quantity_times_price_minus_discount():
    orders = pd.DataFrame({"quantity": [2, -1], "unit_price": [10.0, 5.0], "discount": [1.0, 0.0]})
    assert pipeline.add_revenue(orders)["revenue"].tolist() == [19.0, -5.0]


def test_revenue_by_region_sums_and_sorts():
    orders = pd.DataFrame({"region": ["West", "East", "West"], "revenue": [1.004, 2.0, 3.0]})
    totals = pipeline.revenue_by_region(orders)
    assert totals["region"].tolist() == ["East", "West"]
    assert totals["revenue"].tolist() == [2.0, 4.0]


# The whole pipeline on the real file ------------------------------------------

@pytest.fixture(scope="module")
def cleaned():
    return pipeline.clean(pipeline.read_raw(SALES))


def test_counts_on_sales_csv(cleaned):
    # The same numbers as the README's problem table.
    orders, counts = cleaned
    assert len(orders) == 1500
    assert counts == {
        "headers renamed": 7,
        "non-order lines removed": 2,
        "duplicate lines removed": 5,
        "regions fixed": 15,
        "thousands separators removed": 4,
        "decimal commas fixed": 7,
        "missing prices filled": 4,
        "empty discounts set to 0": 963,
        "matches TOTAL line": True,
        "negative quantities kept": 6,
        "large quantities kept": 4,
    }


def test_clean_data_is_ready_for_calculation(cleaned):
    orders, _ = cleaned
    assert sorted(orders["region"].unique()) == ["Central", "East", "North", "South", "West"]
    assert orders["order_id"].is_unique
    assert orders[["quantity", "unit_price", "discount"]].notna().all().all()
    assert (orders["quantity"] < 0).sum() == 6


def test_output_file_is_up_to_date(tmp_path):
    output = tmp_path / "revenue_by_region.csv"
    pipeline.run(SALES, str(output))
    assert output.read_text() == (HERE / "revenue_by_region.csv").read_text()
    totals = pd.read_csv(output)
    assert list(totals.columns) == ["region", "revenue"]
    assert round(totals["revenue"].sum(), 2) == 2570247.03
