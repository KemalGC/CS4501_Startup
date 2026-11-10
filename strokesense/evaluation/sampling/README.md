# Full-source-rate comparison

Fresh identical CLI requests on the first 20 seconds of IMG_9673, except target
fps 15 versus 30 (actual 14.8227 vs 29.6454). Eight-seat tracker, same nano weights,
same tiles and configured ONNX providers. The earlier half-rate run predates only
the degenerate-angle correction; that scan found no collapsed limb segments.

Run `evaluation/sampling/compare.py` to compare private caches and saved metrics.
The full-rate run also passes `evaluation/pipeline/verify.py`.

| Diagnostic | Half rate | Full rate |
|---|---:|---:|
| Analysed frames | 296 | 592 |
| Accepted cycles | 36 | 34 |
| Supported crew events | 6 | 6 |
| Boat cadence estimate | 22.465 spm | 22.077 spm |
| Total CLI wall time | 32 s | 72 s |

All 296 common source frames have **exactly identical** cached boxes/keypoints.
Thus inference differences on those frames are not a confound. Tracking, additional
observations, smoothing and event selection can still contribute to differences.
Paired catches differ by up to ~0.24 s and finishes by ~0.32 s among the greedy
nearest-catch matches; the JSON retains every match. These are agreement diagnostics,
not error estimates: neither output is independent ground truth, and a nearest
match is not proof of event identity. More/fewer accepted cycles is not accuracy.

No sampling default change is justified by this experiment. The same five-sample
minimum quadratic smoothing window is used at both rates, giving different time
support. A next experiment should separate observation density from filter time
support, and test known fast/reversal motion before changing smoothing. Similar
outputs across rates alone would not establish correctness.

Private artifacts: `results/full-rate-evaluation/` and
`results/final-pipeline-evaluation/`, including annotated videos, frame snapshots,
metrics, caches, logs and the full-rate invariant verification.

## Isolating filter support

`filter_support.py` keeps production unchanged and tests full-rate default
five-sample fits against a nine-sample fit (~same temporal support as half-rate
five-sample fits). It uses known 20/32/40 spm synthetic joint motion, clean input,
1.5/3 px white noise, and 1.5/3 px temporally correlated noise (AR coefficient .85,
stationary marginal variance). Five seeds per noisy condition; clean inputs run
once. Ground truth comes directly from the generated joint geometry, before any
filter. Errors omit five boundary samples at each rate. Real cached full-rate
tracks are then replayed with the two filters; event counts are diagnostic only.

Mean elbow-angle RMSE in degrees:

| Input | Half default | Full default | Full wider |
|---|---:|---:|---:|
| Clean | 0.924 | 0.131 | 0.845 |
| White noise, 1.5 px | 4.475 | 4.238 | 3.494 |
| White noise, 3 px | 8.596 | 8.205 | 6.198 |
| Correlated noise, 1.5 px | 5.746 | 5.786 | 5.668 |
| Correlated noise, 3 px | 11.634 | 11.865 | 11.476 |

The wider window has a clear white-noise benefit, but attenuates clean movement
and offers much less benefit against persistent errors. Correlated noise is a
controlled counterexample, not a measured model of these videos. This does not
justify a uniform wider filter or a sampling-default change. Merely making outputs
more similar across frame rates could erase useful source-frame detail.

The full-rate real replay accepts 34 cycles with default support and 35 with wider
support. Neither count establishes better phase selection. Complete synthetic
errors and both real event lists are saved in `filter_support_results.json`.
