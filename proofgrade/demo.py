"""Demonstrate validation retries with deliberately faulty offline candidates."""

from dataclasses import asdict
import json

from proofgrade.feedback import generate_feedback
from proofgrade.providers import DemoProvider


class FaultInjectedProvider(DemoProvider):
    def __init__(self, always_fail=False):
        self.always_fail = always_fail

    def generate(self, context, failures):
        candidate = super().generate(context, failures)
        if self.always_fail or not failures:
            candidate["correction"] = "x=999"
        return candidate


def main():
    results = {}
    for name, provider in [("bad_candidate_then_recovery", FaultInjectedProvider()),
                           ("three_bad_candidates_withheld", FaultInjectedProvider(True))]:
        result = generate_feedback("2(x+3)=10", ["2x+3=10"], "x=2", provider)
        results[name] = asdict(result)
    print(json.dumps({"provider": "deterministic demo; no real model calls", "scenarios": results}, indent=2))
    if results["bad_candidate_then_recovery"]["attempts"] != 2 or results["three_bad_candidates_withheld"]["hint"] is not None:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
