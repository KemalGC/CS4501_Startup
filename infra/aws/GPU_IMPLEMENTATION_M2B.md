# GPU milestone 2B — durable outbox and terminal reconciliation (staged)

**No AWS deployment, GPU instance, charge, or customer payment is enabled.**
This milestone lives only in draft PR #163 on
`aws-paid-gpu-integration-prep-20261120`.

## What is implemented

- `gpu_queued_at` is recorded on paid job enqueue. An outbox recovery routine
  queries only due `gpu_queued` records using the existing
  `status-expires_at-index`, then re-reads each record from DynamoDB with
  `ConsistentRead=True` before taking any action.
- Lost/ambiguous SQS FIFO sends are replayed using only an opaque, server
  generated job ID and an interval-based deduplication ID. Replays after 24h
  are **manual review only**, avoiding unsafe retries after ECS's idempotency
  window. The library of paid GPU queue consumers still requires active
  membership and server-authorized S3 keys.
- ECS dispatcher writes `gpu_dispatch_started_at` at the beginning of a
  possible task launch. Existing ambiguous `gpu_dispatching` states are
  never blindly relaunched by the scheduled reconciler. Direct retry under
  the original ECS client token must be within 23h or fails closed.
- Submitted GPU tasks now have separate `expires_at` (next poll) and
  `gpu_task_deadline_epoch` (maximum permitted task duration). A scheduled
  reconciler can check STOPPED tasks approximately every 15 minutes, then
  consume/refund a paid credit with the existing one-time transaction.
- A task still RUNNING is rescheduled. Tasks whose deadline passes without
  confirmed STOPPED/exit code are flagged for manual review; **no credit is
  guessed/refunded and no slot is released**. Duplicate queue messages after
  terminal settlement are safely acknowledged rather than poisoning the FIFO.
- `gpu_recovery.tf` optionally declares a separate 15-minute EventBridge
  rule, Lambda, and narrowly scoped IAM. Every resource is guarded by the
  pre-existing scaffold flag, which defaults **false**; additionally the
  EventBridge rule has `state = "DISABLED"` and the Lambda env has
  `GPU_RECONCILE_ENABLED = "false"`. Its IAM explicitly excludes task
  launch/stop permissions and payment administration.
- New Python and frontend configuration regression tests cover outbox
  replay, stale GSI results, one-task FIFO safety, duplicate terminal
  settlement, zero-cost defaults and forced manual review.

## Missing before enabling

This is still NOT a complete recoverable paid pipeline:
- No approved GPU ECS cluster, running CUDA image, hardware capacity provider
  or trusted subscription billing.
- No live SQS producer or event-source mapping enabled, and no GPU reconcile
  schedule enabled. Public API blocks paid jobs.
- No automatic cancellation of a hung GPU task: an operator must verify the
  ECS state. Future capacity rollout requires a bounded StopTask strategy
  and a documented escalation path.
- No paid report frontend/schema compatibility or 30-day retention QA.
- No live AWS GPU/VRAM benchmark or cost-per-video measurement.
- No production alerting on GPU dead-letter queue/manual-review counters.

## Local, zero-cost verification

```powershell
cd C:\Users\kemal\IdeaProjects\CS4501_StartupAws
git pull --ff-only
cd strokesense
py -m unittest aws_app.test_gpu_preparation aws_app.test_gpu_worker aws_app.test_gpu_dispatcher aws_app.test_gpu_lifecycle aws_app.test_gpu_queue_handler aws_app.test_gpu_recovery
cd ..\infra\aws
terraform fmt -check
terraform validate
```

**Do not run `terraform apply` or flip GPU/paid flags.** Queue scaffold
`enable_paid_gpu_queue_scaffold` must remain false unless explicitly
reviewed and authorized. Even when a scaffold is created, its triggers
remain disabled and compute is not provisioned.

AWS reference: SQS FIFO dedupe is five minutes; ECS RunTask clientToken
idempotency is at most 24 hours. These windows motivate the replay design.
