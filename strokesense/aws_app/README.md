# StrokeSense AWS API

This module is a Python Lambda HTTP API v2.0 handler for an isolated AWS-dev
environment. It is **not** a replacement for the live Render analyzer. The
Batch CPU adapter in `worker.py` streams a bounded S3 upload, executes the
existing analysis command, and verifies the real HTML/metrics output before
publishing a private `report.json`. The operator-only 2-vCPU Fargate smoke
test completed successfully on November 19, 2026; public compute stays gated
until server-side admissions and public-user flows have been reviewed.

## Identity and authorization

Configure an API Gateway HTTP API JWT authorizer with the intended Cognito user
pool issuer, audience, and JWT scopes as appropriate. Authenticate **every**
user-data route. Only `GET /health` and the strictly validated, rate-limited
`POST /feedback` usability survey are public. Lambda uses the verified
`requestContext.authorizer.jwt.claims.sub` as the account key; it does not trust
user IDs from incoming JSON. Do not expose this Lambda directly via a public
Function URL or attach additional routes without their authorizer. The AWS execution role
provides credentials to boto3; never ship AWS keys to Vercel or the browser.

## API contract

Send `Authorization: Bearer <Cognito JWT>` and JSON to API Gateway for each
route below (other than health). The `video_id` and `job_id` are the same
opaque 32-hex ID, and all record lookups require the matching Cognito owner.

| HTTP route | Request JSON | Success response |
| --- | --- | --- |
| `POST /uploads/start` | `{ "size_bytes": 100000000, "content_type": "video/mp4", "tier": "free", "filename":"eights.mp4", "allow_admin_review":false }` | `201 {video_id, part_size_bytes, part_count, expires_at, tier,filename,allow_admin_review}` |
| `POST /uploads/part` | `{ "video_id": "...", "part_number": 1 }` | `200 {url, method:"PUT", part_number, required_size_bytes, expires_in}` |
| `POST /uploads/complete` | `{ "video_id": "...", "parts": [{"part_number":1,"etag":"..."}, ...] }` | `200 {video_id, status:"uploaded", size_bytes}` |
| `POST /uploads/abort` | `{ "video_id": "..." }` | `200 {video_id, status:"aborted"}` |
| `POST /analysis/jobs` | `{ "video_id": "..." }` | `202 {job_id, video_id, status:"submitted"}` (or `503` if Batch is unconfigured) |
| `GET /analysis/jobs?limit=20&cursor=...` | None | `200 {jobs:[...],next_cursor}` from owner-only DynamoDB index (max 30/page) |
| `GET /analysis/jobs/{job_id}` | None | `200` owner-only job details, timing, report/video expiry, consent flag |
| `POST /analysis/jobs/{job_id}/review` | `{ "allow_admin_review": false }` | `200 {job_id,allow_admin_review}`; owner can revoke future admin access |
| `GET /reports/{job_id}` | None | `200 {job_id,download_url,expires_in,report_expires_at}` only for successful, non-expired reports |
| `GET /reports/{job_id}/artifacts` | None | `200 {job_id,video_url,rowers,expires_in,report_expires_at}`; short-lived private MP4/JPEG URLs, after the same owner/status/expiry checks. Existing jobs without media return `video_url:null,rowers:{}`. |
| `GET /admin/jobs?limit=20&cursor=...` | None | `200 {jobs:[...],next_cursor}` for **explicitly opted-in** videos only |
| `GET /admin/videos/{job_id}` | None | `200 {job_id,video_url,video_type,expires_in,video_expires_at}`; only if signed-in admin, opted in, annotated or original retained, atomic audit succeeds |
| `GET /health` | None | `200 {status:"ok"}` public |
| `POST /feedback` | `{ "rating": 1, "comment": "Optional short comment" }` | `201 {submitted:true}` public |

Website usability ratings are anonymous: a 1–5 integer is required, a comment
of at most 1000 characters is optional, and unknown fields are rejected.
Neither Cognito identity nor the originating raw IP is stored in a review.
Per-source (10/day) and global (100/day) DynamoDB transaction limits plus API
Gateway route throttling reduce anonymous spam. Short-lived daily limit keys
expire after three days; feedback records expire after roughly 90 days by
DynamoDB TTL. The public API exposes no feedback-reading endpoint. Operators
can inspect the private feedback table using their AWS console permissions.

The browser slices `File` into `part_size_bytes` blobs, calls `/uploads/part`
for every 1-based part, `PUT`s each blob to the returned S3 URL and captures
the `ETag` response header. It completes with the ordered part/ETag list.
The presigned upload part includes the **exact expected Content-Length** for
that part (browser Blob uploads supply this header automatically). Configure
S3 bucket CORS to allow the AWS-dev frontend origin's PUTs and expose `ETag`.
The frontend should call `/uploads/abort` after cancellations and recoverable
upload failures to restore the reservation. S3 lifecycle should abort stale
multipart uploads as a backstop.

## Private My Analyses and optional admin review

