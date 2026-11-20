# Paid GPU implementation — milestone 1

Code-only implementation; no paid users, GPU compute or billing enabled.

## Implemented on the GPU feature branch

- Dedicated paid GPU worker under strokesense/aws_app/gpu_worker.py with strict owner-scoped S3 paths, pinned-model verification, CUDA preflight, 750 MB input cap, and real StrokeSense CLI processing.
- Strict CUDA ONNX execution in strokesense/strokesense/pose.py. Trusted STROKESENSE_REQUIRE_CUDA=1 forbids CPU graph-node fallback and runtime fallback. CPU worker retains its old behavior.
- GPU dispatcher with FIFO message enqueue helper, deterministic ECS RunTask clientToken, approved digest-pinned task and GPU=0.125 validation, and a one-job DynamoDB capacity lock. Not wired into the live API.
- GPU lifecycle settlement waits for ECS STOPPED and a valid final S3 report before consuming or refunding a reserved paid credit. Lock release follows settlement.
- A separate prototype Dockerfile with an operator-supplied SHA256-pinned CUDA+cuDNN runtime image and ONNX Runtime GPU. Requires actual image/hardware tests.
- Offline tests for isolation, CUDA enforcement, ECS idempotency, one-job lock, private artifacts and membership/credit checks.

## What is NOT yet working/live

- This starts from the existing YOLO11n ONNX baseline accelerated by CUDA; it is not a more accurate premium model yet.
- No verified G6f GPU run, model benchmark, CUDA/cuDNN compatibility test, credit provider, checkout, SQS FIFO, ECS capacity provider, dispatcher Lambda or paid status UI.
- No AWS instances or other paid resources provisioned. Terraform enable_gpu stays false and refuses true.
- Backend PAID_BILLING_ENABLED and PAID_GPU_ENABLED remain false, GPU_DISPATCH_READY unset; paid uploads/jobs remain blocked.
- A 750 MB paid upload limit does not lift the existing CLI 180-second clip bound or 120 MB annotated-video limit.

## Next gates before enabling GPU/paid memberships

1. Pin and scan CUDA image digest and Python dependencies. Benchmark the model on a reviewed GPU and measure actual CUDA utilization, VRAM (<3 GB), latency, throughput and result quality.
2. Wire dedicated SQS FIFO/DLQ, durable enqueue retries, ECS GPU capacity scheduling and a max-one-task limit, with operator-approved scaling to zero and no NAT gateway.
3. Wire the paid lifecycle reconciler and verify idempotent credit consume/refund for success, failure, ambiguous network returns and interrupted jobs.
4. Add owner-scoped paid report/artifact UI support and 30-day retention tests.
5. Integrate a verified payment provider and idempotent subscriptions mapped to immutable Cognito sub IDs. No browser-supplied entitlement claims.
6. Require explicit authorization before creating GPU resources, collecting payments or enabling Deep Analysis.

## Offline test command

From strokesense/: python -m unittest aws_app.test_backend aws_app.test_gpu_preparation aws_app.test_gpu_worker aws_app.test_gpu_dispatcher

These tests do NOT run real GPU inference. Current free CPU AWS production is unaffected.
