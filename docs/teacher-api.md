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
| `POST /assignments/{id}/image-uploads` | Add browser-prepared RGB pixels without native image libraries |
| `POST /assignments/{id}/uploads` | Optional native decoder for encoded files; PDF requires explicit enablement |
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

The default image endpoint `/image-uploads` takes `student_code`, integer `width`
and `height`, and `pixels_base64`. The latter is base64 of exactly
`width * height * 3` raw RGB bytes, top-to-bottom/left-to-right, with no padding
between rows, alpha channel or data-URL prefix. Each side is 1–2400 pixels, with
at most 3,000,000 pixels overall. Extra fields, invalid base64, inconsistent byte
counts and out-of-bounds dimensions are rejected before creating a record.
Ownership is checked before pixel processing. The server constructs an RGB PNG
with only IHDR/IDAT/IEND chunks, using standard-library compression and CRCs.
It never parses client-supplied encoded images on this route.

`static/image-upload.js` decodes JPG/PNG files of at most 8 MiB and 20 megapixels
in the browser, respects EXIF orientation, flattens transparency onto white, and
downsizes to the prepared-image bounds without upscaling. Those source-file checks
are browser checks; the server independently enforces its own pixel/byte limits.

The legacy `/uploads` endpoint takes `student_code` and `file_base64` (raw file
bytes as base64, without a data-URL prefix). It requires the optional native media
libraries. PDF also requires `PROOFGRADE_PDF_UPLOADS=true` and supports 1–5 pages,
8 MiB/file. Native decoding errors do not affect `/image-uploads`.

Only clean PNG pages are retained. There are at most 200 responses per assignment.
Requests are capped before parsing, including chunked bodies: 12 MiB for either
upload endpoint and 256 KiB for other mutations. Source and grade writes retain
the existing ownership, deletion, and review contracts.

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

The authenticated session response exposes `vision_mode`, `hint_mode`, and
`uploads: {images: true, image_transport: "browser_rgb", pdf, message}`. Images
always use browser preparation. PDFs are off by default, with no native imports
during startup or session checks. If explicitly enabled, missing/blocked libraries
set `pdf: false`; native uploads return 503 without creating a record. Browser
photos, typed work, AI extraction, and page reads remain available. The
unauthenticated session has `uploads: null` and does not probe native libraries.
The UI at `/teacher` implements these operations; API details need not
be entered by teachers. Provider tests mock transport; live validation remains.

## Storage lifecycle

The existing practice API remains separate. Its opt-in metrics database is not
used for classroom grades. Teacher records contain submitted work and should be
deleted through the assignment/submission controls when no longer needed.
