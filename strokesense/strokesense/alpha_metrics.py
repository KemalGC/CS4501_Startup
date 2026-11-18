"""Reproducible software QA counts; never participant or model accuracy.

Issue #122. A test ID is a full unittest ID printed by the runner, not an
assertion count. Missing run completion and missing authorship stay unknown.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Mapping, Iterable


def assert_same_commit(expected: str, actual: str) -> None:
    if not all(isinstance(x, str) and re.fullmatch(r'[0-9a-f]{40}', x) for x in (expected, actual)):
        raise ValueError('full_commit_sha_required')
    if expected != actual:
        raise ValueError('run_source_commit_mismatch')


def parse_unittest_log(log: str) -> dict:
    """Parse one completed unittest run; preserve duplicate discovery counts."""
    ids = re.findall(r'^test\S+\s+\(([^)]+)\)', log, re.MULTILINE)
    runs = list(re.finditer(r'^Ran (\d+) tests? in ([\d.]+)s\s*$', log, re.MULTILINE))
    result = {'complete': False, 'executions': None, 'unique_tests': len(set(ids)),
              'repeated_executions': max(0, len(ids) - len(set(ids))),
              'passed': None, 'failures': None, 'errors': None, 'skipped': None,
              'expected_failures': None, 'unexpected_successes': None,
              'pass_rate_pct': None, 'test_ids': sorted(set(ids))}
    if len(runs) != 1:
        return result
    run = runs[0]
    count = int(run.group(1))
    end = re.search(r'^(OK|FAILED)(?:\s*\(([^)]*)\))?\s*$', log[run.end():], re.MULTILINE)
    result['executions'] = count
    result['duration_seconds'] = float(run.group(2))
    if not end:
        return result
    values = {'failures': 0, 'errors': 0, 'skipped': 0,
              'expected failures': 0, 'unexpected successes': 0}
    if end.group(2):
        for token in end.group(2).split(','):
            pair = token.strip().split('=')
            if len(pair) != 2 or pair[0] not in values or not pair[1].isdigit():
                return result
            values[pair[0]] = int(pair[1])
    nonpasses = sum(values.values())
    if nonpasses > count or (end.group(1) == 'OK' and (values['failures'] or values['errors'] or values['unexpected successes'])):
        return result
    result.update(complete=True, passed=count - nonpasses, failures=values['failures'],
                  errors=values['errors'], skipped=values['skipped'],
                  expected_failures=values['expected failures'],
                  unexpected_successes=values['unexpected successes'],
                  pass_rate_pct=100.0 * (count - nonpasses) / count if count else None,
                  repeated_executions=max(0, count - len(set(ids))))
    # A quiet log can prove the execution count, but not the unique-test count.
    result['identity_listing_complete'] = len(ids) == count
    if len(ids) != count:
        result['unique_tests'] = None
        result['repeated_executions'] = None
    return result


def _coverage_pair(totals: Mapping, numerator: str, denominator: str) -> tuple:
    a, b = totals.get(numerator, 0), totals.get(denominator, 0)
    if type(a) is not int or type(b) is not int or not 0 <= a <= b:
        raise ValueError('invalid_coverage_counts')
    return a, b, 100.0 * a / b if b else None


def coverage_metrics(document: Mapping) -> dict:
    totals = document.get('totals', {})
    if not isinstance(totals, dict):
        raise ValueError('invalid_coverage_totals')
    a, b, percent = _coverage_pair(totals, 'covered_lines', 'num_statements')
    c, d, branch_percent = _coverage_pair(totals, 'covered_branches', 'num_branches')
    return {'covered_lines': a, 'executable_lines': b, 'line_coverage_pct': percent,
            'covered_branches': c, 'branches': d, 'branch_coverage_pct': branch_percent,
            'scope': 'Python strokesense package under the declared test command; not model accuracy'}


def issue_metrics(mapping: Mapping[str, Iterable[str]], ids: Iterable[str], closed: Iterable[int]) -> dict:
    known = set(ids)
    closed = {str(n) for n in closed}
    mapped = {}
    for issue, cases in mapping.items():
        if not str(issue).isdigit() or isinstance(cases, (str, bytes)):
            raise ValueError('invalid_issue_mapping')
        mapped[str(issue)] = sorted(set(cases))
        if not set(mapped[str(issue)]).issubset(known):
            raise ValueError('mapped_test_not_in_run')
    links = sum(len(cases) for cases in mapped.values())
    unique = set().union(*(set(x) for x in mapped.values())) if mapped else set()
    return {'issues': len(mapped), 'closed_issues': len(set(mapped) & closed),
            'test_issue_links': links, 'unique_mapped_tests': len(unique),
            'average_tests_per_issue': links / len(mapped) if mapped else None,
            'method': 'Distinct test IDs per mapped issue, summed across issues; shared tests can map to multiple issues',
            'mapping': mapped}


def test_provenance(ids: Iterable[str], records: Mapping[str, str]) -> dict:
    known = set(ids)
    allowed = {'ai_generated', 'human_refined_or_added', 'unknown'}
    if any(v not in allowed for v in records.values()) or not set(records).issubset(known):
        raise ValueError('invalid_test_provenance')
    counts = {k: 0 for k in allowed}
    for test in known:
        counts[records.get(test, 'unknown')] += 1
    return {'total': len(known), **counts,
            'overall_ai_pct': 100.0 * counts['ai_generated'] / len(known) if known and not counts['unknown'] else None,
            'method': 'Explicit test-level provenance only; unknown is not human-written and cannot establish an overall ratio'}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--log', required=True)
    parser.add_argument('--coverage', required=True)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--run-sha', required=True)
    parser.add_argument('--mapping')
    parser.add_argument('--closed-issues', default='')
    parser.add_argument('--provenance')
    args = parser.parse_args(argv)
    assert_same_commit(args.source_sha, args.run_sha)
    result = {'schema_version': 1, 'commit': args.source_sha,
              'tests': parse_unittest_log(Path(args.log).read_text(encoding='utf-8')),
              'coverage': coverage_metrics(json.loads(Path(args.coverage).read_text(encoding='utf-8')))}
    if args.mapping:
        result['issue_mapping'] = issue_metrics(json.loads(Path(args.mapping).read_text()), result['tests']['test_ids'],
                                               [int(n) for n in args.closed_issues.split(',') if n])
    records = json.loads(Path(args.provenance).read_text()) if args.provenance else {}
    result['provenance'] = test_provenance(result['tests']['test_ids'], records)
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if result['tests']['complete'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
