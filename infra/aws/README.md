# StrokeSense AWS development infrastructure (Terraform)

This directory manages the existing isolated `aws-dev` environment in
`us-east-1`. The existing Vercel/Render production deployment must remain
untouched. **Do not run an unreviewed `terraform apply`.** Review the saved
plan, expected billing, CPU admission controls, and the exact remote-state
backend before changing the deployed stack.

## Architecture

1. **Vercel** (separate `strokesense-aws-dev.vercel.app` project): static SPA;
   users sign in with Google via **Amazon Cognito User Pools**, OAuth 2.0
   authorization code with PKCE, then present a Cognito JWT to API Gateway.
2. **API Gateway HTTP API** validates Cognito JWTs for all user operations;
   a small **Lambda** owns sessions, upload integrity, records, quotas,
   short-lived presigned S3 URLs, Batch submission and status polling. An
   explicitly public, throttled `/feedback` route stores anonymous usability
   ratings and optional comments in a separate private DynamoDB table.
3. The browser uploads directly to a private **S3** bucket with multipart PUTs.
   This avoids API Gateway's 10 MB request-body limitation and makes 750 MB
   paid videos possible without proxying through Lambda or Vercel.
4. **DynamoDB** on-demand stores per-user counters and each job's owner,
   upload reservation, completion state and report expiration. The API uses
   conditional/transactional writes to avoid shared quotas and double charges.
5. **AWS Batch on Fargate** queues CPU-only jobs (2 vCPU, 4 GiB RAM). Its
   managed compute environment uses existing public subnets with outbound-only
   security groups and a public IP assigned to ephemeral containers, without
   an always-running ECS service, NAT gateway or ALB. The queue's default max
   is 10 vCPUs (at most 5 simultaneous jobs, subject to AWS quotas). Docker
   images live in private **ECR**. S3 is the source of truth for reports.
The queue and API job submission are **disabled by default** until a
   tested container image exists and `enable_cpu_analysis=true` is separately
   approved.
6. **CloudWatch, EventBridge and SNS** notify on API throttles/errors and CPU
   Batch failures. A separate scheduled Lambda reconciles failed jobs and
   abandoned reservations every 15 minutes, including when users stop polling.
   **Required AWS Budgets email alerts** monitor gross daily and monthly usage
   across the *entire account*, before promotional credits.

GPU Deep Analysis is **not** deployed, enabled, or billable by this stack:
`enable_gpu=false` rejects attempts to enable it. The [GPU_PLAN.md](GPU_PLAN.md)
explains the deferred `g6f.large` 1/8 L4 (3 GB VRAM) execution design,
required model benchmarks and EC2/ECS scheduling risks.

## Current feature safety gates

| Rule | Deployment value | Enforcement |
| --- | --- | --- |
| Free lifetime processing | 300,000,000 bytes total | DynamoDB atomic reservations; successful jobs consume it |
| Free single video | 100,000,000 bytes | API validation before issuing S3 multipart signatures |
| Paid single video | 750,000,000 bytes | API code limit; **paid billing disabled** in this stack |
| Failed or aborted free video | Refund reserved bytes | API `POST /uploads/abort` and failed Batch status reconciliation |
| Free report retention | 72 hours after success | API access expiry; eventual S3 lifecycle delete at 3 days |
| Paid report retention | 30 days after success | API access expiry; eventual S3 lifecycle delete at 30 days |
| Raw uploaded videos | Temporary | S3 lifecycle delete after 7 days; incomplete multipart after 1 day |
| Paid credits and GPU processing | Disabled | `PAID_BILLING_ENABLED=false`, `PAID_GPU_ENABLED=false` |

### My Analyses, consent and metrics (development only)

