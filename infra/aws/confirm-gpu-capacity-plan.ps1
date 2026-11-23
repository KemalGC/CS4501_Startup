# Validate one saved, targeted ASG subnet-recovery plan. This script only reads
# Terraform/AWS; it never plans, applies, resumes processes, or starts capacity.
[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$PlanPath,
  [Parameter(Mandatory=$true)][string]$ExpectedAccountId,
  [Parameter(Mandatory=$true)][string]$ExpectedSubnetId,
  [Parameter(Mandatory=$true)][string]$ExpectedImageUri,
  [string]$AwsProfile = 'strokesense-admin'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$region = 'us-east-1'
$asgAddress = 'aws_autoscaling_group.gpu[0]'

function Read-CapacityField($Object, [string]$Name) {
  if ($null -ne $Object -and $Object.PSObject.Properties[$Name]) {
    # Preserve empty and singleton arrays on Windows PowerShell 5.1.
    return ,$Object.$Name
  }
  return $null
}
function Count-CapacityItems($Value) {
  if ($null -eq $Value) { return 0 }
  return @($Value).Count
}
function Invoke-CapacityNative([string]$Command, [string[]]$Arguments) {
  $previousPreference = $ErrorActionPreference
  try {
    $ErrorActionPreference = 'Continue'
    $raw = & $Command @Arguments 2>&1
    $code = $LASTEXITCODE
  } finally { $ErrorActionPreference = $previousPreference }
  $message = (@($raw | ForEach-Object {
    if ($_ -is [System.Management.Automation.ErrorRecord]) { [string]$_.Exception.Message }
    else { [string]$_ }
  }) -join "`n").Trim()
  return [pscustomobject]@{ Code = $code; Text = $message }
}
function Read-CapacityJson([string]$Command, [string[]]$Arguments, [string]$Label) {
  $response = Invoke-CapacityNative $Command $Arguments
  if ($response.Code -ne 0) { throw "$Label failed (exit $($response.Code))." }
  try { $value = $response.Text | ConvertFrom-Json }
  catch { throw "$Label returned invalid JSON." }
  if ($null -eq $value) { throw "$Label returned empty JSON." }
  return ,$value
}
function Read-CapacityAws([string[]]$Arguments) {
  # No explicit --profile: retain the same ambient credential chain Terraform
  # uses, including any credential environment variables already in the shell.
  return Read-CapacityJson 'aws' ($Arguments + @('--region', $region, '--output', 'json',
    '--no-cli-pager', '--no-cli-auto-prompt', '--cli-connect-timeout', '10', '--cli-read-timeout', '30')) `
    "AWS $($Arguments[0]) $($Arguments[1])"
}
function Read-CapacityWorkspace {
  $response = Invoke-CapacityNative 'terraform' @('workspace', 'show')
  if ($response.Code -ne 0 -or !$response.Text -or $response.Text -match '\s') {
    throw 'Cannot identify the current Terraform workspace.'
  }
  return $response.Text
}
function Read-CapacityOutput([string]$Name) {
  $value = Read-CapacityField (Read-CapacityField $outputs $Name) 'value'
  if ($value -isnot [string] -or !$value) { throw "Missing current Terraform output: $Name" }
  return $value
}
function Convert-CapacityCanonical($Value) {
  if ($null -eq $Value) { return $null }
  if ($Value -is [System.Collections.IDictionary] -or $Value -is [pscustomobject]) {
    [string[]]$names = @(if ($Value -is [System.Collections.IDictionary]) { $Value.Keys } else { $Value.PSObject.Properties | ForEach-Object { $_.Name } })
    [Array]::Sort($names, [StringComparer]::Ordinal)
    $result = [ordered]@{}
    foreach ($name in $names) { $result[$name] = Convert-CapacityCanonical $Value.$name }
    return $result
  }
  if ($Value -is [System.Collections.IEnumerable] -and $Value -isnot [string]) {
    $result = New-Object System.Collections.ArrayList
    foreach ($entry in $Value) { [void]$result.Add((Convert-CapacityCanonical $entry)) }
    return ,($result.ToArray())
  }
  return $Value
}
function Compare-CapacityValue($Left, $Right) {
  $a = ConvertTo-Json -InputObject (Convert-CapacityCanonical $Left) -Depth 80 -Compress
  $b = ConvertTo-Json -InputObject (Convert-CapacityCanonical $Right) -Depth 80 -Compress
  return $a -ceq $b
}
function Test-CapacityUnknown($Value) {
  if ($null -eq $Value) { return $false }
  if ($Value -is [bool]) { return $Value }
  if ($Value -is [pscustomobject] -or $Value -is [System.Collections.IDictionary]) {
    $names = @(if ($Value -is [System.Collections.IDictionary]) { $Value.Keys } else { $Value.PSObject.Properties | ForEach-Object { $_.Name } })
    foreach ($name in $names) { if (Test-CapacityUnknown $Value.$name) { return $true } }
    return $false
  }
  if ($Value -is [System.Collections.IEnumerable] -and $Value -isnot [string]) {
    foreach ($entry in $Value) { if (Test-CapacityUnknown $entry) { return $true } }
    return $false
  }
  return $true # Malformed unknown metadata must not be treated as false.
}
function Assert-CapacityZero($Object, [string[]]$Fields, [string]$Label) {
  foreach ($field in $Fields) {
    $value = Read-CapacityField $Object $field
    if (($value -isnot [int] -and $value -isnot [long] -and $value -isnot [double] -and $value -isnot [decimal]) -or $value -ne 0) {
      throw "$Label must have known numeric zero for $field."
    }
  }
}
function Assert-CapacityEmpty($Object, [string]$Field, [string]$Label) {
  $value = Read-CapacityField $Object $Field
  if ($null -eq $value -or $value -isnot [array] -or $value.Count -ne 0) { throw "$Label must be confirmed empty." }
}
function Read-CapacityCaller {
  $address = 'data.aws_caller_identity.current'
  $accounts = New-Object System.Collections.ArrayList
  $changes = @($plan.resource_changes | Where-Object { (Read-CapacityField $_ 'address') -ceq $address })
  if ($changes.Count -gt 1) { throw 'Duplicate Terraform caller identity in resource changes.' }
  if ($changes.Count -eq 1) {
    $change = $changes[0].change
    if ($changes[0].mode -cne 'data' -or ($change.actions -join ',') -cne 'no-op' -or
        (Test-CapacityUnknown (Read-CapacityField $change 'after_unknown'))) {
      throw 'Terraform caller identity is deferred or unknown.'
    }
    [void]$accounts.Add((Read-CapacityField $change.after 'account_id'))
  }
  $prior = Read-CapacityField (Read-CapacityField (Read-CapacityField $plan 'prior_state') 'values') 'root_module'
  $planned = Read-CapacityField (Read-CapacityField $plan 'planned_values') 'root_module'
  foreach ($root in @($prior, $planned)) {
    $matches = @((Read-CapacityField $root 'resources') | Where-Object { (Read-CapacityField $_ 'address') -ceq $address })
    if ($matches.Count -gt 1) { throw 'Duplicate Terraform caller identity in saved state/values.' }
    if ($matches.Count -eq 1) {
      if ($matches[0].mode -cne 'data') { throw 'Invalid Terraform caller identity resource mode.' }
      [void]$accounts.Add((Read-CapacityField $matches[0].values 'account_id'))
    }
  }
  if ($accounts.Count -eq 0) { throw 'Missing Terraform caller identity in the saved plan.' }
  foreach ($account in $accounts) {
    if ($account -isnot [string] -or $account -cne $ExpectedAccountId) { throw 'Terraform caller identity does not match the expected AWS account.' }
  }
}

$savedProfile = [Environment]::GetEnvironmentVariable('AWS_PROFILE', 'Process')
$savedPythonEncoding = [Environment]::GetEnvironmentVariable('PYTHONIOENCODING', 'Process')
$savedConsoleEncoding = [Console]::OutputEncoding
try {
  if ($ExpectedAccountId -cnotmatch '^\d{12}$') { throw 'ExpectedAccountId must contain 12 digits.' }
  if ($ExpectedSubnetId -cnotmatch '^subnet-[a-f0-9]{8,17}$') { throw 'ExpectedSubnetId must identify an existing subnet.' }
  if ($AwsProfile -cnotmatch '^[A-Za-z0-9_.-]{1,64}$') { throw 'AwsProfile is invalid.' }
  $imagePattern = '^' + [regex]::Escape($ExpectedAccountId) + '\.dkr\.ecr\.us-east-1\.amazonaws\.com/([a-z0-9][a-z0-9._/-]*)@(sha256:[a-f0-9]{64})$'
  if ($ExpectedImageUri -cnotmatch $imagePattern) { throw 'ExpectedImageUri must be a digest-pinned ECR image in the expected account and region.' }
  $imageMatch = [regex]::Match($ExpectedImageUri, $imagePattern)
  if ((Get-Location).Provider.Name -ne 'FileSystem' -or (Get-Location).ProviderPath -ne $PSScriptRoot) {
    throw 'Run this validator from its existing infra/aws directory and Terraform workspace.'
  }
  foreach ($name in @('TF_CLI_ARGS', 'TF_CLI_ARGS_show', 'TF_CLI_ARGS_output', 'TF_CLI_ARGS_workspace')) {
    if ([Environment]::GetEnvironmentVariable($name, 'Process')) { throw "Review $name before validating the saved plan." }
  }
  foreach ($tool in @('aws', 'terraform')) { if (!(Get-Command $tool -ErrorAction SilentlyContinue)) { throw "$tool is required." } }
  if (!(Test-Path -LiteralPath $PlanPath -PathType Leaf)) { throw 'The saved Terraform plan file does not exist.' }
  $resolvedPath = (Get-Item -LiteralPath $PlanPath).FullName
  $hashBefore = (Get-FileHash -LiteralPath $resolvedPath -Algorithm SHA256).Hash.ToLowerInvariant()
  $env:AWS_PROFILE = $AwsProfile
  $env:PYTHONIOENCODING = 'utf-8'
  [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
  $identity = Read-CapacityAws @('sts', 'get-caller-identity')
  if ((Read-CapacityField $identity 'Account') -cne $ExpectedAccountId) { throw 'Ambient AWS credentials point to the wrong account.' }
  $workspace = Read-CapacityWorkspace
  $plan = Read-CapacityJson 'terraform' @('show', '-json', $resolvedPath) 'Saved Terraform plan inspection'
  if ((Read-CapacityField $plan 'format_version') -cnotmatch '^1\.') { throw 'Unsupported Terraform plan JSON format.' }
  if ((Read-CapacityField $plan 'applyable') -isnot [bool] -or !$plan.applyable -or
      (Read-CapacityField $plan 'errored') -isnot [bool] -or $plan.errored) {
    throw 'The targeted recovery plan must be applyable and error-free.'
  }
  # -target intentionally makes complete=false. Actual deferrals remain denied.
  if ((Count-CapacityItems (Read-CapacityField $plan 'deferred_changes')) -ne 0) { throw 'Deferred changes are not permitted in a capacity recovery plan.' }
  $managed = @($plan.resource_changes | Where-Object { (Read-CapacityField $_ 'mode') -ceq 'managed' })
  $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
  foreach ($entry in $plan.resource_changes) {
    if (!$seen.Add([string]$entry.address)) { throw 'Duplicate managed resource address in the plan.' }
    if ($null -ne (Read-CapacityField $entry 'previous_address') -or $null -ne (Read-CapacityField $entry.change 'importing')) { throw 'Resource moves and imports are not permitted.' }
    $unknown = Read-CapacityField $entry.change 'after_unknown'
    if ($entry.address -ceq $asgAddress -and $unknown -is [pscustomobject]) {
      foreach ($field in @($unknown.PSObject.Properties | ForEach-Object { $_.Name })) {
        if ($field -cne 'availability_zones' -and (Test-CapacityUnknown $unknown.$field)) { throw "Unknown ASG safety field: $field" }
      }
    } elseif (Test-CapacityUnknown $unknown) { throw 'Unknown resource values are not permitted.' }
    if ($entry.mode -ceq 'data' -and ($entry.change.actions -join ',') -cne 'no-op') { throw 'Deferred data-source reads are not permitted.' }
    if (($entry.change.actions -join ',') -ceq 'no-op' -and !(Compare-CapacityValue $entry.change.before $entry.change.after)) {
      throw 'A no-op dependency contains inconsistent before/after values.'
    }
  }
  $changes = @($managed | Where-Object { ($_.change.actions -join ',') -cne 'no-op' })
  if ($changes.Count -ne 1 -or $changes[0].address -cne $asgAddress -or ($changes[0].change.actions -join ',') -cne 'update') {
    throw 'Require exactly one in-place GPU ASG update, zero creates/destroys, and no other managed changes.'
  }
  $before = $changes[0].change.before
  $after = $changes[0].change.after
  if ($null -eq $before -or $null -eq $after) { throw 'The existing ASG before/after values are required.' }
  $names = @(@($before.PSObject.Properties.Name) + @($after.PSObject.Properties.Name) | Sort-Object -Unique)
  foreach ($name in $names) {
    if ($name -cin @('vpc_zone_identifier', 'suspended_processes', 'availability_zones')) { continue }
    if (!(Compare-CapacityValue (Read-CapacityField $before $name) (Read-CapacityField $after $name))) { throw "Unexpected ASG field change: $name" }
  }
  foreach ($value in @($before, $after)) {
    Assert-CapacityZero $value @('min_size', 'max_size', 'desired_capacity') 'The saved ASG'
    if ((Read-CapacityField $value 'protect_from_scale_in') -isnot [bool] -or $value.protect_from_scale_in) { throw 'ASG instance protection must remain disabled.' }
  }
  $oldSubnets = @((Read-CapacityField $before 'vpc_zone_identifier'))
  $newSubnets = @((Read-CapacityField $after 'vpc_zone_identifier'))
  if ($oldSubnets.Count -ne 1 -or $oldSubnets[0] -cnotmatch '^subnet-[a-f0-9]{8,17}$' -or
      $newSubnets.Count -ne 1 -or $newSubnets[0] -cne $ExpectedSubnetId -or $oldSubnets[0] -ceq $ExpectedSubnetId) {
    throw 'ASG must move from one existing subnet to the single expected different subnet.'
  }
  $oldSubnetId = [string]$oldSubnets[0]
  $oldProcesses = @((Read-CapacityField $before 'suspended_processes') | Sort-Object)
  $newProcesses = @((Read-CapacityField $after 'suspended_processes') | Sort-Object)
  if (($oldProcesses -join ',') -cnotin @('AZRebalance,ReplaceUnhealthy', 'AZRebalance,Launch,ReplaceUnhealthy') -or
      ($newProcesses -join ',') -cne 'AZRebalance,ReplaceUnhealthy') {
    throw 'Only removal of the Launch suspension is permitted; replacement and rebalance stay suspended.'
  }
  $expectedInputs = [ordered]@{
    aws_region = $region; enable_cpu_smoke_queue = $false
    enable_paid_gpu_queue_scaffold = $false; enable_gpu_image_repository = $true
    enable_gpu = $true; gpu_smoke_mode = $true; gpu_smoke_approval = 'I_APPROVE_ONE_G6F_SMOKE_INSTANCE'
    gpu_subnet_id = $ExpectedSubnetId; gpu_s3_route_table_ids = @(); gpu_worker_image_uri = $ExpectedImageUri
  }
  foreach ($name in $expectedInputs.Keys) {
    $entry = Read-CapacityField $plan.variables $name
    if ($null -eq $entry -or !(Compare-CapacityValue (Read-CapacityField $entry 'value') $expectedInputs[$name])) { throw "Unexpected effective Terraform input: $name" }
  }
  Read-CapacityCaller
  $subnetOutput = Read-CapacityField (Read-CapacityField $plan.planned_values 'outputs') 'gpu_smoke_subnet_id'
  $outputChange = Read-CapacityField (Read-CapacityField $plan 'output_changes') 'gpu_smoke_subnet_id'
  if ((Read-CapacityField $subnetOutput 'value') -cne $ExpectedSubnetId -or
      (Test-CapacityUnknown (Read-CapacityField $outputChange 'after_unknown')) -or
      ($null -ne $outputChange -and (Read-CapacityField $outputChange 'after') -cne $ExpectedSubnetId)) {
    throw 'The planned GPU subnet output must be known and equal the new subnet.'
  }
  $outputs = Read-CapacityJson 'terraform' @('output', '-json') 'Current Terraform output inspection'
  $asgName = Read-CapacityOutput 'gpu_smoke_asg_name'
  $ltId = Read-CapacityOutput 'gpu_smoke_launch_template_id'
  $ltVersion = Read-CapacityOutput 'gpu_smoke_launch_template_version'
  $cluster = Read-CapacityOutput 'gpu_smoke_ecs_cluster'
  $taskDefinition = Read-CapacityOutput 'gpu_smoke_task_definition'
  $accountPattern = [regex]::Escape($ExpectedAccountId)
  if ($asgName -cnotmatch '^strokesense-[a-z0-9-]+-gpu-one-instance$' -or $ltId -cnotmatch '^lt-[a-f0-9]{8,17}$' -or $ltVersion -cnotmatch '^[1-9][0-9]*$' -or
      $cluster -cnotmatch "^arn:aws:ecs:us-east-1:${accountPattern}:cluster/strokesense-[a-z0-9-]+-gpu$" -or
      $taskDefinition -cnotmatch "^arn:aws:ecs:us-east-1:${accountPattern}:task-definition/strokesense-[a-z0-9-]+-gpu-preflight:[1-9][0-9]*$" -or
      (Read-CapacityOutput 'gpu_smoke_subnet_id') -cne $oldSubnetId) { throw 'Current Terraform outputs do not match the existing smoke stack.' }
  $asgArnPattern = '^arn:aws:autoscaling:us-east-1:' + $accountPattern + ':autoScalingGroup:[a-f0-9-]{36}:autoScalingGroupName/' + [regex]::Escape($asgName) + '$'
  if ($before.id -cne $asgName -or $before.name -cne $asgName -or $before.arn -cnotmatch $asgArnPattern) { throw 'The saved ASG identity does not match the existing account and stack.' }
  $templates = @((Read-CapacityField $after 'launch_template'))
  if ($templates.Count -ne 1 -or $templates[0].id -cne $ltId -or [string]$templates[0].version -cne $ltVersion) { throw 'The saved ASG launch template must match its existing numeric version.' }
  $templateChanges = @($managed | Where-Object { $_.address -ceq 'aws_launch_template.gpu[0]' })
  if ($templateChanges.Count -ne 1 -or ($templateChanges[0].change.actions -join ',') -cne 'no-op' -or
      $templateChanges[0].change.after.id -cne $ltId -or [string]$templateChanges[0].change.after.latest_version -cne $ltVersion -or
      $templateChanges[0].change.after.instance_type -cne 'g6f.xlarge') { throw 'The existing g6f.xlarge launch-template dependency must be unchanged.' }
  $groups = @((Read-CapacityField (Read-CapacityAws @('autoscaling', 'describe-auto-scaling-groups', '--auto-scaling-group-names', $asgName)) 'AutoScalingGroups'))
  if ($groups.Count -ne 1) { throw 'Expected exactly one live smoke ASG.' }
  $group = $groups[0]
  Assert-CapacityZero $group @('MinSize', 'MaxSize', 'DesiredCapacity') 'The live ASG'
  Assert-CapacityEmpty $group 'Instances' 'Live ASG instances'
  if ($group.AutoScalingGroupName -cne $asgName -or $group.AutoScalingGroupARN -cne $before.arn -or
      $group.VPCZoneIdentifier -cne $oldSubnetId -or $group.LaunchTemplate.LaunchTemplateId -cne $ltId -or [string]$group.LaunchTemplate.Version -cne $ltVersion -or
      (Read-CapacityField $group 'NewInstancesProtectedFromScaleIn') -isnot [bool] -or $group.NewInstancesProtectedFromScaleIn) { throw 'Live ASG identity, subnet, template or protection differs from the saved plan.' }
  $liveProcesses = @((Read-CapacityField $group 'SuspendedProcesses') | ForEach-Object { $_.ProcessName } | Sort-Object)
  if (!(Compare-CapacityValue $liveProcesses $oldProcesses)) { throw 'Live ASG process suspensions differ from the saved plan.' }
  $reservations = Read-CapacityAws @('ec2', 'describe-instances', '--filters', "Name=tag:aws:autoscaling:groupName,Values=$asgName",
    'Name=instance-state-name,Values=pending,running,stopping,stopped,shutting-down')
  Assert-CapacityEmpty $reservations 'Reservations' 'Tagged nonterminated GPU instances'
  $services = Read-CapacityAws @('ecs', 'list-services', '--cluster', $cluster)
  Assert-CapacityEmpty $services 'serviceArns' 'GPU ECS services'
  $tasks = Read-CapacityAws @('ecs', 'list-tasks', '--cluster', $cluster, '--desired-status', 'RUNNING')
  Assert-CapacityEmpty $tasks 'taskArns' 'GPU ECS running/pending tasks'
  $subnets = @((Read-CapacityField (Read-CapacityAws @('ec2', 'describe-subnets', '--subnet-ids', $oldSubnetId, $ExpectedSubnetId)) 'Subnets'))
  $oldSubnet = @($subnets | Where-Object { $_.SubnetId -ceq $oldSubnetId })
  $newSubnet = @($subnets | Where-Object { $_.SubnetId -ceq $ExpectedSubnetId })
  if ($subnets.Count -ne 2 -or $oldSubnet.Count -ne 1 -or $newSubnet.Count -ne 1) { throw 'Both exact existing subnets must be returned once.' }
  foreach ($subnet in $subnets) {
    if ($subnet.OwnerId -cne $ExpectedAccountId -or $subnet.State -cne 'available' -or $subnet.VpcId -cnotmatch '^vpc-[a-f0-9]{8,17}$') { throw 'Subnet account, VPC or availability is invalid.' }
  }
  if ($oldSubnet[0].VpcId -cne $newSubnet[0].VpcId -or $newSubnet[0].AvailableIpAddressCount -lt 2 -or
      $newSubnet[0].AvailabilityZone -cnotmatch '^us-east-1[bcd]$' -or $oldSubnet[0].AvailabilityZone -ceq $newSubnet[0].AvailabilityZone) { throw 'The new subnet must be in the same VPC, a different eligible AZ, and have at least two free IPv4 addresses.' }
  $oldZones = @((Read-CapacityField $before 'availability_zones'))
  $newZones = @((Read-CapacityField $after 'availability_zones'))
  $zonesUnknown = Test-CapacityUnknown (Read-CapacityField (Read-CapacityField $changes[0].change 'after_unknown') 'availability_zones')
  if ($oldZones.Count -ne 1 -or $oldZones[0] -cne $oldSubnet[0].AvailabilityZone -or
      (!$zonesUnknown -and ($newZones.Count -ne 1 -or $newZones[0] -cnotin @($oldSubnet[0].AvailabilityZone, $newSubnet[0].AvailabilityZone)))) { throw 'Computed ASG availability zones are inconsistent with the verified subnet move.' }
  $task = Read-CapacityField (Read-CapacityAws @('ecs', 'describe-task-definition', '--task-definition', $taskDefinition)) 'taskDefinition'
  $containers = @((Read-CapacityField $task 'containerDefinitions'))
  if ((Read-CapacityField $task 'taskDefinitionArn') -cne $taskDefinition -or $containers.Count -ne 1 -or $containers[0].name -cne 'gpu-preflight' -or $containers[0].image -cne $ExpectedImageUri) { throw 'The current preflight task must use the exact expected image.' }
  $published = @((Read-CapacityField (Read-CapacityAws @('ecr', 'describe-images', '--repository-name', $imageMatch.Groups[1].Value,
    '--image-ids', ('imageDigest=' + $imageMatch.Groups[2].Value))) 'imageDetails'))
  if ($published.Count -ne 1 -or $published[0].imageDigest -cne $imageMatch.Groups[2].Value -or $published[0].registryId -cne $ExpectedAccountId) { throw 'The selected image digest is not confirmed in the expected ECR registry.' }
  if ((Read-CapacityWorkspace) -cne $workspace) { throw 'Terraform workspace changed during validation.' }
  $hashAfter = (Get-FileHash -LiteralPath $resolvedPath -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($hashAfter -cne $hashBefore) { throw 'The saved plan changed during validation.' }
  Write-Host 'CAPACITY PLAN VERIFIED: 0 creates, 1 ASG update, 0 destroys; capacity remains 0/0/0.'
  Write-Host 'No apply, process resume, or GPU launch ran. Keep the saved plan private.'
  [pscustomobject]@{ ReadyForApply = $true; PlanPath = $resolvedPath; PlanHash = $hashAfter; Workspace = $workspace
    OldSubnetId = $oldSubnetId; SubnetId = $ExpectedSubnetId; ImageUri = $ExpectedImageUri; AsgName = $asgName
    LaunchTemplateId = $ltId; LaunchTemplateVersion = $ltVersion }
} finally {
  [Console]::OutputEncoding = $savedConsoleEncoding
  foreach ($entry in @(@{ Name = 'AWS_PROFILE'; Value = $savedProfile }, @{ Name = 'PYTHONIOENCODING'; Value = $savedPythonEncoding })) {
    if ($null -eq $entry.Value) { Remove-Item -LiteralPath ('Env:' + $entry.Name) -ErrorAction SilentlyContinue }
    else { [Environment]::SetEnvironmentVariable($entry.Name, $entry.Value, 'Process') }
  }
}
