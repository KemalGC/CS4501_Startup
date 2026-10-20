# Teacher workspace API

The teacher API lives at `/api/teacher`. Provision an account locally with:

```sh
python -m proofgrade.teacher_cli kemal
```

The command prompts for a password of at least 12 characters. Passwords are
salted and hashed; sessions expire after eight hours and logout revokes them.
Set `PROOFGRADE_TEACHER_DB` to choose the database path (default
`data/teachers.sqlite3`). Use HTTPS and
`PROOFGRADE_SECURE_COOKIES=true` when hosting.

Every mutation requires `X-ProofGrade-Request: 1`. Browser cross-origin
requests are rejected. Each record lookup checks the signed-in teacher's
ownership. There is no public registration, grading API, or upload URL.

| Endpoint | Operation |
| --- | --- |
| `POST /login`, `POST /logout`, `GET /session` | Session management |
| `GET/POST /assignments` | List and create assignments with validated keys |
| `GET/DELETE /assignments/{id}` | Read or delete an owned assignment |
| `GET/POST /assignments/{id}/submissions` | List or add anonymous student codes |
| `POST /assignments/{id}/uploads` | Add an image/PDF response as private normalized pages |
| `GET/DELETE /submissions/{id}` | Read or delete a response |
| `GET /submissions/{id}/pages/{number}` | Read an owned source PNG, with no-store caching |
| `POST /submissions/{id}/extract` | Request a structured AI transcription draft |
| `POST /submissions/{id}/transcript` | Confirm work and compute draft rubric scores |
| `POST /submissions/{id}/approve` | Finalize all reviewed question scores |
| `GET /submissions/{id}/history` | Review version and approval history |
| `GET /assignments/{id}/analytics` | Approved-result summaries and coverage |
| `GET /assignments/{id}/grades.csv` | Approved grades only |
| `GET /submissions/{id}/feedback.txt` | Approved student feedback, without keys |
| `GET /students/{code}/progress?class_name=...` | Approved scores across assignments |
| `GET/POST /assignments/{id}/practice` | Review or create skill-targeted practice |
| `POST /practice/{id}/approve` | Approve a checked practice set |
| `GET /practice/{id}/questions.txt` | Approved student questions, without keys |

Assignments have 1–5 questions. Each question specifies `id`, `equation`,
`answer`, `skill` (`linear`, `distribution`, or `quadratic`), and 1–5 criteria.
Criteria specify `id`, `label`, `kind`, and 1–20 `points`:

- `final_answer`: full points for the complete correct real solution set.
- `valid_work`: full points when all transitions preserve solutions and there
  is a non-final intermediate equation different from the original.
- `teacher_review`: no automatic score; the teacher must decide.

Teachers can award partial points, change feedback, and revise error tags with
an explanation. Unsupported or unreadable work has unset scores; it cannot
silently receive zeros.

Transcript and approval requests carry the current `revision`. A stale write
returns 409. Changing a transcript invalidates its approval and removes it from
grade exports and analytics until it is reviewed again. Approved results retain
an audit history. Assignment rubrics are immutable after creation; create a
replacement assignment if the rubric changes.

## Uploads and optional model processing

Upload JSON contains `student_code` and `file_base64` (raw file bytes encoded as
base64, without a data-URL prefix). Accept JPG/PNG up to 20 megapixels, or PDF with
1–5 pages, up to 8 MiB per file. Only normalized PNG pages are retained. There are
at most 200 responses per assignment. Requests are capped before parsing,
including chunked bodies: 12 MiB for uploads and 256 KiB for other mutations.

`POST /submissions/{id}/extract` takes `{"revision": 1}` using the current version.
Set `PROOFGRADE_TEACHER_AI=openai`, `OPENAI_API_KEY`, and a vision/Structured
Outputs model in `PROOFGRADE_VISION_MODEL` (fallback `OPENAI_MODEL`). Disabled is
the default; extraction returns 503 when unavailable. Manual transcription works
regardless. Source pages and question prompts are sent to the provider only on
extraction request; answer keys are excluded. Responses use `store=false`.

The model must cover every question exactly once, preserve student mistakes,
cite a valid source page for transcribed work, and flag unreadable content.
Invalid candidates get at most three attempts. A successful extraction creates
a new `transcription_draft` revision and clears prior results/approval. It never
confirms the transcript or releases a grade. Confirm via `/transcript` first.

Practice creation takes `{"skill": "distribution"}` (or `linear`/`quadratic`).
The skill must have lost points in approved results. With teacher AI disabled,
three checked templates are varied; enabled mode proposes three problems and
independently checks every equation, complete key, and skill constraint. Invalid
sets are withheld. The source (`checked_templates` or `openai_checked`) is recorded;
review and `/practice/{id}/approve` are required for the key-free student export.

The session response exposes `vision_mode` and `hint_mode` to identify configured
behavior. The UI at `/teacher` implements these operations; API details need not
be entered by teachers. Provider tests mock transport; live validation remains.

## Storage lifecycle

The existing practice API remains separate. Its opt-in metrics database is not
used for classroom grades. Teacher records contain submitted work and should be
deleted through the assignment/submission controls when no longer needed.
