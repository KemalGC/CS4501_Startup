# Deferred paid Deep Analysis — fractional L4 GPU

**Not provisioned.** `var.enable_gpu` defaults to `false` and rejects `true`
until this lane has an approved implementation. We intentionally did not add
an untested `g6f.large` EC2 Auto Scaling Group and GPU ECS scheduling path to
an otherwise CPU-only deployment, because that could create billable EC2
instances or silently run a CPU inference pipeline on an idle GPU.

## Target design, pending benchmarking/approval

1. Separate **paid queue** and charged user-credit reservation; never mix
   free Batch jobs or their quotas with GPU jobs.
2. Build a CUDA-supported analysis container: ONNX Runtime CUDA Execution
   Provider (with correct CUDA/cuDNN versions) and properly GPU-offloaded
   llama.cpp/llama-cpp-python, when compatible with the desired model. Measure
   max VRAM against the **3 GB GPU memory** on `g6f.large` (1/8 of an L4).
3. Prefer a tested **ECS fractional-GPU task definition** requesting
   `resourceRequirements=[{type="GPU",value="0.125"}]` on G6f capacity.
   AWS documentation demonstrates this with ECS Managed Instances; for EC2
   capacity providers, verify launch AMI/drivers, placement, fractional GPU
   support, supported region/instance, and task state transitions firsthand.
4. Make GPU capacity zero while idle (min=0, desired=0, max=1 if an EC2 ASG
   is used), with exactly one paid task occupying each fraction/slice. Test
   **cold start**, idle teardown, and the provider's ability to scale from zero
   during ECS task placement. ECS Managed Instances may add a management fee.
5. Orchestrate tasks through a durable API/queue dispatcher with idempotent
   credit accounting and failure refund. Do not assume AWS Batch directly
   supports G6f fractional `GPU=0.125` job requirements simply because ECS
   supports that resource type. An EventBridge/SQS completion handler should
   reconcile finished/failed/stale jobs even when the browser is closed.
6. Benchmark on representative long/750 MB uploads and realistic concurrency;
   determine unit credits per job, max duration, and a hard application-side
   throughput ceiling before changing `PAID_GPU_ENABLED` or paid billing.

References:

- [Amazon ECS — specifying fractional GPUs](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-gpu-specifying.html)
- [Amazon ECS Managed Instances — GPU support](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/managed-instances-gpu.html)
- [Amazon ECS EC2 task definition parameters](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_definition_parameters_ec2.html)

**No actual user payment, GPU job, or AWS paid resource is authorized by this
planning document.**
