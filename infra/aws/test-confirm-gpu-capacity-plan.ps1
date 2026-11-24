# Offline tests: fake AWS/Terraform reject any operation outside this validator's
# read-only surface. Compatible with Windows PowerShell 5.1 and PowerShell 7.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:Under = Join-Path $PSScriptRoot 'confirm-gpu-capacity-plan.ps1'
$script:Account = '851226124502'
$script:OldSubnet = 'subnet-0f3c6534cee511e6a'
$script:NewSubnet = 'subnet-0123456789abcdef0'
$script:Vpc = 'vpc-0793c6d459d5f8e89'
$script:Asg = 'strokesense-aws-dev-gpu-one-instance'
$script:AsgArn = 'arn:aws:autoscaling:us-east-1:851226124502:autoScalingGroup:11111111-1111-4111-8111-111111111111:autoScalingGroupName/' + $script:Asg
$script:Lt = 'lt-005c322e797a51386'
$script:Cluster = 'arn:aws:ecs:us-east-1:851226124502:cluster/strokesense-aws-dev-paid-gpu'
$script:Task = 'arn:aws:ecs:us-east-1:851226124502:task-definition/strokesense-aws-dev-gpu-preflight:1'
$script:Digest = 'sha256:' + ('a' * 64)
$script:Image = '851226124502.dkr.ecr.us-east-1.amazonaws.com/strokesense-aws-dev-gpu-worker@' + $script:Digest
$script:Canary = 'PRIVATE_TEST_VALUE_NEVER_PRINT_THIS'
$script:Cases = 0
$script:Failures = 0
$script:OriginalLocation = Get-Location
$script:Directory = Join-Path ([IO.Path]::GetTempPath()) ('strokesense-capacity-tests-' + [guid]::NewGuid().ToString('N'))
[void](New-Item -ItemType Directory -Path $script:Directory)
$script:PlanPath = Join-Path $script:Directory 'capacity recovery plan.tfplan'
$script:EnvironmentNames = @('AWS_PROFILE', 'AWS_ACCESS_KEY_ID', 'PYTHONIOENCODING', 'TF_CLI_ARGS', 'TF_CLI_ARGS_show',
  'TF_CLI_ARGS_output', 'TF_CLI_ARGS_workspace', 'TF_VAR_worker_image_tag', 'TF_VAR_enable_cpu_analysis',
  'STROKESENSE_GPU_PLAN_PATH', 'STROKESENSE_GPU_PLAN_HASH', 'STROKESENSE_GPU_APPLIED_PLAN_HASH')
$script:SavedEnvironment = @{}
foreach ($name in $script:EnvironmentNames) { $script:SavedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }

