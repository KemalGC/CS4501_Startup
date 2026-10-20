# Teacher homework checker: task description and implementation plan

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

Planned state progression:
`uploaded → extraction_draft → transcription_confirmed → grading_draft → approved`.
Failures or unsupported content enter `needs_review` with a reason; they do not
become zero scores. Changing a transcript or rubric invalidates dependent draft
grades and requires rechecking. Changing an approved result requires an explicit
revision and updates the associated analytics.

## Existing foundation versus required work

| Area | Current implementation | Required addition |
| --- | --- | --- |
| Input | Typed steps for fixed practice problems | Teacher-created assignments, rubric/key entry, image/PDF uploads |
| Mathematics | Bounded linear/quadratic checker and first-error detection | Apply the checker to confirmed extracted work and teacher keys |
| AI | Optional text-provider adapter and offline demo | Vision transcription, structured grading proposals, practice proposals |
| Scoring | Correct/incomplete/incorrect/unsupported status | Rubric-level evidence, partial-credit decisions, deterministic totals |
| Review | Student hint and revision interface | Teacher review queue, edits, approval history, finalized feedback |
| Analytics | Optional local practice-outcome aggregates | Reviewed question/skill summaries and per-student progress |
| Practice | Fixed developer-authored problem bank | Skill-targeted follow-up sets with validated keys |
| Persistence | Optional anonymous attempt metrics | Private assignment, file, rubric, review, and export records |
| Deployment | Docker and CI; no hosted app | Teacher access controls, private storage, lifecycle/deletion controls |

Existing practice metrics cannot serve as the classroom grade database. Keep that
workflow functional while the new assignment workflow is introduced.

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

- Produce structured question IDs, ordered equation steps, and source locations.
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
- Release only approved feedback derived from validated claims and templates.
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
- Export approved grades to CSV with assignment, student code, and point totals.

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

## Implementation order and PR boundaries

Start each feature from current `dev` and target `dev`. Preserve the existing
practice flow until the new teacher flow has its own tests and a runnable demo.

1. **Assignments and rubrics:** domain records, validated teacher keys, rubric
   criteria, anonymous student codes, and a typed submission path for testing.
2. **Teacher access and handwriting intake:** protected image/PDF upload,
   extraction provider, source/transcript review, and bounded processing.
3. **Validated grading and review:** criterion-level proposals, deterministic
   scores, approval/override records, retry/fallback behavior, and feedback.
4. **Class analytics and export:** approved-result aggregation, review coverage,
   question/skill summaries, student trends, and CSV export.
5. **Differentiated practice:** checked problem generation, teacher approval,
   and a small follow-up set for each selected gap.
6. **Pilot and deployment:** complete workflow tests, private hosting,
   independently labeled evaluation, and teacher time/quality measurement.

This document defines the work; those features are not implemented by the
description change. The existing offline demo is not an OCR or grading demo.

## Definition of done for the teacher MVP

A teacher can process a small supported worksheet batch end to end: create its
rubric, upload handwritten work, correct extraction, review and approve scores,
export results, inspect confirmed class gaps, and approve a validated follow-up
set. Unsupported or unreadable items stay visible for review. Automated tests
cover data isolation, state changes, scoring bounds, aggregation, retry limits,
and withheld results; browser tests cover the complete teacher workflow.

Use the [pilot plan](pilot-plan.md) for proposed success criteria. Do not claim
time savings, grading accuracy, or improved learning from synthetic tests alone.
