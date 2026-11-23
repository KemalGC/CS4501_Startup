# Switch the idle GPU smoke from G6f to G4dn

**Current next step:** the G4dn migration already succeeded. The pinned model
uses ONNX opset 22, which the published 1.20.2 runtime rejects. Follow
[GPU runtime repair](GPU_RUNTIME_REPAIR.md) to publish the corrected 1.21.1
image and review a fresh image-only plan. The migration commands below are
historical setup instructions; do not repeat an already applied migration.

The operator's two G6f attempts failed on EC2 capacity in `us-east-1a` and
`us-east-1b`. The second transcript confirmed ASG min/max/desired `0/0/0`,
`Launch` suspended, and no active tagged instance. The subsequent G4dn attempt
on 2026-11-23 launched instance `i-0dc5562bfd9372cf4` and reached the preflight
container, which exited with `cuda_session_initialization_failed`. The final
operator transcript confirmed ASG `0/0/0`, `Launch` suspended and that instance
terminated. CUDA inference remains unverified. The recorded evidence is
`gpu-smoke-20261123T150641Z-8226a32d.json`; use the diagnostics below before
considering another attempt.

The selected alternative is **one `g4dn.xlarge`**: four vCPUs, 16 GiB system
memory and one NVIDIA T4 GPU with 16 GiB GPU memory. It fits the same regional
four-vCPU G/VT quota when that quota is otherwise unused. The preparation and
runner recheck the relevant quota and idle state. An account/AZ offering is
not a capacity reservation or a guarantee that AWS can start the host.

This migration keeps the current subnet in `us-east-1b`, official AL2023 ECS
GPU AMI, security groups, encrypted root-volume configuration and published
image. It updates the launch template and both task definitions together:

| Setting | Before | After |
| --- | --- | --- |
| Instance type | `g6f.xlarge` | `g4dn.xlarge` |
| ECS GPU requirement | `0.125` | `1` |
| Terraform acknowledgement | `I_APPROVE_ONE_G6F_SMOKE_INSTANCE` | `I_APPROVE_ONE_G4DN_SMOKE_INSTANCE` |
| Idle ASG min/max/desired | `0/0/0` | `0/0/0` |
| Worker dispatch | Disabled | Disabled |

The allowlist contains these two instance types. The original G6f default is
preserved; a full-GPU hardware run explicitly supplies
`-ExpectedInstanceType g4dn.xlarge`.

## Image and cost

The original hardware migration used this published image:

```text
851226124502.dkr.ecr.us-east-1.amazonaws.com/strokesense-aws-dev-gpu-worker@sha256:cc21a77a44f767fa61ff347ba91e748b3d2acc0914f24a10de54a4a4dc74df16
```

Its runtime is now known to reject the pinned model's opset before CUDA
initialization. Use the runtime repair above before another test. The
preflight checks one visible GPU, runs the
actual model using CUDA, and checks finite outputs. The updated operator also
requires at least 14,000 MiB of reported GPU memory for G4dn; this tolerates
reserved memory while rejecting the old small fractional allocation. Actual
hardware compatibility is established only by a successful smoke result.

AWS's published US East (N. Virginia) reference is approximately **$0.526/hour
for G4dn Linux On-Demand compute**. At that reference rate, 45 minutes is about
**$0.395 for compute**. This is an estimate rather than a spending cap; EBS,
public IPv4, storage/logging and other charges are separate. The scheduled
cutoff requests scale-to-zero, and termination still needs verification.

## 1. Update the existing checkout

Use the same IntelliJ PowerShell terminal and real Terraform backend. Keep
the deployed CPU/OAuth inputs and private Premium owner file in place.

```powershell
& {
    $ErrorActionPreference = "Stop"
    Set-Location "C:\Users\kemal\IdeaProjects\CS4501_StartupAws"
    git pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw "Git update failed." }
    Set-Location ".\infra\aws"
    $env:AWS_PROFILE = "strokesense-admin"
}
```

