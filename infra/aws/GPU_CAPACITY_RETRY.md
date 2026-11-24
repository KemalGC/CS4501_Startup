# Recover the GPU smoke after an Availability Zone capacity failure

**Alternative instance type:** after the reported G6f failures in both
`us-east-1a` and `us-east-1b`, use [the G4dn switch guide](GPU_INSTANCE_RETRY.md)
to try one full NVIDIA T4 GPU. A hardware change updates the launch template
and task definitions as well as the ASG; the subnet-only validator below
deliberately does not approve it.

The first hardware attempt could not obtain a `g6f.xlarge` in `us-east-1a`.
AWS explicitly suggested `us-east-1b`, `us-east-1c` or `us-east-1d`. The
operator's transcript reported the ASG back at min/max/desired `0/0/0`, with
no active instance remaining. It did not establish that CUDA inference works:
the test stopped while waiting for a host.

The next attempt keeps the published image, instance type, launch template and
existing GPU infrastructure. It selects one existing public subnet in
`us-east-1b`, reviews a saved Terraform plan changing only the idle ASG, then
starts one bounded smoke test. An instance-type offering confirms that AWS
supports the type in that zone; it does not reserve capacity or guarantee a
successful launch. There is no automatic loop through zones.

## What is already complete

| Item | Latest operator evidence |
| --- | --- |
| GPU image | Published and verified in ECR at the digest below |
| On-Demand G/VT quota | 4 vCPUs applied in `us-east-1` |
| GPU infrastructure | Initial apply completed: 15 added, 0 changed, 0 destroyed |
| Hardware attempt | Capacity failure in `us-east-1a`; CUDA not reached |
| Cleanup | ASG reported `0/0/0`, with no active host remaining |
| Premium owner | Identity verified; existing admin-group membership confirmed |
| Premium deployment | API ZIP built; plan stopped because the original GPU input file was missing |

Selected image, unchanged by this recovery:

```text
851226124502.dkr.ecr.us-east-1.amazonaws.com/strokesense-aws-dev-gpu-worker@sha256:cc21a77a44f767fa61ff347ba91e748b3d2acc0914f24a10de54a4a4dc74df16
```

## 1. Update the existing checkout

Use the IntelliJ PowerShell terminal in the original checkout. It contains the
real backend configuration and deployed input values. Run each complete block
in order, only after the previous block succeeds.

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

If the preparation helper reports an expired session, renew that same profile:

```powershell
aws login --profile strokesense-admin
```

Keep the current Google OAuth values, CPU inputs and
`premium-owner.auto.tfvars.json` in their existing protected locations. The
commands below do not ask for a new Google OAuth client. `-input=false` stops
a Terraform plan if a required deployment input is missing instead of waiting
for unattended input; restore the existing input before rerunning.

## 2. Prepare a subnet and save the recovery plan

`prepare-gpu-capacity-retry.ps1` reads AWS and Terraform outputs. It checks
account ownership, the deployed image and launch template, idle capacity and
the selected subnet's network path. It creates a local GPU-only input file;
it does not change AWS. The candidate must be in the existing VPC with usable
IPv4 addresses, an effective route to an attached Internet Gateway, DNS, and
a network ACL that this narrow recovery can verify. The launch template
explicitly assigns the host a public IPv4 address; the subnet's automatic
public-IP setting alone is not a reason to reject it.

The helper fails if there is no suitable existing subnet. It does not create
subnets, NAT gateways, routes or a replacement GPU fleet.

```powershell
& {
    $ErrorActionPreference = "Stop"
    Set-Location "C:\Users\kemal\IdeaProjects\CS4501_StartupAws\infra\aws"
    $env:AWS_PROFILE = "strokesense-admin"
    $imageUri = "851226124502.dkr.ecr.us-east-1.amazonaws.com/strokesense-aws-dev-gpu-worker@sha256:cc21a77a44f767fa61ff347ba91e748b3d2acc0914f24a10de54a4a4dc74df16"

    $retry = .\prepare-gpu-capacity-retry.ps1 -ExpectedAccountId 851226124502 -AwsProfile strokesense-admin -ExpectedImageUri $imageUri -AvailabilityZone us-east-1b -OutputPath ".\gpu-capacity-retry.tfvars.json"
    if (!$retry.ReadyForPlan) { throw "Capacity retry preparation did not complete." }
    $retry | Format-List OldSubnetId, SubnetId, AvailabilityZone, InputsPath

    $planPath = Join-Path (Get-Location).Path "gpu-capacity-retry.tfplan"
    if (Test-Path -LiteralPath $planPath) {
        throw "A recovery plan already exists. Inspect it or choose a fresh plan filename; do not overwrite a reviewed plan."
    }
    if ((Get-FileHash -LiteralPath $retry.InputsPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $retry.InputsHash) {
        throw "The prepared input file changed. Run preparation again."
    }

    terraform plan "-input=false" "-target=aws_autoscaling_group.gpu[0]" "-var-file=$($retry.InputsPath)" "-out=$planPath"
    if ($LASTEXITCODE -ne 0) { throw "Capacity recovery plan failed." }

    $check = .\confirm-gpu-capacity-plan.ps1 -PlanPath $planPath -ExpectedAccountId 851226124502 -AwsProfile strokesense-admin -ExpectedSubnetId $retry.SubnetId -ExpectedImageUri $imageUri
    if (!$check.ReadyForApply) { throw "The saved recovery plan was not verified." }
    $check | Format-List ReadyForApply, OldSubnetId, SubnetId, PlanPath, PlanHash, Workspace
}
```

