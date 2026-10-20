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
| `GET/DELETE /submissions/{id}` | Read or delete a response |
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

The existing practice API remains separate. Its opt-in metrics database is not
used for classroom grades. Teacher records contain submitted work and should be
deleted through the assignment/submission controls when no longer needed.
