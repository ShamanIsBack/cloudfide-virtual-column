"""Tests for add_virtual_column (Part 1).

The sample tests in test_virtual_column.py cover the basics. These cover the
decisions written down in the README: precedence, parentheses, numbers, and the
cases that must return an empty DataFrame.
"""

import pandas as pd
import pytest

from solution import add_virtual_column


@pytest.fixture
def df():
    return pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6], "c": [7, 8, 9]})


def with_column(df, name, values):
    """The expected result: the original frame plus one new column."""
    expected = df.copy()
    expected[name] = values
    return expected


def assert_invalid(result):
    """Invalid input gives an empty DataFrame with no columns at all.

    Checking the columns as well as .empty matters: a valid result on a frame
    with no rows is also .empty, but it still has its columns.
    """
    assert result.empty
    assert len(result.columns) == 0


# Valid formulas ---------------------------------------------------------------

@pytest.mark.parametrize(
    "role, values",
    [
        ("a + b", [5, 7, 9]),
        ("a - b", [-3, -3, -3]),
        ("a * b", [4, 10, 18]),
        ("a + b * c", [29, 42, 57]),      # * before +
        ("a - b - c", [-10, -11, -12]),   # left to right: (a - b) - c
        ("(a + b) * c", [35, 56, 81]),    # parentheses override precedence
        ("((a))", [1, 2, 3]),
        ("a * 2", [2, 4, 6]),
        ("a", [1, 2, 3]),
        ("a * a", [1, 4, 9]),
        ("  a+b  *c ", [29, 42, 57]),     # spaces anywhere, or none
    ],
)
def test_valid_formulas(df, role, values):
    result = add_virtual_column(df, role, "new")
    assert result.equals(with_column(df, "new", values))


def test_decimal_number_gives_float_column(df):
    result = add_virtual_column(df, "a * 0.5", "half")
    assert result.equals(with_column(df, "half", [0.5, 1.0, 1.5]))


def test_integer_columns_stay_int64(df):
    result = add_virtual_column(df, "a * b", "product")
    assert result["product"].dtype == "int64"


def test_labels_with_underscores():
    df = pd.DataFrame({"unit_price": [2, 3], "_qty": [10, 20]})
    result = add_virtual_column(df, "unit_price * _qty", "line_total")
    assert result.equals(with_column(df, "line_total", [20, 60]))


# Invalid formulas -> empty DataFrame -----------------------------------------

@pytest.mark.parametrize(
    "role",
    [
        "a & b",       # character outside the allowlist
        "a / b",       # division is not supported
        "a3 + b",      # letters mixed with digits: one invalid label
        "a + d",       # d is not a column
        "a b",         # two labels with no operator
        "-a + b",      # no leading minus
        "a + * b",     # two operators in a row
        "a +",         # operator at the end
        "",            # empty
        "   ",         # only spaces
        "(a + b",      # unbalanced parentheses
        "a + b)",
        "()",
        "2 * 3",       # no column at all
        ".5 * a",      # number must start with a digit
        "1.2.3 * a",
        "a ** b",
        "__import__('os')",
    ],
)
def test_invalid_formulas(df, role):
    assert_invalid(add_virtual_column(df, role, "new"))


@pytest.mark.parametrize("new_column", ["new3", "", "new column", "a"])
def test_invalid_new_column(df, new_column):
    # "a" already exists: we refuse to overwrite it.
    assert_invalid(add_virtual_column(df, "a + b", new_column))


def test_invalid_label_in_dataframe(df):
    # Every column label is checked, also the ones the formula does not use.
    df = df.assign(**{"Unit Price": [1, 1, 1]})
    assert_invalid(add_virtual_column(df, "a + b", "new"))


# Behaviour --------------------------------------------------------------------

def test_input_is_not_changed(df):
    before = df.copy()
    add_virtual_column(df, "a + b", "new")
    assert df.equals(before)


def test_frame_with_no_rows_keeps_its_columns():
    df = pd.DataFrame({"a": pd.Series([], dtype="int64"), "b": pd.Series([], dtype="int64")})
    result = add_virtual_column(df, "a + b", "new")
    assert list(result.columns) == ["a", "b", "new"]
    assert len(result) == 0
