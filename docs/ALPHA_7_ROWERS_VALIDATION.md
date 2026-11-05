# StrokeSense Project Alpha — seven-rower validation and engineering evidence

**Due:** Nov 5, 2026, 11 a.m. Eastern. **Repository:** https://github.com/KemalGC/CS4501_Startup. **Review Site:** https://strokesense-review.kemalgcortuk.chatgpt.site. Working source is on \`dev-consolidated\`; do not assume \`main\` has the latest Alpha.

## Activity 1 — MVP hypothesis check
The original MVP slide states: **"Coaches can review footage faster without losing useful coaching detail."** For the broader Alpha audience, we state the hypothesis as **"Rowers and coaches can review footage faster without losing useful coaching detail."** This is a proposed workflow hypothesis, not proof from pose-estimation output. The original coach-specific success thresholds remain unchanged until the pilot is independently redefined.

The **team-reported revised pilot is seven rowers; two have coached before**. Previously proposed: four coaches, twelve rowers, thirty clips. The actual software study uses seven trimmed **eights-only** clips, 124 seconds total, not seven unique human subjects. Two rowers with prior coaching do not constitute an independent four-coach reference majority.

**Do not place names, contact details, video permissions or raw judgments in public GitHub.** Use a consent-controlled ID-to-person mapping privately; the blank \`docs/alpha_validation_7_template.csv\` contains \`R01\` to \`R07\` as *placeholder identifiers*, not verified individuals or outcomes. The rower-to-coaching-history mapping was not supplied and remains blank.

### Small-pilot collection procedure
1. Record consent and independently verified participant ID/role/coaching history, the recording/boat and review-order assignment. Avoid model-output leakage into the baseline.
2. Have each person review original footage manually, record specific fault/timing judgments and **stopwatch** baseline seconds.
3. Have each use the completed StrokeSense report for an equivalent task, record stopwatch assisted seconds, whether coaching detail was preserved, whether an actionable next step was provided, plus corrections.
4. Where actual independent coach labels exist, calculate per-opportunity fault agreement with denominators. \`cannot_judge\`, estimates, unconsented and withdrawn records cannot silently become measurements.
5. Interview the participants: useful cue, incorrect/missing cue, would-use-again, and first requested change. Quote only consent-cleared nonidentifying feedback.

**Metrics:** percent reduction in median review time \`100 * (median(manual) - median(assisted)) / median(manual)\`; preserved-detail percent among answered respondents; actionable report percent by reviewer role; collegiate rower–coach agreement from eligible, independently recorded paired fault judgments. Original MVP coach-only benchmarks are historical. The revised Alpha target measures are **>=30% review-time reduction, >=70% usefulness among responding rowers and coaches, and >=75% agreement between eligible independently paired collegiate rower and coach technique judgments**. None is claimed achieved.

**Current outcome:** the user supplied a revised sample size/composition but not per-person consent, stopwatch pairs, blind fault labels, detailed responses or coach-majority labels. **NOT YET VALIDATED**; this means evidence is incomplete, not that the hypothesis has been falsified. No measured percentage may be inferred from software tests, sample-size alone, synthetic responses or model SPM estimates.

### Test-first tool
From \`strokesense/\`: \`python -m unittest discover -s tests -p test_alpha_validation.py -v\` (14 test-first synthetic cases) and \`python -m strokesense.alpha_validation --csv ../docs/alpha_validation_7_template.csv\`. Empty answers remain null. Recorded RED: module not present; GREEN: 14/14 passing after implementation and assertion refinement. **Those are software tests, not seven human survey responses.**

## Activity 2 — core user stories / GitHub Issues

The following **nine core Alpha stories** are an intentionally selected product scope, not a census of historical GitHub issues. Each story links unique trackable tickets with acceptance criteria; read the linked issue's full acceptance checklist.

| ID | User story (As a…, I want…, so that…) | Acceptance evidence | Issue links | Status |
|---|---|---|---|---|
| S1 | As a rower or coach, I want permission-checked video upload and one-click analysis, so I can review without manual setup. | Consent/Origin/size checks, duplicate-safe upload, status/report | #29 #88 #94 | Local Alpha done |
| S2 | As a rower or coach, I want detected rowers and a confirmed eight on one boat, so other crews cannot enter results. | Detect candidates; select exactly eight; withhold ambiguous | #98 #100 | Local Alpha done |
| S3 | As a rower, I want one shared boat cadence and per-seat timing, so rower cards do not disagree about SPM. | Common cycle estimate or withheld; raw observations preserved | #108 #118 | Cadence done, wider validation open |
| S4 | As a rower or coach, I want video-linked reports and frames, so I can verify every technique claim. | Report/overlay/clip matching, failure warnings, snapshot links | #95 #111 | Curated clip reports done |
| S5 | As a rower or coach, I want independently checked LLM coaching cues, so numeric hallucinations do not appear as confirmed advice. | Offline reject/correct/withhold; live reviewed in-product provider demonstration outstanding | #14 #15 #17 #50 #56 #120 | Partial |
| S6 | As a tester, I want a usable saved review form with owner-only exports, so I can give private product feedback. | Clip-specific persistence, role, technical questions, withdraw and exports | #110 #115 #117 | Site live separately; Python guest variant open |
| S7 | As a researcher, I want seven-rower baseline vs assisted data, so we can decide if the hypothesis holds. | Pair timing, preserve detail, independent fault labels, real n | #119 | Open |
| S8 | As a tester, I want a separate private optional-demo upload, so I can inspect my own video without contaminating the seven research clips. | Private upload and playback, quota, delete, no fake analysis | #121 | Open |
| S9 | As a developer, I want exact test/coverage/provenance metrics, so we can substantiate QA slides. | Test runs, line coverage, AI/manual provenance, issue-to-test map | #122 | In progress |

**Core user story count: 9. Linked unique issues: 21.** Additional historical issues remain in the repository.

## Activity 3 — test-driven development and engineering metrics

Before the Nov 4 Alpha work, GitHub had **105 non-PR issues: 77 closed, 28 open**. Four new tracked requirement gaps #119–#122 raised that to **109 total; 77 closed, 32 open**, as of this Alpha checkpoint. Later changes may alter the count.

The verified merged development source \`7d14b9fe15f7af00616e33d336e2fcd606a69732\` had **718 offline unittest executions + 4 synthetic functions**, **24 hosted HTTP tests**, passing native-browser test scripts, and green GitHub runs. These counts are *executions*, not a deduplicated issue-linked test inventory. Separate 14-case validation tests were written RED then GREEN locally, and have been added on \`dev/2026-11-04-alpha-validation-slides\`. GitHub checks should be reread before claiming their CI completion.

**Coverage:** baseline workflows did not measure line coverage. New \`.github/workflows/strokesense-alpha-coverage.yml\` explicitly measures the **Python package under offline unittest**; report its actual scoped percentage only after the run succeeds. It cannot be claimed as full front-end/LLM/video coverage.

**Average tests/issue:** \`718 / 109 = 6.59\` is only a **repository-wide offline execution-per-issue arithmetic proxy**, not a verified one-to-one issue-test mapping. Do not present it as attributed coverage.

**AI vs manual ratio:** historical per-test authorship/review is **unrecorded/unknown**. The 14 newly added validation tests are AI-assisted drafts; none is claimed human-reviewed. Do not manufacture an attribution ratio for the full suite.

### TDD and demo
- RED: \`test_alpha_validation.py\` initially failed to import an intentionally absent module.
- GREEN: \`alpha_validation.py\` implemented guarded aggregation; 14/14 local synthetic tests passed.
- Existing #56 has an explicitly **synthetic offline LLM-candidate validation/correction** demo. Optional provider adapter #17/#50 requires approved evidence and authorization. **The public review Site is not a verified live LLM coaching endpoint**. For a genuine end-to-end LLM demonstration, complete #120, don't relabel a fixture as a live provider result.
- Saved reports and the separate public video-feedback site demonstrate the implemented review workflow; no claim of professional coaching accuracy before independent labels.

## Presentation timing and deliverables

The assignment asks for an 8-minute section including a 2-minute Q&A, although its suggested sections sum to more than eight minutes. Prepare a practical **6-minute talk + 2-minute Q&A**: 1:35 hook/pilot, 2:30 end-to-end saved-result demo + honest LLM boundary, 1:10 engineering metrics, 0:45 next stage.

Deliverables by Nov 5 11 a.m.: **Slides PDF, Part 1 Activities PDF, repo link**. A random teammate is selected to speak; all should rehearse and be ready.

**Outstanding before claiming a validated MVP:** real signed/consented test responses, paired stopwatch readings and fault labels; independent collegiate rower/coach paired judgments, reproducible coverage percentage, and a verified live LLM path where required. The conservative pivot option is to focus on verified rhythm and evidence-first coach review, pending actual user feedback—not a proven new market claim.
