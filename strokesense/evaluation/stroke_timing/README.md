# Fractional stroke-event clock

Previously the pipeline refined catch times for crew synchronization, but used
integer frame indices to compute rate, drive time, and recovery time. Those
quantities could therefore disagree even for an identical detected cycle.

The revised measurement uses fractional catch, finish, and next-catch times
consistently. Integer indices still select actual measured poses and evidence
images. Fractional finish times are retained in the existing stroke JSON and
shifted correctly when analysis operates on a segment of a longer track.
Invalid or out-of-bracket refinements fall back to the original discrete clock.
No event is invented and this does not change stroke candidate selection.

On 12 analytic sinusoidal-motion cases (10/15/30 fps; 18.7/22.3/31.1/43.7 spm),
mean rate RMSE from frame quantization decreases from 0.4253 spm to 0.00171 spm.
This measures only numerical timing precision with ideal observations. It is
not a real-video catch/contact accuracy claim: joint localization and phase
selection errors remain much larger in actual footage.

Three new regressions cover rate quantization, a consistent event clock, and
fractional finish offsets after gaps. The frozen starting implementation is
`baseline_strokes.py`; the reproducible benchmark is `compare.py`.

From `app/strokesense`:

```sh
.venv/bin/python evaluation/stroke_timing/compare.py
.venv/bin/python -m unittest discover -s tests -p test_fractional_timing.py -v
```
