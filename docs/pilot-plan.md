# ProofGrade teacher homework-grading pilot

## Hypothesis and participants

Teachers can grade supported handwritten algebra assignments and prepare targeted
follow-up faster with ProofGrade, while retaining comparable grading quality and
control over final results. Recruit 3–5 math teachers or algebra tutors. Begin
with synthetic or permitted, de-identified short worksheets and anonymous student
codes. This pilot has not been conducted, and the teacher workflow is not yet
implemented.

The initial scope is linear and quadratic equations in one real variable on a
known worksheet layout. The first feasibility study does not establish benefits
for other subjects, arbitrary handwriting, or school-wide deployment.

## Review the materials first

Prepare 30–50 instructor-reviewed question responses with source images,
transcripts, answer keys, rubric criteria, reference scores, and error labels.
Include correct alternative methods, partial work, missing roots, unreadable
writing, and unsupported notation. Resolve reviewer disagreements before using
a reference score. Keep an unseen evaluation set separate from prompt development.

The current repository's 30 practice problems and 42 regression cases remain
developer-authored fixtures with review status pending. They test the typed
checker; they do not evaluate handwriting recognition or teacher grading. Review
and extend them, and add independent handwritten examples before the pilot.

## Session procedure

1. Agree on the assignment scope, rubric, permitted samples, anonymous identifiers,
   and deletion date. Explain where model processing occurs.
2. Have each teacher grade matched worksheet batches manually and with ProofGrade.
   Counterbalance the order across teachers and use different but comparable work
   to reduce recall effects.
3. Measure the complete workflow: assignment setup, uploads, transcript correction,
   grade review, overrides, export, and follow-up preparation. Record inference
   time separately; model latency is not the teacher's total grading time.
4. Use independent reference judgments to evaluate both draft suggestions and
   final teacher-approved grades. Record the frequency and reason for overrides.
5. Ask teachers to inspect the class summary and identify one reteaching priority.
   Check the displayed aggregates against approved source records.
6. Ask each teacher to review a generated practice set for that priority, checking
   mathematical correctness, skill fit, and difficulty.
7. Collect a 1–5 usefulness rating, willingness to reuse, and examples of extra work
   or confusion. Report individual outcomes and counts given the small sample.

## Proposed success criteria

These are feasibility targets to test, not measured results or universal quality
thresholds. Report raw counts, unresolved items, and uncertainty.

| Goal | Measurement | Proposed target |
| --- | --- | --- |
| Reduce grading effort | Total teacher minutes per matched batch, including setup, extraction fixes, and grade review | At least 30% lower median time than manual grading |
| Accurate draft scores | Exact rubric-score agreement with independent references among supported, legible responses | At least 90%; report score differences and teacher override rate |
| Correct extraction | Extracted equation steps matching the reviewed transcript / all labeled steps | Report accuracy and correction time; keep unreadable items separate |
| Find invalid steps | Correct first-error location / independently labeled incorrect solutions | At least 90%; separately report false flags on valid work |
| Preserve teacher control | Released grade/feedback records with an approval / all released records | 100%; no unresolved item silently becomes a zero |
| Reliable class summaries | Displayed aggregates reconciled to approved records | Exact match, with reviewed and unresolved counts visible |
| Useful follow-up | Proposed practice sets teachers accept as skill-appropriate, with only minor edits / sets reviewed | At least 80%; no mathematically invalid item released |
| Teacher usefulness | Teachers rating usefulness 4 or 5 / teachers answering | At least 80%; report the count and specific reasons |

Report draft coverage and abstention as well as agreement. A system can appear
accurate by declining difficult responses. Separate model failures, handwriting
ambiguity, unsupported mathematics, and teacher rubric disagreements.

## Data collection and current implementation limits

The teacher pilot will need assignment records, protected source files, confirmed
transcripts, rubric versions, draft/final grades, approval history, timings, and
override reasons. Define access and deletion behavior before collecting that data.
Do not store identifying classroom work merely because the existing practice
collection setting is enabled.

The current SQLite attempt store records anonymous practice outcomes only. Its
`proofgrade.metrics` reports do not measure teacher grading time, score agreement,
OCR correction, or classroom performance. Add dedicated pilot measurements when
the assignment workflow is implemented. Keep offline demos and live-model runs
separate, and report model usage costs alongside measured teacher time.

## Learning outcomes and demonstration

After grading feasibility is established, optionally compare performance on an
independent, similar problem before and after teacher-approved targeted practice.
Track whether it is solved without further hints. Treat a small uncontrolled
study as exploratory evidence, not proof of learning gains.

The teacher MVP demonstration should show a short worksheet batch, source versus
transcript review, a checked distribution error, a teacher score override, approved
grade export, a class skill-gap summary, and a validated follow-up set. Include an
unreadable response and an invalid model candidate to show review and retry paths.

Until those features exist, the current demo remains the typed-algebra example
`2(x+3)=10` followed by `2x+3=10`, with a checked hint and student revision.
`python -m proofgrade.demo` demonstrates offline fault injection only; it does not
demonstrate handwriting extraction, grading, or real model performance.
