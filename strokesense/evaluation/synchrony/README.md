# Crew catch association

The previous implementation anchored to whichever rower had the most detected
catches. It could reuse another rower's catch, omit endpoints of disconnected
accepted cycles, and retain stale timing fields after evidence disappeared.

The candidate groups observed catch endpoints around a robust crew median.
Each physical identity contributes once per event; each observed catch is used
at most once. Duplicate identities/seats cannot vote. A strict majority of the
input crew is required, and per-seat summary values need two supported events.
Ambiguous nearby catches from a rower do not vote in that candidate group.
Nothing is imputed and individual timing offsets are retained.

Association uses a radius of 17.5% of the median cycle period (each rower gets
one period vote). This is a matching tolerance, not a correctness threshold.
Severe desynchronization or poor detection can leave insufficient consensus;
withholding a score is preferable to assigning different strokes to one event.
This does not resolve incorrectly localized joints or incorrectly detected catches.

Run from `app/strokesense`:

```
.venv/bin/python -m unittest discover -s tests -p test_synchrony.py -v
.venv/bin/python evaluation/synchrony/compare.py
```

Nine regression tests cover analytic offsets, event uniqueness, disconnected
cycles, duplicate identities, false extra catches, a 4/4 crew split, changing
cadence, invalid evidence, and stale results. The clustered false-catch case
has one rower with accepted cycles (10,40), (14,44), (70,100), and seven with
(10,40), (40,70), (70,100). The reference-based method reuses the seven rowers'
frame-10 catches at reference frame 14 and omits frame 40. The candidate retains
four distinct crew events and excludes that rower's ambiguous early candidates.

Real-footage replay holds tracks, body conditioning, and detected strokes fixed.
`results.json` retains per-seat values and the candidate's event associations.
Mean absolute seat offsets in ms (baseline → candidate):

| Segment | Offset | Supported crew events |
|---|---:|---:|
| 0185 boat 1 | 43.02 → 34.09 | 6 |
| 0185 boat 2 | 96.40 → unavailable | 1 |
| 9673 boat 1 | 60.92 → 51.37 | 10 |
| 9674 boat 1 | 108.77 → 91.65 | 8 |
| 9674 boat 2 | 74.62 → 75.74 | 6 |

Lower offsets are **not** evidence of better accuracy: matching changes which
observations qualify. There are no independently labeled catch times in this
comparison. The main verified improvements are evidence independence, event
uniqueness, endpoint retention, and correct abstention under insufficient support.

Full suite after implementation: 792 tests, ten pre-existing application failures,
no new failures; the existing intermittent preview timeout did not recur. The ninth
synchrony test was added afterward and all nine passed in the focused run.
