# Milestone 3 — Operator-only GPU EC2 smoke activation (NOT APPLIED)

This supersedes the 2C permanent-disable note for an isolated manual NVIDIA
preflight. Paid Deep Analysis remains disabled, and PR #163 remains a DRAFT.

### What changed

- `enable_gpu=false` is still the default. Setting it true now requires all
  of `gpu_smoke_mode=true`, `enable_gpu_image_repository=true`,
  `gpu_smoke_approval="I_APPROVE_ONE_G6F_SMOKE_INSTANCE"`, and all CPU/paid
  public queue switches OFF. Do not use this acknowledgement until the operator
  has reviewed cost and is prepared to run one billable test.
- A private immutable GPU ECR repository may be created independently using
  `enable_gpu_image_repository=true`, while `enable_gpu=false`. No EC2.
- ECS-on-EC2 GPU resources are review-only by default. When deliberately
  provisioned, the ASG has min=0, desired=0, max=1, g6f.xlarge On-Demand,
  with ECS managed scaling DISABLED for the smoke; no task is run by apply.
- A separate GPU=0.125 preflight task executes CUDA ONNX validation only, with
  NO customer S3/DynamoDB task role or job overrides. The paid worker
  task/queue trigger and account billing remain inactive.
- Operator-only `gpu-smoke.ps1` verifies account/ASG/task identity,
  schedules a ONE-TIME AWS Auto Scaling cutoff for max/min/desired=0 before
  launching, scales to exactly one instance, runs the CUDA preflight, and
  scales back to zero in finally. Default cutoff is 45 minutes.
  This is a scheduled shutdown guard, NOT a dollar-denominated billing cap.
- The GPU host has an 80 GiB encrypted, delete-on-termination gp3 root volume.
  GPU worker containers have no public IP; a reviewed S3 Gateway VPC endpoint
  serves their private media paths. No NAT gateway is created.

### Review before any real apply

1. Confirm AWS account, us-east-1 **g6f.xlarge On-Demand quota/AZ inventory**,
   actual On-Demand price and any EBS/ECR/S3 charges. Public estimate as of
   Nov 2026 is about $0.2375 per hour for EC2 compute only.
   AWS Budgets are delayed alerts, NOT a hard AWS bill cap.
2. Confirm the intended public subnet, its route table, an available task ENI
   and the S3 Gateway endpoint route. Check quota for 1 G-family instance.
3. Obtain and audit a matching SHA256-pinned CUDA/cuDNN Linux x86_64 base
   image and dependency lock (onnxruntime-gpu, CUDA, cuDNN compatibility).
   NEVER guess or invent a digest. The Dockerfile requires `CUDA_BASE_IMAGE`.
4. First use the existing encrypted Terraform backend to plan and apply ONLY
   the image repository:
   - `enable_gpu_image_repository=true`
   - `enable_gpu=false`, `gpu_smoke_mode=false`
   Inspect every planned change before apply.
5. From the repository `strokesense/` directory, build and scan the reviewed
   `Dockerfile.aws-gpu` for linux/amd64, push to the private ECR repo, read
   the ECR `imageDigest` and construct
   `<ECR_REPO_URL>@sha256:<verified-digest>`. Confirm the model and CUDA
   libraries are built into the image. Do not push credentials to GitHub.
6. For a SEPARATE reviewed GPU infrastructure plan, set
   `enable_gpu=true`, `gpu_smoke_mode=true`,
   `enable_gpu_image_repository=true`, and the approval token, reviewed
   `gpu_subnet_id`, `gpu_s3_route_table_ids`, and digest-pinned
   `gpu_worker_image_uri`. Keep `enable_paid_gpu_queue_scaffold=false`,
   `enable_cpu_analysis=false`, `enable_cpu_smoke_queue=false`.
   Review `terraform plan -out=gpu-smoke.tfplan` before applying that exact
   plan. This creates cost-bearing infrastructure resources (EBS only after
   instance launch); the EC2 ASG itself is initially at zero.
7. ONLY after direct approval for the billable hardware run:
   `.\gpu-smoke.ps1 -ExpectedAccountId 123456789012 -ApproveCharge`
   (replace the account ID). This script must run from Windows PowerShell
   with AWS CLI v2, working Terraform output/state, and correct AWS privileges.
   It creates the AWS cutoff before starting the one host.
8. Inspect CloudWatch logs and task exit code. After success or failure,
   check EC2 instance termination, ASG max=0/desired=0, and billing. The
   operator script deliberately leaves max=0 after cleanup so another test
   cannot accidentally re-launch without a separately reviewed plan.

### Important limitations

- This does NOT run an actual rowing video or prove quality/performance.
  The real pose+LLM pipeline must be benchmarked on 3 GB VRAM before paid
  analysis, along with report/UI schema, authorization and refund checks.
- The GPU image may not build or fit 3 GB VRAM until CUDA dependencies and
  memory use are validated. No built image or tested NVIDIA inference yet.
- This is an operator-only smoke test, not an always-on GPU production
  service. The one-instance cap is not an AWS dollar cap.
- Do NOT enable SQS dispatch, paid Lambda flags, payments, or merge the draft
  PR as part of this smoke test.
- AWS scheduled ASG shutdown is a best-effort infrastructure guard; operator
  must still verify no running instances and that no other user changed ASG.
- Do not run Terraform apply at the same time as the smoke test, because it
  could undo the ASG max=0 scheduled emergency cutoff.

References: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-gpu-specifying.html
https://docs.aws.amazon.com/AmazonECS/latest/developerguide/managed-scaling-behavior.html
https://docs.aws.amazon.com/autoscaling/ec2/userguide/scheduled-scaling-create-scheduled-action.html
