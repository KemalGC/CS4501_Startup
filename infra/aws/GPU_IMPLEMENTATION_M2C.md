# GPU milestone 2C — zero-resource ECS capacity blueprint (draft)

**Stage only.** This is not a deployment or approval to incur GPU charges.
Milestone 2C is added to draft PR #163. Terraform still rejects
\`enable_gpu=true\` and defaults it to false; all new EC2/ECS/AMI/IAM/S3
resources therefore have \`count=0\`. The paid queue and reconcile Lambda
remain disabled separately, and the API cannot submit paid jobs.

## Changes

- Fixed ECS \`RunTask\` networking. An ECS EC2 task using \`awsvpc\`
  receives **no public IP**. Only the ASG EC2 host is configured with a
  public IP for ECS agent, ECR image pulling and logs.
- Rejected stale-slot stealing: an active lock cannot be replaced just because
  its diagnostic expiry timestamp elapsed. Slot release is tied to confirmed
  ECS STOPPED and one-time credit settlement; unknown tasks remain for review.
- Declared an entirely **inert** ECS-on-EC2 GPU cluster, capacity provider,
  launch template, separate worker IAM/S3 permissions, task definition, log
  group and S3 gateway VPC endpoint. This is **not ECS Managed Instances**:
  the capacity provider uses a one-instance Auto Scaling Group.
- The ASG has \`min=0, desired=0, max=1\`, uses the maintained ECS GPU-optimized
  Amazon Linux 2023 AMI, and cannot scale beyond **one** g6f.xlarge instance.
  The proposed task reserves **2 vCPU, 8 GiB RAM and GPU=0.125**; the host has
  4 vCPU/16 GiB, leaving overhead for the ECS agent. GPU VRAM remains only
  ~3 GB. Whether the real model fits has not been tested.
- A reviewed private ECR image must be pinned by sha256 digest, and the
  dispatcher can only pass the dedicated worker/execution roles and launch
  that exact task definition in the isolated GPU cluster. Existing API and
  reconciler roles have no RunTask/StopTask privileges.
- Private S3 uploads and paid reports are task-role scoped, with no inbound
  host/task security-group rules and no NAT gateway. The operator must review
  the selected public subnet and S3 gateway route table before any launch.

## Hardware and billing review

Candidate: \`g6f.xlarge\` in \`us-east-1\`: NVIDIA L4 1/8 slice (~3 GB VRAM),
4 vCPU, 16 GiB host RAM. A third-party catalog currently lists about
**$0.2375 per instance hour** for On-Demand EC2. This is only an indicative
estimate, **not an AWS quote**. A 30-minute billed lifetime would be roughly
$0.12 EC2 compute, and two hours roughly $0.48, *before* EBS, S3, data
transfer, logs, ECR and taxes. Review live AWS account pricing, quota,
availability-zone placement and the real charge duration before approval.
Savings credits and AWS Budgets alerts are **not hard spend caps**.

The ECS capacity provider can auto-scale to zero while idle, but AWS may
start by requesting two instances from an empty provider. The ASG maximum
of one bounds what can actually launch; whether zero-to-one scheduling works
must be explicitly verified in a controlled smoke test. Idle termination
also has a nonzero delay. No promise of zero idle cost until measured.

## Still blocked before any real NVIDIA GPU run

1. Run \`terraform fmt -check\`, \`terraform validate\`, the no-GPU-default
   safety regression tests and all backend tests in CI; inspect a saved
   operator-side \`terraform plan\` using existing encrypted state.
2. Review real AWS costs/quotas, AZ, IAM, subnet and S3 VPC endpoint access.
   Validate the ECS cluster's cold start from **0 to at most 1** instance.
3. Build, scan, pin and benchmark a CUDA/cuDNN image; test that ONNX actually
   uses the CUDA execution provider with 3 GB VRAM, that it can download and
   publish a report, and that image/model integrity checks pass.
4. Add and test a **bounded StopTask/watchdog** or a strictly supervised
   operator kill procedure. Current 55-minute worker timeout does not bound
   all ECS/EC2 billing if a task stalls. Test ECS STOPPED handling, one-time
   credit settlement, queued retries and private 30-day paid-report UI.
5. Require explicit user approval for a **single manual hardware preflight**
   and a hard external spend/instance shutoff procedure. Only a separate
   reviewed change may remove the \`enable_gpu\` safety validation, apply
   infrastructure, enable queue delivery or billing. This PR stays draft.

## Reference documentation

- AWS ECS fractional GPUs: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-gpu-specifying.html
- AWS EC2 awsvpc task networking: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-networking-awsvpc.html
- AWS ECS capacity from zero: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/managed-scaling-behavior.html
- ECS GPU-optimized AMIs: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/retrieve-ecs-optimized_AMI.html
- Third-party indicative price: https://www.doit.com/compute/compute/aws/us-east-1/g6f.xlarge
