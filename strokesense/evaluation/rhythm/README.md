# Rhythm evidence on the source timeline

Stroke segmentation previously removed nonfinite samples before autocorrelation.
That concatenated separated observations and changed their time spacing. Generic
single-rower selection also filled absence with a median, treating invented
values as rhythm evidence.

Both paths now share a missing-aware rhythm calculation. Lag products use only
observed pairs at their original source-frame offsets. Pair-count correction and
a minimum support gate handle gaps without pretending that missing samples were
measured. Leading/trailing absence is ignored without collapsing internal gaps.
Complete finite signals retain the previous autocorrelation strength and lag
taper. Existing stroke amplitude, observed-phase, and cycle-quality gates remain.

Seven new regressions cover complete-signal equivalence, missing observations,
source-time preservation at the segmentation call boundary, missing edges,
unsupported inputs, common crew/single-rower policy, and invalid settings.

`compare.py` replays the same real tracks and body conditioning through the
frozen and revised stroke selector. Accepted-cycle counts changed as follows:

| Segment | Before | After |
|---|---:|---:|
| 0185 boat 1 | 30 | 31 |
| 0185 boat 2 | 16 | 16 |
| 9673 boat 1 | 64 | 63 |
| 9674 boat 1 | 51 | 55 |
| 9674 boat 2 | 33 | 33 |

These counts are diagnostics, not independent event accuracy. No missing event
is synthesized, and no rower is forced to a crew-average rate.

Validation: the four legacy synthetic analysis/fault tests pass. Full unittest
suite: 784 tests, with the same ten baseline application failures and one baseline
cold-model preview timeout; no additional failures were introduced.

Run from `app/strokesense`:

```sh
.venv/bin/python evaluation/rhythm/compare.py
.venv/bin/python -m unittest discover -s tests -p test_rhythm.py -v
```
