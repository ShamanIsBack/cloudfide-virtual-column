import re

import pandas

# Step 1: the tokeniser ----------------------------------------------------------

# Cut generously: a whole run of word-like characters, or one operator/bracket,
# or any other single non-space character (so that it can be rejected below).
PIECE = re.compile(r"[A-Za-z0-9_.]+|[-+*()]|\S")

# Then judge strictly.
LABEL = re.compile(r"[A-Za-z_]+")
NUMBER = re.compile(r"\d+(\.\d+)?")
OPERATORS = {"+", "-", "*", "(", ")"}


class InvalidRole(Exception):
    """The expression is not one we accept."""


def tokenize(role: str) -> list[tuple[str, str]]:
    """Turn "(a + b) * 2" into [("(", "("), ("label", "a"), ("+", "+"), ...]."""
    tokens = []
    for piece in PIECE.findall(role):
        if LABEL.fullmatch(piece):
            tokens.append(("label", piece))
        elif NUMBER.fullmatch(piece):
            tokens.append(("number", piece))
        elif piece in OPERATORS:
            tokens.append((piece, piece))
        else:
            raise InvalidRole(f"not allowed: {piece!r}")
    return tokens


# Step 2: the parser -------------------------------------------------------------
#
#   expression  =  term   { ("+" | "-")  term   }
#   term        =  factor { "*"          factor }
#   factor      =  label  |  number  |  "(" expression ")"
#
# One method per rule. Each method reads the tokens its rule covers and returns
# the computed value: a column (pandas Series) or a plain number.


class Parser:
    def __init__(self, tokens: list[tuple[str, str]], df: pandas.DataFrame):
        self.tokens = tokens
        self.position = 0
        self.df = df

    def peek(self) -> str | None:
        """The kind of the next token, without using it up. None at the end."""
        if self.position < len(self.tokens):
            return self.tokens[self.position][0]
        return None

    def take(self) -> tuple[str, str]:
        """Use up the next token and return it."""
        token = self.tokens[self.position]
        self.position += 1
        return token

    def parse(self):
        value = self.expression()
        if self.peek() is not None:  # tokens left over, e.g. "a b" or "a + b)"
            raise InvalidRole(f"unexpected {self.peek()!r}")
        return value

    def expression(self):
        value = self.term()
        while self.peek() in ("+", "-"):
            if self.peek() == "+":
                self.take()
                value = value + self.term()
            else:
                self.take()
                value = value - self.term()
        return value

    def term(self):
        value = self.factor()
        while self.peek() == "*":
            self.take()
            value = value * self.factor()
        return value

    def factor(self):
        kind = self.peek()
        if kind == "label":
            _, name = self.take()
            if name not in self.df.columns:
                raise InvalidRole(f"no column {name!r}")
            return self.df[name]
        if kind == "number":
            _, text = self.take()
            return float(text) if "." in text else int(text)
        if kind == "(":
            self.take()
            value = self.expression()
            if self.peek() != ")":
                raise InvalidRole("missing ')'")
            self.take()
            return value
        raise InvalidRole(f"expected a column, a number or '(', got {kind!r}")


# Step 3: the function the brief asks for ----------------------------------------


def add_virtual_column(df: pandas.DataFrame, role: str, new_column: str) -> pandas.DataFrame:
    empty = pandas.DataFrame([])

    # Every label must be letters and underscores: the frame's columns and the new one.
    labels_ok = all(isinstance(label, str) and LABEL.fullmatch(label) for label in df.columns)
    new_ok = isinstance(new_column, str) and LABEL.fullmatch(new_column) and new_column not in df.columns
    if not (labels_ok and new_ok and isinstance(role, str)):
        return empty

    try:
        value = Parser(tokenize(role), df).parse()
    except InvalidRole:
        return empty

    if not isinstance(value, pandas.Series):  # only numbers, e.g. "2 * 3": no column used
        return empty

    result = df.copy()
    result[new_column] = value
    return result