`GET /analysis/jobs` uses the Cognito `sub` as the DynamoDB GSI partition,
returns only owner-visible display fields (filename, timestamps, status,
processing times, video/report expiration), and validates paginated cursors
against the **same owner**. It never returns an S3 key, email or another
account's record. The `GET /analysis/jobs/{id}` route also returns these
fields while checking the current Batch state. `video_available` is a
time-window eligibility flag, not a guarantee the object still exists; a
media presign route must check S3 before returning a URL.

**History is currently temporary.** A successful free job's metadata is
eligible for DynamoDB TTL deletion after its 3-day report period and the
default 7-day grace, not stored forever. Raw video uploads follow the
Terraform S3 lifecycle setting (currently 7 days in this branch; other
environments can be shorter); report access expires at 3 days. Physical S3
and DynamoDB TTL cleanup is asynchronous. An expired original cannot be
replayed from a remaining history card. Extending metadata or original video
retention requires a new privacy decision; it is not enabled here.

Video-admin consent is **false by default**. The uploader must actively
check a clearly worded choice before upload. `filename` is stored only as a
sanitized basename (128 visible characters maximum). An owner may change or
revoke consent with `POST /analysis/jobs/{id}/review`, including after an
upload. Revocation atomically removes the sparse admin-listing index value.

Admin viewing requires **both** a Cognito-signed access token containing the
`strokesense-admin` group and an immutable Cognito `sub` listed privately in
`ADMIN_COGNITO_SUBS`. No admin rights derive from a display email, browser
flag, or user-provided JSON. The group is provisioned empty; manually verify
the intended Google-linked identity, add that specific Cognito user to the
group, then configure their exact sub. Empty allowlist rejects all admins.

An administrator can list only opted-in jobs. The API prefers a completed
job's annotated MP4 when a bounded `artifacts.json` manifest declares it and
the 3-day report is still available. It falls back to the original video
if that file remains within its independent raw-upload retention. A URL is
issued for at most **60 seconds** only after `HeadObject` finds the selected
video and a single DynamoDB transaction (a) rechecks live consent and the
*selected media type's* expiry and (b) writes an audit event to the private
`admin_access_audit` table.
Failure of that transaction blocks the URL. Audit fields: admin/owner Cognito
subs, job ID, video type, time, source IP, hashed user agent, action and 90-day TTL;
no emails, JWTs or S3 signed URLs. Previously issued URLs may remain valid
for up to 60 seconds after revocation, and already downloaded copies cannot
be recalled. The upload notice must disclose this accurately, including the
possibility that footage contains third-party rowers.

## Real analysis timing

AWS Batch's authoritative `createdAt`, `startedAt` and `stoppedAt` millisecond
timestamps yield `queue_wait_ms` (submit → RUNNING, **including image pull and
cold start**) and `batch_run_ms` (RUNNING → terminal). The worker also records
`analysis_wall_ms` (actual inference subprocess wall time), `cpu_time_ms`
(child-process user+system CPU consumption), and when video metadata is
available `video_duration_ms`. It writes a tiny `runtime-metrics.json`
beside the report and always commits `report.json` last. On Batch settlement,
the API saves available timing fields in the same atomic quota transaction;
both polling and the scheduled reconciler use this path. Missing metrics
from older workers remain `null`, never synthetic. These measurements are
not Fargate billing totals.

## Plan, quota, and failure rules

- Free: lifetime **300,000,000 bytes** of *successful* analysis, and at most
  **100,000,000 bytes per video**. Bytes are reserved before presigning; every
  create/settle/refund is an atomic DynamoDB transaction with an owner/job
  state condition. Failed/cancelled jobs refund their reservation; successful
  analyses consume it only if Batch succeeds and a report exists in S3.
- Paid: at most **750,000,000 bytes per video**, one verified credit per video.
  `PAID_BILLING_ENABLED=false` by default, and zero paid credits at account
  creation: payment, Stripe webhooks, idempotent credit grants, and GPU compute
  **are not implemented**. Do not enable paid until that is built and tested.
- The upload authorization expires after 1 hour; incomplete reservations are
  reconciled on the owner's next new upload **and** by the scheduled
  `aws_app.reconcile` Lambda every 15 minutes, independently of browser polls.
  Ambiguous in-flight Batch submissions raise an operations alarm and require
  manual review rather than risking a double refund.
- Report links are presigned for at most 15 minutes and are accessible only
  before **72 hours (free)** or **30 days (paid)** after successful settlement.
  API checks expiry server-side. S3 lifecycle/deletion policy should also
  physically remove expired data; don't rely on URL expiration alone.
- A missing report after Batch success is treated as failure, and quota is
  refunded. The worker exits nonzero on decoding failures, invalid measurement
  artifacts, analysis failures, or failed S3 uploads. No fake reports.

## AWS Batch CPU container (operator smoke-tested)

From the repository's `strokesense/` directory, with Docker installed:

```sh
docker build -f Dockerfile.aws-cpu -t strokesense-aws-cpu:dev .
```

