# Startup 5: FormScout — Self-Correcting Tests for Registration Forms

**Inspiration from YC Startup Directory:** [Autosana (YC Summer 2025)](https://www.ycombinator.com/companies/autosana), which uses AI agents to create and run end-to-end tests and close the loop with coding agents.

**Proposed startup (our adaptation):** FormScout specializes in **verifying sign-up, registration, and RSVP web forms** run by small clubs and project teams. The product automatically writes Playwright tests from plain-language form requirements and accepts test artifacts only after execution and independent checks. It is deliberately far narrower than general mobile/web QA.

## How this idea meets all eight criteria

### 1. Solves one problem extremely well
Small organizations can lose sign-ups when a form button breaks, a required field is silently skipped, or confirmation does not appear. FormScout concentrates on one repeatable user journey: **can a visitor successfully submit a form, and are common invalid inputs handled correctly?** It does not attempt to test every feature of a website.

### 2. I know or can access target customers
Student clubs, small project teams, and friends building event sites are reachable through university networks. I can request consent to test public demo forms or run FormScout only on form sites that their owners authorize, then evaluate usefulness with organizers.

### 3. Familiar with the infrastructure
The MVP uses TypeScript, Playwright, GitHub Actions, Docker, FastAPI, and an LLM API. Prior software development, automated testing, and cloud deployment experience transfer directly; learning Playwright's test runner is manageable.

### 4. Significantly reimagines the problem
Generic end-to-end test suites are cumbersome to create and maintain. FormScout turns a **small organizer's plain-English acceptance criteria** into repeatable, evidence-backed form checks. It is not another generic browser agent: it is an always-ready safety net specifically for RSVP and registration flows.

### 5. An LLM/generative model is core
The LLM reads a form specification and DOM snapshots and **generates Playwright test code**, meaningful assertions, and selector repairs when the form changes. Template-only testing cannot adapt well to arbitrary field names, validation messages, and multi-step registration flows.

### 6. Validation guardrail: no unvalidated LLM artifact reaches users
Generated tests are quarantined and must pass:
- syntax/type checks plus linting;
- a policy validator requiring meaningful assertions, a successful positive path, and at least one invalid-input path;
- Playwright execution against an isolated authorized staging form;
- a negative-control check using a planted broken demo behavior to confirm the test actually fails when it should.

A test that simply passes because it does not assert anything is rejected. Only validated tests and evidence-linked failure reports can be displayed/exported; all others remain internal. A failing product can be reported as a bug **only if** the report's steps and evidence are verified, not because a flaky test failed once.

### 7. Automatic self-correction loop
When compilation fails, selectors no longer exist, or the negative control does not trip, the backend sends the **runner error, DOM snapshot, and failed policy check** to the LLM. It regenerates the test and reruns all validators, with a three-attempt budget. Crucially, the agent may repair a broken selector but cannot delete a required assertion to make a faulty site look healthy.

### 8. Fully deployable MVP
A GitHub Action or hosted Docker worker downloads the staging URL and approved test specification, generates and runs Playwright tests in an isolated browser, and uploads **validated** test artifacts. A lightweight web dashboard and FastAPI orchestration service can be deployed on a cloud container platform. Credentials are synthetic; production form submissions, real payments, and external attacks are excluded.

## Concrete MVP demonstration
1. A form owner provides a demo RSVP form and requirements: name/email required, valid submission leads to confirmation.
2. The LLM generates Playwright tests for successful and invalid submissions.
3. Compilation, assertion policy, real browser runs, and a negative-control run validate the tests.
4. Intentionally rename a form field to trigger a selector failure and automatic LLM correction.
5. Once corrected and revalidated, publish only the passing test suite and evidence.

**Validation/quality metric:** Percentage of generated suites passing all validators; defect detection rate on intentionally broken demo forms; successful auto-repairs; flaky-test rate.

**Boundaries:** Test only owned/authorized sites. Passing tests provide bounded evidence, not proof of bug-free software.
