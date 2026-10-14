# Startup 4: EventSync — Verified Event Calendar Entries for Student Clubs

**Inspiration from YC Startup Directory:** [Gumloop (YC Winter 2024)](https://www.ycombinator.com/companies/gumloop), an AI-agent platform for automating workflows.

**Proposed startup (our adaptation):** EventSync accepts messy club event announcements (emails, posts, and copied messages) and outputs **accurate, source-grounded calendar entries**. It is a purpose-built verified event publishing workflow, not a general agent-building platform.

## How this idea meets all eight criteria

### 1. Solves one problem extremely well
Students miss events or put them on calendars with the wrong day, location, or time because announcements arrive as informal text. EventSync solves one problem: transforming an announcement into a **correct event entry suitable for calendar import**. It does not replace club messaging, ticketing, or event management.

### 2. I know or can access target customers
I am involved in university courses and student organizations where event information circulates in chat or email. I can invite organizers to contribute public/permissioned sample announcements and test whether the resulting events match the originals.

### 3. Familiar with the infrastructure
The project uses Python/FastAPI, an LLM API, date/time parsing libraries, an iCalendar (`.ics`) generator/parser, an events database, and AWS/container hosting. Calendar formats and time-zone libraries are learnable within an MVP.

### 4. Significantly reimagines the problem
Calendar tools usually expect a user to type event fields. Generic AI extraction sometimes invents missing details. EventSync introduces **evidence-backed calendar publishing**: every required field traces to words in the source, contradictions are flagged, and ambiguous dates are withheld, so automation is trustworthy enough for organizers.

### 5. An LLM/generative model is core
The LLM interprets free-form announcements such as "meeting next Thurs at 7 in Thornton A238" and **generates a structured event object** including a name, start/end candidates, location, timezone assumption flag, and source-text evidence spans. Rigid regex alone cannot robustly understand diverse casual messages.

### 6. Validation guardrail: no unvalidated LLM artifact reaches users
No generated event object, summary, or `.ics` file is released until:
- Pydantic validates the required structure;
- the claimed date/time/location values are corroborated against cited source spans and independently parsed where feasible;
- timezone policy is explicitly applied (for example `America/New_York`), with ambiguous DST and relative dates rejected without reference dates;
- the event has `start < end`, no impossible date, and an `.ics` file that can be parsed back to identical fields.

If the source omits essential details, the app asks the organizer instead of guessing. Source corroboration does not guarantee every interpretation, so organizer approval is required before sending public invitations.

### 7. Automatic self-correction loop
On a failed schema/date/evidence/iCalendar check, the system returns the exact error (for example `LOCATION_NOT_IN_SOURCE` or `INVALID_TIMEZONE`) to the LLM along with the original announcement. It retries extraction and validation up to three times. Persistent ambiguous announcements go into a review queue; no invalid calendar file is exposed.

### 8. Fully deployable MVP
A FastAPI backend accepts pasted text, stores a verified event record, and generates a downloadable `.ics` file. A small React frontend shows validation status and source spans. Package in Docker and deploy to a low-cost container host or AWS. Publishing to Google Calendar can be a later OAuth-based extension; the MVP requires no access to anyone's private email.

## Concrete MVP demonstration
1. Paste "IEEE tech talk, Fri Oct 23 at 6 PM, Thornton A238" and supply the relevant year and club time zone.
2. The LLM extracts title, location, and start time with supporting source spans.
3. The independent validator checks the calendar date, source evidence, and serialized `.ics` fields.
4. A deliberately hallucinated location triggers automatic feedback and retry.
5. Only a validated event is downloadable. An announcement with no clear time is held for clarification.

**Validation/quality metric:** Exact-match accuracy on date, time, and venue against organizer-labeled announcements; number of clarification prompts; rate of invalid event releases (target: zero in test scenarios).

**Boundaries:** Never invent a start or end time; if duration is absent, ask the organizer or use a preapproved organization rule that is clearly disclosed and verified.
