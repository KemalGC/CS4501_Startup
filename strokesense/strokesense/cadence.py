"""Evidence-qualified crew cadence, not forced per-person agreement.

Consensus is a heuristic across per-rower median cycle rates, not a common-clock
measurement or proof of synchronized catches. Raw strokes/summaries are retained.
"""
from __future__ import annotations
import math
from statistics import median

VERSION = 'crew-cadence-consensus-v1'
_LABELS = {
    'no_cycles': 'No usable cycles',
    'insufficient_cycles': 'Unconfirmed: fewer than 2 cycles',
    'unstable_cycles': 'Unconfirmed: variable cycle estimates',
    'inconsistent_with_crew': 'Unconfirmed: differs from crew estimate',
    'agrees': 'Consistent with crew estimate',
    'unconfirmed': 'Crew agreement unavailable',
}


def estimate(rowers):
    per = {}; eligible = []
    for rower in rowers:
        values = [float(s.rate) for s in rower.strokes
                  if isinstance(s.rate, (int, float)) and math.isfinite(s.rate)
                  and 12 <= s.rate <= 50]
        raw = float(median(values)) if values else None
        state = 'no_cycles' if not values else 'insufficient_cycles'
        if len(values) >= 2:
            spread = float(median([abs(v - raw) for v in values]))
            state = 'unstable_cycles' if spread > max(2., .10 * raw) else 'unconfirmed'
            if state == 'unconfirmed':
                eligible.append((rower.seat, raw, len(values)))
        per[rower.seat] = {'raw_spm': raw, 'cycles': len(values), 'state': state}
    consensus = None; support = []
    if len(eligible) >= min(3, max(2, len(rowers))):
        centre = float(median([r[1] for r in eligible]))
        support = [r for r in eligible if abs(r[1] - centre) <= max(2., .10 * centre)]
        minimum = max(min(3, max(2, len(rowers))), len(eligible)//2 + 1)
        if len(support) >= minimum:
            consensus = float(median([r[1] for r in support]))
            supported = {r[0] for r in support}
            for seat, _, _ in eligible:
                per[seat]['state'] = 'agrees' if seat in supported else 'inconsistent_with_crew'
        else:
            support = []
    return {'version': VERSION, 'state': 'estimated' if consensus is not None else 'insufficient_agreement',
        'rate_spm': consensus, 'supporting_rowers': len(support), 'eligible_rowers': len(eligible),
        'total_rowers': len(rowers), 'supporting_cycles': sum(r[2] for r in support),
        'per_rower': per}


def qualification(result, seat):
    return _LABELS[result['per_rower'][seat]['state']]


def description(result):
    if result['rate_spm'] is None:
        return 'Crew cadence unavailable: not enough agreeing multi-cycle observations.'
    return (f"Estimated crew cadence: {result['rate_spm']:.1f} spm; "
            f"{result['supporting_rowers']} of {result['total_rowers']} rowers support it "
            f"({result['supporting_cycles']} observed cycles).")
