"""Parse a small algebra grammar without eval or sympify on user text."""

from dataclasses import dataclass
import re

import sympy as sp

X = sp.Symbol("x", real=True)
MAX_LENGTH = 256
MAX_STEPS = 20
TOKEN = re.compile(r"\s*(sqrt|\d+(?:\.\d+)?|\.\d+|x|\*\*|[()+\-*/^])")


class UnsupportedInput(ValueError):
    pass


def bounded(value):
    value = sp.expand(value)
    if value.has(sp.zoo, sp.oo, -sp.oo, sp.nan) or sp.count_ops(value) > 64:
        raise UnsupportedInput("Expression is too complex or undefined.")
    for number in value.atoms(sp.Rational):
        if abs(int(number.p)).bit_length() > 256 or int(number.q).bit_length() > 256:
            raise UnsupportedInput("Numbers are too large for this practice checker.")
    if sp.Poly(value, X).degree() > 2:
        raise UnsupportedInput("Only linear and quadratic expressions are supported.")
    return value


class ExpressionParser:
    def __init__(self, text):
        if not text.strip() or len(text) > MAX_LENGTH:
            raise UnsupportedInput("Enter an expression of at most 256 characters.")
        self.tokens = []
        position = 0
        text = text.strip()
        while position < len(text):
            match = TOKEN.match(text, position)
            if not match:
                raise UnsupportedInput("Use x, numbers, +, -, *, /, ^, parentheses, or sqrt(number).")
            self.tokens.append(match.group(1))
            position = match.end()
        if len(self.tokens) > 64:
            raise UnsupportedInput("Use at most 64 tokens per expression.")
        self.position = 0
        self.depth = 0

    def peek(self):
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def take(self):
        token = self.peek()
        self.position += 1
        return token

    def parse(self):
        value = self.expression()
        if self.peek() is not None:
            raise UnsupportedInput("Unexpected notation. Use one expression on each side of =.")
        return value

    def expression(self):
        value = self.term()
        while self.peek() in ("+", "-"):
            operator = self.take()
            right = self.term()
            value = bounded(value + right if operator == "+" else value - right)
        return value

    def term(self):
        value = self.unary()
        while self.peek() in ("*", "/", "x", "(", "sqrt"):
            operator = self.peek()
            if operator in ("*", "/"):
                self.take()
            right = self.unary()
            if operator == "/":
                if right.has(X) or right == 0:
                    raise UnsupportedInput("Divide only by a nonzero constant; variable denominators are unsupported.")
                value = bounded(value / right)
            else:
                value = bounded(value * right)
        return value

    def unary(self):
        if self.peek() in ("+", "-"):
            sign = self.take()
            result = self.unary()
            return -result if sign == "-" else result
        value = self.atom()
        if self.peek() in ("^", "**"):
            self.take()
            exponent = self.take()
            if exponent not in ("0", "1", "2"):
                raise UnsupportedInput("Only powers 0, 1, and 2 are supported.")
            if value == 0 and exponent == "0":
                raise UnsupportedInput("0^0 is not supported.")
            value = bounded(value ** int(exponent))
        return value

    def atom(self):
        token = self.take()
        if token == "x":
            return X
        if token and re.fullmatch(r"\d+(?:\.\d+)?|\.\d+", token):
            if len(token) > 12:
                raise UnsupportedInput("Use numbers with at most 12 characters.")
            return bounded(sp.Rational(token))
        if token in ("(", "sqrt"):
            if token == "sqrt" and self.take() != "(":
                raise UnsupportedInput("Write square roots as sqrt(number).")
            self.depth += 1
            if self.depth > 12:
                raise UnsupportedInput("Parentheses are nested too deeply.")
            value = self.expression()
            if self.take() != ")":
                raise UnsupportedInput("Check the closing parentheses.")
            self.depth -= 1
            if token == "sqrt":
                if not value.is_Rational or value < 0:
                    raise UnsupportedInput("Square roots require a nonnegative rational constant.")
                value = bounded(sp.sqrt(value))
            return value
        raise UnsupportedInput("Expected a number, x, or an opening parenthesis.")


@dataclass(frozen=True)
class Statement:
    solutions: sp.Set
    complete: bool


def equation(text):
    if text.count("=") != 1:
        raise UnsupportedInput("Write each equation with exactly one = sign.")
    left, right = text.split("=")
    return ExpressionParser(left).parse(), ExpressionParser(right).parse()


def parse_statement(text):
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_LENGTH:
        raise UnsupportedInput("Each step must contain 1–256 characters.")
    text = text.strip()
    if text == "no real solutions":
        return Statement(sp.S.EmptySet, True)
    if text == "all real numbers":
        return Statement(sp.S.Reals, True)
    alternatives = re.split(r"\s+or\s+", text)
    if len(alternatives) > 2:
        raise UnsupportedInput("Use at most two alternative roots.")
    solutions = sp.S.EmptySet
    complete = True
    for alternative in alternatives:
        left, right = equation(alternative)
        isolated = (left == X and not right.has(X)) or (right == X and not left.has(X))
        if len(alternatives) > 1 and not isolated:
            raise UnsupportedInput("Write alternative roots as x = a or x = b.")
        result = sp.solveset(left - right, X, domain=sp.S.Reals)
        if not isinstance(result, sp.FiniteSet) and result not in (sp.S.Reals, sp.S.EmptySet):
            raise UnsupportedInput("This equation needs manual review.")
        solutions = sp.Union(solutions, result)
        complete = complete and isolated
    return Statement(solutions, complete)


@dataclass(frozen=True)
class CheckResult:
    status: str
    first_error_step: int | None = None
    unsupported_step: int | None = None
    message: str = ""


def check_solution(original: str, steps: list[str]) -> CheckResult:
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        return CheckResult("unsupported", message="Enter between 1 and 20 steps.")
    try:
        previous = parse_statement(original)
    except UnsupportedInput as error:
        return CheckResult("unsupported", unsupported_step=0, message=str(error))
    for index, text in enumerate(steps, start=1):
        try:
            current = parse_statement(text)
        except UnsupportedInput as error:
            return CheckResult("unsupported", unsupported_step=index, message=str(error))
        if current.solutions != previous.solutions:
            return CheckResult("incorrect", first_error_step=index,
                               message=f"Step {index} changes the real solutions of the previous equation.")
        previous = current
    if previous.complete:
        return CheckResult("correct", message="Every step preserves the solution set, and your answer is complete.")
    return CheckResult("incomplete", message="No incorrect step found yet. Continue until you state every solution.")
