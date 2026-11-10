# Source-frame event review

Run `.venv/bin/python evaluation/events/review.py` from `app/strokesense`.
It replays the stored candidate tracks through current body/stroke analysis and
renders original video pixels around the first two accepted cycles for the
leftmost tracked rower in IMG_9673. The crops follow the hip but contain no
predicted skeleton overlay. Private JPEG and a source-frame/crop ledger are in
`results/event-evaluation/`. Frame labels use the source's nominal clock; the
separate source-clock audit found less than 1.6 ms discrepancy.

Initial assistant review (development evidence, not independent labels):

- Cycle analysis frames 59–100: mixed-cue finish and hand minimum both frame 75.
  The rower has bent arms and layback in the surrounding images; hand-reversal
  timing is not sharply identifiable in these small, blurred crops.
- Cycle 100–139: mixed-cue finish is frame 125 (8.433 s), while hand minimum is
  frame 112 (7.556 s), a 0.877 s disagreement. At frame 125 the arms are extended
  and the rower is visibly in recovery. Around frame 112 the rower is finishing
  the arm draw. This establishes a bad mixed-cue finish, but does not establish
  frame 112 as exact ground truth: the hand/handle remains close to the torso
  over several subsequent frames.
- Nine accepted cycles have mixed-minus-hand finish differences in sampled
  frames: 0, 13, -1, 2, -1, 1, -7, 8, -7. Those later disagreements require source
  review before selecting or tuning a replacement policy.

Hypothesis to test: a knee cue is useful for catch localization but knee extension
can plateau through finish and early recovery. Using the minimum of the same
weighted knee/hand signal for finish allows knee noise to move the finish far
from the observed hand reversal. Prefer locally supported hand evidence for
finish only after testing real and synthetic failure cases. No production phase
selection changes have been made as part of this audit.

## Supported hand finish adopted

`candidate_strokes.py` freezes the evaluated candidate; production now uses the
same phase selection. Catch candidates and their refinement are unchanged. A
cycle uses hand reach for finish only if `measurement.segment_supported` passes
(the existing observed-fraction, amplitude, and noise gates) and the candidate
minimum and its neighbors are observed. Otherwise it retains the mixed cue.
Existing visibility and drive-fraction acceptance bounds still apply. Fractional
finish refinement uses the signal that actually selected that finish.

The additional source sheets for cycles 6, 7, and 8 show large mixed/hand
minimum disagreements. Mixed finishes in cycles 6 and 8 occur during the arm
draw; the hand minima occur later with arms drawn in. Cycle 7's hand minimum is
near the transition into the drawn-in pose, while the mixed minimum falls later
within that pose. These views support separating finish cues, but do not provide
sharp ground-truth times: several poses remain similar across multiple frames.
No exact millisecond accuracy claim follows from this assistant review.

The reviewed cycle 100–139 now selects frame 112 instead of frame 125. Candidate
cycles on the five cached segments are 30, 18, 65, 53, 35, compared with baseline
31, 16, 63, 55, 33. Changed acceptance counts are diagnostics, not accuracy.
`comparison.json` records every integer event for both paths.

Three analytic regression tests demonstrate that a knee plateau with a spurious
minimum no longer displaces a supported hand finish, missing hand evidence cannot
override the mixed cue, and clean aligned cues retain their timings. The full
suite ran 796 tests with only the same ten pre-existing application failures;
all four standalone legacy rowing/fault checks pass. Logs are private under
`results/event-evaluation/finish-full-tests.log`.

`review.py` explicitly loads the frozen baseline so the original contact-sheet
comparison remains reproducible after adopting the candidate. The initial notes
above describe the state before adoption; this section records the final decision.

## Additional source-video review

`review_additional.py` renders four large baseline/candidate finish disagreements
on IMG_9674, with exact source-frame/crop ledgers and local angle/confidence traces.
Cases were deliberately selected for large changes, not as a random validation
sample. The assistant reviewed the source-only contact sheets:

- Case 0, first boat slot 7: baseline 10.255 s is visibly in recovery; candidate
  9.378 s is near the final arm draw. This supports the phase-specific correction
  on a second video, without establishing an exact ground-truth finish.
- Case 1, first boat slot 2: candidate 4.655 s occurs earlier in the drawn-in
  posture than baseline 5.195 s. A long similar-pose interval prevents a precise
  timing judgment from the contact sheet alone.
- Case 2, first boat slot 0: candidate 14.100 s appears near the end of arm draw,
  slightly early; baseline 14.572 s is later in the drawn-in posture. Do not claim
  the candidate is exact. The angle trace shows trunk estimates varying from
  -34.1° to -20.9° in two sampled steps while the arm remains drawn in; several
  estimates have high detector confidence. Shoulder-relative hand and elbow
  minima occur around frame 210, one sample after the hip-relative minimum at
  209. Hip/torso localization is a plausible contributor, not an established
  causal diagnosis from these images.
- Case 3, second boat slot 3: both candidates occur within a drawn-in interval
  with neighboring bodies and oars partly overlapping. The view does not clearly
  resolve which event time is better; this is weaker evidence for the user's
  unobscured-rowing scope.

The four cases broaden development review but remain non-independent and
selection-biased. They support fixing gross late finishes, while showing that
exact phase precision remains limited by projected pose estimates, body overlap,
and sustained similar poses. No new timing heuristic was adopted from this audit.
