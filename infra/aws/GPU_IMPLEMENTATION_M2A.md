# GPU queue milestone 2A — staged only

**No AWS resources have been deployed.** This change remains in draft PR #163.
The site, free CPU Batch, and paid billing settings remain unchanged.

## New implementation

- `gpu_queue.tf` defines a dedicated, encrypted paid-GPU SQS FIFO queue plus a 14-day FIFO dead-letter queue. The DLQ allows only the source GPU queue.
- The Terraform flag `enable_paid_gpu_queue_scaffold` defaults to `false`; with defaults, every new GPU queue, IAM, Lambda and event-source mapping resource uses `count=0`.
- If an operator later explicitly opts into *the inert queue scaffold*, its SQS-to-Lambda event-source mapping is still created with `enabled=false` and the Lambda environment still sets `GPU_DISPATCH_ENABLED=false`, `PAID_GPU_ENABLED=false`, and `PAID_BILLING_ENABLED=false`.
- The isolated IAM role grants only queue receive/delete and DynamoDB get/update; it deliberately grants **no** `ecs:RunTask` or `iam:PassRole`.
- `gpu_queue_handler.py` implements one-message FIFO batches, fixed message group and queue ARN validation, job-ID-only messages, and partial-batch failures so bad or interrupted dispatches are retried rather than silently acknowledged.
- `test_gpu_queue_handler.py` covers valid/invalid messages, wrong source, injected identity/S3 fields, disabled Lambda and retry signals without AWS clients.

## Still missing before activation

1. Explicit approval and a reviewed Terraform plan for *any* AWS resources. No action is required merely to keep this PR ready.
2. An approved GPU ECS cluster/capacity provider/task with verified `GPU=0.125`, reviewed driver/CUDA/cuDNN compatibility and no idle GPU capacity.
3. Least-privilege ECS RunTask and iam:PassRole IAM additions scoped to approved task/roles only; currently intentionally omitted.
4. Durable recovery for messages accepted by AWS before an API timeout, plus safe retry of stale `gpu_queued` and `gpu_dispatching` jobs. Existing `enqueue_paid_analysis` returns an unconfirmed state but does not implement outbox replay.
5. A scheduled/event-driven reconciler to settle GPU credits and release capacity even when the client disconnects; current `gpu_lifecycle` is a callable module only.
6. Verified payments/subscriptions, credit grants, paid report frontend/permissions and end-to-end GPU benchmarks.

## Local verification (no AWS usage)

```powershell
cd C:\Users\kemal\IdeaProjects\CS4501_StartupAws\strokesense
py -m unittest aws_app.test_gpu_preparation aws_app.test_gpu_worker aws_app.test_gpu_dispatcher aws_app.test_gpu_lifecycle aws_app.test_gpu_queue_handler
```

Do not change `enable_gpu`, `enable_paid_gpu_queue_scaffold`, or the paid/billing flags without an explicit reviewed deployment. AWS budget alerts are not spending caps.