If the session has expired, run `aws login --profile strokesense-admin`, finish
the sign-in, and rerun the failed preparation. No new Google OAuth client is
needed.

## 2. Prepare and validate a new migration plan

The preparation reads the existing G6f template and fractional task to verify
the starting state, checks G4dn offerings in the current AZ, and writes a
separate input file. It changes no AWS resource. A requested type change keeps
the existing subnet, rather than combining hardware and network changes.

```powershell
& {
    $ErrorActionPreference = "Stop"
    Set-Location "C:\Users\kemal\IdeaProjects\CS4501_StartupAws\infra\aws"
    $env:AWS_PROFILE = "strokesense-admin"
    $imageUri = "851226124502.dkr.ecr.us-east-1.amazonaws.com/strokesense-aws-dev-gpu-worker@sha256:cc21a77a44f767fa61ff347ba91e748b3d2acc0914f24a10de54a4a4dc74df16"

    $retry = .\prepare-gpu-capacity-retry.ps1 -ExpectedAccountId 851226124502 -AwsProfile strokesense-admin -ExpectedImageUri $imageUri -AvailabilityZone us-east-1b -InstanceType g4dn.xlarge -OutputPath ".\gpu-g4dn-retry.tfvars.json"
    if (!$retry.ReadyForPlan -or !$retry.IsInstanceTypeChange -or $retry.CurrentInstanceType -ne "g6f.xlarge" -or $retry.InstanceType -ne "g4dn.xlarge") {
        throw "Expected a prepared G6f-to-G4dn migration. Do not create or repeat a different plan."
    }
    $retry | Format-List CurrentInstanceType, InstanceType, GpuResource, SubnetId, AvailabilityZone, InputsPath

    $planPath = Join-Path (Get-Location).Path "gpu-g4dn-migration.tfplan"
    if (Test-Path -LiteralPath $planPath) { throw "This plan filename already exists. Review it or select a fresh filename instead of overwriting it." }
    if ((Get-FileHash -LiteralPath $retry.InputsPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $retry.InputsHash) { throw "Prepared input file changed." }

    terraform plan "-input=false" "-target=aws_autoscaling_group.gpu[0]" "-target=aws_ecs_task_definition.gpu[0]" "-target=aws_ecs_task_definition.gpu_preflight[0]" "-var-file=$($retry.InputsPath)" "-out=$planPath"
    if ($LASTEXITCODE -ne 0) { throw "G4dn migration plan failed." }

    $check = .\confirm-gpu-instance-plan.ps1 -PlanPath $planPath -ExpectedAccountId 851226124502 -AwsProfile strokesense-admin -ExpectedSubnetId $retry.SubnetId -ExpectedImageUri $imageUri -ExpectedInstanceType g4dn.xlarge
    if (!$check.ReadyForApply) { throw "The saved G4dn migration plan was not verified." }
    $check | Format-List ReadyForApply, PlanPath, PlanHash, Workspace
}
```

All three complete `-target=...` arguments are quoted for PowerShell. Targeting
only the ASG would miss the task-definition changes. The targets are an
exceptional hardware recovery in a branch that also contains an undeployed
Premium API change; the separate full Premium plan still needs review later.

### Expected plan

There are exactly four managed resource changes:

| Resource | Allowed change |
| --- | --- |
| `aws_launch_template.gpu[0]` | New template version changing only the instance type |
| `aws_autoscaling_group.gpu[0]` | Reference the new numeric template version; optionally remove the Launch cleanup latch; remain `0/0/0` in the same subnet |
| `aws_ecs_task_definition.gpu_preflight[0]` | New revision requiring one GPU, with the same image, command and other configuration |
| `aws_ecs_task_definition.gpu[0]` | New revision requiring one GPU; worker dispatch remains disabled |

