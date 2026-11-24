# Premium access for the AWS website

This release prepares **Premium** account access and its administration on the
separate `website-aws-dev` site. The owner is
`kemalgcortuk@gmail.com`, resolved to an existing verified Cognito identity by
the operator helper. Other existing users receive or lose Premium through the
admin page. Grants do not require payment and do not create administrator roles.

**GPU job execution remains a separate rollout.** The account response reports
the stored entitlement and runtime availability independently. This release
keeps runtime availability false because the website API is not yet connected
to the GPU dispatch path. A successful hardware smoke test proves CUDA on the
selected host/image; it does not prove website video upload, queueing,
inference, report delivery or automatic cleanup for customer jobs.

## What is implemented

| Route | Purpose | Authorization |
| --- | --- | --- |
| `GET /me` | Read account capabilities; initialize the configured owner's Premium grant once | Cognito access token and a freshly verified matching user identity |
| `GET /admin/users?email=...` | Find one existing user by exact, verified email and inspect access | Existing admin group **and** configured stable-sub allowlist |
| `POST /admin/users/{sub}/premium` | Grant/revoke access with an audit reason | Same admin checks, fresh target-identity verification and atomic audit |

The three routes use the existing API Gateway JWT authorizer. The API Lambda
receives only `ListUsers` and `AdminGetUser` permissions on the existing user
pool; it cannot add administrators or create users. Premium is stored on the
existing users table, without overwriting free-upload quotas or minting billing
credits. The entitlement change and audit event succeed together or neither
is committed.

The configured owner is protected from revocation in the normal admin panel.
Initialization does not overwrite a previous explicit access decision. A
privileged operator can still withdraw access in the backend; a later account
refresh will not silently reverse that decision.

Existing internal `paid` tier values, S3 paths, Terraform names and AWS resource
names remain compatible with deployed jobs and the selected GPU image. User
interfaces display **Premium**. Renaming physical resources is not necessary for
this product-name change.

## Finish the active hardware test first

Let the existing `gpu-smoke.ps1` process finish. Its successful terminal marker is:

> PASS: verified CUDA inference, stopped task, terminated host and deleted root volume.

Retain its evidence folder. A scheduled shutdown confirmation alone does not
prove task completion or instance termination. Do not start another smoke run
or a concurrent Terraform apply while the existing run is active.

The saved-plan variable warnings in the reported run mean Terraform used the
values saved in that plan. The reported `15 added, 0 changed, 0 destroyed`
apply succeeded. Do not reapply that consumed plan, or change `enable_gpu` into
an ephemeral variable. Future plans need the current, deployed GPU inputs,
including the original `gpu-smoke.tfvars.json`; otherwise old GPU-disabled
shell values can propose removing the newly created infrastructure.

If the test completed cleanup after an insufficient-capacity error, follow
[GPU capacity recovery](GPU_CAPACITY_RETRY.md) before another hardware attempt.
It reconstructs GPU-only inputs from the deployed resources and verifies a
subnet in another Availability Zone. This also handles the reported missing
`gpu-smoke.tfvars.json`; the recovery instructions retain the verified inputs
after applying the subnet update. Keep the already prepared
`premium-owner.auto.tfvars.json`. A successful owner verification and Lambda
ZIP build do not need to be repeated merely because the GPU host could not
launch.

If the hardware was switched to G4dn with [the instance retry guide](GPU_INSTANCE_RETRY.md),
use the retained `gpu-g4dn-retry.tfvars.json` as the GPU input file for the next
full deployment plan. The earlier G6f input files specify a different hardware
profile. The dormant website dispatcher remains a separate runtime rollout;
its admission contract must be updated and tested for the selected full GPU
before enabling Premium job submission.

## 1. Update the working checkout

After the active smoke process has completed cleanup, use the same checkout
that contains the real Terraform backend and recovered deployment inputs.

```powershell
& {
    $ErrorActionPreference = "Stop"
    Set-Location "C:\Users\kemal\IdeaProjects\CS4501_StartupAws"
    git pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw "Git update failed." }
    Set-Location ".\infra\aws"
}
```

If the AWS session has expired, renew it with
`aws login --profile strokesense-admin` and complete the browser sign-in.
Keep the existing Google OAuth and other deployed Terraform inputs in their
current protected source. This feature does not need new Google credentials.

## 2. Verify and prepare the owner

Sign in to the AWS website with the owner's Google account once before setup
if it has never been used there. The helper does not create a replacement
Cognito identity.

```powershell
& {
    $ErrorActionPreference = "Stop"
    Set-Location "C:\Users\kemal\IdeaProjects\CS4501_StartupAws\infra\aws"
    $env:AWS_PROFILE = "strokesense-admin"
    $owner = .\prepare-premium-owner.ps1 -ExpectedAccountId 851226124502 -AwsProfile strokesense-admin -EnsureAdminGroup
    if (!$owner.ReadyForPlan) { throw "Owner setup is incomplete; no deployment plan should be created." }
    $owner | Format-List Status, ReadyForPlan, OwnerSub, AdminGroupMember, AdminGroupAdded

    $admins = ConvertFrom-Json -InputObject ('{"values":' + $env:TF_VAR_admin_cognito_subs + '}')
    $privateInputs = [ordered]@{
        premium_owner_sub = $env:TF_VAR_premium_owner_sub
        admin_cognito_subs = $admins.values
    }
    $privatePath = Join-Path (Get-Location).Path "premium-owner.auto.tfvars.json"
    $json = ConvertTo-Json -InputObject $privateInputs -Depth 4
    [IO.File]::WriteAllText($privatePath, $json, (New-Object Text.UTF8Encoding($false)))
    Write-Host "Verified owner inputs saved for subsequent Terraform plans."
}
```