The entire `-target=...` argument is quoted for Windows PowerShell. Targeting is
used here for an exceptional capacity recovery because the working branch also
contains the separate, undeployed Premium API changes. It is not a substitute
for the later full deployment review.

The accepted plan has **0 to add, 1 to change, 0 to destroy**. The only managed
resource update is `aws_autoscaling_group.gpu[0]`:

- One reviewed subnet replaces the old subnet in `us-east-1a`.
- Min, max and desired capacity remain zero.
- The numeric launch-template version and image remain unchanged.
- `Launch` suspension may be removed while capacity is zero, if the previous
  runner left that cleanup latch in place. `AZRebalance` and `ReplaceUnhealthy`
  remain suspended.
- The subnet output is refreshed with the ASG, so the next task uses the same
  subnet as its host.

Any Lambda, CPU, IAM, security-group, AMI or launch-template update is rejected.
If a newer recommended AMI causes a template change, stop at that specific
validation failure and review it separately. The original
`confirm-gpu-smoke-plan.ps1` checks the initial 15-create plan and is not used
for this recovery.

Terraform's resource-targeting warning is expected for this narrow operation.
A targeted plan can report `complete=false`; the recovery validator explicitly
checks the selected changes and dependencies instead of treating this flag as
proof of a full deployment review.

## 3. Apply the reviewed subnet change at zero capacity

Run this only after reviewing the saved plan above. It rechecks the network,
idle AWS state, account, workspace and saved plan before applying that exact
file. It does not start an instance.