function Copy-FixtureJson($Value) { return (ConvertTo-Json -InputObject $Value -Depth 50 -Compress | ConvertFrom-Json) }
function New-CapacityFixture {
  $before = @{
    id = $script:Asg; name = $script:Asg; arn = $script:AsgArn
    min_size = 0; max_size = 0; desired_capacity = 0; protect_from_scale_in = $false
    vpc_zone_identifier = @($script:OldSubnet); availability_zones = @('us-east-1a')
    suspended_processes = @('Launch', 'ReplaceUnhealthy', 'AZRebalance')
    launch_template = @(@{ id = $script:Lt; name = ''; version = '1' })
    health_check_type = 'EC2'; default_cooldown = 300; capacity_rebalance = $false
    tag = @(@{ key = 'AmazonECSManaged'; value = 'true'; propagate_at_launch = $true })
  }
  $after = Copy-FixtureJson $before
  $after.vpc_zone_identifier = @($script:NewSubnet)
  $after.suspended_processes = @('AZRebalance', 'ReplaceUnhealthy')
  $after.availability_zones = $null
  $ltValue = @{ id = $script:Lt; latest_version = 1; instance_type = 'g6f.xlarge'; image_id = 'ami-0b8f7c7154f9e8f8b' }
  $iamValue = @{ id = 'ecsInstanceRole-strokesense-aws-dev-gpu'; assume_role_policy = '{"Version":"2012-10-17"}' }
  $identity = @{ address = 'data.aws_caller_identity.current'; mode = 'data'; values = @{ account_id = $script:Account } }
  $changes = @(
    @{ address = 'aws_autoscaling_group.gpu[0]'; mode = 'managed'; change = @{ actions = @('update'); before = $before; after = $after; after_unknown = @{ availability_zones = $true } } },
    @{ address = 'aws_launch_template.gpu[0]'; mode = 'managed'; change = @{ actions = @('no-op'); before = (Copy-FixtureJson $ltValue); after = $ltValue; after_unknown = @{} } },
    @{ address = 'aws_iam_role.gpu_ec2_instance[0]'; mode = 'managed'; change = @{ actions = @('no-op'); before = (Copy-FixtureJson $iamValue); after = $iamValue; after_unknown = @{} } }
  )
  $inputs = @{
    aws_region = 'us-east-1'; enable_cpu_smoke_queue = $false; enable_paid_gpu_queue_scaffold = $false
    enable_gpu_image_repository = $true; enable_gpu = $true; gpu_smoke_mode = $true
    gpu_smoke_instance_type = 'g6f.xlarge'
    gpu_smoke_approval = 'I_APPROVE_ONE_G6F_SMOKE_INSTANCE'; gpu_subnet_id = $script:NewSubnet
    gpu_s3_route_table_ids = @(); gpu_worker_image_uri = $script:Image
    # Targeted recovery must not depend on terminal CPU variables or infer a
    # full-stack CPU deployment from otherwise-unused variable defaults.
    enable_cpu_analysis = $false; worker_image_tag = 'cpu-latest'; google_oauth_client_secret = $script:Canary
  }
  $variables = @{}
  foreach ($name in $inputs.Keys) { $variables[$name] = @{ value = $inputs[$name] } }
  $plan = @{
    format_version = '1.2'; terraform_version = '1.10.5'; applyable = $true; complete = $false; errored = $false
    variables = $variables; resource_changes = $changes
    planned_values = @{ root_module = @{ resources = @(
      @{ address = 'aws_autoscaling_group.gpu[0]'; mode = 'managed'; values = $after },
      @{ address = 'aws_launch_template.gpu[0]'; mode = 'managed'; values = $ltValue }
    ) }; outputs = @{ gpu_smoke_subnet_id = @{ sensitive = $false; type = 'string'; value = $script:NewSubnet } } }
    output_changes = @{ gpu_smoke_subnet_id = @{ actions = @('update'); before = $script:OldSubnet; after = $script:NewSubnet; after_unknown = $false } }
    prior_state = @{ values = @{ root_module = @{ resources = @($identity) } } }
  }
  $outputs = @{}
  foreach ($entry in @(
    @('gpu_smoke_asg_name', $script:Asg), @('gpu_smoke_launch_template_id', $script:Lt),
    @('gpu_smoke_launch_template_version', '1'), @('gpu_smoke_ecs_cluster', $script:Cluster),
    @('gpu_smoke_task_definition', $script:Task), @('gpu_smoke_subnet_id', $script:OldSubnet)
  )) { $outputs[$entry[0]] = @{ value = $entry[1] } }
  return @{
    Plan = $plan; Outputs = $outputs; Calls = (New-Object System.Collections.ArrayList); Scenario = ''; WorkspaceCalls = 0
    ExpectedType = 'g6f.xlarge'; ExpectedGpuResource = '0.125'
    Account = $script:Account; PlanPath = $script:PlanPath; Canary = $script:Canary
    LiveAsg = @{ AutoScalingGroupName = $script:Asg; AutoScalingGroupARN = $script:AsgArn
      MinSize = 0; MaxSize = 0; DesiredCapacity = 0; Instances = @(); VPCZoneIdentifier = $script:OldSubnet
      LaunchTemplate = @{ LaunchTemplateId = $script:Lt; Version = '1' }; NewInstancesProtectedFromScaleIn = $false
      SuspendedProcesses = @(@{ ProcessName = 'AZRebalance' }, @{ ProcessName = 'ReplaceUnhealthy' }, @{ ProcessName = 'Launch' }) }
    Subnets = @(
      @{ SubnetId = $script:OldSubnet; OwnerId = $script:Account; VpcId = $script:Vpc; State = 'available'; AvailableIpAddressCount = 16; AvailabilityZone = 'us-east-1a' },
      @{ SubnetId = $script:NewSubnet; OwnerId = $script:Account; VpcId = $script:Vpc; State = 'available'; AvailableIpAddressCount = 32; AvailabilityZone = 'us-east-1b' }
    )
    Reservations = @(); Services = @(); Tasks = @()
    TaskDefinition = @{ taskDefinitionArn = $script:Task; containerDefinitions = @(@{ name = 'gpu-preflight'; image = $script:Image
      resourceRequirements = @(@{ type = 'GPU'; value = '0.125' }) }) }
    Published = @(@{ registryId = $script:Account; imageDigest = $script:Digest })
  }
}
function Find-CapacityChange([string]$Address = 'aws_autoscaling_group.gpu[0]') {
  return ($global:CapacityWorld.Plan.resource_changes | Where-Object { $_.address -ceq $Address }).change
}
function Use-G4dnCapacityFixture {
  $template = Find-CapacityChange 'aws_launch_template.gpu[0]'
  $template.before.instance_type = 'g4dn.xlarge'
  $template.after.instance_type = 'g4dn.xlarge'
  $global:CapacityWorld.Plan.variables.gpu_smoke_instance_type.value = 'g4dn.xlarge'
  $global:CapacityWorld.Plan.variables.gpu_smoke_approval.value = 'I_APPROVE_ONE_G4DN_SMOKE_INSTANCE'
  $global:CapacityWorld.TaskDefinition.containerDefinitions[0].resourceRequirements[0].value = '1'
  $global:CapacityWorld.ExpectedType = 'g4dn.xlarge'
  $global:CapacityWorld.ExpectedGpuResource = '1'
}
function global:aws {
  $a = @($args | ForEach-Object { [string]$_ })
  $op = $a[0] + ' ' + $a[1]
  [void]$global:CapacityWorld.Calls.Add('aws ' + $op)
  if ($a -contains '--profile' -or $env:AWS_PROFILE -cne 'capacity-test-profile' -or $env:AWS_ACCESS_KEY_ID -cne 'fixture-ambient-chain') {
    throw 'The validator changed or bypassed the ambient credential chain.'
  }
  $global:LASTEXITCODE = 0
  $payload = switch -Exact ($op) {
    'sts get-caller-identity' {
      $account = $global:CapacityWorld.Account
      if ($global:CapacityWorld.Scenario -ceq 'wrong-ambient-account') { $account = '111111111111' }
      @{ Account = $account }
    }
    'autoscaling describe-auto-scaling-groups' { @{ AutoScalingGroups = @($global:CapacityWorld.LiveAsg) } }
    'ec2 describe-instances' { @{ Reservations = $global:CapacityWorld.Reservations } }
    'ec2 describe-subnets' { @{ Subnets = $global:CapacityWorld.Subnets } }
    'ecs list-services' { @{ serviceArns = $global:CapacityWorld.Services } }
    'ecs list-tasks' { @{ taskArns = $global:CapacityWorld.Tasks } }
    'ecs describe-task-definition' { @{ taskDefinition = $global:CapacityWorld.TaskDefinition } }
    'ecr describe-images' { @{ imageDetails = $global:CapacityWorld.Published } }
    default { throw "Unexpected AWS operation: $op" }
  }
  return (ConvertTo-Json -InputObject $payload -Depth 50 -Compress)
}
function global:terraform {
  $a = @($args | ForEach-Object { [string]$_ })
  $global:LASTEXITCODE = 0
  if ($a[0] -ceq 'workspace' -and $a[1] -ceq 'show') {
    [void]$global:CapacityWorld.Calls.Add('terraform workspace show')
    $global:CapacityWorld.WorkspaceCalls++
    if ($global:CapacityWorld.Scenario -ceq 'workspace-changed' -and $global:CapacityWorld.WorkspaceCalls -gt 1) { return 'wrong-workspace' }
    return 'capacity-tests'
  }
  if ($a[0] -ceq 'show' -and $a[1] -ceq '-json') {
    [void]$global:CapacityWorld.Calls.Add('terraform show -json')
    if ($a[-1] -cne $global:CapacityWorld.PlanPath) { throw 'Unexpected saved plan path.' }
    if ($global:CapacityWorld.Scenario -ceq 'plan-changed') { [IO.File]::AppendAllText($global:CapacityWorld.PlanPath, 'changed') }
    if ($global:CapacityWorld.Scenario -ceq 'private-show-error') { $global:LASTEXITCODE = 1; return $global:CapacityWorld.Canary }
    if ($global:CapacityWorld.Scenario -ceq 'private-json-error') { return ('{"secret":"' + $global:CapacityWorld.Canary + '",malformed') }
    return (ConvertTo-Json -InputObject $global:CapacityWorld.Plan -Depth 50 -Compress)
  }
  if ($a[0] -ceq 'output' -and $a[1] -ceq '-json') {
    [void]$global:CapacityWorld.Calls.Add('terraform output -json')
    return (ConvertTo-Json -InputObject $global:CapacityWorld.Outputs -Depth 30 -Compress)
  }
  throw 'Unexpected Terraform operation in the read-only validator.'
}
function Invoke-CapacityCase([string]$Scenario, [string]$FailureText = '', [scriptblock]$Mutate = {}) {
  $script:Cases++
  $global:CapacityWorld = New-CapacityFixture
  $global:CapacityWorld.Scenario = $Scenario
  [IO.File]::WriteAllText($script:PlanPath, 'private saved-plan fixture')
  $env:AWS_PROFILE = 'original-profile'
  $env:AWS_ACCESS_KEY_ID = 'fixture-ambient-chain'
  $env:STROKESENSE_GPU_PLAN_PATH = 'old-plan-marker'
  $env:STROKESENSE_GPU_PLAN_HASH = 'old-hash-marker'
  $env:STROKESENSE_GPU_APPLIED_PLAN_HASH = 'old-apply-marker'
  foreach ($name in @('TF_CLI_ARGS', 'TF_CLI_ARGS_show', 'TF_CLI_ARGS_output', 'TF_CLI_ARGS_workspace', 'TF_VAR_worker_image_tag', 'TF_VAR_enable_cpu_analysis')) {
    Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
  }
  & $Mutate
  $profileBefore = [Environment]::GetEnvironmentVariable('AWS_PROFILE', 'Process')
  $encodingBefore = [Environment]::GetEnvironmentVariable('PYTHONIOENCODING', 'Process')
  $messages = New-Object System.Collections.ArrayList
  $failure = ''
  try {
    & $script:Under -PlanPath $script:PlanPath -ExpectedAccountId $script:Account -ExpectedSubnetId $script:NewSubnet `
      -ExpectedImageUri $script:Image -AwsProfile 'capacity-test-profile' *>&1 | ForEach-Object { [void]$messages.Add($_) }
  } catch { $failure = $_.Exception.Message }
  $results = @($messages | Where-Object { $null -ne $_ -and $_.PSObject.Properties['ReadyForApply'] })
  $ok = if ($FailureText) { $failure.Contains($FailureText) -and $results.Count -eq 0 } else {
    !$failure -and $results.Count -eq 1 -and $results[0].ReadyForApply -eq $true -and
      $results[0].OldSubnetId -ceq $script:OldSubnet -and $results[0].SubnetId -ceq $script:NewSubnet -and
      $results[0].ImageUri -ceq $script:Image -and $results[0].AsgName -ceq $script:Asg -and
      $results[0].LaunchTemplateId -ceq $script:Lt -and $results[0].LaunchTemplateVersion -ceq '1' -and
      $results[0].InstanceType -ceq $global:CapacityWorld.ExpectedType -and $results[0].GpuResource -ceq $global:CapacityWorld.ExpectedGpuResource -and
      $results[0].Workspace -ceq 'capacity-tests' -and $results[0].PlanPath -ceq $script:PlanPath -and
      $results[0].PlanHash -ceq (Get-FileHash -LiteralPath $script:PlanPath -Algorithm SHA256).Hash.ToLowerInvariant()
  }
  $messagesText = (@($messages | ForEach-Object { [string]$_ }) -join "`n") + $failure
  $private = !$messagesText.Contains($script:Canary)
  $unchanged = [Environment]::GetEnvironmentVariable('AWS_PROFILE', 'Process') -ceq $profileBefore -and
    [Environment]::GetEnvironmentVariable('PYTHONIOENCODING', 'Process') -ceq $encodingBefore -and $env:AWS_ACCESS_KEY_ID -ceq 'fixture-ambient-chain' -and
    $env:STROKESENSE_GPU_PLAN_PATH -ceq 'old-plan-marker' -and $env:STROKESENSE_GPU_PLAN_HASH -ceq 'old-hash-marker' -and
    $env:STROKESENSE_GPU_APPLIED_PLAN_HASH -ceq 'old-apply-marker' -and !(Test-Path Env:TF_VAR_worker_image_tag) -and !(Test-Path Env:TF_VAR_enable_cpu_analysis)
  if ($ok -and $private -and $unchanged) { Write-Host "PASS $Scenario" }
  else {
    $script:Failures++
    Write-Host "FAIL $Scenario outcome=$ok private=$private preserved=$unchanged error=[$($failure.Replace($script:Canary, '[REDACTED]'))]"
  }
}

try {
  Set-Location -LiteralPath $PSScriptRoot
  $probe = @([pscustomobject]@{ address = 'one' }, [pscustomobject]@{ address = 'two' })
  if ($probe.address -isnot [System.Management.Automation.PSMethod]) { throw 'Array.Address collision fixture did not reproduce.' }
  Write-Host 'PASS Windows PowerShell Array.Address collision represented'
  Invoke-CapacityCase 'valid-targeted-incomplete-plan'
  Invoke-CapacityCase 'valid-g4dn-subnet-only-plan' '' { Use-G4dnCapacityFixture }
  Invoke-CapacityCase 'valid-g4dn-current-type-output' '' {
    Use-G4dnCapacityFixture
    $global:CapacityWorld.Outputs.gpu_smoke_instance_type = @{ value = 'g4dn.xlarge' }
  }
  Invoke-CapacityCase 'subnet-plan-rejects-type-change-input' 'gpu_smoke_instance_type' {
    $global:CapacityWorld.Plan.variables.gpu_smoke_instance_type.value = 'g4dn.xlarge'
  }
  Invoke-CapacityCase 'subnet-plan-rejects-actual-type-migration' 'exactly one in-place' {
    (Find-CapacityChange 'aws_launch_template.gpu[0]').actions = @('update')
    (Find-CapacityChange 'aws_launch_template.gpu[0]').after.instance_type = 'g4dn.xlarge'
  }
  Invoke-CapacityCase 'g4dn-rejects-g6f-approval' 'gpu_smoke_approval' {
    Use-G4dnCapacityFixture
    $global:CapacityWorld.Plan.variables.gpu_smoke_approval.value = 'I_APPROVE_ONE_G6F_SMOKE_INSTANCE'
  }
  Invoke-CapacityCase 'g4dn-rejects-fractional-task' 'GPU requirement' {
    Use-G4dnCapacityFixture
    $global:CapacityWorld.TaskDefinition.containerDefinitions[0].resourceRequirements[0].value = '0.125'
  }
  Invoke-CapacityCase 'g6f-rejects-full-gpu-task' 'GPU requirement' {
    $global:CapacityWorld.TaskDefinition.containerDefinitions[0].resourceRequirements[0].value = '1'
  }
  Invoke-CapacityCase 'missing-gpu-requirement' 'GPU requirement' {
    $global:CapacityWorld.TaskDefinition.containerDefinitions[0].resourceRequirements = @()
  }
  Invoke-CapacityCase 'extra-gpu-requirement' 'GPU requirement' {
    $global:CapacityWorld.TaskDefinition.containerDefinitions[0].resourceRequirements += @{ type = 'GPU'; value = '0.125' }
  }
  Invoke-CapacityCase 'deployed-type-output-drift' 'type output differs' {
    $global:CapacityWorld.Outputs.gpu_smoke_instance_type = @{ value = 'g4dn.xlarge' }
  }
  Invoke-CapacityCase 'missing-type-input' 'gpu_smoke_instance_type' {
    $global:CapacityWorld.Plan.variables.Remove('gpu_smoke_instance_type')
  }
  Invoke-CapacityCase 'valid-unset-profile-and-encoding-restored' '' {
    Remove-Item Env:AWS_PROFILE -ErrorAction SilentlyContinue
    Remove-Item Env:PYTHONIOENCODING -ErrorAction SilentlyContinue
  }
  Invoke-CapacityCase 'valid-launch-already-active' '' {
    (Find-CapacityChange).before.suspended_processes = @('AZRebalance', 'ReplaceUnhealthy')
    $global:CapacityWorld.LiveAsg.SuspendedProcesses = @(@{ ProcessName = 'ReplaceUnhealthy' }, @{ ProcessName = 'AZRebalance' })
  }
  Invoke-CapacityCase 'valid-known-new-zone' '' {
    (Find-CapacityChange).after.availability_zones = @('us-east-1b')
    (Find-CapacityChange).after_unknown = @{}
  }
  Invoke-CapacityCase 'valid-provider-retains-computed-old-zone' '' {
    (Find-CapacityChange).after.availability_zones = @('us-east-1a')
    (Find-CapacityChange).after_unknown = @{}
  }
  Invoke-CapacityCase 'valid-reordered-object-fields' '' {
    $old = (Find-CapacityChange).after
    $ordered = [ordered]@{}
    foreach ($name in @($old.PSObject.Properties.Name | Sort-Object -Descending)) { $ordered[$name] = $old.$name }
    (Find-CapacityChange).after = $ordered
  }
  Invoke-CapacityCase 'valid-pruned-unrelated-outputs' '' {
    $global:CapacityWorld.Plan.output_changes['cpu_batch_job_definition_arn'] = @{ actions = @('update'); after_unknown = $true }
  }
  Invoke-CapacityCase 'wrong-ambient-account' 'Ambient AWS credentials'
  Invoke-CapacityCase 'nonapplyable' 'applyable and error-free' { $global:CapacityWorld.Plan.applyable = $false }
  Invoke-CapacityCase 'errored' 'applyable and error-free' { $global:CapacityWorld.Plan.errored = $true }
  Invoke-CapacityCase 'deferred' 'Deferred changes' { $global:CapacityWorld.Plan.deferred_changes = @(@{ reason = 'instance_count_unknown' }) }
  Invoke-CapacityCase 'original-fifteen-creates' 'exactly one in-place' { (Find-CapacityChange).actions = @('create') }
  Invoke-CapacityCase 'asg-replacement' 'exactly one in-place' { (Find-CapacityChange).actions = @('delete', 'create') }
  Invoke-CapacityCase 'api-change' 'exactly one in-place' {
    $global:CapacityWorld.Plan.resource_changes += @{ address = 'aws_lambda_function.api'; mode = 'managed'; change = @{ actions = @('update'); before = @{}; after = @{}; after_unknown = @{} } }
  }
  Invoke-CapacityCase 'lt-update' 'exactly one in-place' { (Find-CapacityChange 'aws_launch_template.gpu[0]').actions = @('update') }
  Invoke-CapacityCase 'iam-update' 'exactly one in-place' { (Find-CapacityChange 'aws_iam_role.gpu_ec2_instance[0]').actions = @('update') }
  Invoke-CapacityCase 'duplicate-resource' 'Duplicate managed resource' { $global:CapacityWorld.Plan.resource_changes += $global:CapacityWorld.Plan.resource_changes[0] }
  Invoke-CapacityCase 'move' 'moves and imports' { $global:CapacityWorld.Plan.resource_changes[0].previous_address = 'aws_autoscaling_group.old[0]' }
  Invoke-CapacityCase 'import' 'moves and imports' { (Find-CapacityChange).importing = @{ id = $script:Asg } }
  Invoke-CapacityCase 'unknown-max' 'Unknown ASG safety field' { (Find-CapacityChange).after_unknown.max_size = $true }
  Invoke-CapacityCase 'unknown-lt' 'Unknown resource values' { (Find-CapacityChange 'aws_launch_template.gpu[0]').after_unknown.id = $true }
  Invoke-CapacityCase 'changed-launch-template' 'Unexpected ASG field change' { (Find-CapacityChange).after.launch_template[0].version = '2' }
  Invoke-CapacityCase 'hidden-asg-change' 'Unexpected ASG field change' { (Find-CapacityChange).after.default_cooldown = 1 }
  Invoke-CapacityCase 'nonzero-capacity' 'known numeric zero' { (Find-CapacityChange).before.max_size = 1; (Find-CapacityChange).after.max_size = 1 }
  Invoke-CapacityCase 'null-capacity' 'known numeric zero' { (Find-CapacityChange).before.max_size = $null; (Find-CapacityChange).after.max_size = $null }
  Invoke-CapacityCase 'string-false-protection' 'protection must remain disabled' { (Find-CapacityChange).before.protect_from_scale_in = 'false'; (Find-CapacityChange).after.protect_from_scale_in = 'false' }
  Invoke-CapacityCase 'multiple-subnets' 'single expected different subnet' { (Find-CapacityChange).after.vpc_zone_identifier = @($script:NewSubnet, $script:OldSubnet) }
  Invoke-CapacityCase 'wrong-subnet' 'single expected different subnet' { (Find-CapacityChange).after.vpc_zone_identifier = @($script:OldSubnet) }
  Invoke-CapacityCase 'launch-still-suspended' 'Only removal of the Launch' { (Find-CapacityChange).after.suspended_processes = @('AZRebalance', 'ReplaceUnhealthy', 'Launch') }
  Invoke-CapacityCase 'unsafe-resume' 'Only removal of the Launch' { (Find-CapacityChange).after.suspended_processes = @('AZRebalance') }
  Invoke-CapacityCase 'different-image-input' 'Unexpected effective Terraform input: gpu_worker_image_uri' { $global:CapacityWorld.Plan.variables.gpu_worker_image_uri.value = 'wrong' }
  Invoke-CapacityCase 'disabled-gpu' 'Unexpected effective Terraform input: enable_gpu' { $global:CapacityWorld.Plan.variables.enable_gpu.value = $false }
  Invoke-CapacityCase 'non-smoke' 'Unexpected effective Terraform input: gpu_smoke_mode' { $global:CapacityWorld.Plan.variables.gpu_smoke_mode.value = $false }
  Invoke-CapacityCase 'queue-scaffold-enabled' 'Unexpected effective Terraform input: enable_paid_gpu_queue_scaffold' { $global:CapacityWorld.Plan.variables.enable_paid_gpu_queue_scaffold.value = $true }
  Invoke-CapacityCase 'route-change' 'Unexpected effective Terraform input: gpu_s3_route_table_ids' { $global:CapacityWorld.Plan.variables.gpu_s3_route_table_ids.value = @('rtb-12345678') }
  Invoke-CapacityCase 'missing-caller' 'Missing Terraform caller identity' { $global:CapacityWorld.Plan.prior_state.values.root_module.resources = @() }
  Invoke-CapacityCase 'wrong-caller' 'caller identity does not match' { $global:CapacityWorld.Plan.prior_state.values.root_module.resources[0].values.account_id = '111111111111' }
  Invoke-CapacityCase 'duplicate-caller' 'Duplicate Terraform caller identity' { $global:CapacityWorld.Plan.prior_state.values.root_module.resources += $global:CapacityWorld.Plan.prior_state.values.root_module.resources[0] }
  Invoke-CapacityCase 'old-output' 'planned GPU subnet output' { $global:CapacityWorld.Plan.planned_values.outputs.gpu_smoke_subnet_id.value = $script:OldSubnet }
  Invoke-CapacityCase 'unknown-output' 'planned GPU subnet output' { $global:CapacityWorld.Plan.output_changes.gpu_smoke_subnet_id.after_unknown = $true }
  Invoke-CapacityCase 'wrong-existing-asg' 'ASG identity does not match' { (Find-CapacityChange).before.id = 'wrong'; (Find-CapacityChange).after.id = 'wrong' }
  Invoke-CapacityCase 'live-asg-busy' 'known numeric zero' { $global:CapacityWorld.LiveAsg.DesiredCapacity = 1 }
  Invoke-CapacityCase 'live-asg-member' 'Live ASG instances' { $global:CapacityWorld.LiveAsg.Instances = @(@{ InstanceId = 'i-test' }) }
  Invoke-CapacityCase 'live-subnet-drift' 'Live ASG identity' { $global:CapacityWorld.LiveAsg.VPCZoneIdentifier = $script:NewSubnet }
  Invoke-CapacityCase 'live-template-drift' 'Live ASG identity' { $global:CapacityWorld.LiveAsg.LaunchTemplate.Version = '2' }
  Invoke-CapacityCase 'live-process-drift' 'process suspensions differ' { $global:CapacityWorld.LiveAsg.SuspendedProcesses = @() }
  Invoke-CapacityCase 'tagged-instance' 'Tagged nonterminated' { $global:CapacityWorld.Reservations = @(@{ Instances = @(@{ InstanceId = 'i-test' }) }) }
  Invoke-CapacityCase 'running-task' 'GPU ECS running/pending tasks' { $global:CapacityWorld.Tasks = @('arn:task') }
  Invoke-CapacityCase 'ecs-service' 'GPU ECS services' { $global:CapacityWorld.Services = @('arn:service') }
  Invoke-CapacityCase 'different-vpc' 'same VPC' { $global:CapacityWorld.Subnets[1].VpcId = 'vpc-1234567890abcdef0' }
  Invoke-CapacityCase 'wrong-subnet-account' 'Subnet account' { $global:CapacityWorld.Subnets[1].OwnerId = '111111111111' }
  Invoke-CapacityCase 'no-free-ips' 'two free IPv4' { $global:CapacityWorld.Subnets[1].AvailableIpAddressCount = 1 }
  Invoke-CapacityCase 'same-zone' 'different eligible AZ' { $global:CapacityWorld.Subnets[1].AvailabilityZone = 'us-east-1a' }
  Invoke-CapacityCase 'wrong-computed-zone' 'Computed ASG availability zones' { (Find-CapacityChange).after.availability_zones = @('us-east-1f'); (Find-CapacityChange).after_unknown = @{} }
  Invoke-CapacityCase 'wrong-task-image' 'current preflight task' { $global:CapacityWorld.TaskDefinition.containerDefinitions[0].image = 'wrong' }
  Invoke-CapacityCase 'unpublished-image' 'selected image digest' { $global:CapacityWorld.Published = @() }
  Invoke-CapacityCase 'wrong-ecr-account' 'selected image digest' { $global:CapacityWorld.Published[0].registryId = '111111111111' }
  Invoke-CapacityCase 'workspace-changed' 'workspace changed'
  Invoke-CapacityCase 'plan-changed' 'saved plan changed'
  Invoke-CapacityCase 'private-show-error' 'Saved Terraform plan inspection failed'
  Invoke-CapacityCase 'private-json-error' 'Saved Terraform plan inspection returned invalid JSON'
} finally {
  foreach ($name in $script:EnvironmentNames) {
    if ($null -eq $script:SavedEnvironment[$name]) { Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue }
    else { [Environment]::SetEnvironmentVariable($name, $script:SavedEnvironment[$name], 'Process') }
  }
  Set-Location -LiteralPath $script:OriginalLocation.ProviderPath
  Remove-Item Function:global:aws -ErrorAction SilentlyContinue
  Remove-Item Function:global:terraform -ErrorAction SilentlyContinue
  Remove-Variable CapacityWorld -Scope Global -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $script:Directory -Recurse -Force -ErrorAction SilentlyContinue
}
if ($script:Failures) { throw "$script:Failures of $script:Cases capacity-plan scenarios failed." }
Write-Host "All $script:Cases capacity-plan scenarios passed."
