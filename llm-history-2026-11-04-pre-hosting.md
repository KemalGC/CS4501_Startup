# StrokeSense current handoff

Prior root content is preserved byte-for-byte in llm-history-2026-11-03-report-library.md (blob81325d699e57564cb1da42b6f658d263bbb5e49d). Earlier histories remain linked. Manual work does not resume the expired October sprint or change schedules.

## 2026-11-03-2124-manual — ten-video alpha and five quality questions (#113)

User asked for ten good test videos, retaining current useful clips, and about five extra quality questions. Started2026-11-03T21:24:04.059084-05:00 (monotonic283.199435222). The21:51:45.868 checkpoint measured1661.809seconds (27m41.809s), excluding later packaging/CI/publication. Final duration belongs in issue closeout. This is not a timed sprint and no30-minute claim is made.

Inspected dev-consolidated e18945d21b4f278d07db637e68c9af188369b12f and main3d383110dcfcbfcb1cf7a46681c6523f6e20a4fc. Topic dev/2026-11-03-2124-review-quality holds production checkpoint35d91f3a270824f57026358143b34442c25fc7a8. Issue113 contains the story and criteria before code. No PR, main/default/settings/schedule changes or private-media publication. Integration and email remain PENDING here; only issue closeout may claim confirmed publication/communication.

### Feature and traceability

Add exactly five report-level questions: clarity, specificity, completeness, evidence support, actionability. Each is answered ONCE per clip/report revision, not five times for each of six aspects. Preserve all existing aspect usefulness/perceived-accuracy questions. Response scale1–5 with explicit Cannot judge and Not applicable; no preselected rating. These are subjective quality judgments, not true accuracy labels.

New feedback_quality.py implements quality-v1 schema, strict exact-field/rating validation and an additive consent-owned quality_responses table in the existing SQLite database. Five answers are transactionally upserted per reviewer/clip/analysis-version/questionnaire-version/question. Existing rows remain untouched. Skip reasons retain null numeric scores. Withdrawal cascades through both response tables. Separate owner-only CSV/JSON exports are formula-safe. New quality.js/css and index/app integration render, save and resume five blank-required responses, with race guards and unsaved-answer warnings. Existing owner counts are explicitly aspect-only; new quality exports are separate. Server retains origin,CSRF,session,asset-sandbox and private-owner gates.

### Actual tests and known failures

Before implementation, test_feedback_quality.py ran20 executions (10new methods plus10imported baseline cases) with21 failing assertions/subtests for missing metadata/routes. Expected missing-behavior failures, not import errors. Local test-only commit/log preserved before production; remote production commit contains tests and code together and is NOT described as a separate remote red checkpoint. After implementation all20 passed in1.286s.

Complete local `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MPLBACKEND=Agg python strokesense/quality.py`:654 executions passed in82.215s plus4legacy synthetic functions. Counts include repeated fixtures, not654 unique tests. node syntax checks passed. Local native-browser navigation was ERR_BLOCKED_BY_ADMINISTRATOR; not bypassed. Exact-source offline CI41762924839 passed. Downloaded its source artifact and byte-compared feedback.py,feedback_quality.py,app.js,index.html,quality.js,quality.css,test_feedback_quality.py and browser workflow to locally tested bytes; all matched.

Initial browser CI41762924896 passed old feedback save/resume/export but failed its library test because Playwright string wait_for_function hit the page's strict Content Security Policy. Replace those string waits with locator text assertions in the three feedback harnesses. Production CSP is not relaxed, checks are not removed, and expected text remains identical. Final corrected Chrome/CI outcome is pending at this documentation checkpoint; do not infer success.

Private-package eight-to-ten updater initially rejected the changed catalog as a different study. An observed regression reproduced that failure. Corrected upgrader accepts only the known previous/current study-ID sets, validates all assets/paths before writing, refuses symlink/junction/path traversal and differing existing media, backs up old app/catalog, copies new assets, and publishes the catalog last. No .feedback data or removed old files are deleted. Five updater tests passed in0.018s, including exact sentinel database/key preservation. Windows GUI execution remains untested.

### Footage screening and real inference

Nine supplied archives comprised five distinct archives plus four exact SHA256 duplicate archives. Screened23 distinct source video files using multiple source-time images, not model scores. Fixed ten-clip selection before inference: retain five useful existing recordings, add five recordings spanning five source sessions; omit a paired encoding and old low-evidence cases from the ACTIVE core, without deleting old files/ratings. Seven intended eights and three intended fours. Four clips per planned reviewer gives20clip reviews and two judgments per clip across5people; not20 independent participants. Detailed private filenames/windows and assignment are in the delivered study guide, not this public handoff.

Actual new runs used checksum-verified YOLO11n-pose ONNX93e2866b0ce678f99b4dd88af0c12e9ea2edf079a361dc2ecbc6226b77ff6408, ONNXRuntime1.23.2,10samplefps,dominant-crew mode and2threads per worker. Two workers ran concurrently. Five23–27second excerpts completed in690.329seconds aggregate WALL time. Individual durations were220.367,173.324,181.257,417.761,335.744seconds; their sum is not wall time. Original full clips are preserved as browser previews; annotations cover the declared analysis window, not the full source in every case. These runs use learned pose plus deterministic measurements, NOT new Qwen output or a trained technique classifier.

All five added clips generated provisional reports and annotated media. Expected/model track counts by test ID: T06 eight/eight, T07 four/four, T08 four/SEVEN, T09 eight/eight,T10four/four. T08 has an explicit foreground-four versus seven-track warning in its report/catalog: possible cross-crew contamination. Do not hide it or call matching counts elsewhere correct identity. The challenging clip remains useful to evaluate completeness and evidence support. Independent catches, biomechanical angles, fault accuracy and coach judgments are not established. No missing values were fabricated.

### Delivery and remaining work

Private full study pack contains10source previews/posters,10reports/annotations, five quality questions, new selected-video manifest and run records. No models, participant data or owner key should be shipped. Source Git update intentionally does not contain private study media. Final archive CRC/media/HTTP checks, optional guide/slides and publication are pending at this checkpoint and must be confirmed in issue113. Existing review responses remain associated with original analysis revisions; removed clips remain in owner exports/history after upgrade.

Human test review and the five actual rower sessions remain pending. No public hosting, model-training improvement, five-participant result, independent accuracy metric, Windows certification or grade/rubric-completion claim. No suspicious AI-checker or hidden instruction was encountered in inspected source; hidden CSRF form elements are legitimate, not a checker.

Next action: run the planned five supervised reviewer sessions with the fixed ten-clip set, inspect T08 identity contamination and other timestamped concerns, and summarize quality with valid response denominators separately from perceived accuracy. Do not count successful software tests as actual participant feedback.
