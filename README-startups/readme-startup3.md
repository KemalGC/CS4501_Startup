# Startup 3: ClubExpense — Verified Reimbursements from Receipts

**Inspiration from YC Startup Directory:** [Invofox (YC Summer 2022)](https://www.ycombinator.com/companies/invofox), which turns business documents into structured, validated data.

**Proposed startup (our adaptation):** ClubExpense automatically prepares **accurate reimbursement drafts from student-organization receipts**, using LLM extraction and strict validation before the report can be viewed/exported. This is a narrow end-user workflow inspired by, but distinct from, Invofox's developer document API.

## How this idea meets all eight criteria

### 1. Solves one problem extremely well
Volunteer club treasurers spend time transcribing store receipts into reimbursement spreadsheets and checking totals. The MVP solves one problem: converting a single ordinary receipt into a **correct, policy-checked reimbursement draft**. It does not execute payments, give tax advice, or attempt enterprise accounting.

### 2. I know or can access target customers
I participate in university organizations and can approach student-club treasurers and members who submit travel, equipment, or event expenses. The first pilot would use volunteer-provided or synthetic receipts with sensitive details redacted, after permission from the organization.

### 3. Familiar with the infrastructure
This can use Python/FastAPI, image upload and OCR/vision LLM calls, Pydantic, SQLite/PostgreSQL, object storage, and a simple dashboard. My prior work with APIs, event pipelines, and AWS makes the backend and deployment manageable.

### 4. Significantly reimagines the problem
Unlike generic invoice OCR, ClubExpense outputs a **ready-to-review club reimbursement entry** with line items, exact decimal totals, category rules, duplicate alerts, and source evidence. It replaces a multi-step student organization process, not just an OCR task.

### 5. An LLM/generative model is core
Receipts vary widely in layout, store wording, and abbreviations. A vision-enabled LLM **extracts and normalizes** merchant names, dates, purchased items, taxes, tips, and eligible expense categories into a prescribed JSON schema. Without generative interpretation the heterogeneous text normalization is substantially harder.

### 6. Validation guardrail: no unvalidated LLM artifact reaches users
Before any LLM-produced reimbursement entry is displayed or exported, an independent validator checks:
- schema, required fields, valid date/currency format, and decimal precision;
- exact arithmetic: line totals + tax + tip − discounts = reported total, allowing only a disclosed rounding tolerance;
- extracted fields against OCR/source text snippets or image-region evidence where available;
- organization-specific limits and duplicate hashes.

Unclear or unsupported fields are not invented. If a date or total cannot be corroborated from the source, the report remains blocked and requests manual confirmation. Verification catches some but not all visual extraction errors; humans approve the final reimbursement.

### 7. Automatic self-correction loop
The validator returns machine-readable errors such as `TOTAL_MISMATCH: expected 38.42 from line items, got 39.42` or `DATE_NOT_GROUNDED`. The backend gives the LLM the error codes, relevant source snippets, and existing candidate for an automatic retry. After at most three attempts, unresolved entries are held for manual inspection without an exported draft.

### 8. Fully deployable MVP
Build a responsive upload webpage and Dockerized FastAPI service with LLM access, image/OCR processing, a private S3-compatible image store, and PostgreSQL. Deploy behind HTTPS on a small cloud container host. A verified draft can be exported as CSV; a payment gateway and bank connections are explicitly out of scope.

## Concrete MVP demonstration
1. Upload a sample receipt with two products, sales tax, and total.
2. The LLM returns normalized JSON plus source text references.
3. The validator recomputes amounts using `Decimal`, detects a deliberately altered total, and sends the difference back to the LLM.
4. The corrected draft passes checks and becomes downloadable as CSV.
5. A deliberately unreadable receipt is blocked instead of fabricated.

**Validation/quality metric:** Percentage of fully correct receipt drafts; human corrections per receipt; false approvals among a labeled test set.

**Boundaries:** No funds move automatically, and receipts are not used without permission. Reimbursement authorization remains with the club's treasurer.
