"""One boat cadence from overlapping observed periods; phase is a separate issue.

The six-second neighborhood is a short smoothing horizon for cycle midpoints,
not a resampling clock or a guarantee of six seconds of continuous visibility.
It suppresses catch-location jitter while retaining changes over a few strokes.
Only rowers with an actually observed interval at the current source time vote.
No gap, catch, missed cycle or half/double-rate correction is synthesized.
"""
from __future__ import annotations
from collections import Counter
import math
from numbers import Real
from statistics import median

VERSION = 'shared-boat-cadence-v3'
LEGACY_VERSION = 'crew-cadence-consensus-v1'
PERIOD_NEIGHBORHOOD_SECONDS = 6.0
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
    return {'version': LEGACY_VERSION, 'state': 'estimated' if consensus is not None else 'insufficient_agreement',
        'rate_spm': consensus, 'supporting_rowers': len(support), 'eligible_rowers': len(eligible),
        'total_rowers': len(rowers), 'supporting_cycles': sum(r[2] for r in support),
        'per_rower': per}


def qualification(result, seat):
    return _LABELS[result['per_rower'][seat]['state']]


def description(result):
    if result['rate_spm'] is None:
        return 'Crew cadence unavailable: not enough unambiguous, overlapping multi-cycle observations.'
    if result.get('method') == 'overlapping_interval_trend':
        return (f"Estimated crew cadence: {result['rate_spm']:.1f} spm shared by the boat; "
                f"{result['supporting_rowers']} of {result['total_rowers']} rowers contribute "
                f"{result['supporting_cycles']} observed cycle intervals across "
                f"{result['support_duration_seconds']:.1f} supported seconds. "
                'This measures the common rhythm, not identical catch timing.')
    if result.get('method') == 'shared_observed_catch_intervals':
        return (f"Estimated crew cadence: {result['rate_spm']:.1f} spm; "
                f"{len(result['shared_cycles'])} shared boat cycles, "
                f"{result['supporting_rowers']} of {result['total_rowers']} supporting rowers "
                f"({result['supporting_cycles']} rower-cycle observations).")
    return (f"Estimated crew cadence: {result['rate_spm']:.1f} spm; "
            f"{result['supporting_rowers']} of {result['total_rowers']} rowers support it "
            f"({result['supporting_cycles']} observed cycles; legacy rate-only consensus).")


def _observed_timeline(rowers, result, observed_intervals):
    """Retain the stricter simultaneous-catch evidence as a separate diagnostic."""
    minimum = min(3, max(2, len(rowers)))
    intervals, candidates = [], []
    for seat, per in result['per_rower'].items():
        if per['state'] in ('no_cycles', 'insufficient_cycles', 'unstable_cycles'):
            continue
        unique = set()
        for item in observed_intervals:
            if item['rower'] != seat:
                continue
            a, b = item['catch_seconds'], item['next_catch_seconds']
            intervals.append((seat, a, b))
            unique.update((a, b))
        candidates.extend((t, seat) for t in sorted(unique))
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


def _finite_number(value):
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)


def _timed_intervals(rowers):
    """Unique complete observed intervals, with no duplicated identity votes."""
    seats = Counter(r.seat for r in rowers)
    identities = [('track', getattr(r, 'tid')) if isinstance(getattr(r, 'tid', None), (str, int))
                  else ('seat', r.seat) for r in rowers]
    counts = Counter(identities)
    intervals = []
    for rower, identity in zip(rowers, identities):
        k = getattr(rower, 'k', None)
        fps = getattr(k, 'fps', None)
        if seats[rower.seat] != 1 or counts[identity] != 1 or not _finite_number(fps) or fps <= 0:
            continue
        n = getattr(k, 'n', None)
        last = (float(n)-1)/fps if _finite_number(n) and n > 1 else None
        pairs = {}
        for stroke in rower.strokes:
            a, b = getattr(stroke, 'catch_t', None), getattr(stroke, 'next_catch_t', None)
            if not _finite_number(a) or not _finite_number(b):
                continue
            a, b = float(a/fps), float(b/fps)
            if a < 0 or not 1.2 <= b-a <= 5.0 or (last is not None and b > last + 1e-7):
                continue
            pairs.setdefault((round(a, 9), round(b, 9)), (a, b))
        ordered = sorted(pairs.values())
        # Overlapping cycles from one track are not independent observations.
        conflicts = {i for i, (a, b) in enumerate(ordered)
                     if any(i != j and min(b, d)-max(a, c) > 1e-7
                            for j, (c, d) in enumerate(ordered))}
        for i, (a, b) in enumerate(ordered):
            if i not in conflicts:
                intervals.append({'id': len(intervals), 'rower': rower.seat,
                                  'catch_seconds': a, 'next_catch_seconds': b,
                                  'period_seconds': b-a, 'rate_spm': 60/(b-a)})
    return intervals


