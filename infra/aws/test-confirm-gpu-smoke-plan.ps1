# Offline regression tests for the saved GPU plan validator. The in-memory
# aws/terraform fakes reject every operation except the expected read calls.
# powershell -NoProfile -File infra/aws/test-confirm-gpu-smoke-plan.ps1
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:Under = Join-Path $PSScriptRoot 'confirm-gpu-smoke-plan.ps1'
$script:ImageUri = '851226124502.dkr.ecr.us-east-1.amazonaws.com/strokesense-aws-dev-gpu-worker@sha256:' + ('a' * 64)
$script:SubnetId = 'subnet-0f3c6534cee511e6a'
$script:VpcId = 'vpc-0793c6d459d5f8e89'
$script:CpuTag = 'media-20261119122801'
$script:SecretCanary = 'TEST_ONLY_SECRET_SHOULD_NOT_APPEAR_IN_DIAGNOSTICS'
$script:Failures = 0
$script:CaseCount = 0
$script:OriginalLocation = Get-Location
$script:TempDirectory = Join-Path ([IO.Path]::GetTempPath()) ('strokesense-plan-tests-' + [guid]::NewGuid().ToString('N'))
$script:PlanPath = Join-Path $script:TempDirectory 'saved GPU plan.tfplan'
[void](New-Item -ItemType Directory -Path $script:TempDirectory)

