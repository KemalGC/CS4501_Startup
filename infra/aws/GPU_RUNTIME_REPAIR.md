# Repair the pinned GPU model/runtime mismatch

## Confirmed failure and scope

The 2026-11-23 G4dn attempt reached the preflight container. Its complete
CloudWatch capture contains ten messages, ending with the generic category
`cuda_session_initialization_failed`; the old image discarded the underlying
Python exception. The saved evidence confirms task shutdown, ASG `0/0/0`,
Launch suspension, instance `i-0dc5562bfd9372cf4` termination, no remaining
tracked root volumes and no cleanup errors. These are recorded observations,
not a new live AWS inspection.

The exact pinned 11,853,451-byte model has SHA256
`93e2866b0ce678f99b4dd88af0c12e9ea2edf079a361dc2ecbc6226b77ff6408`, IR 10
and ONNX opset **22**. The exact old `onnxruntime-gpu==1.20.2` rejects it
because it supports opset **21**. This rejection was reproduced before CUDA
initialization with the GPU package's explicit CPU provider. The same model
loads and produces finite `[1,56,8400]` outputs with `onnxruntime-gpu==1.21.1`.
This proves a software compatibility blocker; a hardware smoke must still
establish actual CUDA execution.

The repair pins GPU runtime **1.21.1**, retains the model and existing CUDA
12.6.3/cuDNN 9 base, and adds actual model loading/inference to the image
build. The exact Linux Python 3.10 wheel records CUDA build version **12.2**.
The build verifies that metadata, loads NVIDIA libraries through ORT's public
`preload_dlls` API, and checks CUDA provider relocations with the dynamic
linker's trace mode and shared provider bridge. It does not run the provider's
private constructors outside ORT's initialization lifecycle. The model check
uses the GPU package's CPU provider, never installs the
separate CPU-only package, and explicitly reports GPU inference as unverified.

Preflight failures now include bounded structured diagnostics under
`STROKESENSE_GPU_PREFLIGHT_FAILURE`: failure stage, exception chain, runtime
version, advertised providers and best-effort GPU/driver identity. Strict
CUDA provider selection, CPU fallback rejection, model integrity, finite
inference output and cleanup requirements remain in place.

