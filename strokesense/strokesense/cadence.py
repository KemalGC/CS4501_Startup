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


def _legacy_estimate(rowers):
    per = {}; eligible = []
    for rower in rowers:
        values = [float(s.rate) for s in rower.strokes
                  if isinstance(getattr(s, 'rate', None), (int, float)) and math.isfinite(s.rate)
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
    if result.get('method') == 'shared_observed_catch_intervals':
        return (f"Estimated crew cadence: {result['rate_spm']:.1f} spm; "
                f"{len(result['shared_cycles'])} shared boat cycles, "
                f"{result['supporting_rowers']} of {result['total_rowers']} supporting rowers "
                f"({result['supporting_cycles']} rower-cycle observations).")
    return (f"Estimated crew cadence: {result['rate_spm']:.1f} spm; "
            f"{result['supporting_rowers']} of {result['total_rowers']} rowers support it "
            f"({result['supporting_cycles']} observed cycles; legacy rate-only consensus).")


def estimate(rowers):
    """Shared catch intervals, not agreement between unrelated recording windows.

    Legacy rate-only objects keep their labeled fallback for compatibility. Real
    pipeline rowers carry fps and source-indexed catch pairs. No peak is inserted
    or corrected here: rejected/missed cycles remain unavailable.
    """
    result = _legacy_estimate(rowers)
    timed = [r for r in rowers if getattr(getattr(r, 'k', None), 'fps', None) is not None]
    if not timed:
        result['method'] = 'legacy_rate_only_consensus'
        return result
    minimum = min(3, max(2, len(rowers)))
    intervals, candidates = [], []
    for r in timed:
        if result['per_rower'][r.seat]['state'] in ('no_cycles', 'insufficient_cycles', 'unstable_cycles'):
            continue
        fps = float(r.k.fps)
        if not math.isfinite(fps) or fps <= 0:
            continue
        unique = set()
        for stroke in r.strokes:
            a = getattr(stroke, 'catch_t', None)
            b = getattr(stroke, 'next_catch_t', None)
            if any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in (a, b)):
                continue
            a, b = a/fps, b/fps
            if not 1.2 <= b-a <= 5.:
                continue
            intervals.append((r.seat, a, b))
            unique.update((a, b))
        candidates.extend((t, r.seat) for t in sorted(unique))
    # A cluster has bounded total width: no transitive chain of distant peaks.
    clusters = []
    for t, seat in sorted(candidates):
        if not clusters or t-clusters[-1][0][0] > .24:
            clusters.append([])
        clusters[-1].append((t, seat))
    events = []
    for cluster in clusters:
        seats = [seat for _, seat in cluster]
        if len(set(seats)) >= minimum and len(set(seats)) == len(seats):
            events.append({'seconds': float(median([t for t, _ in cluster])),
                           'rowers': sorted(seats)})
    shared = []
    for a, b in zip(events, events[1:]):
        support = sorted({seat for seat, begin, end in intervals
                          if abs(begin-a['seconds']) <= .15 and abs(end-b['seconds']) <= .15})
        period = b['seconds']-a['seconds']
        if len(support) >= minimum and 1.2 <= period <= 5.:
            shared.append({'catch_seconds': a['seconds'], 'next_catch_seconds': b['seconds'],
                           'rate_spm': 60/period, 'rowers': support})
    durations = [c['next_catch_seconds']-c['catch_seconds'] for c in shared]
    consensus = 60/float(median(durations)) if len(shared) >= 2 else None
    supporters = set(seat for c in shared for seat in c['rowers'])
    # Consecutive five-cycle windows require six supported catch events.
    windows = []
    for i in range(max(0, len(shared)-4)):
        five = shared[i:i+5]
        if all(abs(a['next_catch_seconds']-b['catch_seconds']) < 1e-6
               for a, b in zip(five, five[1:])):
            span = five[-1]['next_catch_seconds']-five[0]['catch_seconds']
            windows.append({'catch_seconds': five[0]['catch_seconds'],
                            'next_catch_seconds': five[-1]['next_catch_seconds'],
                            'cycles': 5, 'rate_spm': 300/span})
    for seat, per in result['per_rower'].items():
        if per['state'] in ('agrees', 'inconsistent_with_crew', 'unconfirmed'):
            per['state'] = ('agrees' if consensus is not None and seat in supporters else
                            'inconsistent_with_crew' if consensus is not None else 'unconfirmed')
    result.update(version='crew-catch-timeline-v2', method='shared_observed_catch_intervals',
                  state='estimated' if consensus is not None else 'insufficient_agreement',
                  rate_spm=consensus, supporting_rowers=len(supporters),
                  supporting_cycles=sum(len(c['rowers']) for c in shared),
                  shared_cycles=shared, catch_events=events, five_cycle_windows=windows,
                  sample_ready=bool(windows), time_basis='seconds_relative_to_analysis_start')
    return result
