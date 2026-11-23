# Read-only validation of an existing full GPU smoke plan. This script never
# runs terraform plan/apply or launches AWS capacity. Invoke it from infra/aws
# in the terminal holding the recovered deployed CPU inputs.
[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$PlanPath,
  [Parameter(Mandatory=$true)][string]$ExpectedAccountId,
  [Parameter(Mandatory=$true)][string]$ExpectedImageUri,
  [Parameter(Mandatory=$true)][string]$ExpectedSubnetId,
  [string]$AwsProfile = 'strokesense-admin'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$region = 'us-east-1'
$markerNames = @(
  'STROKESENSE_GPU_PLAN_PATH', 'STROKESENSE_GPU_PLAN_HASH',
  'STROKESENSE_GPU_PLAN_WORKSPACE', 'STROKESENSE_GPU_APPLIED_PLAN_HASH',
  'STROKESENSE_GPU_APPLIED', 'STROKESENSE_GPU_PLAN_APPLIED'
)
function Clear-PlanMarkers {
  foreach ($name in $markerNames) { Remove-Item "Env:$name" -ErrorAction SilentlyContinue }
}
Clear-PlanMarkers

function Read-Field($Object, [string]$Name) {
  if ($null -ne $Object -and $Object.PSObject.Properties[$Name]) { return $Object.$Name }
  return $null
}
function Invoke-PlanNative([string]$Command, [string[]]$Arguments) {
  $savedPreference = $ErrorActionPreference
  try {
    # Windows PowerShell redirects native stderr as ErrorRecords. Retain the
    # actual exit code instead of allowing those records to short-circuit it.
    $ErrorActionPreference = 'Continue'
    $raw = & $Command @Arguments 2>&1
    $code = $LASTEXITCODE
  } finally { $ErrorActionPreference = $savedPreference }
  $text = (@($raw | ForEach-Object {
    if ($_ -is [System.Management.Automation.ErrorRecord]) { [string]$_.Exception.Message }
    else { [string]$_ }
  }) -join "`n").Trim()
  return [pscustomobject]@{ Code = $code; Text = $text }
}
function Read-AwsJson([string[]]$Arguments) {
  # Use the same ambient credential chain as Terraform, with AWS_PROFILE set
  # temporarily below. An explicit --profile would bypass credential env vars.
  $result = Invoke-PlanNative 'aws' ($Arguments + @(
    '--region', $region, '--output', 'json', '--no-cli-pager',
    '--no-cli-auto-prompt', '--cli-connect-timeout', '10', '--cli-read-timeout', '30'
  ))
  if ($result.Code -ne 0) {
    throw "AWS $($Arguments[0]) $($Arguments[1]) failed (exit $($result.Code)): $($result.Text)"
  }
  try { $json = $result.Text | ConvertFrom-Json }
  catch { throw "AWS $($Arguments[0]) $($Arguments[1]) returned invalid JSON." }
  if ($null -eq $json) { throw 'AWS returned null JSON.' }
  return $json
}
function Read-Workspace {
  $result = Invoke-PlanNative 'terraform' @('workspace', 'show')
  if ($result.Code -ne 0 -or !$result.Text -or $result.Text -match '\s') {
    throw 'Cannot identify the current Terraform workspace.'
  }
  return $result.Text
}
function Read-PlannedResource([string]$Address) {
  $selected = @($plan.planned_values.root_module.resources | Where-Object { $_.address -ceq $Address })
  if ($selected.Count -ne 1) { throw "Missing or ambiguous planned resource: $Address" }
  return $selected[0].values
}

$savedProfile = [Environment]::GetEnvironmentVariable('AWS_PROFILE', 'Process')
$savedPythonEncoding = [Environment]::GetEnvironmentVariable('PYTHONIOENCODING', 'Process')
$savedConsoleEncoding = [Console]::OutputEncoding
try {
  if ($ExpectedAccountId -cnotmatch '^\d{12}$') { throw 'ExpectedAccountId must contain 12 digits.' }
  if ($ExpectedSubnetId -cnotmatch '^subnet-[a-f0-9]{8,17}$') { throw 'ExpectedSubnetId must identify an existing subnet.' }
  $imagePattern = '^' + [regex]::Escape($ExpectedAccountId) + '\.dkr\.ecr\.us-east-1\.amazonaws\.com/[a-z0-9][a-z0-9._/-]*@sha256:[a-f0-9]{64}$'
  if ($ExpectedImageUri -cnotmatch $imagePattern) { throw 'ExpectedImageUri must be a digest-pinned ECR image in the expected account and region.' }
  if ($AwsProfile -cnotmatch '^[A-Za-z0-9_.-]{1,64}$') { throw 'AwsProfile is invalid.' }
  if ((Get-Location).Provider.Name -ne 'FileSystem' -or (Get-Location).ProviderPath -ne $PSScriptRoot) {
    throw 'Run this script from its existing infra/aws directory and Terraform workspace.'
  }
  foreach ($name in @('TF_CLI_ARGS', 'TF_CLI_ARGS_show', 'TF_CLI_ARGS_workspace')) {
    if ([Environment]::GetEnvironmentVariable($name, 'Process')) { throw "Review $name before validating the saved plan." }
  }
  foreach ($tool in @('aws', 'terraform')) {
    if (!(Get-Command $tool -ErrorAction SilentlyContinue)) { throw "$tool is required." }
  }
  if (!(Test-Path -LiteralPath $PlanPath -PathType Leaf)) { throw 'The saved Terraform plan file does not exist.' }
  $resolvedPlanPath = (Get-Item -LiteralPath $PlanPath).FullName
  $hashBefore = (Get-FileHash -LiteralPath $resolvedPlanPath -Algorithm SHA256).Hash.ToLowerInvariant()
  $cpuTag = [string]$env:TF_VAR_worker_image_tag
  $cpuEnabled = $false
  if ($cpuTag -cnotmatch '^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$' -or $cpuTag -ceq 'cpu-latest') {
    throw 'The recovered deployed CPU image tag is missing from this terminal.'
  }
  if (![bool]::TryParse([string]$env:TF_VAR_enable_cpu_analysis, [ref]$cpuEnabled) -or !$cpuEnabled) {
    throw 'The confirmed deployed CPU analysis flag must still be true in this terminal.'
  }

  $env:AWS_PROFILE = $AwsProfile
  $env:PYTHONIOENCODING = 'utf-8'
  [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
  $identity = Read-AwsJson @('sts', 'get-caller-identity')
  if ($identity.Account -cne $ExpectedAccountId) { throw 'Ambient AWS credentials point to the wrong account.' }
  $workspace = Read-Workspace
  $subnetResponse = Read-AwsJson @('ec2', 'describe-subnets', '--subnet-ids', $ExpectedSubnetId)
  $subnets = @($subnetResponse.Subnets)
  if ($subnets.Count -ne 1 -or $null -eq $subnets[0]) { throw 'Exactly one existing subnet is required.' }
  $subnet = $subnets[0]
  if ($subnet.SubnetId -cne $ExpectedSubnetId -or $subnet.OwnerId -cne $ExpectedAccountId -or $subnet.State -cne 'available' -or $null -eq $subnet.AvailableIpAddressCount -or $subnet.AvailableIpAddressCount -lt 2) {
    throw 'Subnet account, state, or available IPv4 addresses failed verification.'
  }
  $vpcId = [string]$subnet.VpcId
  if ($vpcId -cnotmatch '^vpc-[a-f0-9]{8,17}$') { throw 'Subnet VPC information is incomplete.' }

  $jsonResult = Invoke-PlanNative 'terraform' @('show', '-json', $resolvedPlanPath)
  if ($jsonResult.Code -ne 0) { throw "Cannot inspect the saved Terraform plan (exit $($jsonResult.Code))." }
  # This JSON contains sensitive values. Neither it nor a JSON parser exception
  # is printed, including when the native command returns malformed output.
  try { $plan = $jsonResult.Text | ConvertFrom-Json }
  catch { throw 'The saved Terraform plan did not produce valid JSON.' }
  if ($null -eq $plan -or (Read-Field $plan 'format_version') -notmatch '^1\.') { throw 'Unsupported Terraform plan JSON format.' }
  if (($plan.PSObject.Properties['applyable'] -and $plan.applyable -ne $true) -or
      ($plan.PSObject.Properties['errored'] -and $plan.errored -ne $false) -or
      ($plan.PSObject.Properties['complete'] -and $plan.complete -ne $true)) {
    throw 'Terraform did not produce a complete, applyable, error-free plan.'
  }
  $expectedCreates = @(
    'aws_ecs_cluster.gpu[0]'
    'aws_iam_role.gpu_ec2_instance[0]'
    'aws_iam_role_policy_attachment.gpu_ec2_instance[0]'
    'aws_iam_instance_profile.gpu_ec2[0]'
    'aws_security_group.gpu_instance[0]'
    'aws_security_group.gpu_task[0]'
    'aws_launch_template.gpu[0]'
    'aws_autoscaling_group.gpu[0]'
    'aws_ecs_capacity_provider.gpu[0]'
    'aws_ecs_cluster_capacity_providers.gpu[0]'
    'aws_iam_role.gpu_worker[0]'
    'aws_iam_role_policy.gpu_worker[0]'
    'aws_cloudwatch_log_group.gpu_worker[0]'
    'aws_ecs_task_definition.gpu[0]'
    'aws_ecs_task_definition.gpu_preflight[0]'
  )
  $managedChanges = @($plan.resource_changes | Where-Object { $_.mode -ceq 'managed' })
  $stateTransitions = @($managedChanges | Where-Object {
    $null -ne (Read-Field $_ 'previous_address') -or $null -ne (Read-Field $_.change 'importing')
  })
  if ($stateTransitions.Count -ne 0) { throw 'Plan rejected: unexpected existing-resource moves/imports.' }
  $changes = @($managedChanges | Where-Object { ($_.change.actions -join ',') -cne 'no-op' })
  # Arrays have their own .Address method. Never use $changes.address here:
  # that resolves the method, making every expected resource appear missing.
  $actualAddresses = @($changes | ForEach-Object { [string]$_.address })
  $seenAddresses = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
  foreach ($change in $managedChanges) {
    if (!$seenAddresses.Add([string]$change.address)) { throw "Plan rejected: duplicate managed resource address $($change.address)." }
  }
  $invalidChanges = @($changes | Where-Object {
    $_.address -cnotin $expectedCreates -or ($_.change.actions -join ',') -cne 'create'
  })
  $missingCreates = @($expectedCreates | Where-Object { $_ -cnotin $actualAddresses })
  if ($changes.Count -ne 15 -or $invalidChanges.Count -ne 0 -or $missingCreates.Count -ne 0) {
    throw "Plan rejected: require exactly 15 GPU creates and no other managed changes (changes=$($changes.Count), unexpected=$($invalidChanges.Count), missing=$($missingCreates.Count))."
  }

  $expectedInputs = [ordered]@{
    aws_region = $region
    worker_image_tag = $cpuTag
    enable_cpu_analysis = $cpuEnabled
    enable_cpu_smoke_queue = $false
    enable_paid_gpu_queue_scaffold = $false
    enable_gpu_image_repository = $true
    enable_gpu = $true
    gpu_smoke_mode = $true
    gpu_smoke_approval = 'I_APPROVE_ONE_G6F_SMOKE_INSTANCE'
    gpu_subnet_id = $ExpectedSubnetId
    gpu_s3_route_table_ids = @()
    gpu_worker_image_uri = $ExpectedImageUri
  }
  foreach ($key in $expectedInputs.Keys) {
    $entry = $plan.variables.PSObject.Properties[$key]
    if ($null -eq $entry) { throw "Missing effective Terraform input: $key" }
    $actualJson = ConvertTo-Json -InputObject $entry.Value.value -Depth 5 -Compress
    $expectedJson = ConvertTo-Json -InputObject $expectedInputs[$key] -Depth 5 -Compress
    if ($actualJson -cne $expectedJson) { throw "Unexpected effective Terraform input: $key" }
  }
  $plannedIdentity = Read-PlannedResource 'data.aws_caller_identity.current'
  if ($plannedIdentity.account_id -cne $ExpectedAccountId) { throw 'Terraform is using a different AWS account.' }
  foreach ($address in @('aws_security_group.batch_jobs', 'aws_security_group.gpu_instance[0]', 'aws_security_group.gpu_task[0]')) {
    $group = Read-PlannedResource $address
    if ($group.vpc_id -cne $vpcId) { throw "Subnet VPC does not match $address." }
  }
  $asg = Read-PlannedResource 'aws_autoscaling_group.gpu[0]'
  if ($asg.min_size -ne 0 -or $asg.max_size -ne 0 -or $asg.desired_capacity -ne 0 -or $asg.protect_from_scale_in -ne $false) {
    throw 'GPU ASG must remain at min/max/desired 0/0/0 with scale-in allowed.'
  }
  if (@($asg.vpc_zone_identifier).Count -ne 1 -or $asg.vpc_zone_identifier[0] -cne $ExpectedSubnetId) { throw 'ASG subnet differs from the verified subnet.' }
  if ((($asg.suspended_processes | Sort-Object) -join ',') -cne 'AZRebalance,ReplaceUnhealthy') {
    throw 'Expected ASG replacement/rebalance suspension is missing.'
  }
  $template = Read-PlannedResource 'aws_launch_template.gpu[0]'
  if ($template.instance_type -cne 'g6f.xlarge') { throw 'Only g6f.xlarge is approved.' }
  if (@($template.network_interfaces).Count -ne 1 -or $template.network_interfaces[0].associate_public_ip_address -ne $true) {
    throw 'The GPU host needs the reviewed public-IP interface.'
  }
  $capacity = Read-PlannedResource 'aws_ecs_capacity_provider.gpu[0]'
  $capacitySettings = @($capacity.auto_scaling_group_provider)
  if ($capacitySettings.Count -ne 1 -or $capacitySettings[0].managed_draining -cne 'DISABLED' -or $capacitySettings[0].managed_termination_protection -cne 'DISABLED') {
    throw 'GPU managed draining/termination protection must remain disabled for the smoke.'
  }
  $scaling = @($capacitySettings[0].managed_scaling)
  if ($scaling.Count -ne 1 -or $scaling[0].status -cne 'DISABLED') { throw 'GPU automatic scaling must remain disabled.' }
  foreach ($address in @('aws_ecs_task_definition.gpu[0]', 'aws_ecs_task_definition.gpu_preflight[0]')) {
    $task = Read-PlannedResource $address
    try { $containers = @($task.container_definitions | ConvertFrom-Json) }
    catch { throw "Cannot inspect container definitions for $address." }
    if ($containers.Count -ne 1 -or $null -eq $containers[0] -or $containers[0].image -cne $ExpectedImageUri) {
      throw "Unexpected image in $address."
    }
  }
  if ((Read-Workspace) -cne $workspace) { throw 'Terraform workspace changed during plan verification.' }
  $hashAfter = (Get-FileHash -LiteralPath $resolvedPlanPath -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($hashAfter -cne $hashBefore) { throw 'The saved plan changed during verification.' }

  $env:STROKESENSE_GPU_PLAN_PATH = $resolvedPlanPath
  $env:STROKESENSE_GPU_PLAN_HASH = $hashAfter
  $env:STROKESENSE_GPU_PLAN_WORKSPACE = $workspace
  Write-Host 'PLAN VERIFIED: 15 GPU resources to create, 0 changes, 0 destroys. ASG remains 0/0/0.'
  Write-Host 'No apply or GPU launch ran. Keep this terminal open and the saved plan private.'
  [pscustomobject]@{
    ReadyForApply = $true
    PlanPath = $resolvedPlanPath
    PlanHash = $hashAfter
    Workspace = $workspace
    Creates = 15
  }
} catch {
  Clear-PlanMarkers
  throw
} finally {
  [Console]::OutputEncoding = $savedConsoleEncoding
  foreach ($entry in @(
    @{ Name = 'AWS_PROFILE'; Value = $savedProfile },
    @{ Name = 'PYTHONIOENCODING'; Value = $savedPythonEncoding }
  )) {
    if ($null -eq $entry.Value) { Remove-Item "Env:$($entry.Name)" -ErrorAction SilentlyContinue }
    else { [Environment]::SetEnvironmentVariable($entry.Name, $entry.Value, 'Process') }
  }
}
