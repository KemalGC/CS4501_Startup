# StrokeSense AWS development infrastructure (Terraform)

**No AWS resources have been created.** This directory describes a proposed
isolated `aws-dev` environment in `us-east-1`. The existing Vercel/Render live
deployment must remain untouched. **Do not run `terraform apply` until the real
inference adapter, cost controls, Google OAuth registration, and account billing
plan have been explicitly reviewed and approved.** A Terraform plan itself
does not provision resources, but it can require AWS account read access.

## Architecture

1. **Vercel** (separate `strokesense-aws-dev.vercel.app` project): static SPA;
   users sign in with Google via **Amazon Cognito User Pools**, OAuth 2.0
   authorization code with PKCE, then present a Cognito JWT to API Gateway.
2. **API Gateway HTTP API** validates Cognito JWTs for all user operations;
   a small **Lambda** owns sessions, upload integrity, records, quotas,
   short-lived presigned S3 URLs, Batch submission and status polling.
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
   is 6 vCPUs (at most 3 simultaneous jobs, subject to AWS quotas). Docker
   images live in private **ECR**. S3 is the source of truth for reports.
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

**The worker is not functional yet.** `strokesense/aws_app/worker.py` is a
deliberate fail-closed stub: every Batch job exits nonzero and does not create
a fake report. Integrate and benchmark the existing ONNX/llama-cpp pipeline
with S3 input/output in a CPU container before applying this stack, and make
the worker check real report output before returning success. The API
reconciles failed Batch state when the user polls job status. The scheduled
`aws_app.reconcile` Lambda independently checks overdue upload reservations and
Batch jobs every 15 minutes; failed jobs are refunded transactionally even
when a user closes the tab. Ambiguous `submitting` transitions are **flagged
for operator review**, not blindly refunded, to avoid a concurrent paid job.
The separate Batch failure EventBridge rule sends an operations alert; it does
not perform quota reconciliation itself. Integration tests against real AWS
services are still required before production use.

## API contract and frontend configuration

All routes besides `GET /health` require Cognito JWT authorization at the
API Gateway layer *and* server-side ownership checks in Lambda:

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

After infrastructure deployment the `terraform output` values are the
appropriate frontend *public* environment settings:

- `api_base_url` → `STROKESENSE_AWS_API_URL`.
- `cognito_domain` → `STROKESENSE_COGNITO_DOMAIN`.
- `cognito_user_pool_client_id` → `STROKESENSE_COGNITO_CLIENT_ID`.
- `aws_region` and `cognito_user_pool_id` → corresponding public client values
  if the OAuth client requires them.

The website build also accepts `STROKESENSE_ENABLE_DEEP_ANALYSIS=false`, which
must stay false until the paid GPU path is explicitly implemented. The current
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
https://strokesense-aws-dev-<AWS_ACCOUNT_ID>.auth.us-east-1.amazoncognito.com/oauth2/idpresponse
```

The Cognito user pool domain uses **classic hosted UI** (`user_pool_tier =
"LITE"`, `managed_login_version = 1`) because social federation works on the
Lite plan; managed login requires Cognito Essentials/Plus. The web client uses
the **code grant with PKCE** and has **no client secret**. AWS/Cognito holds
the Google OAuth client secret; the browser does not. Google IdP maps the
provider's email and `email_verified` attributes. Review Google OAuth consent
screen/testing audience and the real SPA redirect path before deployment.

## Local-only preparation (no AWS changes)

1. Install Terraform 1.6+ (AWS provider 5.98–6.x), Python, `pip`, and `zip`.
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

4. Run the backend unit tests from the repo root (`PYTHONPATH=strokesense
   python -m unittest aws_app.test_backend`), and build a local Lambda ZIP from the
   repo root using `bash infra/aws/build_lambda.sh`.
   The `aws-dev` GitHub Actions workflow also checks backend tests, frontend
   tests/build and Terraform formatting/validation without AWS credentials.
5. In `infra/aws`, run `terraform fmt -check -recursive`, `terraform init
   -backend=false`, and `terraform validate`. Review `terraform plan` only
   with appropriate AWS read-only credentials and after provider installation.
6. Do **not** push a worker image, create a Vercel production deployment, or
   run `terraform apply` before implementing the worker, verifying quota/refund
   behavior end to end, accepting an AWS spend limit/billing plan and getting
   explicit approval.

Terraform state contains Google OAuth credentials and other sensitive values.
Protect state with an encrypted, access-controlled backend for any actual
deployment; local `.tfstate` and `.tfvars` are ignored by Git but remain
recoverable on the local disk. Do not put secrets into `.tf` or examples.

## Cost and safety notes

- With zero submitted jobs, no Fargate workers consume vCPU/RAM, but storage,
  ECR image retention, HTTP API/Lambda requests, DynamoDB reads/writes,
  logs/alarms, and Cognito usage can still incur small charges. SNS alerts
  and the selected Cognito plan can have usage-based fees.
- Fargate bills for time spent starting and running containers and transferring
  data; the 3-minute existing Render benchmark is **not** guaranteed on a
  2-vCPU/4-GiB Fargate task. 750 MB video input does not establish inference
  runtime; duration, frame count, decoding and AI model complexity do.
- Default 6 max vCPUs caps **parallel CPU capacity**, not total monthly cost;
  the 1-hour per-attempt timeout is a backstop, not a budget limit.
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