References: [ORT compatibility](https://onnxruntime.ai/docs/reference/compatibility.html),
[exact GPU 1.21.1 release](https://pypi.org/project/onnxruntime-gpu/1.21.1/),
[CUDA 12.6 compatibility guidance](https://docs.nvidia.com/cuda/archive/12.6.1/cuda-c-best-practices-guide/index.html).

## 1. Update the checkout and obtain the tested image

Run each PowerShell block as one block in IntelliJ. Keep the existing real
backend, CPU/OAuth inputs and `premium-owner.auto.tfvars.json`. Do not paste
PowerShell prompt prefixes or the output of commands as input.

```powershell
& {
    $ErrorActionPreference = "Stop"
    Set-Location "C:\Users\kemal\IdeaProjects\CS4501_StartupAws"
    $branch = git branch --show-current
    if ($LASTEXITCODE -ne 0 -or ($branch -join "").Trim() -ne "aws-paid-gpu-integration-prep-20261120") { throw "Use the existing GPU feature branch." }
    git pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw "Git update failed." }
    Set-Location ".\infra\aws"
    $env:AWS_PROFILE = "strokesense-admin"
    aws sts get-caller-identity --profile strokesense-admin --query Account --output text --no-cli-pager
    if ($LASTEXITCODE -ne 0) { throw "AWS session check failed. Run aws login --profile strokesense-admin, then retry." }
}
```

Open the successful **StrokeSense GPU Image** run for the repaired source
revision and download its `strokesense-gpu-<commit>-<run>-<attempt>` artifact.
Extract the outer ZIP. Use the directory containing `image-manifest.json`,
`SHA256SUMS` and `strokesense-gpu-image.tar.gz`; leave the inner `.tar.gz` intact.
Artifacts expire after three days.

The real image build must pass all of these: native NVIDIA library loading
and CUDA provider relocation checks,
pinned-model CPU inference, GPU unit tests, rejection without a NVIDIA driver,
and the default disabled worker. These checks do not certify hardware or scan
the new image for vulnerabilities. The downloadable metadata includes the
archive SHA256 and distinct OCI index, amd64 manifest and configuration digests.
The workflow prints `IMAGE_MANIFEST_SHA256` for independent metadata checking.

## 2. Publish through the resumable AWS CLI uploader

Use the successful workflow's exact source commit and metadata SHA256 when
prompted. The publisher verifies the archive and referenced blobs, reuses
existing ECR layers, resumes its own saved part checkpoints, publishes the
amd64 manifest, independently reads it back and runs the image/quota check.
Docker login and Docker Desktop's upload proxy are not used.

```powershell
& {
    $ErrorActionPreference = "Stop"
    Set-Location "C:\Users\kemal\IdeaProjects\CS4501_StartupAws\infra\aws"
    $env:AWS_PROFILE = "strokesense-admin"
    $artifactDirectory = (Read-Host "Full extracted artifact directory containing image-manifest.json").Trim().Trim('"')
    $expectedSource = (Read-Host "40-character source commit from the successful GPU image workflow").Trim()
    $metadataHash = (Read-Host "IMAGE_MANIFEST_SHA256 from that workflow").Trim()
    if ($expectedSource -cnotmatch '^[a-f0-9]{40}$' -or $metadataHash -cnotmatch '^[a-f0-9]{64}$') { throw "Expected exact lowercase source and metadata hashes." }
    $metadataPath = Join-Path $artifactDirectory "image-manifest.json"
    if ((Get-FileHash -LiteralPath $metadataPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $metadataHash) { throw "Artifact metadata differs from the reviewed workflow." }
    $m = Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json
    if ($m.source_commit -cne $expectedSource -or $m.source_repository -cne "https://github.com/KemalGC/CS4501_Startup" -or $m.platform -cne "linux/amd64") { throw "Artifact source or platform mismatch." }
    if ($m.validation.onnxruntime_gpu_version -cne "1.21.1" -or $m.validation.cpu_model_compatibility -cne "pinned_model_loaded_and_finite_outputs" -or $m.validation.cuda_provider_library_linkage -cne "passed_without_initializing_hardware") { throw "The artifact does not contain the verified runtime repair." }
    $publishArgs = @{
        ExpectedAccountId = "851226124502"
        AwsProfile = "strokesense-admin"
        ArtifactDirectory = $artifactDirectory
        ImageTag = $m.ecr_image_tag
        ExpectedSourceCommit = $expectedSource
        ExpectedArchiveSha256 = $m.archive_sha256
        ExpectedArchiveSizeBytes = [long]$m.archive_size_bytes
        ExpectedIndexDigest = $m.oci_index_digest
        ExpectedManifestDigest = $m.registry_manifest_digest
        ExpectedConfigDigest = $m.registry_config_digest
    }
    $ready = .\publish-gpu-artifact.ps1 @publishArgs
    if (!$ready.ReadyForPlan) { throw "Publication or quota readiness is incomplete." }
    $ready | Format-List Status, ReadyForPlan, AppliedGpuVcpuQuota, ImageUri
    Write-Host "Verified image URI is set in this terminal. Continue with the fresh image-update plan."
}
```

If a connection fails, rerun this same block with the same artifact. Keep one
publisher active; it owns a lock and checkpoint scope for that exact manifest.
If AWS login expires, authenticate that profile before resuming. A completed
layer upload alone is insufficient: continue only after the publisher reports
the independently verified manifest and `ReadyForPlan = True`.

The old digest `cc21a77a...74df16` identifies the failing 1.20.2 artifact. Never
reuse it as the replacement or substitute the archive hash/config ID for the
registry manifest digest. Review scans for this new digest separately; scan
results for an older artifact do not transfer to it. The bounded synthetic
smoke processes no customer video.

## 3. Preserve the G4dn inputs and create a new image-only plan

This block copies the ten existing GPU-only settings, changes only the image
URI, and saves a fresh plan. It relies on the verified URI set by Step 2 in
the same terminal. The old G4dn migration plan has already been applied and
must not be applied again.

```powershell
& {
    $ErrorActionPreference = "Stop"
    Set-Location "C:\Users\kemal\IdeaProjects\CS4501_StartupAws\infra\aws"
    $env:AWS_PROFILE = "strokesense-admin"
    $oldImage = "851226124502.dkr.ecr.us-east-1.amazonaws.com/strokesense-aws-dev-gpu-worker@sha256:cc21a77a44f767fa61ff347ba91e748b3d2acc0914f24a10de54a4a4dc74df16"
    $newImage = $env:TF_VAR_gpu_worker_image_uri
    if ($newImage -cnotmatch '^851226124502\.dkr\.ecr\.us-east-1\.amazonaws\.com/strokesense-aws-dev-gpu-worker@sha256:[a-f0-9]{64}$' -or $newImage -ceq $oldImage) { throw "Publish and verify the replacement image in this terminal first." }
    $inputs = Get-Content -LiteralPath ".\gpu-g4dn-retry.tfvars.json" -Raw | ConvertFrom-Json
    $keys = @("enable_gpu", "gpu_smoke_mode", "gpu_smoke_instance_type", "gpu_smoke_approval", "enable_gpu_image_repository", "enable_paid_gpu_queue_scaffold", "enable_cpu_smoke_queue", "gpu_subnet_id", "gpu_s3_route_table_ids", "gpu_worker_image_uri")
    if ((@($inputs.PSObject.Properties.Name | Sort-Object) -join "|") -cne (@($keys | Sort-Object) -join "|")) { throw "The original GPU input file must contain exactly the ten reviewed GPU settings." }
    if ($inputs.gpu_worker_image_uri -cne $oldImage -or $inputs.gpu_subnet_id -cne "subnet-0ff41bd2fe43be5a8" -or $inputs.gpu_smoke_instance_type -cne "g4dn.xlarge" -or $inputs.gpu_smoke_approval -cne "I_APPROVE_ONE_G4DN_SMOKE_INSTANCE") { throw "Original G4dn inputs differ from the reviewed deployment." }
    foreach ($name in @("enable_gpu", "gpu_smoke_mode", "enable_gpu_image_repository")) {
        if ($inputs.$name -isnot [bool] -or !$inputs.$name) { throw "Expected enabled boolean: $name" }
    }
    foreach ($name in @("enable_paid_gpu_queue_scaffold", "enable_cpu_smoke_queue")) {
        if ($inputs.$name -isnot [bool] -or $inputs.$name) { throw "Expected disabled boolean: $name" }
    }
    if ($inputs.gpu_s3_route_table_ids -isnot [array] -or $inputs.gpu_s3_route_table_ids.Count -ne 0) { throw "Unexpected GPU S3 route changes." }
    $inputs.gpu_worker_image_uri = $newImage
    $inputPath = Join-Path (Get-Location).Path "gpu-image-update.tfvars.json"
    $content = ($inputs | ConvertTo-Json -Depth 6) + [Environment]::NewLine
    if (Test-Path -LiteralPath $inputPath) {
        if ([IO.File]::ReadAllText($inputPath) -cne $content) { throw "The new input filename already contains different values." }
    } else {
        [IO.File]::WriteAllText($inputPath, $content, (New-Object Text.UTF8Encoding($false)))
    }
    $planPath = Join-Path (Get-Location).Path "gpu-image-update.tfplan"
    if (Test-Path -LiteralPath $planPath) { throw "This plan file already exists. Review its status before creating another plan." }
    $planArgs = @("plan", "-input=false", "-var-file=$inputPath", "-target=aws_autoscaling_group.gpu[0]", "-target=aws_ecs_task_definition.gpu_preflight[0]", "-target=aws_ecs_task_definition.gpu[0]", "-out=$planPath")
    terraform @planArgs
    if ($LASTEXITCODE -ne 0) { throw "GPU image update plan failed." }
    $check = .\confirm-gpu-image-plan.ps1 -PlanPath $planPath -ExpectedAccountId 851226124502 -AwsProfile strokesense-admin -ExpectedSubnetId $inputs.gpu_subnet_id -ExpectedPreviousImageUri $oldImage -ExpectedImageUri $newImage
    if (!$check.ReadyForApply) { throw "The image update plan did not pass review." }
    $check | Format-List ReadyForApply, PlanPath, PlanHash, Workspace, ImageUri, LaunchTemplateVersion
}
```

Expected changes are two ECS task-definition replacements, plus optionally
an in-place ASG update removing `Launch` from suspended processes. The ASG
remains `0/0/0`. Terraform usually reports **2 to add, 1 to change, 2 to
destroy** when that latch is present; without it, **2 to add, 0 to change, 2
to destroy**. The replacements are task revisions, not instances.

The validator reads the saved plan and live AWS configuration, requiring:

- The same G4dn numeric launch-template version, AMI, subnet, host settings,
  security groups and permissions.
- Both task images changing from the exact old digest to the verified new
  digest, with GPU requirement `1` and other container settings preserved.
- No active GPU host/task and zero ASG capacity before apply.

These three targets are an exceptional recovery for a deployed failure. They
also keep pending Premium application changes out of this image-only plan.
An eventual full deployment still needs a separately reviewed full plan.

The AMI data source follows AWS's current SSM recommendation. If it changed,
Terraform may propose a host-template update; this image-only validator
rejects it. Review that host change separately. Do not use `-refresh=false`
or relax the validator to disguise it as an image change.

## 4. Apply the exact reviewed plan at zero capacity

```powershell
& {
    $ErrorActionPreference = "Stop"
    Set-Location "C:\Users\kemal\IdeaProjects\CS4501_StartupAws\infra\aws"
    $env:AWS_PROFILE = "strokesense-admin"
    $inputs = Get-Content -LiteralPath ".\gpu-image-update.tfvars.json" -Raw | ConvertFrom-Json
    $review = @{
        PlanPath = ".\gpu-image-update.tfplan"
        ExpectedAccountId = "851226124502"
        AwsProfile = "strokesense-admin"
        ExpectedSubnetId = "subnet-0ff41bd2fe43be5a8"
        ExpectedPreviousImageUri = "851226124502.dkr.ecr.us-east-1.amazonaws.com/strokesense-aws-dev-gpu-worker@sha256:cc21a77a44f767fa61ff347ba91e748b3d2acc0914f24a10de54a4a4dc74df16"
        ExpectedImageUri = $inputs.gpu_worker_image_uri
    }
    $check = .\confirm-gpu-image-plan.ps1 @review
    if (!$check.ReadyForApply) { throw "The saved image plan is not verified." }
    if ((Get-FileHash -LiteralPath $check.PlanPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $check.PlanHash) { throw "The plan changed after review." }
    $workspace = terraform workspace show
    if ($LASTEXITCODE -ne 0 -or ($workspace -join "").Trim() -cne $check.Workspace) { throw "Terraform workspace changed." }
    terraform apply "-input=false" $check.PlanPath
    if ($LASTEXITCODE -ne 0) { throw "GPU image apply failed; do not start the smoke." }
    $applied = .\confirm-gpu-image-plan.ps1 @review -VerifyApplied
    if (!$applied.ReadyForSmoke) { throw "Applied GPU image configuration is not verified." }
    $applied | Format-List ReadyForSmoke, ImageUri, InstanceType, SubnetId, LaunchTemplateVersion
}
```

Saved-plan variable warnings mean Terraform uses the values captured when
that plan was created. Changing environment variables during apply cannot
change those saved inputs. The validator checks the actual saved values.
Keep `gpu-image-update.tfvars.json` for later plans; using only the old input
file would select the old image again. Preserve CPU/OAuth and Premium inputs.

## 5. Run one bounded real-GPU test

This is the step that starts one billable G4dn host. It re-verifies the applied
image update, schedules the AWS-side shutdown and runs the pinned model on
CUDA. There is no automated family/AZ retry loop.

```powershell
& {
    $ErrorActionPreference = "Stop"
    Set-Location "C:\Users\kemal\IdeaProjects\CS4501_StartupAws\infra\aws"
    $env:AWS_PROFILE = "strokesense-admin"
    $inputs = Get-Content -LiteralPath ".\gpu-image-update.tfvars.json" -Raw | ConvertFrom-Json
    $oldImage = "851226124502.dkr.ecr.us-east-1.amazonaws.com/strokesense-aws-dev-gpu-worker@sha256:cc21a77a44f767fa61ff347ba91e748b3d2acc0914f24a10de54a4a4dc74df16"
    $applied = .\confirm-gpu-image-plan.ps1 -PlanPath ".\gpu-image-update.tfplan" -ExpectedAccountId 851226124502 -AwsProfile strokesense-admin -ExpectedSubnetId "subnet-0ff41bd2fe43be5a8" -ExpectedPreviousImageUri $oldImage -ExpectedImageUri $inputs.gpu_worker_image_uri -VerifyApplied
    if (!$applied.ReadyForSmoke) { throw "The applied image update is not verified." }
    .\gpu-smoke.ps1 -ExpectedAccountId 851226124502 -AwsProfile strokesense-admin -ExpectedImageUri $inputs.gpu_worker_image_uri -ExpectedInstanceType g4dn.xlarge -ApproveCharge -HardStopMinutes 45
}
```

Keep the terminal open until cleanup finishes. The 45-minute option schedules
a shutdown request; it is not a promise that the test takes 45 minutes or a
fixed spending cap. Success requires the real CUDA inference marker, matching
image digest, finite model results and verified task/instance/root-volume
cleanup. A new failure should expose its precise stage and cause. Preserve
the evidence and use `read-gpu-smoke-logs.ps1` for the exact new attempt if the
first CloudWatch page is incomplete.

## Premium application follow-through

A successful smoke validates the GPU hardware/image path. Premium website
operation additionally requires deploying the prepared entitlement API/UI,
binding the verified owner identity for `kemalgcortuk@gmail.com`, connecting
Premium admission and usage accounting to the durable queue/dispatcher,
reviewing actual worker data access and scans, and running an owner video
through report generation and cleanup. Premium naming and administrator
grants are separate from hardware readiness. Do not mark website GPU
availability true based solely on this synthetic preflight.

Continue with [Premium access](PREMIUM_ACCESS.md) after the CUDA test passes.