def _local_vote(intervals, seconds):
    """Fit periods nearby in time, but vote only while actually observed."""
    if not any(item['catch_seconds'] <= seconds < item['next_catch_seconds'] for item in intervals):
        return None
    local = [item for item in intervals
             if abs((item['catch_seconds']+item['next_catch_seconds'])/2-seconds)
             <= PERIOD_NEIGHBORHOOD_SECONDS/2]
    if not local:
        return None
    period = float(median(item['period_seconds'] for item in local))
    deviation = float(median(abs(item['period_seconds']-period) for item in local))
    tolerance = max(.15, .15*period)
    # Equal mixtures of half/double periods must not become an invented midpoint.
    if deviation > tolerance:
        return None
    kept = [item for item in local if abs(item['period_seconds']-period) <= tolerance]
    # A two-to-one alternating half/double pattern has a zero MAD but is still
    # an unresolved local rhythm. Permit isolated outliers only when the
    # observed local periods lead them by more than one complete interval.
    rejected = len(local)-len(kept)
    if rejected and len(kept)-rejected < 2:
        return None
    period = float(median(item['period_seconds'] for item in kept))
    return {'rower': intervals[0]['rower'], 'period_seconds': period,
            'rate_spm': 60/period, 'interval_ids': [item['id'] for item in kept]}


def _rate_tolerance(rate):
    return max(2., .10*rate)


def _dominant_votes(votes, minimum):
    """Bounded clusters, one vote per rower, with an explicit ambiguity gate."""
    groups = {}
    for seed in votes:
        cluster = [v for v in votes if abs(v['rate_spm']-seed['rate_spm'])
                   <= _rate_tolerance(seed['rate_spm'])]
        centre = float(median(v['rate_spm'] for v in cluster))
        cluster = [v for v in cluster if abs(v['rate_spm']-centre) <= _rate_tolerance(centre)]
        if cluster:
            groups[tuple(sorted(v['rower'] for v in cluster))] = cluster
    def score(group):
        centre = float(median(v['rate_spm'] for v in group))
        return (-len(group), float(median(abs(v['rate_spm']-centre) for v in group)), centre)
    ranked = sorted(groups.values(), key=score)
    if not ranked or len(ranked[0]) < minimum:
        return [], 'insufficient_overlap'
    best = ranked[0]
    if len(best) <= len(votes)/2:
        return [], 'ambiguous_cadence'
    centre = float(median(v['rate_spm'] for v in best))
    for alternate in ranked[1:]:
        other = float(median(v['rate_spm'] for v in alternate))
        if (abs(other-centre) > max(_rate_tolerance(centre), _rate_tolerance(other))
                and len(alternate) >= len(best)-1):
            return [], 'ambiguous_cadence'
    return best, None


def _trend_cells(by_rower, minimum):
    # Changes in observation coverage AND smoothing membership are boundaries.
    # Evaluating only event boundaries would miss an interval entering/leaving
    # a neighborhood without a new catch at that same source time.
    observed = sorted({t for values in by_rower.values() for item in values
                       for t in (item['catch_seconds'], item['next_catch_seconds'])})
    if not observed:
        return [], 0., 0.
    boundaries = set(observed)
    for values in by_rower.values():
        for item in values:
            midpoint = (item['catch_seconds']+item['next_catch_seconds'])/2
            boundaries.update(t for t in (midpoint-PERIOD_NEIGHBORHOOD_SECONDS/2,
                                           midpoint+PERIOD_NEIGHBORHOOD_SECONDS/2)
                              if observed[0] < t < observed[-1])
    boundaries = sorted(boundaries)
    cells, ambiguous_seconds, observable_seconds = [], 0., 0.
    for start, end in zip(boundaries, boundaries[1:]):
        if end-start < 1e-9:
            continue
        seconds = (start+end)/2
        active = sum(any(item['catch_seconds'] <= seconds < item['next_catch_seconds']
                         for item in values) for values in by_rower.values())
        if active >= minimum:
            observable_seconds += end-start
        votes = [v for values in by_rower.values()
                 if (v := _local_vote(values, seconds)) is not None]
        selected, reason = _dominant_votes(votes, minimum)
        if reason == 'ambiguous_cadence':
            ambiguous_seconds += end-start
        if selected:
            cells.append({'start_seconds': start, 'end_seconds': end,
                          '_votes': selected, '_eligible': len(votes)})
    # A single lucky period from a track cannot establish multi-cycle support.
    # This only removes votes/cells; it never makes a rejected minority win.
    while cells:
        contributions = {}
        for cell in cells:
            for vote in cell['_votes']:
                contributions.setdefault(vote['rower'], set()).update(vote['interval_ids'])
        good = {seat for seat, ids in contributions.items() if len(ids) >= 2}
        trimmed = []
        removed = False
        for cell in cells:
            votes = [v for v in cell['_votes'] if v['rower'] in good]
            if len(votes) >= minimum and len(votes) > cell['_eligible']/2:
                trimmed.append({**cell, '_votes': votes})
                removed |= len(votes) != len(cell['_votes'])
            else:
                removed = True
        cells = trimmed
        if not removed:
            break
    return cells, float(ambiguous_seconds), float(observable_seconds)


