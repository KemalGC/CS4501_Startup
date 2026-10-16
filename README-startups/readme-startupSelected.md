# Startup 2: ProofGrade — Verified Feedback on Math Solutions

**Inspiration from YC Startup Directory:** [Frizzle (YC Summer 2025)](https://www.ycombinator.com/companies/frizzle), which applies AI to math assignment grading and instructional feedback.

**Proposed startup (our adaptation):** ProofGrade focuses on a smaller, verifiable outcome: **explaining the first invalid step in a typed algebra solution and generating a checked next hint**. This is an original specialized MVP, not a claim that Frizzle operates this way.

## How this idea meets all eight criteria

### 1. Solves one problem extremely well
Students often know that their answer is wrong without knowing **where their reasoning first broke**. The MVP takes typed, step-by-step linear and quadratic equation solutions, identifies the first non-equivalent transformation, and offers one correct hint. It does not attempt handwritten OCR, essay grading, or every branch of mathematics.

### 2. I know or can access target customers
College students, peer tutors, and teaching assistants are accessible through my university classes and prior teaching-assistant experience. I could pilot with volunteers using **practice exercises**, not confidential graded submissions, and ask instructors to judge the feedback.

### 3. Familiar with the infrastructure
The MVP needs Python, SymPy, JSON schema validation, FastAPI, an LLM API, and a simple web form. I understand the underlying algebra and probability/coursework context; learning the precise SymPy APIs and constructing a test bank are achievable.

### 4. Significantly reimagines the problem
Rather than a general AI tutor that explains anything, ProofGrade makes **mathematical correctness a machine-checkable prerequisite for personalized feedback**. Students see the earliest verifiably incorrect step and a hint specifically tied to that step, not a confident unverified explanation or an answer dump.

### 5. An LLM/generative model is core
The LLM interprets the student's sequence, selects which misconception best explains the mistake, and **generates a tailored hint and worked corrective transition**. Deterministic algebra code independently verifies these suggestions but does not write the personalized pedagogical feedback itself.

### 6. Validation guardrail: no unvalidated LLM artifact reaches users
The LLM must return structured JSON containing the cited step number, equation before/after, the claimed correction, and a constrained hint. Before any feedback appears:
- Pydantic/JSON Schema checks the object and step indices;
- SymPy checks equation equivalence on the declared real-number domain and verifies the corrected transition and final solution against a trusted answer key;
- the hint must reference a verified error category from a fixed taxonomy and cannot introduce an unchecked new mathematical result.

The final displayed explanation is assembled from verified fields and approved templates. Ambiguous variable domains, extraneous roots, or unverifiable reasoning cause withholding and referral to human review.

### 7. Automatic self-correction loop
If SymPy detects a false correction or JSON validation fails, the backend sends the LLM the **failing transformation, counterexample or symbolic difference, and schema errors**. The LLM regenerates the candidate and it is rechecked, up to three attempts. A fallback is "This solution needs manual review," never unverified advice.

### 8. Fully deployable MVP
Deploy a FastAPI backend with SymPy, a web frontend for entering algebra steps, and a small database for anonymous practice results. Package in Docker and host on a container service. Start with 30–50 instructor-reviewed algebra examples and synthetic student errors; use no student identifiers without appropriate permission.

## Concrete MVP demonstration
1. User enters `2(x+3)=10` → `2x+3=10` → `2x=7`.
2. SymPy verifies that the expansion step is not equivalent to the original.
3. The LLM generates an error diagnosis and hint such as "Distribute the 2 to both terms."
4. A structured validator checks the claimed corrected equation (`2x+6=10`) and references to the first error.
5. On deliberate LLM miscalculation, validator feedback triggers automatic regeneration; only the checked hint is released.

**Validation/quality metric:** Accuracy of first-error location; fraction of feedback passing symbolic verification; human tutor rating for hint usefulness.

**Boundaries:** Start with typed algebra and practice content only. Correctness is checked inside a declared mathematical scope; unsupported questions are rejected rather than guessed.
