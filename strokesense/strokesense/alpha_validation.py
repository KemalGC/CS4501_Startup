"""Privacy-safe seven-rower StrokeSense Alpha pilot summary.

Seven rowers, two with prior coaching experience, are team-reported recruitment
composition; this does NOT establish a qualified coach-majority reference.
"""
from __future__ import annotations
import argparse
import csv
import json
import math
import re
from statistics import median
from pathlib import Path

EXPECTED_ROWS = 7
REPORTED_PRIOR_COACHING = 2
FIELDS = (
    'participant_id', 'consent', 'coached_before', 'baseline_seconds',
    'assisted_seconds', 'timing_method', 'detail_preserved', 'actionable',
    'comment', 'withdrawn',
)
ANSWER = frozenset({'yes', 'no', ''})

def _seconds(raw):
    if raw == '':
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError('invalid_seconds') from None
    if not (math.isfinite(value) and 0 < value <= 86400):
        raise ValueError('invalid_seconds')
    return value

def _ratio(yes, n):
    return {'yes_n': yes, 'responded_n': n, 'pct': round(yes * 100 / n, 2) if n else None}

def summarize(rows):
    """Summarize *observed* responses, leaving unknown quantities explicitly null."""
    rows = list(rows)
    if len(rows) > EXPECTED_ROWS:
        raise ValueError('pilot_exceeds_declared_sample')
    ids = set()
    clean = []
    all_profile_yes = 0
    known_profile_n = 0
    for row in rows:
        if not isinstance(row, dict) or set(row) != set(FIELDS):
            raise ValueError('invalid_columns')
        rid = row['participant_id']
        if not isinstance(rid, str) or re.fullmatch(r'R[0-9]{2}', rid) is None:
            raise ValueError('invalid_participant_id')
        if rid in ids:
            raise ValueError('duplicate_participant_id')
        ids.add(rid)
        for field in ('consent', 'coached_before', 'detail_preserved', 'actionable', 'withdrawn'):
            if row[field] not in ANSWER:
                raise ValueError('invalid_' + field)
        if row['timing_method'] not in ('', 'stopwatch', 'estimate'):
            raise ValueError('invalid_timing_method')
        if not isinstance(row['comment'], str) or len(row['comment']) > 1000 or '\x00' in row['comment']:
            raise ValueError('invalid_comment')
        before = _seconds(row['baseline_seconds'])
        after = _seconds(row['assisted_seconds'])
        if row['coached_before']:
            known_profile_n += 1
            all_profile_yes += row['coached_before'] == 'yes'
        if row['withdrawn'] == 'yes' or row['consent'] != 'yes':
            continue
        clean.append((row, before, after))
    timed = [(before, after) for row, before, after in clean
             if row['timing_method'] == 'stopwatch' and before is not None and after is not None]
    med_before = median([x[0] for x in timed]) if timed else None
    med_after = median([x[1] for x in timed]) if timed else None
    reduction = round((med_before - med_after) / med_before * 100, 2) if timed else None
    details = [r['detail_preserved'] for r, _, _ in clean if r['detail_preserved']]
    actions = [r['actionable'] for r, _, _ in clean if r['actionable']]
    return {
        'schema_version': 1,
        'population': 'team-reported seven rowers; two have coached before; not a verified expert-majority panel',
        'declared_sample_n': EXPECTED_ROWS,
        'declared_prior_coaching_n': REPORTED_PRIOR_COACHING,
        'profile_rows_n': len(rows),
        'profile_prior_coaching_known_n': known_profile_n,
        'profile_prior_coaching_yes_n': all_profile_yes,
        'consented_n': len(clean),
        'timed_pairs_n': len(timed),
        'median_baseline_seconds': med_before,
        'median_assisted_seconds': med_after,
        'median_review_time_reduction_pct': reduction,
        'detail_preserved': _ratio(details.count('yes'), len(details)),
        'actionable': _ratio(actions.count('yes'), len(actions)),
        'expert_agreement_pct': None,
        'qualified_coach_actionability_pct': None,
        'slide_targets': {'review_time_reduction_pct': 30, 'coach_majority_agreement_pct': 75,
                          'qualified_coach_actionability_pct': 70},
        'decision': 'NOT_YET_VALIDATED',
        'reason': 'No independently verified expert-majority fault agreement or qualified-coach usefulness benchmark. Human timings and detail judgments may also be incomplete.',
        'limitations': [
            'An email entered without verification is self-declared identity, not a unique verified participant.',
            'Paired stopwatch timings compare median durations; estimates and missing times are excluded.',
            'Two rowers with prior coaching experience do not replace four independent coaches.',
            'Synthetic code tests and pose model predictions are not validation outcomes.',
        ],
    }

def load_pilot_csv(path):
    with Path(path).open(newline='', encoding='utf-8-sig') as fp:
        reader = csv.DictReader(fp)
        if reader.fieldnames != list(FIELDS):
            raise ValueError('invalid_header')
        return list(reader)

def main(argv=None):
    parser = argparse.ArgumentParser(description='Summarize real, consent-cleared StrokeSense Alpha pilot rows')
    parser.add_argument('--csv', required=True, help='Private participant CSV; never commit responses')
    args = parser.parse_args(argv)
    print(json.dumps(summarize(load_pilot_csv(args.csv)), indent=2, ensure_ascii=True))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
