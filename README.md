# Virtual columns in a pandas DataFrame

Recruitment task for Cloudfide. Three parts:

1. `solution.py`: `add_virtual_column(df, role, new_column)` adds a column calculated from an expression such as
   `"quantity * price"`.
2. `pipeline.py`: cleans `sales.csv`, adds `revenue` with that function and writes `revenue_by_region.csv`.
3. Tests for both parts (85 in total).

## Setup

Python 3.12 or newer (tested with 3.14.5).

```
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux
pip install -r requirements.txt
```

`requirements.txt` pins pandas 3.1.1, numpy 2.5.5 and pytest 9.2.0. JupyterLab, needed only for the notebook, is in
`requirements-dev.txt`.

## Run the pipeline

```
python pipeline.py
```

It reads `sales.csv`, writes `revenue_by_region.csv` and prints what it changed:

```
headers renamed to snake_case:            7 columns
non-order lines removed:                  2
exact duplicate lines removed:            5
regions with extra spaces or wrong case:  15
quantities with a thousands separator:    4
unit prices with a decimal comma:         7
missing unit prices filled from product:  4
empty discounts set to 0:                 963
sums checked against the TOTAL line:      match
kept, flagged: negative quantity:         ['SO-10421', 'SO-10515', 'SO-10779', 'SO-11011', 'SO-11289', 'SO-11445']
kept, flagged: quantity of 1000 or more:  ['SO-10251', 'SO-10734', 'SO-11088', 'SO-11312']
order lines used:                         1500
total revenue:                            2570247.03
written:                                  revenue_by_region.csv
```

Result (`revenue_by_region.csv` is committed, so it can be seen without running anything):

| region | revenue |
|---|---|
| Central | 515824.67 |
| East | 442219.91 |
| North | 665897.52 |
| South | 504036.04 |
| West | 442268.89 |

Other files can be passed with `--input` and `--output`. If a file contains a kind of problem the cleaning steps do not
know, the pipeline stops with an error that names the values. That covers a quantity like `12.5`, a date in another
format, an order ID it does not recognise (`so-10001`), an empty region or product, a product with two different
prices, and sums that do not match the file's TOTAL line. I chose that over guessing, because a guess would end up in
the totals without anyone seeing it.

## Run the tests

```
pytest
```

85 tests: the 6 sample tests in `test_virtual_column.py`, 53 in `test_solution.py` and 26 in `test_pipeline.py`. The
pipeline tests include a run on `sales.csv` that checks every count in the table below, and a check that the committed
`revenue_by_region.csv` is what the pipeline produces.

## Problems found in `sales.csv`

The full exploration is in `notebooks/explore_sales.ipynb`.

| Problem | Rows | Handling |
|---|---|---|
| Headers with spaces and capitals; `Quantity ` has a trailing space | all 7 columns | renamed to `snake_case`, which Part 1 requires |
| Header line repeated inside the data (line 753 of the file) | 1 | removed |
| `TOTAL` line at the end | 1 | removed after its sums are compared with ours |
| Region with extra spaces or wrong case (`' South'`, `EAST`, `west  `) | 15 | spaces stripped, title case |
| Quantity with a space as thousands separator (`1 762`) | 4 | space removed |
| Negative quantity | 6 | kept as returns, listed in the output |
| Unit price with a decimal comma (`39,90`) | 7 | comma replaced with a point |
| Unit price missing | 4 | filled with the product's price |
| Discount empty | 963 | set to 0, as the task describes |
| Exact duplicate lines | 5 | copies removed |
| Product names, order dates | 0 | checked, no problems |

After cleaning, 1,500 order lines remain. Their quantities and discounts, taken before the duplicates are removed,
match the TOTAL line exactly.

## How `add_virtual_column` works

The expression is never passed to `eval` or `DataFrame.eval`, which the pandas documentation warns can run arbitrary
code. The function reads the expression itself, in three steps:

1. **Tokenise.** Cut the string into pieces: labels, numbers, `+ - * ( )`. Any other character makes the expression
   invalid.
2. **Parse.** A small recursive-descent parser checks that the pieces are in a valid order and computes the result with
   normal precedence:
   ```
   expression  =  term   { ("+" | "-")  term   }
   term        =  factor { "*"          factor }
   factor      =  label  |  number  |  "(" expression ")"
   ```
3. **Build the result** on a copy of the input, which is never changed.

This is more code than a regular expression plus `eval` (about 100 lines without comments), but the code that checks
the expression is the same code that computes it.

Any invalid input returns an empty DataFrame, as the task asks. That includes a column used in the expression that
does not hold numbers (text, dates, true/false), a number too large for the column, and input that is not a
DataFrame. Arithmetic itself follows numpy's rules, so a result too large for an integer column wraps around instead
of raising.

Brackets nested hundreds deep also give an empty DataFrame. A very long formula without nesting is valid and still
computed, only slowly (10,000 terms on 100,000 rows takes about a second), so a service that accepts formulas from
users should limit their length.

## Assumptions

Where the task leaves room, these are the choices I made.

**Part 1**

- The example in the task calls the function with `"total"` but prints a column named `price_total`. I follow the
  `new_column` argument, as the sample tests do. I kept the parameter name `role` as given.
- Normal precedence: `*` before `+` and `-`, left to right within the same level. `a - b - c` is `(a - b) - c`.
- Parentheses are accepted for grouping. Unbalanced or empty parentheses make the expression invalid.
- Numbers are accepted (`price * 2`, `price * 0.5`): digits with an optional decimal point. A word that mixes letters
  and digits, such as `label3`, is one invalid label. An expression must use at least one column (`2 * 3` is invalid).
- No leading minus: `-a + b` is invalid. `0 - a + b` works.
- Letters mean `a` to `z` and `A` to `Z`, and digits mean `0` to `9`.
- Every column label in the DataFrame is checked, including labels the expression does not use. Column values are
  checked only for the columns the expression uses, so a text column such as `name` in the task's example is fine.
- If `new_column` already exists, the result is empty. The task asks for an additional column, and overwriting would
  replace original data without warning.
- A DataFrame with numeric columns but no rows gives a result with the new column and no rows.

**Part 2**

- Counts in the problems table are on the 1,505 order lines, before the 5 duplicate copies are removed.
- Negative quantities are treated as returns and kept, so they lower their region's revenue. The export's TOTAL line
  counts them as negative. Their combined revenue is -913.00 (0.04% of the total).
- Returns have no link to the order they return: each negative order ID appears only once, and the file has no
  original order field. Five of the six have earlier sales of the same product in the same region; SO-11011 (West,
  desk lamp, 3 January) comes before any such sale. That is a question for the owner of the source system. It does
  not affect revenue by region.
- The four quantities written with a space (`1 762`) are read as thousands. A number formatter writes 1762 as
  `1 762`, these are the only four values of 1,000 or more, and the TOTAL line matches only with this reading.
- Those four lines are much larger than any other (the next largest quantity is 40) and make up 12.6% of total
  revenue and 31% of North's. Nothing in the file says they are wrong, so I kept them; the pipeline lists them in
  its output so they stay visible.
- Exact duplicate lines (same order ID, same content, directly below the original) are export errors and are removed.
  No order ID is used twice with different content.
- A missing unit price is filled with the product's price. This works because every product has exactly one price in
  the file. One of the four lines also has a discount of exactly 5% of its value at that price. If a product ever had
  two prices, the pipeline would stop.

## How this was built

I built this in cooperation with Claude Code, an AI coding assistant. We worked through the design, the data and the
code together, and I made the final calls.
