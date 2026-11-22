# Milestone 3 — Operator-only GPU EC2 smoke activation

This supersedes the 2C permanent-disable note for an isolated manual NVIDIA
preflight. Paid Deep Analysis remains disabled, and PR #163 remains a DRAFT.

### What changed

- `enable_gpu=false` is still the default. Setting it true now requires all
  of `gpu_smoke_mode=true`, `enable_gpu_image_repository=true`,
  `gpu_smoke_approval="I_APPROVE_ONE_G6F_SMOKE_INSTANCE"`, with the paid GPU
  scaffold and CPU smoke queue OFF. **Preserve live CPU analysis.** Use this acknowledgement when the operator
  has reviewed cost and is prepared to run one billable test.
- A private immutable GPU ECR repository may be created independently using
  `enable_gpu_image_repository=true`, while `enable_gpu=false`. No EC2.
- ECS-on-EC2 GPU resources are review-only by default. When deliberately
  provisioned for smoke, the ASG has min=0, desired=0, max=0, g6f.xlarge On-Demand,
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
  The blank-input smoke creates **no S3 gateway endpoint** and changes no shared
  S3 routes. The host pulls the image and ships logs; the task has no public IP.
  A future real-data worker needs a separately reviewed S3 access path.
- Terraform checks the Amazon-owned AL2023 ECS GPU AMI is release 20261119 or
  newer, including the GRID userspace fix. The ASG uses a numeric launch-template
  version, and the runner checks that version and AMI before starting capacity.
- An exit-zero task is insufficient: the runner requires the pinned model's
  structured CUDA inference evidence and exact running image digest. Missing
  logs, unverified termination, and unverifiable volume deletion fail the run.

### Start here: verify the image and request the quota

Run from the existing authenticated checkout's `infra/aws` directory. This
command performs no Terraform apply and launches no instance. The optional
`-RequestQuotaIncrease` requests **4 total vCPUs** only when necessary; it checks
request history first to avoid duplicates. AWS may open a support case.

```powershell
$ready = .\prepare-gpu-smoke.ps1 -ExpectedAccountId 851226124502 -AwsProfile strokesense-admin -ImageTag gpu-smoke-20261120211125 -ExpectedImageDigest sha256:9250535f526d3f0f686759b0c56acc511281c39d078343bc8e3e7c851651a208 -RequestQuotaIncrease
$ready
```

The tag above is the previously published image, not a newly built image of
every later source commit. The helper sets `TF_VAR_gpu_worker_image_uri` only
after ECR verifies the complete digest. It returns `ReadyForPlan = false` while
quota approval is pending, plus the exact request ID and resume command. Check
that property before continuing. Do not interpret a successfully submitted
request as an applied quota increase. The runner checks available capacity again.

### Obtain the image for the current source revision

The **StrokeSense GPU Image** GitHub Actions workflow builds relevant PR changes
for `linux/amd64`, with the pinned CUDA base and the source revision in an OCI
label. It validates the GPU package/model, runs the GPU unit tests, and proves
the worker remains disabled and a CPU host rejects real GPU preflight.

On success, download the `strokesense-gpu-<commit>-<run>-<attempt>` artifact from
that workflow run. It expires after three days and contains:

- `strokesense-gpu-image.tar.gz`: the tested Docker image.
- `image-manifest.json`: source revision, local image ID, platform and checks.
- `SHA256SUMS`: the archive checksum.

After extracting it, verify and load it in a single script scope:

```powershell
& {
  $manifest = Get-Content .\image-manifest.json -Raw | ConvertFrom-Json
  $archive = Join-Path (Get-Location) 'strokesense-gpu-image.tar.gz'
  if ((Get-FileHash $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $manifest.archive_sha256) { throw 'Archive checksum mismatch' }
  docker load --input $archive
  if ($LASTEXITCODE -ne 0) { throw 'Docker image load failed' }
  $actualId = docker image inspect $manifest.image_tag --format '{{.Id}}'
  if ($LASTEXITCODE -ne 0 -or $actualId.Trim() -ne $manifest.image_id) { throw 'Loaded image does not match the build artifact' }
  Write-Host "Loaded verified source $($manifest.source_commit) as $($manifest.image_tag)"
}
```

Publish that image to the existing ECR repository using the authenticated local
publisher, with a new immutable tag. Re-run `prepare-gpu-smoke.ps1` with that
tag and its independently checked ECR digest. **Neither the archive checksum
nor the local Docker image ID is the ECR manifest digest.** The workflow does
not have AWS credentials, publish to ECR, scan vulnerabilities, or test hardware.

The newer source checks every warm-up and measured inference result, including
intermittent non-finite/empty output. The previously published digest cannot
acquire that fix; use a newly published artifact to exercise the updated code.

### Review before any real apply

1. Confirm AWS account, us-east-1 **g6f.xlarge On-Demand quota/AZ inventory**,
   actual On-Demand price and any EBS/ECR/S3 charges. Public estimate as of
   Nov 2026 is about $0.2375 per hour for EC2 compute only.
   AWS Budgets are delayed alerts, NOT a hard AWS bill cap.
2. Confirm the intended public subnet, Internet Gateway route, and an available
   task ENI. Check 4 free On-Demand G/VT vCPUs. Smoke creates no S3 endpoint;
   do not change the route table serving the live CPU analyzer.
3. Obtain and audit a matching SHA256-pinned CUDA/cuDNN Linux x86_64 base
   image and dependency lock (onnxruntime-gpu, CUDA, cuDNN compatibility).
   NEVER guess or invent a digest. The Dockerfile requires `CUDA_BASE_IMAGE`.