The owner JWT protects `GET /analysis/jobs?limit=20&cursor=...` and
`GET /analysis/jobs/{id}`. The library queries `user_id-created_at-index`
without a cross-user scan, with a 30-item page cap. Display fields include
sanitized filename, status, upload size, creation/submission/completion times,
video duration if measured, Batch queue/run timing, worker CPU/wall time,
and report/video expiry. **Cards do not guarantee video playback:** original
files and reports expire independently and may already be physically absent.
The existing metadata TTL remains seven days after terminal completion or
seven days *after the three-day report period* on success. The new
`terminal_job_record_grace_days` variable defaults to seven; do not extend
without explicit retention consent.

Uploaders can explicitly set `allow_admin_review=true` on `/uploads/start`;
all existing and omitted values default false. They can revoke with
`POST /analysis/jobs/{id}/review`. Only opted-in records enter the sparse
`admin_partition-created_at-index`. `GET /admin/jobs` queries that index;
`GET /admin/videos/{id}` checks current Dynamo consent, S3 object presence,
and retention, prefers the bounded manifest-backed annotated MP4 (within the
report's 3-day window) and falls back to the original, then creates a <=60s
video URL and atomically writes an `admin_access_audit` record. The audit has a 90-day TTL
by default and contains no raw URL, JWT or email. Revoke blocks subsequent
signatures but cannot retract a URL already issued (up to 60s) or a file
already downloaded.

Admin authentication needs **both** verified membership in the Cognito
`strokesense-admin` group **and** a separately configured exact Cognito
`sub` in `admin_cognito_subs` (empty by default = disabled). Do not grant
admin based solely on any email address string.
After the intended person signs in with Google, the operator must verify
the resulting immutable `sub`, assign that specific Cognito user to the
group, and securely configure the allowlist. No group assignments or AWS
deployments are performed by these Terraform changes.

## Cost alerts and pre-deployment safety gate

Terraform **requires a real `alert_email`** before `terraform plan` or
`terraform apply`. Set `TF_VAR_alert_email` in your local shell or another
private variable provider; do not commit your email address as a deployment
default. Confirm the separate SNS subscription email for operational alarms.

- **Daily gross-cost budget:** `$3/day` by default, with actual-cost emails at
  25% ($0.75), 50% ($1.50), 80% ($2.40), and 100% ($3.00).
- **Monthly gross-cost budget:** `$30/month` by default, with an actual-cost
  email at 80% ($24) and a 100% forecasted alert. The forecast may not be
  available until AWS has accumulated several weeks of billing history.
- **Credits excluded:** `cost_types { include_credit = false }` makes the
  budgets measure usage before the $100 promotional credit is applied.
- **Account-wide:** Costs from *other* AWS workloads in this account also
  count. These are not isolated StrokeSense budgets until billing tags are
  activated and the spend allocation is independently verified.

AWS Budgets emails are monitoring-only and free, but **neither a budget nor
an alert stops a running Fargate task, EC2 instance, or future charge**.
AWS billing information is delayed (typically 8–12 hours between budget
refreshes), so these alerts are not real-time circuit breakers. The Fargate
job timeout and max-vCPU setting limit individual-job and concurrent capacity,
not the month's spend. AWS may offer separate account-level spending controls;
review them in Billing before deployment instead of assuming an alarm is a cap.

The AWS **Free Plan expiration and the promotional credit expiration are
different dates**. The screenshot shows a $100 credit expiring May 22, 2027,
but does *not* establish that the account remains on the Free Plan until then.
Check the actual Free Plan time remaining in the AWS console before deploying;
the account's Free Plan may end earlier, regardless of unused credits.

References: [AWS Budgets pricing](https://aws.amazon.com/aws-cost-management/aws-budgets/pricing/),
[AWS Budget alert update cadence](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-best-practices.html),
[AWS Free Tier plans](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier-plans.html).

## DynamoDB recovery and provider compatibility

Both `users` (lifetime quotas and eventual paid-credit records) and `jobs`
(report ownership and in-flight processing state) enable **point-in-time
recovery**. DynamoDB charges separately for continuous backup storage; this
extra cost must be included in the final deployment review even if the tables
start small. This setting is code-only until the stack is separately approved
and deployed.

The AWS provider is constrained to **6.37+** to support the `key_schema`
blocks on global secondary indexes and avoid earlier provider index drift and
recreation bugs. The table-level `hash_key` arguments are
still necessary: `key_schema` is supported **inside** GSI blocks, not at the
table resource level. Current provider releases can still emit deprecation
warnings about table-level `hash_key` even though the documented alternative
is not valid at that location. Do not substitute `key_schema` at the top level
merely to silence a warning; it prevents `terraform validate` from succeeding.

## Secure Terraform state (separate approval required)

Terraform state contains sensitive values including the Google OAuth **client
secret**, even when console output masks them. Do not run the first
`terraform apply` with a local state backend or put state in GitHub. The
[S3 backend template](backend.s3.tf.example) describes a **separately
provisioned** backend; creating its S3 bucket can incur charges and is not
authorized by a read-only `terraform plan`.

Before the separately approved deployment:

1. Use a **dedicated, non-root deployment identity** with access limited to
   the StrokeSense stack and a separate state bucket. Do not create root
   access keys; browser/SSO-based temporary credentials are preferred.
2. Obtain explicit approval to create a dedicated private S3 **state bucket**
   in `us-east-1`, outside this stack. Enable Block Public Access, versioning,
   server-side encryption, and narrowly scoped read/write permissions for
   `strokesense/aws-dev/terraform.tfstate` and its `.tflock` object. Restrict
   state access to the deployment role and trusted maintainers.
3. With Terraform **1.10+**, copy `backend.s3.tf.example` to the ignored
   `backend.tf` and replace the placeholder with that precreated bucket name.
   The template sets `encrypt = true` and `use_lockfile = true`; S3-native
   locking avoids creating a second DynamoDB lock table.
4. From `infra/aws`, run `terraform init -reconfigure` if no state exists, or
   review `terraform init -migrate-state` if a local state already exists.
   Inspect the backend and IAM settings before any write to AWS. Do not
   disclose state files, `terraform show -json`, or saved plan files publicly.

Only use `terraform init -backend=false` for local, backend-free checks before
the approved S3 state bucket exists. The sample backend file is ignored by
Terraform until deliberately copied to `backend.tf`.

**The CPU worker passed an isolated AWS Batch smoke test.**
`strokesense/aws_app/worker.py` streams bounded S3 input, runs the existing
Render CPU command (10 FPS, 2 threads, bounded media), and verifies measured
HTML/JSON artifacts before publishing the private `report.json` success
marker. `strokesense/Dockerfile.aws-cpu` installs inference dependencies and
FFmpeg and bakes the integrity-checked ONNX model into a non-root image.
The benchmarked Docker image was pushed to private ECR and processed an
authorized 239-frame rowing clip successfully on November 19, 2026, producing
a private S3 report. This does not by itself validate public Cognito-to-report
flows, concurrency or rate caps; review those separately before enabling the
public queue. The API reconciles failed Batch state when
the user polls job status. The scheduled
`aws_app.reconcile` Lambda independently checks overdue upload reservations and
Batch jobs every 15 minutes; failed jobs are refunded transactionally even
when a user closes the tab. Ambiguous `submitting` transitions are **flagged
for operator review**, not blindly refunded, to avoid a concurrent paid job.
The separate Batch failure EventBridge rule sends an operations alert; it does
not perform quota reconciliation itself. Integration tests against real AWS
services are still required before production use.

### Operator-only CPU smoke test before public rollout

Terraform creates the ECR repository in the same stack as the Batch job
definition, so the first apply cannot reference an image already uploaded
to that new repository.

1. **Before any AWS write:** build `strokesense/Dockerfile.aws-cpu` locally
   and benchmark a permission-cleared rowing clip at 2 vCPU / 4 GiB.
   Unit tests with simulated S3 do not replace this real-video benchmark.
   On Windows, the repository includes a non-deploying PowerShell preflight:
   `./infra/aws/benchmark-cpu-worker.ps1 -VideoPath 'C:\path\to\rowing.mp4'`
   from the repository root. It builds `linux/amd64` and refuses to pass
   unless the container produces an HTML report and real stroke metrics.
2. **With separate deployment approval:** create the encrypted remote-state
   bucket and apply Terraform with `enable_cpu_analysis=false`. The API
   refuses analysis submissions and the Batch queue stays disabled.
3. **With separate image-push approval:** publish the benchmarked image to
   the new ECR repository using a unique version tag/digest.
4. **For an isolated one-job smoke test:** set `worker_image_tag` to the
   tested image tag, `cpu_max_vcpus=2`, `enable_cpu_smoke_queue=true` and
   **keep `enable_cpu_analysis=false`**. Review and apply the plan. The Batch
   queue can run an operator-submitted job, but the public Lambda still has
   `CPU_BATCH_JOB_QUEUE=""` and rejects all analysis submissions. Never
   set the public flag just to run a smoke test.
5. Use an authorized clip uploaded privately to S3 and submit exactly one
   Batch job as the deployment administrator. Verify the Batch exit status,
   CloudWatch logs and ownership-scoped S3 `report.json`, then return
   `enable_cpu_smoke_queue=false`. No public visitor can submit jobs during
   this test. The 2-vCPU limit constrains concurrency, **not total job count**;
   never leave a manual test loop running unattended.
6. **Public launch is a separate decision:** implement and verify an
   account-wide admission/spending guardrail before setting
   `enable_cpu_analysis=true`. Per-user byte quotas and AWS Budgets alert
   emails alone do not impose a hard dollar cap.

The initial AWS-dev infrastructure already exists. Continue using its
configured encrypted S3 Terraform backend; never initialize a separate local
state or re-create existing resources. Run `terraform validate` and review a
fresh `terraform plan -out` against the current remote state before any apply.

## API contract and frontend configuration

All video, account, analysis and report routes require Cognito JWT authorization
at API Gateway *and* server-side ownership checks in Lambda. Only `GET /health`
and `POST /feedback` are public:

| Method | Route | Purpose |
| --- | --- | --- |
| POST | `/uploads/start` | Validate quota and content size; reserve bytes; start S3 multipart |
| POST | `/uploads/part` | Authorize one multipart part; return short-lived S3 PUT URL |
| POST | `/uploads/complete` | Validate all signed parts and finalize object |
| POST | `/uploads/abort` | Cancel multipart upload and refund reserved bytes |
| POST | `/analysis/jobs` | Submit one idempotent CPU Batch job |
| GET | `/analysis/jobs/{id}` | Fetch own job state and reconcile Batch completion/failure |
| GET | `/reports/{id}` | Return short-lived link only for own unexpired report |
| GET | `/health` | Public no-user-data liveness check |
| POST | `/feedback` | Public 1–5 usability rating, optional ≤1000-character comment; no user/video records exposed |

`/feedback` has 1 request/second API Gateway route throttling (burst 4), plus
atomic DynamoDB caps of 10 submissions/source IP/day and 100 globally/day.
The source IP is hashed and used only for a short-lived daily rate counter;
feedback entries store no raw source IP, account ID or email and expire after
approximately 90 days. There is no public feedback-reading API.

After infrastructure deployment the `terraform output` values are the
appropriate frontend *public* environment settings:

- `api_base_url` → `STROKESENSE_AWS_API_URL`.
- `cognito_domain` → `STROKESENSE_COGNITO_DOMAIN`.
- `cognito_user_pool_client_id` → `STROKESENSE_COGNITO_CLIENT_ID`.
- `aws_region` and `cognito_user_pool_id` → corresponding public client values
  if the OAuth client requires them.

The website build uses `STROKESENSE_ENABLE_CPU_ANALYSIS=false` as a separate
browser-side safety gate. Set it to `true` and redeploy the AWS-dev Vercel
project **only after** AWS compute is enabled and verified. It also accepts
`STROKESENSE_ENABLE_DEEP_ANALYSIS=false`, which must stay false until the
paid GPU path is explicitly implemented. The current
AWS-dev frontend completes Google sign-in on `/demos/`; all callback URLs above
are exact `/demos/` paths, not the root domain.

Use **exact** development and localhost origins for S3 and API CORS; preview
deployment URLs need an explicit additional origin, not wildcard CORS. Never
place the Google client secret, AWS access keys, paid-credit privileges, or
quota counters in a Vercel public variable.

Presigned multipart URLs are returned by AWS (the frontend must use the full
returned URL, whether its S3 hostname is regional or global). The Lambda is
configured to prefer the regional S3 endpoint in `us-east-1`; S3 CORS applies
to the browser's Vercel origin, and exposes `ETag` for completed multipart parts.

## Google OAuth setup

The Google OAuth **Web application** authorized redirect URI must equal:

```
https://strokesense-dev-<AWS_ACCOUNT_ID>.auth.us-east-1.amazoncognito.com/oauth2/idpresponse
```

The domain is `${cognito_domain_prefix}-<AWS_ACCOUNT_ID>` (default prefix
`strokesense-dev`). It deliberately does not reuse the `strokesense-aws-dev`
resource prefix: Cognito rejects domain prefixes containing `aws`, `amazon` or
`cognito`, and the variable validation enforces this at plan time. After apply,
copy `terraform output google_oauth_redirect_uri` verbatim into Google. Also
list `amazoncognito.com` under the OAuth consent screen's authorized domains.

The Cognito user pool domain uses **classic hosted UI** (`user_pool_tier =
"LITE"`, `managed_login_version = 1`) because social federation works on the
Lite plan; managed login requires Cognito Essentials/Plus. The web client uses
the **code grant with PKCE** and has **no client secret**. AWS/Cognito holds
the Google OAuth client secret; the browser does not. Google IdP maps the
provider's email and `email_verified` attributes. Review Google OAuth consent
screen/testing audience and the real SPA redirect path before deployment.

## Lambda reserved concurrency

AWS always keeps at least 10 concurrent executions unreserved per account and
region. New accounts often have a total Lambda concurrency quota of 10, so any
reserved concurrency fails with a quota error. Both Lambdas therefore default
to unreserved (`-1`):

| Variable | Default | Intended value after quota increase |
|---|---|---|
| `api_reserved_concurrency` | `-1` | `10` (API cost/abuse ceiling) |
| `reconcile_reserved_concurrency` | `-1` | `1` (no overlapping reconciler runs) |

While unreserved, requests are rate-limited by the HTTP API stage
(20 req/s, burst 40), plus a stricter feedback-only route limit
(1 req/s, burst 4). JWT authorization protects every route except
`GET /health` and `POST /feedback`. These limits reduce abuse but are
not account spending caps. Check the quota with
`aws lambda get-account-settings`. Once the Service Quotas "Concurrent
executions" value (`L-B99A9384`) is raised, set the variables (for example
`TF_VAR_api_reserved_concurrency=10`) and run a reviewed plan/apply.

## Local-only preparation (no AWS changes)

1. Install Terraform 1.10+ (needed for S3-native backend lockfiles), AWS
   provider 6.37–6.x, Python, `pip`, and `zip`.
2. From `infra/aws`, review `terraform.tfvars.example`, Vercel CORS origins,
   Cognito callback/logout routes, the `vpc_id` and **public** `subnet_ids`.
   The default VPC is used if IDs are omitted, but check that every selected
   subnet has a working Internet Gateway route; private subnets without NAT
   cannot pull the container image or call S3.
3. Keep the Google secret outside source control and shared output. Example:

   ```bash
   export TF_VAR_alert_email='you@example.com'
   export TF_VAR_google_oauth_client_id='your-google-web-client-id'
   # Load TF_VAR_google_oauth_client_secret from a private secret manager.
   # Never echo it, commit it, or pass it on a public CLI command line.
   ```

4. Run the backend unit tests from `strokesense/` with `python -m unittest
   discover -s aws_app -p 'test_*.py'`, and build a local Lambda ZIP from the
   repo root using `bash infra/aws/build_lambda.sh`, or on Windows PowerShell
   using `./infra/aws/build_lambda.ps1`.
   The `aws-dev` GitHub Actions workflow also checks backend tests, frontend
   tests/build and Terraform formatting/validation without AWS credentials.
5. In `infra/aws`, run `terraform fmt -check -recursive`, `terraform init
   -backend=false`, and `terraform validate`. Review `terraform plan` only
   with appropriate AWS read-only credentials and after provider installation.
6. The operator-only worker smoke test is complete. **Do not enable public
   analysis or apply unreviewed infrastructure changes** until verifying the
   global 5/day and 50/month admission caps, the 10-vCPU five-job ceiling,
   refund behavior, cost alerts, and browser-to-report flow. Keep paid/GPU
   processing disabled.

Local `.tfstate` and `.tfvars` are ignored by Git but remain recoverable on
the local disk. Do not put secrets into `.tf` or example files; follow the
secure state procedure above before any actual deployment.

## Cost and safety notes

- With zero submitted jobs, no Fargate workers consume vCPU/RAM, but storage,
  ECR image retention, HTTP API/Lambda requests, DynamoDB reads/writes,
  logs/alarms, and Cognito usage can still incur small charges. SNS alerts
  and the selected Cognito plan can have usage-based fees.
- Fargate bills for time spent starting and running containers and transferring
  data; the 3-minute existing Render benchmark is **not** guaranteed on a
  2-vCPU/4-GiB Fargate task. 750 MB video input does not establish inference
  runtime; duration, frame count, decoding and AI model complexity do.
- Default 10 max vCPUs permits **up to five parallel 2-vCPU workers** (if AWS
  Fargate account quotas permit). This caps concurrent CPU capacity, not total
  monthly cost. DynamoDB admission limits separately bound all public CPU
  submissions to 5 per UTC day and 50 per UTC month; the 1-hour per-attempt
  timeout is a backstop, not a dollar cap.
- Both account-wide budgets use gross cost (before credits), with
  `daily_budget_usd = 3` and `monthly_budget_usd = 30`. The email recipient
  is required, but alerts remain delayed and do not enforce a hard spend cap.
  Check AWS Free Plan expiration and eligible credit coverage before deployment.
- S3 lifecycle expiration is asynchronous. The API must deny report access at
  its exact 72-hour or 30-day deadline, regardless of physical deletion time.
- 750 MB uploads need multipart upload and S3 direct transfer; incomplete
  uploads incur storage until aborted or cleaned up. Explicitly handle upload
  failures/browser tab closure and stale quota reservations.

## Production acceptance checklist

- [ ] Actual model pipeline produces a valid distinct report for uploaded
      user-owned clips and never reports success without output.
- [ ] Free 300 MB lifetime limit works with concurrent browser sessions;
      failed/aborted/expired uploads and failed jobs refund deterministically.
- [ ] Global CPU limits reject a sixth submission on the same UTC day and a
      51st in the same UTC month, including across separate Cognito accounts;
      five 2-vCPU jobs do not exceed the 10-vCPU compute cap.
- [ ] Anonymous `/feedback` accepts 1–5 ratings and optional comments, safely
      rejects malformed/spam submissions, and cannot expose private feedback.
- [ ] Expired report downloads return a useful 4xx message; own reports work,
      other users' job IDs never grant access to another report.
- [ ] 750 MB paid uploads and paid-credit ledger are implemented and tested;
      paid route stays closed until billing is truly connected.
- [ ] Separate AWS-dev Vercel project uses PKCE, exact redirect URIs, no
      shared/cross-user data, and strict CORS.
- [ ] Real video benchmarking, Fargate network/S3 transfer, load/concurrency,
      container CPU/memory limits, retry behavior and cost alerts are tested.
- [ ] Quota reconciliation runs even when the user never polls; CloudWatch
      monitoring identifies idle stuck reservations and job failures.
- [ ] AWS account spending controls, verified billing alert recipient, Free Plan
      expiry and credit expiration,
      account plan, and GPU hardware costs are approved before charges.