def _coalesce_trend(cells):
    trend = []
    for cell in cells:
        votes = cell['_votes']
        rate = 60/float(median(v['period_seconds'] for v in votes))
        seats = sorted(v['rower'] for v in votes)
        ids = sorted({i for v in votes for i in v['interval_ids']})
        item = {'start_seconds': cell['start_seconds'], 'end_seconds': cell['end_seconds'],
                'rate_spm': rate, 'rowers': seats, 'observations': len(ids), 'interval_ids': ids}
        if (trend and abs(trend[-1]['end_seconds']-item['start_seconds']) < 1e-8
                and abs(trend[-1]['rate_spm']-rate) < 1e-9 and trend[-1]['rowers'] == seats):
            previous = trend[-1]
            previous['end_seconds'] = item['end_seconds']
            previous['interval_ids'] = sorted(set(previous['interval_ids']) | set(ids))
            previous['observations'] = len(previous['interval_ids'])
        else:
            trend.append(item)
    return trend


def estimate(rowers):
    """Fit one shared boat rate without confusing phase offsets with cadence.

    At least three distinct rowers (two for a pair) must support a strict local
    majority. Each contributor supplies at least two real cycle observations;
    simultaneous supported time must span at least 1.5 typical periods (and 2s)
    and cover a majority of time with at least the minimum observed rowers.
    That overlap gate permits fixed catch-phase offsets in a two-cycle sample.
    It is not a claim of two aligned boat cycles; those remain in shared_cycles.
    The coverage gate prevents a brief clear tail from hiding divided footage;
    wholly unobserved gaps do not count toward its denominator.

    Local consensus is robust in period space. Its time-weighted mean rate is
    the clip's shared summary; it is not eight separate rower measurements.
    """
    rowers = list(rowers)
    result = _legacy_estimate(rowers)
    if not any(getattr(getattr(r, 'k', None), 'fps', None) is not None for r in rowers):
        result['method'] = 'legacy_rate_only_consensus'
        for per in result['per_rower'].values():
            per['shared_rate_spm'] = result['rate_spm']
        return result
    raw_states = {seat: per['state'] for seat, per in result['per_rower'].items()}
    intervals = _timed_intervals(rowers)
    _observed_timeline(rowers, result, intervals)
    by_rower = {r.seat: [item for item in intervals if item['rower'] == r.seat] for r in rowers}
    eligible = {seat: values for seat, values in by_rower.items() if len(values) >= 2}
    minimum = min(3, max(2, len(rowers)))
    cells, ambiguous_seconds, observable_seconds = _trend_cells(eligible, minimum)
    trend = _coalesce_trend(cells)
    duration = float(sum(item['end_seconds']-item['start_seconds'] for item in trend))
    candidate = (sum(item['rate_spm']*(item['end_seconds']-item['start_seconds'])
                     for item in trend)/duration) if duration > 0 else None
    enough_time = candidate is not None and duration + 1e-7 >= max(2., 1.5*60/candidate)
    support_fraction = duration/observable_seconds if observable_seconds else 0.
    enough_coverage = support_fraction > .5 + 1e-9
    rate = float(candidate) if enough_time and enough_coverage else None
    contributions = {seat: {i for item in trend for i in item['interval_ids']
                            if intervals[i]['rower'] == seat} for seat in by_rower}
    supporters = {seat for seat, ids in contributions.items() if len(ids) >= 2}
    for seat, per in result['per_rower'].items():
        count = len(by_rower.get(seat, []))
        if count < 2:
            per['state'] = 'no_cycles' if count == 0 else 'insufficient_cycles'
        elif rate is not None and seat in supporters:
            per['state'] = 'agrees'
        elif raw_states[seat] == 'unstable_cycles':
            per['state'] = 'unstable_cycles'
        else:
            per['state'] = 'inconsistent_with_crew' if rate is not None else 'unconfirmed'
        per.update(shared_rate_spm=rate, contributing_cycles=len(contributions.get(seat, set())),
                   observed_cycles=count)
    reason = (None if rate is not None else
              'insufficient_supported_coverage' if trend and not enough_coverage else
              'insufficient_supported_duration' if trend else
              'ambiguous_cadence' if ambiguous_seconds > 0 else 'insufficient_overlap')
    result.update(version=VERSION, method='overlapping_interval_trend',
                  state='estimated' if rate is not None else 'insufficient_agreement',
                  rate_spm=rate, supporting_rowers=len(supporters), eligible_rowers=len(eligible),
                  supporting_cycles=sum(len(ids) for ids in contributions.values()),
                  support_duration_seconds=duration, ambiguous_duration_seconds=ambiguous_seconds,
                  observable_duration_seconds=observable_seconds, support_fraction=support_fraction,
                  rate_range_spm=([min(item['rate_spm'] for item in trend),
                                   max(item['rate_spm'] for item in trend)] if rate is not None else None),
                  trend=trend, interval_evidence=intervals,
                  reason=reason, period_neighborhood_seconds=PERIOD_NEIGHBORHOOD_SECONDS,
                  summary_method='time_weighted_mean_of_robust_local_period_consensus',
                  scope='shared_boat_estimate')
    return result
