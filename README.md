# ProofGrade

ProofGrade helps students find the first incorrect step in typed algebra practice
and revise their work using a checked hint. The selected startup brief is in
[README-startups/readme-startupSelected.md](README-startups/readme-startupSelected.md).

## Development

Requires Python 3.11 or newer.

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -q
```

## Supported algebra

- One real variable, `x`; linear or quadratic expressions.
- Exact integers, fractions, decimals, parentheses, implicit multiplication
  (`2x`, `2(x+3)`), and powers `^` / `**` with exponents 0, 1, or 2.
- `sqrt(number)` for nonnegative rational constants, including irrational roots.
- State both roots on one line: `x = -2 or x = 2`.
- Use `no real solutions` or `all real numbers` when appropriate.
- Up to 20 submitted steps, 256 characters per step, and bounded expression complexity.

Variable denominators, inequalities, complex numbers, handwriting, arbitrary
functions, and reasoning outside this grammar need manual review. Unsupported
syntax is distinguished from a mathematical error. Step numbers start at 1 for
the first submitted line after the original problem.

The checker compares real solution sets. This detects lost and added roots; it
does not certify every explanation or prove which operation the student intended.
A valid sequence is only marked complete when the final line states all roots
or the applicable special solution set. No AI-generated text is used by this layer.

## MVP acceptance goals

Proposed pilot targets: at least 90% first-error agreement on instructor-reviewed
examples, 70% correction after one hint, and 80% usefulness ratings of 4/5 or higher.
These are targets, not measured results. Human review and student testing are still
required before claiming learning benefits. The next changes add validated hints,
the student interface, and pilot/deployment support.
