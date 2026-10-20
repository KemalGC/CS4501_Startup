# Startup 2: ProofGrade — AI Homework Grading for Math Teachers

**Inspiration from YC Startup Directory:** [Frizzle (YC Summer 2025)](https://www.ycombinator.com/companies/frizzle), whose directory profile describes AI grading of handwritten math assignments, classroom analytics, and differentiated assessment.

**Proposed startup:** ProofGrade helps math teachers turn handwritten homework into reviewed grades, actionable feedback, and targeted follow-up practice. Teachers upload assignment images or scanned PDFs together with an answer key and rubric. The system extracts each student's work, proposes question-level scores and feedback, and highlights uncertain readings or reasoning for teacher review. Confirmed results feed a class dashboard showing common errors and students who need support. Teachers can then approve differentiated practice addressing those gaps.

**Core value:** Reduce the time teachers spend grading and organizing follow-up instruction while keeping them in control of final scores and feedback. Time savings, grading accuracy, and learning benefits are hypotheses to measure, not established product claims.

**Initial scope:** One class or tutoring group, linear and quadratic algebra in one real variable, and short worksheets using a known question layout. The teacher is the primary user; students receive teacher-approved feedback and practice.

**Implementation status:** This is the revised product direction. The current code checks typed algebra from a fixed practice bank and produces verified hints. Handwriting extraction, assignment uploads, rubric scoring, teacher review, classroom dashboards, and differentiated assessment still need to be built. See the [implementation plan](../docs/homework-checker-plan.md).

## How this idea meets all eight criteria

### 1. Solves one problem extremely well

Teachers need to grade a set of math assignments and decide what to reteach. ProofGrade makes that workflow the product: upload work, review proposed grades, identify repeated mistakes, and prepare targeted follow-up. The first release supports short linear/quadratic algebra worksheets so correctness can be checked within a declared mathematical scope.

### 2. I know or can access target customers

Recruit math teachers, algebra tutors, and teaching assistants through university teaching and tutoring networks. Begin with 3–5 educators and synthetic or permitted, de-identified homework samples. Confirm access to the target teachers before making adoption claims. Ask them to supply a rubric, review grading quality, and compare total grading time with their usual process.

### 3. Familiar with the infrastructure

Reuse the Python/FastAPI backend, bounded SymPy checker, Pydantic validation, web interface, and Docker packaging. Add a vision-capable model for handwriting transcription, private file storage, assignment/submission records, rubric scoring, a teacher review interface, and class-level reporting. Model credentials stay on the server. Upload processing and the teacher workflow are new engineering work.

### 4. Significantly reimagines the problem

An assignment becomes an input to a continuous instructional workflow: question-level evidence informs grading, reviewed mistakes reveal class learning gaps, and those gaps guide the next practice set. ProofGrade combines teacher judgment with independently checked algebra. Each suggested score should be traceable to the student's work and the applicable rubric criterion.

### 5. An LLM/generative model is core

A vision-capable model transcribes handwritten equations and associates them with worksheet questions. A model proposes structured error categories, feedback, and follow-up practice tied to reviewed learning gaps. Deterministic code checks mathematical claims, score arithmetic, and schema validity. Teachers approve ambiguous interpretations and final grading decisions.

### 6. Validation guardrail: no unchecked final grading or feedback is released

Before a result can be finalized:

- Validate the extraction schema and associate every extracted step with a question and source region.
- Show the original image beside its transcription for teacher confirmation or correction. Symbolic correctness cannot establish that handwriting was read accurately.
- Validate the teacher's answer key within the supported grammar and flag inconsistent keys.
- Check equation transitions, complete solution sets, and proposed corrections over the real-number domain.
- Tie every proposed point award to a rubric criterion and source evidence; compute totals deterministically and keep scores within the rubric's bounds.
- Assemble student feedback from validated fields and approved templates. Require a teacher decision for unsupported reasoning or subjective criteria.
- Label suggestions as drafts until the teacher approves them. Preserve edits and approvals; release only approved grades and feedback.
- Build analytics from confirmed results, showing review coverage and unresolved work separately. An unreadable answer is not automatically a wrong answer.

The restricted parser, validation boundaries, and teacher review are part of the workflow. A model's confidence alone does not certify transcription or grading.

### 7. Automatic self-correction loop

When a candidate violates the schema, cites a missing step, exceeds rubric limits, or fails mathematical checks, return specific validation evidence to the model and retry for at most three total attempts. If it still fails, mark the item for manual review and withhold the proposed final result. Unclear handwriting requires confirmation; repeated generation cannot establish what a student wrote. Follow-up problems and answer keys undergo the same bounded validation process.

### 8. Fully deployable MVP

Package the backend and teacher interface in Docker for a private pilot. Support teacher sign-in, restricted assignment uploads, persistent assignment/review records, and deletion of uploaded work. Begin with 3–5-question worksheets and 30–50 instructor-reviewed examples, including synthetic handwriting and errors. Provide a review queue, a class summary, CSV export of approved grades, and one small follow-up practice set for each confirmed skill gap.

The repository currently provides a runnable typed-algebra foundation and CI checks; the proposed teacher application and its hosting are not yet implemented.

## Concrete MVP demonstration

1. A teacher creates a five-question algebra assignment, confirms the answer key, and sets point values.
2. The teacher uploads a small batch of photographed or scanned student submissions.
3. ProofGrade extracts equations and displays each image beside the transcription; the teacher resolves uncertain readings.
4. For `2(x+3)=10` followed by `2x+3=10`, the checker identifies the invalid distribution step. The system proposes rubric-based credit and a checked explanation.
5. The teacher edits or approves suggested scores and feedback, then exports the finalized results.
6. The dashboard shows which questions and skills caused the most difficulty, together with how much work has been reviewed.
7. The system proposes a short distribution practice set with checked answer keys; the teacher approves it before sharing.
8. A deliberately invalid model candidate triggers regeneration, while an unreadable or unsupported response stays in manual review.

**Validation/quality metrics:** Total grading time including review and corrections; score agreement with an independently reviewed rubric; transcription correction rate; first-error accuracy; teacher override rate; teacher-rated feedback usefulness; and correctness of differentiated practice.

**Boundaries:** Start with supported algebra on short, known-layout worksheets. General proofs, diagrams, arbitrary notation, essays, other subjects, LMS integration, and automatic gradebook posting are outside the first release. Teachers control final grading. No time-saving or learning claim is made until it is measured.

See the [teacher pilot plan](../docs/pilot-plan.md) for the evaluation procedure.