`-EnsureAdminGroup` authorizes the requested owner's membership in the existing
`strokesense-admin` group. The helper first verifies the AWS account, pool,
unambiguous verified email, enabled identity and stable sub. It preserves the
other deployed administrators and any valid administrators already supplied in
`TF_VAR_admin_cognito_subs`. A different previously configured owner causes a
failure rather than silently transferring ownership.

On success it sets only these two Terraform environment inputs in this terminal:

- `TF_VAR_premium_owner_sub`
- `TF_VAR_admin_cognito_subs`

The helper neither deploys Lambda nor changes GPU/CPU settings. Without
`-EnsureAdminGroup`, it performs identity and membership checks without adding
group membership. An unsuccessful check does not publish partial new inputs.

The command block saves these verified values in the local
`premium-owner.auto.tfvars.json`, so subsequent Terraform plans retain them
after the terminal closes. It contains the verified owner sub and merged admin
allowlist only. Keep it alongside the other private deployment inputs; do not
add the values to the public example or hardcode the owner's email in browser
authorization logic. The local `*.tfvars.json` patterns are ignored by Git.

## 3. Build and review the backend deployment

```powershell
& {
    $ErrorActionPreference = "Stop"
    Set-Location "C:\Users\kemal\IdeaProjects\CS4501_StartupAws\infra\aws"
    .\build_lambda.ps1
    if ($LASTEXITCODE -ne 0) { throw "Lambda build failed." }
    terraform validate
    if ($LASTEXITCODE -ne 0) { throw "Terraform validation failed." }
    if (!(Test-Path -LiteralPath ".\gpu-smoke.tfvars.json")) {
        throw "Locate the GPU input file used for the completed smoke apply before planning."
    }
    if (!(Test-Path -LiteralPath ".\premium-owner.auto.tfvars.json")) {
        throw "Complete verified owner setup before creating the deployment plan."
    }
    terraform plan "-var-file=gpu-smoke.tfvars.json" "-var-file=premium-owner.auto.tfvars.json" "-out=premium-access.tfplan"
    if ($LASTEXITCODE -ne 0) { throw "Premium deployment plan failed." }
}
```

If the verified GPU input file was saved elsewhere, use that actual path. Keep
the existing non-GPU deployment inputs as well: CPU image tag, enabled CPU
analysis, limits, concurrency, OAuth settings and alert recipient. Do not copy
the example defaults over those values.

Expected Premium changes are the three authenticated routes, API identity
read permissions, API environment variables/code and the admin group's
description. The reconciler uses the same Lambda ZIP, so its code hash can
change too; its operational settings should be preserved. There should be no
user-pool replacement, CPU job-definition change, media deletion or GPU launch.

Review all actual differences. The smoke runner leaves ASG `Launch` suspended
after cleanup; Terraform can detect that operational change, and its AMI data
lookup can discover a newer image. Treat either GPU difference separately from
this access rollout. Preserve the verified idle state, and do not hide those
differences with a targeted apply. The earlier 15-create smoke-plan validator
is specific to initial GPU infrastructure and is not a validator for this API
deployment.

Once the fresh plan's contents are reviewed, apply that saved file:

```powershell
terraform apply "premium-access.tfplan"
```

Changing `TF_VAR_*` after saving a plan does not change its contents. If inputs
need correction, discard the pending plan and generate a fresh one.

## 4. Publish the AWS website and verify accounts

Use the existing **strokesense-aws-dev** Vercel project and its
`website-aws-dev` root. Keep the current API URL, Cognito domain/client ID,
callback URLs and CPU analysis setting. The Premium frontend rollout flag
stays false during access preparation. The site must successfully load the new
account API before an administrator can grant access.

After backend and website deployment:

1. Sign out and sign back in as `kemalgcortuk@gmail.com`. A fresh access token
   is needed to see newly added Cognito group membership.
2. Open `/demos/`. It should show **Premium access granted** and a separate
   GPU availability message. The free CPU path remains available according to
   its existing controls.
3. Follow **Open admin**, or open `/admin/`. The Premium access panel is
   separate from consented video review.
4. Ask a prospective Premium user to sign in to the AWS site once. Search
   their exact email, confirm the resolved identity, enter an audit reason and
   grant access. Granting Premium does not grant administrator privileges.
5. Ask that user to refresh account access. The server should report the new
   entitlement. Revoke a test grant from the panel and confirm it disappears
   on refresh. No payment or credit purchase is involved.
6. Confirm a normal user cannot use the admin lookup or mutation endpoints,
   and existing CPU analysis/history/private video access still behave as
   before.

## Remaining work before website GPU analysis

After the hardware evidence passes, a separate runtime change must connect
Premium admission to the durable GPU queue/dispatcher, apply bounded usage and
concurrency controls, configure real-video S3 access, and validate one complete
owner-only video job through report delivery and scale-down. Only that verified
runtime rollout should make `/me` report `premium_access.available=true` and
enable the frontend Premium submit option. Changing a UI flag alone cannot
complete this work.

## Offline verification

The CI workflow runs backend unit tests, frontend behavior tests/build,
Terraform formatting/validation, and the owner helper tests under both
Windows PowerShell and PowerShell 7. The helper tests use fake AWS responses
and exercise account/pool mismatches, invalid identity, ambiguous lookup,
native CLI failures, protected owner pins, group changes and preservation of
existing inputs. They do not access AWS.

## Reference behavior

- [Cognito ListUsers](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_ListUsers.html)
  is eventually consistent; the implementation rechecks the candidate with
  [AdminGetUser](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_AdminGetUser.html).
- [DynamoDB transactions](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis.html)
  make the entitlement change and its audit event atomic.
