# ProofGrade pilot

## Hypothesis and participants

With the first invalid algebra step identified and one checked hint, students can
correct that step independently. Recruit 10–15 consenting university students for
practice exercises and ask a tutor or instructor to review the materials. Do not
use confidential graded submissions. This pilot has not been conducted.

## Review the materials first

The repository contains 30 developer-authored practice problems and 42 regression
cases. Every record is marked `review_status: pending`. They are not instructor
reviewed, and passing these cases is not evidence of general accuracy or learning.
Have a reviewer check each answer, error label, and template, then record their
approval before changing the status to `reviewed`. Ten problem IDs are reserved
for the evaluation split, but the current labels were still written during
development. Add independently labeled unseen examples for a credible accuracy
estimate. Do not tune the prompt on those held-out examples.

## Session procedure

1. Explain the practice-only scope and optional outcome collection. Let the
   participant choose whether to opt in. Test demo usability separately from live
   model quality; record which provider mode was used.
2. Give each participant 3–5 suitable problems, including a quadratic with two
   roots. Ask them to enter their own steps and think aloud about the interface.
3. After a verified hint, ask them to revise without revealing the solution. Record
   task completion and confusion; do not intervene until the first revision is done.
4. Collect one end-of-session usefulness rating (1–5) per participant and a brief
   explanation. Keep participant survey results separate from per-attempt ratings.
5. Ask the tutor to assess hint correctness, relevance, and clarity. Review cases
   where the system withholds a hint or gives a generic hint.

## Proposed success criteria

| Goal | Measurement | Proposed target |
| --- | --- | --- |
| Locate first error | Correct first-error location / instructor-labeled incorrect cases | At least 90% |
| Preserve correct work | Correct and incomplete submissions falsely flagged / reviewed valid submissions | Report separately; aim for zero in the small reviewed set |
| Support revision | Initial hinted attempts whose first revision fixes the flagged step / all initial attempts with a verified hint | At least 70%; missing revisions count as not corrected |
| Participant usefulness | Participants rating usefulness 4 or 5 / participants answering the end survey | At least 80%; also report response count |
| Feedback validation | Accepted candidates / (accepted + rejected candidates) | Report alongside withheld-hint and retry rates; never bypass validation |

Use a brief matched comparison with wrong-answer-only feedback if practical;
otherwise describe the pilot as a usability/feasibility study, not proof that the
product caused better learning. Report denominators and the small sample size.

## Data collection and limits

Collection is off by default. When enabled on the server, each participant must
also tick the consent box. SQLite stores random attempt tokens, problem IDs,
outcomes, timings, retry counts, revision links, and optional ratings. It does not
store submitted equations, names, emails, or model text. The application has no
public metrics endpoint. In live AI mode, the relevant equation steps are sent to
OpenAI; the interface discloses that separately from local data collection.

Use `python -m proofgrade.metrics --db data/proofgrade.sqlite3 --mode openai` for
live-mode aggregates, or `--mode demo` for demo records. The first revision of an
initial hinted attempt is the only revision counted for the one-hint metric;
removing the flagged line is not counted as fixing it. Duplicate revisions are
not double-counted. Attempt ratings are not unique-participant ratings. Provider
modes are never silently mixed. Agree on a deletion date for pilot data.

## Product demonstration

Show `2(x+3)=10` followed by `2x+3=10`. Check the hint, revise to `2x+6=10`,
`2x=4`, `x=2`, and show completion. Next demonstrate a missing quadratic root.
Run `python -m proofgrade.demo` to show a deliberately wrong candidate rejected,
a valid second candidate accepted, and three bad candidates withheld. This
command is explicitly a simulated provider demonstration, not a live model test.