Task revisions are replacements in Terraform, so the expected summary is
**2 to add, 2 to change, 2 to destroy**. The two replacement resources are task
definitions. The plan must not replace the ASG or change CPU, Lambda, IAM, ECR,
networking or customer data resources.

The new template version and task ARNs are legitimately unknown until apply.
The dedicated migration validator permits these narrowly scoped computed
values, then requires verification of their concrete values after apply.
Neither the original 15-create validator nor the subnet-only capacity
validator is appropriate for this plan.

### Recover from optional task-field validation errors

The AWS provider can represent unset IPC/PID modes and the preflight's absent
task role as empty strings in refreshed state and `null` in a replacement
plan. The validator compares only missing/null/exact-empty-string forms as
equivalent for these optional strings. Explicit namespace values remain
distinct: omitted IPC uses the Docker daemon default and is not treated as
explicit `none`, `task` or `host`. Live namespace settings are checked too.

The same scoped treatment applies to typed empty optional blocks and the
empty `tags` map. Nonempty values, wrong types, `tags_all`, and unrelated
settings remain subject to the existing checks. When several other fields
differ, their names are reported together without exposing their values.

The exact v6.73.0 provider also marks `enable_fault_injection` as computed.
Both Terraform task resources now explicitly set it to `false`, so a fresh
replacement plan has a known disabled value. Enabled, malformed and unknown
fault-injection values remain rejected, including live readback.

If the older validator stopped on `enable_fault_injection` or `ipc_mode`,
that failure happened before apply. Pull the update and rerun Step 2 to create
the new `gpu-g4dn-migration.tfplan`, then use Steps 3 and 4. Keep the old
`gpu-g4dn-retry.tfplan` separate: it contains the earlier configuration and
does not gain the explicit disabled setting when the source files change.

## 3. Apply the reviewed migration while capacity is zero

This block rechecks preparation and the saved plan, applies that exact plan,
then verifies the resulting ASG, numeric template version and both task
revisions. It does not start an instance.

```powershell
& {
    $ErrorActionPreference = "Stop"
    Set-Location "C:\Users\kemal\IdeaProjects\CS4501_StartupAws\infra\aws"
    $env:AWS_PROFILE = "strokesense-admin"
    $imageUri = "851226124502.dkr.ecr.us-east-1.amazonaws.com/strokesense-aws-dev-gpu-worker@sha256:cc21a77a44f767fa61ff347ba91e748b3d2acc0914f24a10de54a4a4dc74df16"

    $retry = .\prepare-gpu-capacity-retry.ps1 -ExpectedAccountId 851226124502 -AwsProfile strokesense-admin -ExpectedImageUri $imageUri -AvailabilityZone us-east-1b -InstanceType g4dn.xlarge -OutputPath ".\gpu-g4dn-retry.tfvars.json"
    if (!$retry.ReadyForPlan -or !$retry.IsInstanceTypeChange) { throw "Expected the prepared instance-type migration before apply." }

    $check = .\confirm-gpu-instance-plan.ps1 -PlanPath ".\gpu-g4dn-migration.tfplan" -ExpectedAccountId 851226124502 -AwsProfile strokesense-admin -ExpectedSubnetId $retry.SubnetId -ExpectedImageUri $imageUri -ExpectedInstanceType g4dn.xlarge
    if (!$check.ReadyForApply) { throw "The saved migration plan was not verified." }
    if ((Get-FileHash -LiteralPath $check.PlanPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $check.PlanHash) { throw "Saved plan changed after verification." }
    $workspace = terraform workspace show
    if ($LASTEXITCODE -ne 0 -or ($workspace -join "").Trim() -ne $check.Workspace) { throw "Terraform workspace changed after verification." }

    terraform apply "-input=false" $check.PlanPath
    if ($LASTEXITCODE -ne 0) { throw "G4dn migration apply failed; do not start the smoke." }

    $applied = .\confirm-gpu-instance-plan.ps1 -PlanPath $check.PlanPath -ExpectedAccountId 851226124502 -AwsProfile strokesense-admin -ExpectedSubnetId $retry.SubnetId -ExpectedImageUri $imageUri -ExpectedInstanceType g4dn.xlarge -VerifyApplied
    if (!$applied.ReadyForSmoke) { throw "The actual G4dn deployment has not been verified." }
    $applied | Format-List ReadyForSmoke, InstanceType, SubnetId, LaunchTemplateVersion
    Write-Host "G4dn configuration verified at zero capacity. Retain gpu-g4dn-retry.tfvars.json for later Terraform plans."
}
```