4. For a new environment only, use the existing encrypted Terraform backend to
   plan and apply the image repository:
   - `enable_gpu_image_repository=true`
   - `enable_gpu=false`, `gpu_smoke_mode=false`
   Inspect every planned change before apply. The StrokeSense aws-dev repository
   already exists; do not repeat its bootstrap or reapply an old saved plan.
5. From the repository `strokesense/` directory, build and scan the reviewed
   `Dockerfile.aws-gpu` for linux/amd64, push to the private ECR repo, read
   the ECR `imageDigest` and construct
   `<ECR_REPO_URL>@sha256:<verified-digest>`. Confirm the model and CUDA
   libraries are built into the image. Do not push credentials to GitHub.
6. For a SEPARATE reviewed GPU infrastructure plan, set
   `enable_gpu=true`, `gpu_smoke_mode=true`,
   `enable_gpu_image_repository=true`, and the approval token, reviewed
   `gpu_subnet_id`, empty `gpu_s3_route_table_ids=[]`, and digest-pinned
   `gpu_worker_image_uri`. Keep `enable_paid_gpu_queue_scaffold=false` and
   `enable_cpu_smoke_queue=false`. Keep every other variable at its
   **deployed** value (aws-dev runs `enable_cpu_analysis=true` with a pinned
   `worker_image_tag`); first prove the deployed baseline plans
   "No changes", then add only the GPU variables. Reject any plan that
   updates or replaces non-GPU resources.
   Review `terraform plan -out=gpu-smoke.tfplan` before applying that exact
   plan. This creates cost-bearing infrastructure resources (EBS only after
   instance launch); the EC2 ASG itself is initially at zero.
7. With authorization for the single billable hardware run, execute:
   `.\gpu-smoke.ps1 -ExpectedAccountId 851226124502 -AwsProfile strokesense-admin -ExpectedImageUri $ready.ImageUri -ApproveCharge -HardStopMinutes 45`
   Only use `$ready` from a successful verification of the image selected in
   the freshly applied plan. The script prints the preflight evidence, timings
   and verifies EC2 termination. This script must run from Windows PowerShell
   with AWS CLI v2, working Terraform output/state, and correct AWS privileges.
   It creates the AWS cutoff before starting the one host.
8. Inspect CloudWatch logs and task exit code. After success or failure,
   check EC2 instance termination, ASG max=0/desired=0, and billing. The
   operator script deliberately leaves max=0 and Launch suspended after cleanup.
   A second paid attempt needs separate authorization and an explicit review;
   rerunning the script cannot silently start another host.

### Backend and verification checks

Use the original working checkout's backend configuration and deployed inputs.
Do not copy `backend.s3.tf.example` over a real backend, migrate state, or treat
an empty state as a fresh environment. If `backend.tf` is missing, recover the
known correct local configuration before `terraform init`. Keep OAuth values
in the protected input mechanism; state and JSON plan dumps can contain them.

Run formatting, validation, and a full fresh plan; inspect resource effects as
well as action counts. Apply the exact reviewed plan, then run the operator.
Do not run a concurrent Terraform apply while a smoke is active.

The offline checks use fake AWS/Terraform commands and launch nothing:

```powershell
powershell -NoProfile -File .\test-prepare-gpu-smoke.ps1
powershell -NoProfile -File .\test-gpu-smoke.ps1
```

CI runs both suites in Windows PowerShell 5.1 and PowerShell 7. They cover quota
requests, digest failures, stale launch templates, missing/invalid/delayed
inference logs, ambiguous task responses, failed inference, denied volume
inspection, and unsuccessful shutdown. Hardware evidence is still required.

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

### Historical operator report: 2026-11-20 (not a live AWS status check)

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
  media preflight only; **blocks customer processing** pending verified fixes.
  Pillow >=13 needs Python >=3.11; Ubuntu 24.04/Python 3.12 is one option.
  ECR Basic covers OS packages, so absence of its Pillow findings is expected.
  Reconcile the OS findings by digest, CVE/package and scanner database date;
  neither scanner's count alone establishes safety or invalidates the other.
- **Terraform:** `backend.tf` is gitignored; copy it into any fresh checkout
  or worktree, or `init` silently uses an empty local state (an 89-create
  plan is the symptom). Provider auth needs `AWS_PROFILE`. Against the real
  state: deployed baseline = "No changes"; that earlier smoke plan had 16
  creates. Subsequent isolation changes alter the plan; generate a new one.
- **Reported blocker:** EC2 quota L-DB2E81BA "Running On-Demand G and VT instances"
  was **0** in us-east-1; g6f.xlarge needs 4 vCPUs. Recheck the applied quota and
  request history with the preparation helper; this document cannot track them.
- Network: default VPC, subnet us-east-1a `subnet-0f3c6534cee511e6a`, main
  route table `rtb-0d6c2941ced7d17a4` (IGW, no S3 endpoint yet). No bucket
  policy uses SourceIp/SourceVpc conditions. ECS GPU AMI
  `al2023-ami-ecs-gpu-hvm-2023.0.20261119` (ami-0b8f7c7154f9e8f8b).
- Reported compute price: g6f.xlarge $0.2375/h On-Demand; recheck current AWS
  pricing before launch. EBS, public IPv4, ECR storage and logs are separate.
  ASG zero stops EC2 compute charges but does not eliminate all storage costs.

References: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-gpu-specifying.html
https://github.com/aws/amazon-ecs-ami/pull/837
https://github.com/aws/amazon-ecs-ami/blob/main/CHANGELOG.md
https://docs.aws.amazon.com/AmazonECS/latest/developerguide/managed-scaling-behavior.html
https://docs.aws.amazon.com/autoscaling/ec2/userguide/scheduled-scaling-create-scheduled-action.html