```powershell
& {
    $ErrorActionPreference = "Stop"
    Set-Location "C:\Users\kemal\IdeaProjects\CS4501_StartupAws\infra\aws"
    $env:AWS_PROFILE = "strokesense-admin"
    $imageUri = "851226124502.dkr.ecr.us-east-1.amazonaws.com/strokesense-aws-dev-gpu-worker@sha256:cc21a77a44f767fa61ff347ba91e748b3d2acc0914f24a10de54a4a4dc74df16"

    $retry = .\prepare-gpu-capacity-retry.ps1 -ExpectedAccountId 851226124502 -AwsProfile strokesense-admin -ExpectedImageUri $imageUri -AvailabilityZone us-east-1b -OutputPath ".\gpu-capacity-retry.tfvars.json"
    if (!$retry.ReadyForPlan) { throw "Capacity retry preparation did not complete." }
    $check = .\confirm-gpu-capacity-plan.ps1 -PlanPath ".\gpu-capacity-retry.tfplan" -ExpectedAccountId 851226124502 -AwsProfile strokesense-admin -ExpectedSubnetId $retry.SubnetId -ExpectedImageUri $imageUri
    if (!$check.ReadyForApply) { throw "The saved recovery plan was not verified." }
    if ((Get-FileHash -LiteralPath $check.PlanPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $check.PlanHash) {
        throw "The saved plan changed after verification."
    }
    $workspace = terraform workspace show
    if ($LASTEXITCODE -ne 0 -or ($workspace -join "").Trim() -ne $check.Workspace) {
        throw "The Terraform workspace changed after verification."
    }

    terraform apply "-input=false" $check.PlanPath
    if ($LASTEXITCODE -ne 0) { throw "Capacity recovery apply failed; do not start the smoke." }

    $subnet = terraform output -raw gpu_smoke_subnet_id
    if ($LASTEXITCODE -ne 0 -or ($subnet -join "").Trim() -ne $retry.SubnetId) {
        throw "The applied subnet output does not match the reviewed recovery."
    }
    $raw = aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names $check.AsgName --region us-east-1 --output json --no-cli-pager
    if ($LASTEXITCODE -ne 0) { throw "Cannot verify the ASG after apply." }
    $groups = ($raw -join "`n") | ConvertFrom-Json
    if (@($groups.AutoScalingGroups).Count -ne 1) { throw "Expected exactly one GPU ASG." }
    $asg = $groups.AutoScalingGroups[0]
    if ($asg.MinSize -ne 0 -or $asg.MaxSize -ne 0 -or $asg.DesiredCapacity -ne 0 -or @($asg.Instances).Count -ne 0 -or $asg.VPCZoneIdentifier -ne $retry.SubnetId) {
        throw "The applied ASG is not idle in the reviewed subnet."
    }

    $retained = Join-Path (Get-Location).Path "gpu-smoke.tfvars.json"
    if (!(Test-Path -LiteralPath $retained)) {
        Copy-Item -LiteralPath $retry.InputsPath -Destination $retained
        Write-Host "Recovered the missing gpu-smoke.tfvars.json. Keep it with your existing deployment inputs."
    }
    else {
        Write-Host "Existing gpu-smoke.tfvars.json preserved. Use gpu-capacity-retry.tfvars.json for subsequent plans if the old file selects a different subnet."
    }
    Write-Host "Subnet recovery applied; the GPU ASG remains at 0/0/0."
}
```

Do not reapply the old 15-create plan. Saved plans contain their effective
variable values; changing `TF_VAR_*` during apply does not modify the saved
plan. The recovery input file explicitly supplies the GPU flags required for
the already deployed smoke infrastructure.

## 4. Start one new GPU test

This is the step that starts **one billable GPU host**. The smoke runner creates
and verifies a fresh AWS-side zero-capacity cutoff, waits for the host, runs the
preflight, then stops tasks and verifies host/root-volume cleanup. Keep this
terminal running until the command returns. The cutoff is a scheduled shutdown
guard, not a dollar cap.

```powershell
& {
    $ErrorActionPreference = "Stop"
    Set-Location "C:\Users\kemal\IdeaProjects\CS4501_StartupAws\infra\aws"
    $env:AWS_PROFILE = "strokesense-admin"
    $imageUri = "851226124502.dkr.ecr.us-east-1.amazonaws.com/strokesense-aws-dev-gpu-worker@sha256:cc21a77a44f767fa61ff347ba91e748b3d2acc0914f24a10de54a4a4dc74df16"
    .\gpu-smoke.ps1 -ExpectedAccountId 851226124502 -AwsProfile strokesense-admin -ExpectedImageUri $imageUri -ApproveCharge -HardStopMinutes 45
}
```

A successful run ends with:

```text
PASS: verified CUDA inference, stopped task, terminated host and deleted root volume.
```

If capacity is also unavailable in `us-east-1b`, the runner records that failure,
attempts to suspend `Launch`, returns capacity to zero and verifies cleanup.
When no instance was observed, the evidence says so instead of claiming an
empty list of instances was terminated. It does not report CUDA success.

Retain the printed evidence path. A different-zone retry needs a new reviewed
input/plan pair: select `-AvailabilityZone us-east-1c` or `us-east-1d`, with fresh
`-OutputPath` and plan filenames throughout steps 2 and 3. Do not run simultaneous
smokes or resume `Launch` manually to bypass the checks. An offering in another
zone is still not a guarantee of capacity.

## 5. Resume the Premium deployment

After the hardware attempt finishes cleanup, continue
[Premium access and deployment](PREMIUM_ACCESS.md). The latest transcript already
verified the intended owner and saved `premium-owner.auto.tfvars.json`. Keep
that file. The missing GPU input file can now be supplied by the retained
`gpu-smoke.tfvars.json` or the explicitly selected
`gpu-capacity-retry.tfvars.json`.

That file contains only the GPU settings. A full Premium plan still requires
the **deployed CPU, OAuth and other application inputs**. Inspect the full plan
for unintended CPU changes, GPU removal, changes to the cleanup latch or a
new AMI. Do not use the subnet-only validator or another targeted apply to
approve a Premium deployment.

Premium access grants, CUDA validation and website GPU job dispatch are separate
completion criteria. The current API/admin UI implementation prepares access;
the website should show GPU availability only after the queue/dispatcher and a
complete owner video job have been validated.

## Offline validation

The Windows CI matrix runs the preparation and saved-plan tests under Windows
PowerShell 5.1 and PowerShell 7, together with the expanded smoke-runner tests.
All use fake AWS/Terraform responses. The plan checks reject additional resource
changes and unknown safety values; preparation checks cover network selection
and account/idle-state mismatches. No CI job applies Terraform or starts AWS
capacity.

The subnet output dependency was also exercised with a provider-free Terraform
fixture: a targeted managed-resource update refreshed the subnet output while
leaving an unrelated resource unchanged. The former variable-only output was
omitted from that targeted plan, which would have left the runner with stale
placement data.

## References

- [AWS: Auto Scaling instance-launch failures](https://docs.aws.amazon.com/autoscaling/ec2/userguide/ts-as-instancelaunchfailure.html)
- [AWS: Instance-type offerings](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_DescribeInstanceTypeOfferings.html)
- [AWS: Subnet route tables](https://docs.aws.amazon.com/vpc/latest/userguide/subnet-route-tables.html)
- [Terraform: Planning and exceptional resource targeting](https://developer.hashicorp.com/terraform/cli/commands/plan)