If apply succeeded but a later verification failed or the terminal closed,
rerun the `-VerifyApplied` check in the next block. Do not apply the consumed
plan a second time. An unsuccessful verification is a blocker for launching;
it does not mean the template/task change should be blindly repeated.

## 4. Verify again and run one G4dn smoke

This is the block that starts a billable host. It keeps the one-instance limit,
fresh AWS-side cutoff and task/host/root-volume cleanup checks. The expected
instance type is explicit, so the old G6f command cannot silently authorize a
different host.

```powershell
& {
    $ErrorActionPreference = "Stop"
    Set-Location "C:\Users\kemal\IdeaProjects\CS4501_StartupAws\infra\aws"
    $env:AWS_PROFILE = "strokesense-admin"
    $imageUri = "851226124502.dkr.ecr.us-east-1.amazonaws.com/strokesense-aws-dev-gpu-worker@sha256:cc21a77a44f767fa61ff347ba91e748b3d2acc0914f24a10de54a4a4dc74df16"

    $subnet = terraform output -raw gpu_smoke_subnet_id
    if ($LASTEXITCODE -ne 0 -or ($subnet -join "").Trim() -notmatch '^subnet-[a-f0-9]{8,17}$') { throw "Cannot read the deployed GPU subnet." }
    $applied = .\confirm-gpu-instance-plan.ps1 -PlanPath ".\gpu-g4dn-migration.tfplan" -ExpectedAccountId 851226124502 -AwsProfile strokesense-admin -ExpectedSubnetId ($subnet -join "").Trim() -ExpectedImageUri $imageUri -ExpectedInstanceType g4dn.xlarge -VerifyApplied
    if (!$applied.ReadyForSmoke) { throw "The actual G4dn deployment has not been verified." }

    .\gpu-smoke.ps1 -ExpectedAccountId 851226124502 -AwsProfile strokesense-admin -ExpectedImageUri $imageUri -ExpectedInstanceType g4dn.xlarge -ApproveCharge -HardStopMinutes 45
}
```

The success marker remains:

```text
PASS: verified CUDA inference, stopped task, terminated host and deleted root volume.
```

Keep the terminal open until cleanup completes and retain the printed evidence
path. A launch failure is still possible for G4dn; successful preparation proves
configuration and offering support, not current spare EC2 capacity. The runner
does not automatically move to another AZ or instance family.

## Diagnose a failed CUDA session without another GPU launch

The fixed category `cuda_session_initialization_failed` does not identify the
underlying library, driver, or graph error. The Python preflight chains the
underlying exception but the published image logs only the category. Earlier
smoke runners also discarded native ONNX Runtime lines beginning with
timestamps or ANSI color sequences. Those messages may still be in CloudWatch.

Let the active runner finish its cleanup and return the evidence path first.
The updated runner retains the unfiltered first CloudWatch page in its evidence
and prints at most the last 80 entries so logging does not delay cleanup with
a pagination loop. That snapshot is explicitly labeled `FIRST_CLOUDWATCH_PAGE`.
For the full stream, use the read-only helper after cleanup:

```powershell
& {
    $ErrorActionPreference = "Stop"
    Set-Location "C:\Users\kemal\IdeaProjects\CS4501_StartupAws"
    git pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw "Git update failed." }
    Set-Location ".\infra\aws"

    $evidencePath = "C:\Users\kemal\AppData\Local\Temp\strokesense-gpu-smoke\gpu-smoke-20261123T150641Z-8226a32d.json"
    .\read-gpu-smoke-logs.ps1 -ExpectedAccountId 851226124502 -AwsProfile strokesense-admin -EvidencePath $evidencePath -ExpectedInstanceId i-0dc5562bfd9372cf4
}
```

The helper matches the instance in the local smoke evidence, checks the AWS
account and task/log stream identity, reads every page through a fixed snapshot
time, and saves an unfiltered UTF-8 log plus event JSON beside the evidence
file, using unique names to preserve earlier snapshots. Empty pages
are not treated as the end of the stream. It makes only AWS read calls; it does
not apply Terraform, change capacity, rerun inference, or certify live cleanup.
If the evidence was written to a custom directory, supply `-EvidencePath` with
the JSON path printed by the runner. Repeating the helper refreshes diagnostics
without creating a GPU host.

Interpret the native error before editing the image. For example, a message
about graph nodes assigned to CPU points to the strict
`session.disable_cpu_ep_fallback=1` contract; it does not prove CUDA was missing.
A missing shared library or CUDA driver/context failure calls for a different
fix. Retain the existing CUDA and finite-output checks while gathering this
evidence. The generic category alone does not justify changing hardware or
declaring a successful inference run.

References:

- [CloudWatch GetLogEvents pagination](https://docs.aws.amazon.com/cli/latest/reference/logs/get-log-events.html)
- [ONNX Runtime session configuration](https://github.com/microsoft/onnxruntime/blob/main/include/onnxruntime/core/session/onnxruntime_session_options_config_keys.h)
- [ONNX Runtime CUDA requirements](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html)

## After this attempt

Keep `gpu-g4dn-retry.tfvars.json` with the private deployment inputs. Use it
explicitly as the GPU `-var-file` for a later full Premium deployment plan;
the old G6f files can otherwise propose reverting the selected profile.
Retain the existing CPU/OAuth inputs and `premium-owner.auto.tfvars.json`.

The dormant worker task definition is updated for consistency, but website
GPU submission is still disabled. The future dispatcher/admission change
must understand the selected full-GPU requirement and validate a complete
owner-only video job before Premium availability is advertised.

The original 15-create bootstrap validator remains specific to the initial
G6f deployment. This guide applies to the already created and idle deployment.

## Verification and references

Windows CI exercises the runner, preparation, subnet-only validation and new
instance-migration validation under both Windows PowerShell 5.1 and PowerShell
7. The fixtures include legacy G6f behavior, full-GPU matching, instance/count
and memory mismatches, scoped unknown plan values, permitted task revisions,
unrelated resource rejection and applied-state mismatches. The tests do not
call AWS or start capacity.

- [AWS ECS supported GPU types and task requirements](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-gpu.html)
- [AWS ECS task registration and the disabled fault-injection default](https://docs.aws.amazon.com/AmazonECS/latest/APIReference/API_RegisterTaskDefinition.html)
- [AWS provider v6.73.0 task-definition schema, registration and readback](https://github.com/hashicorp/terraform-provider-aws/blob/v6.73.0/internal/service/ecs/task_definition.go)
- [AWS On-Demand vCPU quotas](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-on-demand-instances.html)
- [NVIDIA driver support by EC2 family](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/install-nvidia-driver.html)
- [ONNX Runtime CUDA/cuDNN requirements](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html)
- [NVIDIA cuDNN 9.5.1 support matrix](https://docs.nvidia.com/deeplearning/cudnn/backend/v9.5.1/reference/support-matrix.html)
- [AWS April 2026 G4dn reference price for us-east-1](https://aws.amazon.com/cn/blogs/china/florence-2-deploy-inferentia2-guide/)
