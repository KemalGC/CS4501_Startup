# StrokeSense paid GPU integration — gated Phase 0

**Status as of November 20, 2026:** This is *preparation only*. It creates no GPU
instances, GPU ECS capacity provider, payment endpoints, subscription products,
API routes, or running tasks. Existing free CPU analysis is unchanged. The
existing Terraform flag `enable_gpu` must remain `false` and still rejects
`true`. Never set `PAID_GPU_ENABLED`, `GPU_DISPATCH_READY`, or
`PAID_BILLING_ENABLED` until the entire paid lane is independently tested
and billing is explicitly approved.

## Chosen target (not yet benchmarked)

- **Candidate hardware:** one ECS G6f partition on `g6f.large`: **2 vCPU,
  8 GiB system RAM, and 1/8 NVIDIA L4 / 3 GiB VRAM**.
- **Scheduler candidate:** Amazon ECS on EC2 or ECS Managed Instances, with
  `resourceRequirements: [{ "type":"GPU","value":"0.125" }]`. ECS Fargate
  **does not support fractional GPU**. Do not assume AWS Batch Fargate
  schedules fractional GPUs. Start with an operator-initiated smoke task;
  evaluate scale-to-zero and minimum billing before choosing either ECS
  capacity provider.
- **Task draft:** `infra/aws/gpu-task-definition.example.json` is an intentionally
  non-deployable **preflight-only** task spec. It is not a GPU analyzer.
- **GPU readiness probe:** `python -m aws_app.gpu_preflight --model
  /app/models/yolo11n-pose.onnx` checks exactly one GPU partition,
  reports enough free VRAM, and requires ONNX Runtime's CUDA provider to
  be the first active provider for the model. It does **not** prove end-to-end
  GPU inference performance and never accepts silent CPU-only fallback.
- **Model:** Baseline existing YOLO pose ONNX model for comparison; a
  premium-quality model (and optional quantized LLM) must be **chosen and
  benchmarked separately**. GPU acceleration alone does not improve the
  coaching predictions. Verify actual CUDA kernel utilization, VRAM, FPS,
  output quality, driver/CUDA/cuDNN/ORT compatibility, and model licensing.
  3 GiB VRAM may not fit the desired larger pose+LLM combination.

Official references:
- https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-gpu-specifying.html
- https://docs.aws.amazon.com/AmazonECS/latest/developerguide/managed-instances-gpu.html
- https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_definition_parameters_ec2.html

## Membership/billing security contract prepared in code

The users table stores candidate backend-owned fields:
`paid_membership_status` (`active`), `paid_membership_expires_at` (Unix UTC
seconds), and existing `paid_credits_available/reserved/used`.

The preparation adds three fail-closed runtime switches:
1. `PAID_BILLING_ENABLED`: **false** in Terraform.
2. `PAID_GPU_ENABLED`: **false** in Terraform.
3. `GPU_DISPATCH_READY`: **absent/false** in production (no GPU dispatcher).

All must be true *before* a paid upload is even eligible. In that future
scenario, the backend re-reads membership from DynamoDB using a strongly
consistent read; it checks active/not expired and at least one unused credit.
A paid-credit **reservation transaction checks membership and expiry again
atomically**, preventing a cancellation/expiry race. User-controlled JSON
fields, Google email, frontend toggles and claims do not grant paid access.

Critically, **all paid jobs are still rejected at `submit_analysis`**.
The free `CPU_BATCH_JOB_QUEUE` and global free-job counters cannot be used
to process a paid upload, even if an operator enables the above switches in
a test. A GPU dispatcher and idempotent billing reconciliation must be
implemented before lifting this hard stop.

**There is no verified payment webhook yet.** Do not directly grant
membership/credits in production. Do not accept billing state from the
browser. A future billing integration must verify the provider signature,
deduplicate immutable event IDs, map verified customers to immutable Cognito
`sub`, manage subscription expiration/renewal/refunds, handle webhook
out-of-order delivery and retries, and use conditional credit writes. No
payment or membership entitlement is activated in this PR.

## Proposed future paid job flow (not implemented)

```
verified payment webhook -> DynamoDB membership/credits
Cognito JWT -> API -> strong membership check -> private S3 multipart upload
   -> one atomic credit reservation + one durable paid admission record
   -> dedicated paid SQS queue (idempotent dispatch key / DLQ)
   -> ECS GPU task (one job at a time, bounded deadline, owner-validated S3)
   -> actual CUDA ONNX inference + optional GPU-compatible LLM
   -> private report and annotated MP4 written last
   -> EventBridge/SQS completion reconciler consumes or refunds credit once
   -> per-user My Analyses + expiry (current paid retention setting: 30 days)
```

Do **not** use the existing CPU Batch job definition as the paid dispatcher.
Do not use a manual DynamoDB credit field write to simulate an actual paid
purchase outside isolated test fixtures.

## Next implementation gates

1. **Select paid model**: compare CPU YOLO baseline, CUDA YOLO, and optional
   larger model; record model version and stable output schema. Determine if
   3 GiB is enough; if not, change instance type before provisioning.
2. **Local GPU smoke**: build reproducible `linux/amd64` CUDA/ORT pinned
   image, run preflight on an explicitly approved GPU host, then run one
   representative private training clip. Save timing, VRAM peak and GPU
   utilization; ensure the process refuses to run if CUDA fails.
3. **Infrastructure approval**: operator reviews EC2/ECS choices, scale-to-zero
   behavior, idle cost, IAM isolation, ECR scanning, CloudWatch alarms, and
   a Terraform plan with **zero unintended changes to free CPU resources**.
   Budget alerts are **not hard spending caps**. Avoid NAT gateways.
4. **Durable paid queue and reconciliation**: one claimed task per paid video,
   deduplicated dispatch, retries, crash handling, expiry, no duplicate GPU
   billing, and atomic consume/refund. Prove concurrent and interrupted cases.
5. **Verified membership + actual payments**: choose billing provider and
   pricing, build signed-webhook handling/idempotency, test subscription expiry,
   refunds/chargebacks, cancellation, credit balances, and safe account mapping.
6. **User experience & security**: paid-only GPU job routing, transparent
   pricing, terms, upload limit, no guaranteed performance claims, privacy
   and report retention; accessibility and mobile report/video tests.
7. **Explicit go-live approval**: only after all above, deploy guarded backend
   and confirm a zero/one-job smoke limit. Then separately enable paid checkout
   and the Deep Analysis button. Do not automatically flip any switch.

## Minimal no-cost verification

```bash
# Run from strokesense/ in the repo. Requires no GPU or AWS credentials.
python -m unittest aws_app.test_gpu_preparation
# To test on an APPROVED, already-running GPU machine later:
python -m aws_app.gpu_preflight --model /app/models/yolo11n-pose.onnx
```

The second command fails closed on ordinary CPU hosts.
