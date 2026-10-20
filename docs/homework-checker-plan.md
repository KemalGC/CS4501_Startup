# Teacher homework checker: task description and implementation status

## Objective

Build a teacher-facing homework checker that converts handwritten algebra
assignments into reviewable grades, clear feedback, class learning-gap analytics,
and differentiated follow-up practice. The first goal is to reduce total teacher
grading and follow-up preparation time while preserving review and correction.

The product direction is inspired by
[Frizzle's YC profile](https://www.ycombinator.com/companies/frizzle).
Frizzle's promotional time-saving figures are not evidence for ProofGrade.

## Primary user and workflow

The primary user is a math teacher or algebra tutor reviewing one class or group.
The initial scope is short worksheets containing 3–5 linear or quadratic
equations in one real variable, with a teacher-confirmed answer key and rubric.

1. Create an assignment with questions, skill tags, point values, and a rubric.
2. Upload a batch of JPG/PNG images or scanned PDFs using anonymous student codes.
3. Review the extracted work beside the original source and correct transcription.
4. Review proposed per-question points, cited evidence, and checked feedback.
5. Approve or override results, retaining a record of the decision.
6. Export approved grades and inspect class and student summaries.
7. Select a confirmed skill gap and approve a checked follow-up practice set.

Implemented submission states are `transcription_draft → grading_draft → approved`.
Teacher confirmation creates the grading draft. A per-question `needs_review` flag
marks unreadable/unsupported work; it is not a separate submission state. Such
work has unset suggested scores. Re-extracting or reconfirming a transcript
invalidates prior approval, removes the result from analytics/exports, and requires
review again. Rubrics are immutable; create a replacement assignment for changes.
Writes require a current revision so stale reviews cannot overwrite newer work.

## Implementation snapshot — 2026-10-20

| Area | Implemented in the MVP | Remaining validation or scope |
| --- | --- | --- |
| Input | Teacher assignments, checked keys/rubrics, JPG/PNG/PDF uploads, anonymous codes | Real worksheet layout/handwriting evaluation |
| Mathematics | First invalid transition, full solution sets, bounded algebra | Instructor-reviewed independent cases |
| AI | Optional vision transcription, text hints, checked practice; bounded retries | Credentialed live-model smoke test and measured accuracy |
| Scoring | Criterion evidence, deterministic totals, partial-credit overrides | Educator rubric calibration and agreement measurement |
| Review | Source/transcript view, explicit confirmation, grade approval, history | Pilot usability and total teacher-time measurement |
| Analytics | Approved question/skill summaries, coverage, student progress, CSV | Teacher evaluation of instructional usefulness |
| Practice | Checked template or model proposals and approval before download | Teacher assessment of difficulty and skill fit |
| Persistence | Private SQLite records/source pages; cascading deletion | Managed backups and a pilot retention process |
| Delivery | Accounts, teacher UI, Docker, Python/browser/container CI | Hosted pilot and production operations |
| Data | Dataset guide and reproducible MathWriting preparation/scoring | Curated DrawEduMath subset and reference grading labels |

The preserved student practice flow is at `/practice`. Its optional metrics remain
separate from the teacher database. All model calls are disabled by default;
manual transcripts and checked templates make the full review workflow runnable.

## MVP requirements and acceptance criteria

### Assignment setup and uploads

- Teachers create questions, a server-side answer key, skill labels, and a bounded
  point rubric. Flag unsupported or inconsistent keys before grading.
- Accept JPG/PNG and scanned PDF submissions for the known worksheet layout.
  Configure file-size, page-count, and processing limits; reject unsupported files.
- Associate each submission with an assignment and anonymous student code.
- Allow teachers to inspect source pages, retry a failed extraction, and delete
  a submission and its retained files.

### Handwriting extraction

- Produce structured question IDs, ordered equation steps, and source page numbers.
  Region bounding boxes are outside the current implementation.
- Show the source and transcript together. Teachers confirm transcription before
  a proposed grade can be finalized.
- Flag unreadable work and missing question mappings; never silently invent a
  missing step or treat extraction failure as an incorrect student answer.
- Treat all uploaded content as student data, not instructions to the application
  or model. Text embedded in a worksheet cannot change the grading rubric.

### Grading and feedback

- Support the existing declared real-number algebra grammar and parser limits.
- Record the first invalid transition and whether the final solution is complete.
- Score only against the teacher's approved rubric. A valid alternative solution
  method must not lose credit merely for differing from a model solution.
- Link proposed credit to specific criteria and evidence. Compute totals in code.
  Criteria that cannot be checked deterministically require a teacher decision.
- Keep draft scores and final approved scores distinct. Allow teacher overrides.
- Release only approved feedback. Automated hints use validated claims and
  templates; teachers may write their own reviewed feedback with a decision reason.
- Retry invalid model candidates at most three total times, then require review.
- Keep answer keys and hidden grading evidence out of student-facing exports.

### Class analytics

- Show per-question accuracy, reviewed skill gaps, and students needing follow-up.
- Use only approved results for grading statistics and show the total submission
  count, reviewed count, and unresolved count so coverage is visible.
- Derive summaries from stored records and reviewed tags, not invented model
  statistics. Update summaries after an approved grade is revised.
- Provide per-student trends once multiple assignments exist; do not describe one
  worksheet as proof of mastery.
- Export each assignment’s approved grades to CSV with student code, earned and
  possible points, and percentage; the selected assignment supplies the context.

### Differentiated assessment

- Teachers select a skill gap confirmed during review.
- Propose a small practice set at an appropriate algebra difficulty and attach
  the targeted skill and complete server-side answer key.
- Check every proposed equation, answer, and explanatory mathematical claim.
  Withhold unsupported or failed candidates.
- Require teacher approval before sharing a practice set with students.
- Measure subsequent independent problem-solving separately from whether a
  student copied or completed a correction on the original submission.

### Teacher access and retained work

- Restrict assignments, uploaded images, answer keys, and reviews to the teacher
  authorized to access them; do not expose uploads through public static URLs.
- Keep model credentials on the server and disclose when assignment content is
  sent to a model provider.
- Define retention and deletion behavior for uploaded files and derived records.
- Pilot with synthetic or permitted, de-identified work. The current practice
  consent checkbox does not authorize storing handwritten assignments.

## Delivered PR boundaries and next work

Feature PRs target `dev`. The implementation is split into the teacher backend
(PR #6), uploads/model integration/teacher UI/browser CI (PR #7), and dataset
support plus operating documentation. Both backend and interface are merged into
`dev`; `main` remains the release target.

The teacher workflow and original student flow pass browser checks, including
mobile layout; Python tests cover isolation, revisions, scoring, analytics, upload
processing, provider failures, and checked practice. CI also builds/runs Docker.

Next work is validation and deployment: configure a model for a credentialed smoke
test, curate permitted handwritten examples with independent grading references,
measure full teacher effort, and deploy a private pilot. No hosting, measured time
savings, or classroom grading accuracy is implied by passing developer tests.

## Definition of done for the teacher MVP

A teacher can process a small supported worksheet batch end to end: create its
rubric, upload handwritten work, correct extraction, review and approve scores,
export results, inspect confirmed class gaps, and approve a validated follow-up
set. Unsupported or unreadable items stay visible for review. Automated tests
cover data isolation, state changes, scoring bounds, aggregation, retry limits,
and withheld results; browser tests cover the complete teacher workflow.

Use the [pilot plan](pilot-plan.md) for proposed success criteria. Do not claim
time savings, grading accuracy, or improved learning from synthetic tests alone.
