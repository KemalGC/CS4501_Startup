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
| `POST /uploads/start` | `{ "size_bytes": 100000000, "content_type": "video/mp4", "tier": "free" }` | `201 {video_id, part_size_bytes, part_count, expires_at, tier}` |
| `POST /uploads/part` | `{ "video_id": "...", "part_number": 1 }` | `200 {url, method:"PUT", part_number, required_size_bytes, expires_in}` |
| `POST /uploads/complete` | `{ "video_id": "...", "parts": [{"part_number":1,"etag":"..."}, ...] }` | `200 {video_id, status:"uploaded", size_bytes}` |
| `POST /uploads/abort` | `{ "video_id": "..." }` | `200 {video_id, status:"aborted"}` |
| `POST /analysis/jobs` | `{ "video_id": "..." }` | `202 {job_id, video_id, status:"submitted"}` (or `503` if Batch is unconfigured) |
| `GET /analysis/jobs/{job_id}` | None | `200 {job_id,video_id,status,tier,report_expires_at?}` |
| `GET /reports/{job_id}` | None | `200 {job_id,download_url,expires_in,report_expires_at}` only for successful, non-expired reports |
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