$script:MarkerNames = @(
  'STROKESENSE_GPU_PLAN_PATH', 'STROKESENSE_GPU_PLAN_HASH',
  'STROKESENSE_GPU_PLAN_WORKSPACE', 'STROKESENSE_GPU_APPLIED_PLAN_HASH',
  'STROKESENSE_GPU_APPLIED', 'STROKESENSE_GPU_PLAN_APPLIED'
)
$script:EnvironmentNames = $script:MarkerNames + @(
  'AWS_PROFILE', 'TF_VAR_worker_image_tag', 'TF_VAR_enable_cpu_analysis',
  'TF_CLI_ARGS', 'TF_CLI_ARGS_show', 'TF_CLI_ARGS_workspace', 'PYTHONIOENCODING'
)
$script:SavedEnvironment = @{}
foreach ($name in $script:EnvironmentNames) {
  $script:SavedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

function New-PlanFixture {
  $expected = @(
    'aws_ecs_cluster.gpu[0]', 'aws_iam_role.gpu_ec2_instance[0]',
    'aws_iam_role_policy_attachment.gpu_ec2_instance[0]', 'aws_iam_instance_profile.gpu_ec2[0]',
    'aws_security_group.gpu_instance[0]', 'aws_security_group.gpu_task[0]',
    'aws_launch_template.gpu[0]', 'aws_autoscaling_group.gpu[0]',
    'aws_ecs_capacity_provider.gpu[0]', 'aws_ecs_cluster_capacity_providers.gpu[0]',
    'aws_iam_role.gpu_worker[0]', 'aws_iam_role_policy.gpu_worker[0]',
    'aws_cloudwatch_log_group.gpu_worker[0]', 'aws_ecs_task_definition.gpu[0]',
    'aws_ecs_task_definition.gpu_preflight[0]'
  )
  $resources = New-Object System.Collections.ArrayList
  $changes = New-Object System.Collections.ArrayList
  foreach ($address in $expected) {
    $values = @{}
    switch -Exact ($address) {
      'aws_security_group.gpu_instance[0]' { $values.vpc_id = $script:VpcId }
      'aws_security_group.gpu_task[0]' { $values.vpc_id = $script:VpcId }
      'aws_autoscaling_group.gpu[0]' {
        $values = @{ min_size = 0; max_size = 0; desired_capacity = 0; protect_from_scale_in = $false
          vpc_zone_identifier = @($script:SubnetId); suspended_processes = @('AZRebalance', 'ReplaceUnhealthy') }
      }
      'aws_launch_template.gpu[0]' {
        # AWS provider 6.73 serializes this optional flag as a string in the
        # operator's actual plan. Casting the string "false" to bool is unsafe.
        $values = @{ instance_type = 'g6f.xlarge'; network_interfaces = @(@{ associate_public_ip_address = 'true' }) }
      }
      'aws_ecs_capacity_provider.gpu[0]' {
        $values = @{ auto_scaling_group_provider = @(@{
          managed_draining = 'DISABLED'; managed_termination_protection = 'DISABLED'
          managed_scaling = @(@{ status = 'DISABLED' })
        }) }
      }
      'aws_ecs_task_definition.gpu[0]' {
        $values.container_definitions = ConvertTo-Json -InputObject @(@{ name = 'gpu-worker'; image = $script:ImageUri }) -Compress
      }
      'aws_ecs_task_definition.gpu_preflight[0]' {
        $values.container_definitions = ConvertTo-Json -InputObject @(@{ name = 'gpu-preflight'; image = $script:ImageUri }) -Compress
      }
    }
    [void]$resources.Add(@{ address = $address; mode = 'managed'; values = $values })
    [void]$changes.Add(@{ address = $address; mode = 'managed'
      change = @{ actions = @('create'); before = $null; after = $values; after_unknown = @{} } })
  }
  $cpuValues = @{ container_properties = '{"image":"cpu-worker:media-20261119122801"}' }
  # Terraform 1.10.5 omits already-read data sources from planned_values and
  # resource_changes. Their refreshed values live in prior_state, even on a
  # first plan. Match that real emitted shape instead of inventing a planned
  # caller-identity resource that made the earlier fixture falsely reassuring.
  $identityResource = @{ address = 'data.aws_caller_identity.current'; mode = 'data'; values = @{ account_id = '851226124502' } }
  [void]$resources.Add(@{ address = 'aws_security_group.batch_jobs'; mode = 'managed'; values = @{ vpc_id = $script:VpcId } })
  [void]$resources.Add(@{ address = 'aws_batch_job_definition.cpu'; mode = 'managed'; values = $cpuValues })
  [void]$changes.Add(@{ address = 'aws_batch_job_definition.cpu'; mode = 'managed'
    change = @{ actions = @('no-op'); before = $cpuValues; after = $cpuValues; after_unknown = @{} } })
  $inputs = @{
    aws_region = 'us-east-1'; worker_image_tag = $script:CpuTag; enable_cpu_analysis = $true
    enable_cpu_smoke_queue = $false; enable_paid_gpu_queue_scaffold = $false
    enable_gpu_image_repository = $true; enable_gpu = $true; gpu_smoke_mode = $true
    gpu_smoke_approval = 'I_APPROVE_ONE_G6F_SMOKE_INSTANCE'; gpu_subnet_id = $script:SubnetId
    gpu_s3_route_table_ids = @(); gpu_worker_image_uri = $script:ImageUri
    google_oauth_client_secret = $script:SecretCanary
  }
  $variables = @{}
  foreach ($key in $inputs.Keys) { $variables[$key] = @{ value = $inputs[$key] } }
  return @{
    format_version = '1.2'; terraform_version = '1.10.5'; applyable = $true; complete = $true; errored = $false
    variables = $variables; resource_changes = @($changes.ToArray())
    planned_values = @{ root_module = @{ resources = @($resources.ToArray()) } }
    prior_state = @{ format_version = '1.0'; terraform_version = '1.10.5'
      values = @{ root_module = @{ resources = @($identityResource) } } }
  }
}

function Find-PlanResource([string]$Address) {
  return ($global:PlanCheckWorld.Plan.planned_values.root_module.resources | Where-Object { $_.address -ceq $Address })
}
function Find-PlanChange([string]$Address) {
  return ($global:PlanCheckWorld.Plan.resource_changes | Where-Object { $_.address -ceq $Address })
}
function Find-PriorResource([string]$Address) {
  return ($global:PlanCheckWorld.Plan.prior_state.values.root_module.resources | Where-Object { $_.address -ceq $Address })
}
function global:aws {
  $a = @($args | ForEach-Object { [string]$_ })
  $op = $a[0] + ' ' + $a[1]
  [void]$global:PlanCheckWorld.Calls.Add('aws ' + $op)
  $global:LASTEXITCODE = 0
  switch -Exact ($op) {
    'sts get-caller-identity' {
      $account = '851226124502'
      if ($global:PlanCheckWorld.Scenario -eq 'wrong-ambient-account') { $account = '111111111111' }
      return (@{ Account = $account } | ConvertTo-Json -Compress)
    }
    'ec2 describe-subnets' {
      return (@{ Subnets = @(@{ SubnetId = $global:PlanCheckWorld.SubnetId; OwnerId = '851226124502'; VpcId = $global:PlanCheckWorld.VpcId
        State = 'available'; AvailableIpAddressCount = 32; AvailabilityZone = 'us-east-1a' }) } | ConvertTo-Json -Depth 5 -Compress)
    }
    default { throw "Unexpected AWS operation in read-only validator: $op" }
  }
}
function global:terraform {
  $a = @($args | ForEach-Object { [string]$_ })
  $global:LASTEXITCODE = 0
  if ($a[0] -eq 'workspace' -and $a[1] -eq 'show') {
    [void]$global:PlanCheckWorld.Calls.Add('terraform workspace show')
    return 'gpu-tests'
  }
  if ($a[0] -eq 'show' -and $a -contains '-json') {
    [void]$global:PlanCheckWorld.Calls.Add('terraform show -json')
    if ($a[-1] -cne $global:PlanCheckWorld.PlanPath) { throw 'Validator did not inspect the specified saved plan.' }
    if ($global:PlanCheckWorld.Scenario -eq 'changed-plan-file') {
      [IO.File]::AppendAllText($global:PlanCheckWorld.PlanPath, ' changed during inspection')
    }
    if ($global:PlanCheckWorld.Scenario -eq 'malformed-private-json') {
      return ('{"secret":"' + $global:PlanCheckWorld.SecretCanary + '", malformed')
    }
    if ($global:PlanCheckWorld.Scenario -eq 'failed-private-show') {
      $global:LASTEXITCODE = 1
      return ('private diagnostic ' + $global:PlanCheckWorld.SecretCanary)
    }
    return (ConvertTo-Json -InputObject $global:PlanCheckWorld.Plan -Depth 30 -Compress)
  }
  [void]$global:PlanCheckWorld.Calls.Add('terraform ' + ($a -join ' '))
  throw 'Unexpected Terraform operation in read-only validator.'
}

function Invoke-PlanCase([string]$Scenario, [bool]$ExpectFailure, [scriptblock]$Mutate = {}) {
  $script:CaseCount++
  $global:PlanCheckWorld = @{ Scenario = $Scenario; Plan = (New-PlanFixture); Calls = (New-Object System.Collections.ArrayList)
    SubnetId = $script:SubnetId; VpcId = $script:VpcId; PlanPath = $script:PlanPath; SecretCanary = $script:SecretCanary }
  [IO.File]::WriteAllText($script:PlanPath, 'offline saved-plan bytes')
  foreach ($name in $script:MarkerNames) { [Environment]::SetEnvironmentVariable($name, 'stale-marker', 'Process') }
  foreach ($name in @('TF_CLI_ARGS', 'TF_CLI_ARGS_show', 'TF_CLI_ARGS_workspace')) {
    [Environment]::SetEnvironmentVariable($name, $null, 'Process')
  }
  $env:TF_VAR_worker_image_tag = $script:CpuTag
  $env:TF_VAR_enable_cpu_analysis = 'true'
  & $Mutate
  $messages = New-Object System.Collections.ArrayList
  $failure = $null
  try {
    $parameters = @{ PlanPath = $script:PlanPath; ExpectedAccountId = '851226124502'; ExpectedImageUri = $script:ImageUri
      ExpectedSubnetId = $script:SubnetId; AwsProfile = 'test-gpu-plan-profile' }
    & $script:Under @parameters *>&1 | ForEach-Object { [void]$messages.Add($_) }
  } catch { $failure = $_.Exception.Message }
  $results = @($messages | Where-Object { $null -ne $_ -and $_.PSObject.Properties['ReadyForApply'] })
  $result = $null
  if ($results.Count -eq 1) { $result = $results[0] }
  $outcome = (($null -ne $failure) -eq $ExpectFailure)
  $noAppliedMarker = !(Test-Path Env:STROKESENSE_GPU_APPLIED_PLAN_HASH) -and
    !(Test-Path Env:STROKESENSE_GPU_APPLIED) -and !(Test-Path Env:STROKESENSE_GPU_PLAN_APPLIED)
  if ($ExpectFailure) {
    $markers = !(Test-Path Env:STROKESENSE_GPU_PLAN_PATH) -and !(Test-Path Env:STROKESENSE_GPU_PLAN_HASH) -and
      !(Test-Path Env:STROKESENSE_GPU_PLAN_WORKSPACE) -and $noAppliedMarker -and $null -eq $result
  } else {
    $expectedHash = (Get-FileHash -LiteralPath $script:PlanPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $markers = $null -ne $result -and $result.ReadyForApply -eq $true -and $result.Creates -eq 15 -and
      $result.PlanPath -ceq $script:PlanPath -and $result.PlanHash -ceq $expectedHash -and $result.Workspace -ceq 'gpu-tests' -and
      $env:STROKESENSE_GPU_PLAN_PATH -ceq $script:PlanPath -and
      $env:STROKESENSE_GPU_PLAN_HASH -ceq $expectedHash -and
      $env:STROKESENSE_GPU_PLAN_WORKSPACE -ceq 'gpu-tests' -and $noAppliedMarker
  }
  $diagnostics = (@($messages | ForEach-Object { [string]$_ }) -join "`n") + "`n" + $failure
  $private = !$diagnostics.Contains($script:SecretCanary)
  $permitted = @('aws sts get-caller-identity', 'aws ec2 describe-subnets', 'terraform workspace show', 'terraform show -json')
  $readOnly = @($global:PlanCheckWorld.Calls | Where-Object { $_ -cnotin $permitted }).Count -eq 0
  # Assert the scenario reached its intended gate, not an unrelated early error.
  $expectedCalls = 4
  $expectedWorkspaceReads = 1
  if (!$ExpectFailure -or $Scenario -eq 'changed-plan-file') {
    $expectedCalls = 5; $expectedWorkspaceReads = 2
  }
  if ($Scenario -eq 'wrong-ambient-account') { $expectedCalls = 1; $expectedWorkspaceReads = 0 }
  $reachedGate = $global:PlanCheckWorld.Calls.Count -eq $expectedCalls -and
    @($global:PlanCheckWorld.Calls | Where-Object { $_ -ceq 'terraform workspace show' }).Count -eq $expectedWorkspaceReads
  if ($Scenario -ne 'wrong-ambient-account') {
    $reachedGate = $reachedGate -and @($global:PlanCheckWorld.Calls | Where-Object { $_ -ceq 'terraform show -json' }).Count -eq 1
  }
  $expectedReasons = @{
    'unexpected-cpu-update' = 'require exactly 15 GPU creates'
    'unexpected-api-update' = 'require exactly 15 GPU creates'
    'missing-resource' = 'require exactly 15 GPU creates'
    'duplicate-resource' = 'duplicate managed resource address'
    'address-case-mismatch' = 'require exactly 15 GPU creates'
    'resource-replacement' = 'require exactly 15 GPU creates'
    'state-only-move' = 'moves/imports'
    'state-only-import' = 'moves/imports'
    'wrong-worker-image' = 'Unexpected image in aws_ecs_task_definition.gpu[0]'
    'wrong-preflight-image' = 'Unexpected image in aws_ecs_task_definition.gpu_preflight[0]'
    'nonzero-asg' = 'GPU ASG must remain'
    'null-asg-capacity' = 'GPU ASG must remain'
    'unknown-asg-capacity' = 'min_size'
    'changed-cpu-image-input' = 'Unexpected effective Terraform input: worker_image_tag'
    'disabled-cpu-analysis-input' = 'Unexpected effective Terraform input: enable_cpu_analysis'
    'wrong-ambient-account' = 'Ambient AWS credentials point to the wrong account'
    'wrong-planned-account' = 'Terraform is using a different AWS account'
    'wrong-prior-account' = 'Terraform is using a different AWS account'
    'missing-identity' = 'Missing Terraform caller identity in the saved plan'
    'duplicate-prior-identity' = 'Ambiguous Terraform caller identity: duplicate entries in refreshed prior state'
    'duplicate-planned-identity' = 'Ambiguous Terraform caller identity: duplicate entries in planned values'
    'conflicting-identity' = 'Conflicting Terraform caller identity accounts in the saved plan'
    'deferred-identity-read' = 'Terraform caller identity is deferred or changes during apply'
    'unknown-identity-account' = 'Terraform caller identity account is unknown until apply'
    'false-public-ip-string' = 'The GPU host needs the reviewed public-IP interface'
    'null-public-ip-flag' = 'The GPU host needs the reviewed public-IP interface'
    'wrong-existing-vpc' = 'Subnet VPC does not match aws_security_group.batch_jobs'
    'wrong-gpu-vpc' = 'Subnet VPC does not match aws_security_group.gpu_task[0]'
    'changed-plan-file' = 'The saved plan changed during verification'
    'malformed-private-json' = 'The saved Terraform plan did not produce valid JSON'
    'failed-private-show' = 'Cannot inspect the saved Terraform plan'
  }
  $rightReason = !$ExpectFailure -or ([string]$failure).Contains($expectedReasons[$Scenario])
  $inputsPreserved = $env:TF_VAR_worker_image_tag -ceq $script:CpuTag -and $env:TF_VAR_enable_cpu_analysis -ceq 'true'
  if ($outcome -and $markers -and $private -and $readOnly -and $inputsPreserved -and $reachedGate -and $rightReason) {
    Write-Host "PASS $Scenario"
  } else {
    $script:Failures++
    $safeFailure = [string]$failure
    $safeFailure = $safeFailure.Replace($script:SecretCanary, '[REDACTED TEST CANARY]')
    Write-Host "FAIL $Scenario outcome=$outcome markers=$markers private=$private readOnly=$readOnly inputs=$inputsPreserved stage=$reachedGate reason=$rightReason error=[$safeFailure]"
  }
}

try {
  Set-Location -LiteralPath $PSScriptRoot
  # This is the original failure mode: object[] has an Address(int) method.
  # Explicit projection must return the actual resource addresses instead.
  $probe = @([pscustomobject]@{ address = 'one' }, [pscustomobject]@{ address = 'two' })
  if ($probe.address -isnot [System.Management.Automation.PSMethod] -or
      (@($probe | ForEach-Object { $_.address }) -join ',') -cne 'one,two') {
    throw 'The Array.Address collision regression fixture did not reproduce the operator failure.'
  }
  Write-Host 'PASS Array.Address collision reproduced'

  Invoke-PlanCase 'valid-15-resource-plan' $false
  Invoke-PlanCase 'valid-planned-identity' $false {
    $identity = Find-PriorResource 'data.aws_caller_identity.current'
    $global:PlanCheckWorld.Plan.planned_values.root_module.resources += $identity
    $global:PlanCheckWorld.Plan.Remove('prior_state')
  }
  Invoke-PlanCase 'valid-agreeing-identity' $false {
    $global:PlanCheckWorld.Plan.planned_values.root_module.resources += @{
      address = 'data.aws_caller_identity.current'; mode = 'data'; values = @{ account_id = '851226124502' }
    }
  }
  Invoke-PlanCase 'unexpected-cpu-update' $true {
    (Find-PlanChange 'aws_batch_job_definition.cpu').change.actions = @('update')
  }
  Invoke-PlanCase 'unexpected-api-update' $true {
    $global:PlanCheckWorld.Plan.resource_changes += @{ address = 'aws_lambda_function.api'; mode = 'managed'; change = @{ actions = @('update') } }
  }
  Invoke-PlanCase 'missing-resource' $true {
    $global:PlanCheckWorld.Plan.resource_changes = @($global:PlanCheckWorld.Plan.resource_changes | Where-Object { $_.address -cne 'aws_ecs_cluster.gpu[0]' })
  }
  Invoke-PlanCase 'duplicate-resource' $true {
    $global:PlanCheckWorld.Plan.resource_changes += (Find-PlanChange 'aws_ecs_cluster.gpu[0]')
  }
  Invoke-PlanCase 'address-case-mismatch' $true {
    (Find-PlanChange 'aws_ecs_cluster.gpu[0]').address = 'aws_ecs_cluster.GPU[0]'
  }
  Invoke-PlanCase 'resource-replacement' $true {
    (Find-PlanChange 'aws_launch_template.gpu[0]').change.actions = @('delete', 'create')
  }
  Invoke-PlanCase 'state-only-move' $true {
    (Find-PlanChange 'aws_batch_job_definition.cpu').previous_address = 'aws_batch_job_definition.old_cpu'
  }
  Invoke-PlanCase 'state-only-import' $true {
    (Find-PlanChange 'aws_batch_job_definition.cpu').change.importing = @{ id = 'unexpected-import' }
  }
  Invoke-PlanCase 'wrong-worker-image' $true {
    (Find-PlanResource 'aws_ecs_task_definition.gpu[0]').values.container_definitions = '[{"image":"other-image:latest"}]'
  }
  Invoke-PlanCase 'wrong-preflight-image' $true {
    (Find-PlanResource 'aws_ecs_task_definition.gpu_preflight[0]').values.container_definitions = '[{"image":"other-image:latest"}]'
  }
  Invoke-PlanCase 'nonzero-asg' $true {
    (Find-PlanResource 'aws_autoscaling_group.gpu[0]').values.desired_capacity = 1
  }
  Invoke-PlanCase 'null-asg-capacity' $true {
    (Find-PlanResource 'aws_autoscaling_group.gpu[0]').values.max_size = $null
  }
  Invoke-PlanCase 'unknown-asg-capacity' $true {
    (Find-PlanResource 'aws_autoscaling_group.gpu[0]').values.Remove('min_size')
    (Find-PlanChange 'aws_autoscaling_group.gpu[0]').change.after_unknown.min_size = $true
  }
  Invoke-PlanCase 'changed-cpu-image-input' $true {
    $global:PlanCheckWorld.Plan.variables.worker_image_tag.value = 'different-cpu-image'
  }
  Invoke-PlanCase 'disabled-cpu-analysis-input' $true {
    $global:PlanCheckWorld.Plan.variables.enable_cpu_analysis.value = $false
  }
  Invoke-PlanCase 'wrong-ambient-account' $true
  Invoke-PlanCase 'wrong-planned-account' $true {
    $identity = Find-PriorResource 'data.aws_caller_identity.current'
    $identity.values.account_id = '111111111111'
    $global:PlanCheckWorld.Plan.planned_values.root_module.resources += $identity
    $global:PlanCheckWorld.Plan.Remove('prior_state')
  }
  Invoke-PlanCase 'wrong-prior-account' $true {
    (Find-PriorResource 'data.aws_caller_identity.current').values.account_id = '111111111111'
  }
  Invoke-PlanCase 'missing-identity' $true {
    $global:PlanCheckWorld.Plan.Remove('prior_state')
  }
  Invoke-PlanCase 'duplicate-prior-identity' $true {
    $global:PlanCheckWorld.Plan.prior_state.values.root_module.resources += (Find-PriorResource 'data.aws_caller_identity.current')
  }
  Invoke-PlanCase 'duplicate-planned-identity' $true {
    $identity = Find-PriorResource 'data.aws_caller_identity.current'
    $global:PlanCheckWorld.Plan.planned_values.root_module.resources += @($identity, $identity)
  }
  Invoke-PlanCase 'conflicting-identity' $true {
    $global:PlanCheckWorld.Plan.planned_values.root_module.resources += @{
      address = 'data.aws_caller_identity.current'; mode = 'data'; values = @{ account_id = '111111111111' }
    }
  }
  Invoke-PlanCase 'deferred-identity-read' $true {
    $global:PlanCheckWorld.Plan.resource_changes += @{
      address = 'data.aws_caller_identity.current'; mode = 'data'
      change = @{ actions = @('read'); before = @{ account_id = '851226124502' }; after = @{}; after_unknown = @{ account_id = $true } }
    }
  }
  Invoke-PlanCase 'unknown-identity-account' $true {
    $global:PlanCheckWorld.Plan.resource_changes += @{
      address = 'data.aws_caller_identity.current'; mode = 'data'
      change = @{ actions = @('no-op'); before = @{ account_id = '851226124502' }; after = @{}; after_unknown = @{ account_id = $true } }
    }
  }
  Invoke-PlanCase 'false-public-ip-string' $true {
    (Find-PlanResource 'aws_launch_template.gpu[0]').values.network_interfaces[0].associate_public_ip_address = 'false'
  }
  Invoke-PlanCase 'null-public-ip-flag' $true {
    (Find-PlanResource 'aws_launch_template.gpu[0]').values.network_interfaces[0].associate_public_ip_address = $null
  }
  Invoke-PlanCase 'wrong-existing-vpc' $true {
    (Find-PlanResource 'aws_security_group.batch_jobs').values.vpc_id = 'vpc-00000000000000000'
  }
  Invoke-PlanCase 'wrong-gpu-vpc' $true {
    (Find-PlanResource 'aws_security_group.gpu_task[0]').values.vpc_id = 'vpc-00000000000000000'
  }
  Invoke-PlanCase 'changed-plan-file' $true
  Invoke-PlanCase 'malformed-private-json' $true
  Invoke-PlanCase 'failed-private-show' $true
} finally {
  Remove-Item Function:\aws -ErrorAction SilentlyContinue
  Remove-Item Function:\terraform -ErrorAction SilentlyContinue
  Remove-Variable PlanCheckWorld -Scope Global -ErrorAction SilentlyContinue
  foreach ($name in $script:EnvironmentNames) {
    [Environment]::SetEnvironmentVariable($name, $script:SavedEnvironment[$name], 'Process')
  }
  Remove-Item -LiteralPath $script:TempDirectory -Recurse -Force -ErrorAction SilentlyContinue
  Set-Location -LiteralPath $script:OriginalLocation.Path
}
if ($script:Failures) { throw "$script:Failures of $script:CaseCount saved GPU plan scenarios failed." }
Write-Host "All $script:CaseCount saved GPU plan scenarios passed."
$global:LASTEXITCODE = 0
