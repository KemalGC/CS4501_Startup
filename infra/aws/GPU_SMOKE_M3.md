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
   `gpu_worker_image_uri`. Keep `enable_paid_gpu_queue_scaffold=false` and
   `enable_cpu_smoke_queue=false`. Keep every other variable at its
   **deployed** value (aws-dev runs `enable_cpu_analysis=true` with a pinned
   `worker_image_tag`); first prove the deployed baseline plans
   "No changes", then add only the GPU variables. Reject any plan that
   updates or replaces non-GPU resources.
   Review `terraform plan -out=gpu-smoke.tfplan` before applying that exact
   plan. This creates cost-bearing infrastructure resources (EBS only after
   instance launch); the EC2 ASG itself is initially at zero.
7. ONLY after direct approval for the billable hardware run:
   `.\gpu-smoke.ps1 -ExpectedAccountId 123456789012 -AwsProfile <profile> -ApproveCharge`
   (replace the account ID). It prints the preflight evidence line, timings
   and verifies EC2 termination. This script must run from Windows PowerShell
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
- The image builds and passes in-container checks, but NVIDIA inference has
  not run on real hardware yet (local Docker/WSL2 exposes no GPU adapter).
  3 GB VRAM fit is unproven until the AWS preflight runs.
- This is an operator-only smoke test, not an always-on GPU production
  service. The one-instance cap is not an AWS dollar cap.
- Do NOT enable SQS dispatch, paid Lambda flags, payments, or merge the draft
  PR as part of this smoke test.
- AWS scheduled ASG shutdown is a best-effort infrastructure guard; operator
  must still verify no running instances and that no other user changed ASG.
- Do not run Terraform apply at the same time as the smoke test, because it
  could undo the ASG max=0 scheduled emergency cutoff.

### Status 2026-11-20 (pre-apply; nothing billable created)

- **Image:** `strokesense-aws-dev-gpu-worker:gpu-smoke-20261120211125` →
  `sha256:9250535f526d3f0f686759b0c56acc511281c39d078343bc8e3e7c851651a208`
  (linux/amd64 OCI manifest, uid 10001, byte-identical to the locally built
  manifest). Base `nvidia/cuda:12.6.3-cudnn-runtime-ubuntu22.04@sha256:5f0d2d82…`,
  onnxruntime-gpu 1.20.2 (CUDA EP, no CPU onnxruntime), libcudnn.so.9,
  libcublas.so.12, pinned YOLO model re-verified as the worker user.
  Superseded: `gpu-smoke-20261120200736` (`sha256:1a52cf63…`), unhardened.
- **Security:** hardening removed distro ffmpeg 4.4.2 (libav*/codec tree),
  bs4/soupsieve and pip, and applied Ubuntu updates. Old image: ECR 17 unique
  CRITICAL / 108 unique HIGH CVEs (43/393 per-package); Trivy 5 C / 44 H.
  New image Trivy: 5 C / 24 H, **all Pillow 12.3.0** (fixed in 13.0.0,
  which requires Python >= 3.11); 0 C/H in Ubuntu packages. ECR basic scan of
  the new image reported zero findings at all severities while Trivy still
  sees 62 MEDIUM/LOW Ubuntu findings; treat that ECR result as unverified.
  Pillow reachability: only matplotlib's Agg PNG *encoding* of app-generated
  charts; uploaded media is decoded by OpenCV's bundled FFmpeg (not
  inventoried by either scanner). Acceptable for the isolated, no-customer-
  media preflight; **blocks customer processing** until the base moves to an
  Ubuntu 24.04 / Python 3.12 CUDA image with Pillow >= 13.
- **Terraform:** `backend.tf` is gitignored; copy it into any fresh checkout
  or worktree, or `init` silently uses an empty local state (an 89-create
  plan is the symptom). Provider auth needs `AWS_PROFILE`. Against the real
  state: deployed baseline = "No changes"; baseline + GPU smoke = 16 GPU-only
  creates, 0 changes, 0 destroys.
- **Blocker:** EC2 quota L-DB2E81BA "Running On-Demand G and VT instances"
  is **0** in us-east-1; g6f.xlarge needs 4 vCPUs. No increase requested yet.
- Network: default VPC, subnet us-east-1a `subnet-0f3c6534cee511e6a`, main
  route table `rtb-0d6c2941ced7d17a4` (IGW, no S3 endpoint yet). No bucket
  policy uses SourceIp/SourceVpc conditions. ECS GPU AMI
  `al2023-ami-ecs-gpu-hvm-2023.0.20261119` (ami-0b8f7c7154f9e8f8b).
- Cost: g6f.xlarge $0.2375/h On-Demand; a 45-minute run is about $0.18 plus a
  few cents of EBS/public IPv4. Resources in the plan cost nothing at ASG 0.

References: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-gpu-specifying.html
https://docs.aws.amazon.com/AmazonECS/latest/developerguide/managed-scaling-behavior.html
https://docs.aws.amazon.com/autoscaling/ec2/userguide/scheduled-scaling-create-scheduled-action.html