The CPU image installs the existing inference requirements and FFmpeg, bundles
the pinned 11.85 MB ONNX model after validating its SHA256, and runs an
unprivileged container. The 1.1 GB local LLM and GPU libraries are intentionally
excluded from the free tier until separately benchmarked and approved.

Required Batch variables are `STROKESENSE_JOB_ID`,
`STROKESENSE_USER_HASH`, `STROKESENSE_S3_BUCKET`,
`STROKESENSE_INPUT_KEY`, and `STROKESENSE_REPORT_KEY`; they are supplied by
the authenticated API, not by the browser. Paid keys are rejected. The output
JSON contains measured metrics and standalone HTML with inline charts/photos
for the sandboxed Vercel report preview. The success object is written last.

### Optional annotated media

When the CPU analyzer produces `original_annotated.mp4` and
`mistake_frames.json`, the worker validates and uploads the MP4 and referenced
timestamped JPEGs to the **same private per-user/per-job report prefix**, then
stores a tiny `artifacts.json` manifest. Only after those writes succeed does
it commit `report.json`, the success marker. The standalone JSON report is
unchanged and is never filled with video bytes. Media is bounded to a 120 MiB
MP4, 2 MiB per JPEG, 36 MiB of JPEGs across at most 128 unique frames, and a
64 KiB gallery manifest. Failures before the final report commit correctly
fail the Batch job rather than claiming a successful analysis.

`GET /reports/{job_id}/artifacts` is another authenticated, owner-checked
endpoint, not a public S3 index. It reads only that job's fixed manifest and
presigns only the fixed `annotated.mp4` name and validated `frames/*.jpg`
basenames. Its response contains a nullable `video_url` and `rowers` indexed
by seat (`R1`, `R2`, etc.); each rower has `snapshots` containing
`{label,time_seconds,url}` and `mistake_sequences` containing
`{code,stroke,frames:[{label,time_seconds,url}]}`. URL lifetimes never exceed
15 minutes or the remaining private report lifetime. Missing manifests for
older analyses yield an empty media response without changing report access.

The existing S3 IAM grants (`cpu_job` PutObject and API GetObject on
`reports/*`), HTTPS-only bucket policy, private bucket, restricted CORS and
`reports/free/` deletion lifecycle already cover these objects. Terraform
**must add the authenticated API Gateway route** before the new Lambda version
can serve it. Deploy the new CPU container image for new media to be persisted;
old Batch job-definition revisions cannot retroactively restore temp files
from earlier jobs. Keep Vercel CSP `media-src` and `img-src` restricted to the
actual S3 bucket host, and do not expose raw keys or presigning credentials.
The isolated AWS-dev registry contains the versioned smoke-tested image. Public
visitor submissions still require reviewed server-side admission caps, a
controlled Terraform apply, and an authenticated browser-to-report test.

## Lambda configuration

ZIP root must contain `aws_app/`, and Lambda's handler setting is
`aws_app.handler.lambda_handler`. Install `aws_app/requirements.txt` into the
deployment artifact or use a Python runtime that already contains boto3.

Required environment variables: `S3_BUCKET`, `USERS_TABLE`, `JOBS_TABLE`.
`FEEDBACK_TABLE` is required to enable public feedback collection; without it
only that endpoint returns `503`.
Optional (defaults in parentheses): `CPU_BATCH_JOB_QUEUE` (empty),
`CPU_BATCH_JOB_DEFINITION` (empty), `FREE_LIFETIME_BYTES` (300000000),
`FREE_MAX_VIDEO_BYTES` (100000000), `PAID_MAX_VIDEO_BYTES` (750000000),
`FREE_REPORT_TTL_SECONDS` (259200), `PAID_REPORT_TTL_SECONDS` (2592000),
`PAID_BILLING_ENABLED` (`false`). The compute job requires both CPU Batch
environment variables and an actual valid inference container.
Additional private/admin settings: `RAW_UPLOAD_TTL_SECONDS` (604800 by this
branch's defaults), `TERMINAL_RECORD_GRACE_SECONDS` (604800),
`ADMIN_AUDIT_TABLE` (empty disables admin presigns),
`ADMIN_COGNITO_SUBS` (empty denies all admin requests), and
`ADMIN_AUDIT_TTL_DAYS` (90). No admin secret is sent to Vercel.

DynamoDB tables: `users` PK `user_id`; `jobs` PK `job_id`, GSI
`user_id-created_at-index` on PK `user_id` and SK `created_at`. S3 prefixes:
`uploads/`, `reports/free/`, `reports/paid/`.
Anonymous reviews use a separate private `feedback` table keyed by
`feedback_id` and automatically expire after about 90 days.

## Local tests

From the `strokesense/` directory:

```sh
python -m unittest discover -s aws_app -p 'test_*.py' -v
```

These tests use in-memory stand-ins and require no AWS account or boto3
installation, including `test_worker.py` for the S3-to-report contract.
Before deployment, add AWS emulator/integration tests with
real S3 presigned multipart signatures, IAM, CORS, JWT enforcement, and
failure/retry races; verify AWS costs and budget alarms. A successful Docker
build and real-video inference benchmark are still required.
