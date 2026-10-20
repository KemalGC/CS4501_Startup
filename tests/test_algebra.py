import pytest

from proofgrade.algebra import UnsupportedInput, check_solution, parse_statement


@pytest.mark.parametrize("original,steps,status,index", [
    ("2(x+3)=10", ["2x+3=10", "2x=7"], "incorrect", 1),
    ("2(x+3)=10", ["2x+6=10", "2x=4", "x=2"], "correct", None),
    ("2(x+3)=10", ["2x+6=10", "2x=16"], "incorrect", 2),
    ("2x=4", ["2x=4"], "incomplete", None),
    ("x^2=4", ["x=2"], "incorrect", 1),
    ("x^2=4", ["x=-2 or x=2"], "correct", None),
    ("x^2=2", ["x=-sqrt(2) or x=sqrt(2)"], "correct", None),
    ("x(x-1)=0", ["x-1=0"], "incorrect", 1),
    ("x=2", ["x^2=4"], "incorrect", 1),
    ("x^2+1=0", ["no real solutions"], "correct", None),
    ("x+1=x+1", ["all real numbers"], "correct", None),
    ("x+1=x+2", ["no real solutions"], "correct", None),
    ("0.1x=0.3", ["x=3"], "correct", None),
    ("-x^2=-4", ["x^2=4", "x=2 or x=-2"], "correct", None),
    ("2x=4", ["x=3", "malformed"], "incorrect", 1),
])
def test_transitions(original, steps, status, index):
    result = check_solution(original, steps)
    assert (result.status, result.first_error_step) == (status, index)


@pytest.mark.parametrize("text", [
    "__import__('os').system('id')=0", "x.__class__=1", "y=1", "sin(x)=0",
    "1/x=2", "x/0=1", "sqrt(x)=2", "x^999=0", "x^2^2=0", "x*x*x=0",
    "sqrt(-1)=0", "1==1", "1=1=1", "x<=2", "[1]=1", "x=", "x=2 3",
    "x=" + "(" * 13 + "1" + ")" * 13, "x=" + "9" * 13,
    "x=1 or x=2 or x=3", "x^2=4 or x=3", "x=0^0",
])
def test_rejects_unsupported_and_executable_input(text):
    with pytest.raises(UnsupportedInput):
        parse_statement(text)


def test_unsupported_step_is_not_marked_as_math_error():
    result = check_solution("2x=4", ["x=2", "some explanation"])
    assert result.status == "unsupported"
    assert result.unsupported_step == 2
    assert result.first_error_step is None


def test_limits_and_missing_steps():
    assert check_solution("x=1", []).status == "unsupported"
    assert check_solution("x=1", ["x=1"] * 21).status == "unsupported"
    assert check_solution("x=" + "1" * 257, ["x=1"]).unsupported_step == 0
