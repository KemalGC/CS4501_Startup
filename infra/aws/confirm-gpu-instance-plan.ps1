# Read-only gate for the existing G6f -> G4dn migration. Verify the saved plan
# before apply, then use -VerifyApplied to check concrete AWS revisions before
# the separately invoked, charged smoke. This script never changes AWS/state.
[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$PlanPath,
  [Parameter(Mandatory=$true)][string]$ExpectedAccountId,
  [Parameter(Mandatory=$true)][string]$ExpectedSubnetId,
  [Parameter(Mandatory=$true)][string]$ExpectedImageUri,
  [ValidateSet('g4dn.xlarge')][string]$ExpectedInstanceType = 'g4dn.xlarge',
  [string]$AwsProfile = 'strokesense-admin',
  [switch]$VerifyApplied
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$region = 'us-east-1'
$asgAddress = 'aws_autoscaling_group.gpu[0]'
$templateAddress = 'aws_launch_template.gpu[0]'
$preflightAddress = 'aws_ecs_task_definition.gpu_preflight[0]'
$workerAddress = 'aws_ecs_task_definition.gpu[0]'

function Read-InstanceField($Object, [string]$Name) {
  if ($null -ne $Object -and $Object.PSObject.Properties[$Name]) { return ,$Object.$Name }
  return $null
}
function Read-InstanceList($Object, [string]$Name, [string]$Label) {
  $value = Read-InstanceField $Object $Name
  if ($value -isnot [array]) { throw "$Label must contain the $Name array." }
  return ,$value
}
function Convert-InstanceObject([string]$Text, [string]$Label) {
  try { $envelope = ConvertFrom-Json -InputObject ('{"value":' + $Text + '}') -ErrorAction Stop }
  catch { throw "$Label returned invalid JSON." }
  $value = Read-InstanceField $envelope 'value'
  if ($value -isnot [pscustomobject]) { throw "$Label must return a JSON object." }
  return $value
}
function Invoke-InstanceNative([string]$Command, [string[]]$Arguments) {
  $priorPreference = $ErrorActionPreference
  try {
    $ErrorActionPreference = 'Continue'
    $raw = & $Command @Arguments 2>&1
    $code = $LASTEXITCODE
  } finally { $ErrorActionPreference = $priorPreference }
  $lines = @($raw | ForEach-Object {
    if ($_ -is [System.Management.Automation.ErrorRecord]) { [string]$_.Exception.Message }
    else { [string]$_ }
  })
  return [pscustomobject]@{ Code = $code; Text = ($lines -join [Environment]::NewLine).Trim() }
}
function Read-InstanceJson([string]$Command, [string[]]$Arguments, [string]$Label) {
  $result = Invoke-InstanceNative $Command $Arguments
  if ($result.Code -ne 0) { throw "$Label failed (exit $($result.Code))." }
  return Convert-InstanceObject $result.Text $Label
}
function Read-InstanceAws([string[]]$Arguments) {
  # Match Terraform's ambient credential chain; explicit --profile would skip
  # credential environment variables that Terraform may still use.
  $result = Read-InstanceJson 'aws' ($Arguments + @('--region', $region, '--output', 'json', '--no-cli-pager', '--no-cli-auto-prompt', '--cli-connect-timeout', '10', '--cli-read-timeout', '30')) ("AWS " + $Arguments[0] + ' ' + $Arguments[1])
  if ((Read-InstanceField $result 'NextToken') -or (Read-InstanceField $result 'nextToken')) { throw 'AWS returned incomplete pagination.' }
  return $result
}
function Read-InstanceWorkspace {
  $result = Invoke-InstanceNative 'terraform' @('workspace', 'show')
  if ($result.Code -ne 0 -or !$result.Text -or $result.Text -match '\s') { throw 'Cannot identify the Terraform workspace.' }
  return $result.Text
}
function Read-InstanceOutput([string]$Name) {
  $value = Read-InstanceField (Read-InstanceField $outputs $Name) 'value'
  if ($value -isnot [string] -or !$value) { throw "Missing current Terraform output: $Name" }
  return $value
}
function Convert-InstanceCanonical($Value) {
  if ($null -eq $Value) { return $null }
  if ($Value -is [System.Collections.IDictionary] -or $Value -is [pscustomobject]) {
    [string[]]$names = @(if ($Value -is [System.Collections.IDictionary]) { $Value.Keys } else { $Value.PSObject.Properties | ForEach-Object { $_.Name } })
    [Array]::Sort($names, [StringComparer]::Ordinal)
    $result = [ordered]@{}
    foreach ($name in $names) { $result[$name] = Convert-InstanceCanonical $Value.$name }
    return $result
  }
  if ($Value -is [System.Collections.IEnumerable] -and $Value -isnot [string]) {
    $result = New-Object System.Collections.ArrayList
    foreach ($item in $Value) { [void]$result.Add((Convert-InstanceCanonical $item)) }
    return ,($result.ToArray())
  }
  return $Value
}
function Compare-InstanceValue($Left, $Right) {
  $a = ConvertTo-Json -InputObject (Convert-InstanceCanonical $Left) -Depth 80 -Compress
  $b = ConvertTo-Json -InputObject (Convert-InstanceCanonical $Right) -Depth 80 -Compress
  return $a -ceq $b
}
function Test-InstanceUnknown($Value) {
  if ($null -eq $Value) { return $false }
  if ($Value -is [bool]) { return $Value }
  if ($Value -is [System.Collections.IDictionary] -or $Value -is [pscustomobject]) {
    $names = @(if ($Value -is [System.Collections.IDictionary]) { $Value.Keys } else { $Value.PSObject.Properties | ForEach-Object { $_.Name } })
    foreach ($name in $names) { if (Test-InstanceUnknown $Value.$name) { return $true } }
    return $false
  }
  if ($Value -is [System.Collections.IEnumerable] -and $Value -isnot [string]) {
    foreach ($item in $Value) { if (Test-InstanceUnknown $item) { return $true } }
    return $false
  }
  return $true
}
function Assert-InstanceUnchanged($Before, $After, [string[]]$Allowed, [string]$Label) {
  if ($Before -isnot [pscustomobject] -or $After -isnot [pscustomobject]) { throw "$Label requires existing before/after objects." }
  $names = @(@($Before.PSObject.Properties | ForEach-Object { $_.Name }) + @($After.PSObject.Properties | ForEach-Object { $_.Name }) | Sort-Object -Unique)
  foreach ($name in $names) {
    if ($name -cin $Allowed) { continue }
    if (!(Compare-InstanceValue (Read-InstanceField $Before $name) (Read-InstanceField $After $name))) { throw "Unexpected $Label field change: $name" }
  }
}
function Assert-InstanceZero($Value, [string[]]$Fields) {
  foreach ($name in $Fields) {
    $number = Read-InstanceField $Value $name
    if (($number -isnot [int] -and $number -isnot [long] -and $number -isnot [double] -and $number -isnot [decimal]) -or $number -ne 0) {
      throw "ASG $name must be a known numeric zero."
    }
  }
}
function Assert-InstanceEmpty($Value, [string]$Field, [string]$Label) {
  $items = Read-InstanceList $Value $Field $Label
  if ($items.Count -ne 0) { throw "$Label must be empty." }
}
function Assert-InstanceUnknownFields($Unknown, [string[]]$Allowed, [string]$Label) {
  if ($null -eq $Unknown) { return }
  if ($Unknown -isnot [pscustomobject]) { throw "Malformed $Label unknown metadata." }
  foreach ($property in $Unknown.PSObject.Properties) {
    if (!(Test-InstanceUnknown $property.Value)) { continue }
    if ($property.Name -cnotin $Allowed -or $property.Value -isnot [bool] -or !$property.Value) { throw "Unknown $Label safety field: $($property.Name)" }
  }
}
function Read-InstanceCaller {
  $accounts = New-Object System.Collections.ArrayList
  $address = 'data.aws_caller_identity.current'
  $changes = @($plan.resource_changes | Where-Object { $_.address -ceq $address })
  if ($changes.Count -gt 1) { throw 'Duplicate saved caller identity.' }
  if ($changes.Count -eq 1) {
    if ($changes[0].mode -cne 'data' -or ($changes[0].change.actions -join ',') -cne 'no-op') { throw 'Saved caller identity is deferred.' }
    [void]$accounts.Add((Read-InstanceField $changes[0].change.after 'account_id'))
  }
  $priorRoot = Read-InstanceField (Read-InstanceField (Read-InstanceField $plan 'prior_state') 'values') 'root_module'
  $plannedRoot = Read-InstanceField (Read-InstanceField $plan 'planned_values') 'root_module'
  foreach ($root in @($priorRoot, $plannedRoot)) {
    $matches = @((Read-InstanceField $root 'resources') | Where-Object { (Read-InstanceField $_ 'address') -ceq $address })
    if ($matches.Count -gt 1) { throw 'Duplicate saved caller identity.' }
    if ($matches.Count -eq 1) {
      if ($matches[0].mode -cne 'data') { throw 'Invalid saved caller identity mode.' }
      [void]$accounts.Add((Read-InstanceField $matches[0].values 'account_id'))
    }
  }
  if ($accounts.Count -eq 0) { throw 'Missing saved caller identity.' }
  foreach ($account in $accounts) {
    if ($account -isnot [string] -or $account -cne $ExpectedAccountId) { throw 'Saved caller identity does not match the expected account.' }
  }
}
function Read-InstanceContainers([string]$Text) {
  try { $wrapper = ConvertFrom-Json -InputObject ('{"containers":' + $Text + '}') -ErrorAction Stop }
  catch { throw 'Task container definitions are invalid JSON.' }
  $items = Read-InstanceList $wrapper 'containers' 'Task container definitions'
  if ($items.Count -ne 1 -or $items[0] -isnot [pscustomobject]) { throw 'Each GPU task must contain exactly one container.' }
  return ,$items
}
function Convert-InstanceContainer($Container) {
  # ECS adds semantically empty/default fields on read. Normalize only these
  # documented absence defaults; keep every nonempty security/runtime setting.
  $result = Convert-InstanceCanonical $Container
  foreach ($name in @('environment','environmentFiles','mountPoints','portMappings','volumesFrom','systemControls','secrets','dependsOn','ulimits','links','extraHosts','dnsServers','dnsSearchDomains','dockerSecurityOptions','credentialSpecs')) {
    if ($result.Contains($name) -and ($null -eq $result[$name] -or ($result[$name] -is [array] -and $result[$name].Count -eq 0))) { $result.Remove($name) }
  }
  foreach ($name in @('privileged','readonlyRootFilesystem','disableNetworking','interactive','pseudoTerminal')) {
    if ($result.Contains($name) -and $result[$name] -is [bool] -and !$result[$name]) { $result.Remove($name) }
  }
  if ($result.Contains('essential') -and $result.essential -is [bool] -and $result.essential) { $result.Remove('essential') }
  if ($result.Contains('cpu') -and $result.cpu -eq 0 -and $result.cpu -isnot [string]) { $result.Remove('cpu') }
  if ($result.Contains('logConfiguration') -and $null -ne $result.logConfiguration -and $result.logConfiguration.Contains('secretOptions')) {
    $options = $result.logConfiguration.secretOptions
    if ($null -eq $options -or ($options -is [array] -and $options.Count -eq 0)) { $result.logConfiguration.Remove('secretOptions') }
  }
  return $result
}
function Assert-InstanceContainer($Container, [string]$Name, [string]$GpuUnits) {
  if ((Read-InstanceField $Container 'name') -cne $Name -or (Read-InstanceField $Container 'image') -cne $ExpectedImageUri) { throw 'GPU container name or image differs from the reviewed image.' }
  $requirements = Read-InstanceList $Container 'resourceRequirements' 'GPU container'
  if ($requirements.Count -ne 1 -or $requirements[0].type -cne 'GPU' -or [string]$requirements[0].value -cne $GpuUnits) { throw 'GPU container resource requirement does not match the reviewed instance.' }
}
function Assert-InstanceFaultInjectionDisabled($Task, [string]$Field) {
  # ECS defaults this optional boolean to false. Provider readback can expose
  # false while a replacement plan omits the unset argument or represents it
  # as null. Only those disabled representations are equivalent; never coerce
  # strings/numbers or permit an enabled value. Unknowns are checked separately.
  # https://docs.aws.amazon.com/AmazonECS/latest/APIReference/API_RegisterTaskDefinition.html
  $value = Read-InstanceField $Task $Field
  if ($null -ne $value -and ($value -isnot [bool] -or $value)) {
    throw 'Fault injection must remain disabled in each reviewed GPU task definition.'
  }
}
function Assert-InstanceTaskPlan($Entry, [string]$ContainerName) {
  if (($Entry.change.actions -join ',') -cnotin @('delete,create','create,delete')) { throw 'Both GPU task definitions must register replacement revisions.' }
  $before = $Entry.change.before; $after = $Entry.change.after
  Assert-InstanceFaultInjectionDisabled $before 'enable_fault_injection'
  Assert-InstanceFaultInjectionDisabled $after 'enable_fault_injection'
  Assert-InstanceUnchanged $before $after @('arn','arn_without_revision','id','revision','container_definitions','enable_fault_injection') 'task definition'
  Assert-InstanceUnknownFields (Read-InstanceField $Entry.change 'after_unknown') @('arn','arn_without_revision','id','revision') 'task definition'
  if ($before.network_mode -cne 'awsvpc' -or !(Compare-InstanceValue $before.requires_compatibilities @('EC2')) -or
      [string]$before.cpu -cne '2048' -or [string]$before.memory -cne '8192') { throw 'Task CPU, memory or EC2 networking differs from the reviewed smoke.' }
  if ($ContainerName -ceq 'gpu-preflight' -and (Read-InstanceField $before 'task_role_arn')) { throw 'Preflight must not carry a customer task role.' }
  $oldContainers = Read-InstanceContainers $before.container_definitions
  $newContainers = Read-InstanceContainers $after.container_definitions
  Assert-InstanceContainer $oldContainers[0] $ContainerName '0.125'
  Assert-InstanceContainer $newContainers[0] $ContainerName $profile.GpuResource
  $left = Convert-InstanceContainer $oldContainers[0]
  $right = Convert-InstanceContainer $newContainers[0]
  $left.Remove('resourceRequirements'); $right.Remove('resourceRequirements')
  if (!(Compare-InstanceValue $left $right)) { throw 'Only the GPU allocation may change inside task container definitions.' }
}
function Assert-InstanceLiveTask([string]$Arn, $Value, [string]$ContainerName, [string]$GpuUnits) {
  if ($Arn -cnotmatch ('^arn:aws:ecs:us-east-1:' + $ExpectedAccountId + ':task-definition/' + [regex]::Escape($Value.family) + ':[1-9][0-9]*$')) { throw 'Task definition ARN does not match the reviewed family/account.' }
  $task = Read-InstanceField (Read-InstanceAws @('ecs','describe-task-definition','--task-definition',$Arn)) 'taskDefinition'
  if ((Read-InstanceField $task 'taskDefinitionArn') -cne $Arn -or (Read-InstanceField $task 'status') -cne 'ACTIVE') { throw 'The reviewed task revision is not active or its identity differs.' }
  Assert-InstanceFaultInjectionDisabled $task 'enableFaultInjection'
  foreach ($mapping in @(@('family','family'),@('network_mode','networkMode'),@('cpu','cpu'),@('memory','memory'),@('execution_role_arn','executionRoleArn'),@('task_role_arn','taskRoleArn'))) {
    $wanted = Read-InstanceField $Value $mapping[0]
    $actual = Read-InstanceField $task $mapping[1]
    if ([string]$wanted -cne [string]$actual) { throw "Live task differs from the saved plan: $($mapping[1])" }
  }
  if (!(Compare-InstanceValue (Read-InstanceField $task 'requiresCompatibilities') @('EC2'))) { throw 'Live task must require EC2.' }
  $actualContainers = Read-InstanceList $task 'containerDefinitions' 'Live task'
  $wantedContainers = Read-InstanceContainers $Value.container_definitions
  if ($actualContainers.Count -ne 1) { throw 'Live task must contain exactly one GPU container.' }
  Assert-InstanceContainer $actualContainers[0] $ContainerName $GpuUnits
  if (!(Compare-InstanceValue (Convert-InstanceContainer $actualContainers[0]) (Convert-InstanceContainer $wantedContainers[0]))) { throw 'Live task container does not match the reviewed revision.' }
  foreach ($name in @('volumes','placementConstraints')) {
    $items = Read-InstanceField $task $name
    if ($null -ne $items -and @($items).Count -ne 0) { throw "Live task has unexpected $name." }
  }
}
function Assert-InstanceLiveTemplate($Value, [string]$Version, [string]$Type) {
  $versions = Read-InstanceList (Read-InstanceAws @('ec2','describe-launch-template-versions','--launch-template-id',$templateId,'--versions',$Version)) 'LaunchTemplateVersions' 'Live launch template'
  if ($versions.Count -ne 1 -or $versions[0].LaunchTemplateId -cne $templateId -or [string]$versions[0].VersionNumber -cne $Version) { throw 'The concrete launch-template version does not match the reviewed ASG.' }
  $data = $versions[0].LaunchTemplateData
  if ($data.InstanceType -cne $Type -or $data.ImageId -cne $Value.image_id -or $data.UserData -cne $Value.user_data -or $data.MetadataOptions.HttpTokens -cne 'required') { throw 'Live launch-template type, AMI, bootstrap or IMDS configuration differs.' }
  $interfaces = Read-InstanceList $data 'NetworkInterfaces' 'Live launch template'
  $plannedInterfaces = Read-InstanceList $Value 'network_interfaces' 'Saved launch template'
  if ($interfaces.Count -ne 1 -or $plannedInterfaces.Count -ne 1 -or $interfaces[0].DeviceIndex -ne 0 -or
      (Read-InstanceField $interfaces[0] 'AssociatePublicIpAddress') -isnot [bool] -or
      (Read-InstanceField $interfaces[0] 'AssociatePublicIpAddress') -ne $true -or
      (Read-InstanceField $interfaces[0] 'DeleteOnTermination') -isnot [bool] -or
      (Read-InstanceField $interfaces[0] 'DeleteOnTermination') -ne $true -or
      (Read-InstanceField $interfaces[0] 'SubnetId') -or (Read-InstanceField $interfaces[0] 'NetworkInterfaceId') -or
      !(Compare-InstanceValue @($interfaces[0].Groups | Sort-Object) @($plannedInterfaces[0].security_groups | Sort-Object))) { throw 'Live launch-template networking differs from the reviewed configuration.' }
  $profiles = Read-InstanceList $Value 'iam_instance_profile' 'Saved launch template'
  if ($profiles.Count -ne 1 -or $data.IamInstanceProfile.Arn -cne $profiles[0].arn) { throw 'Live launch-template instance profile differs.' }
  $disks = Read-InstanceList $data 'BlockDeviceMappings' 'Live launch template'
  $plannedDisks = Read-InstanceList $Value 'block_device_mappings' 'Saved launch template'
  if ($disks.Count -ne 1 -or $plannedDisks.Count -ne 1 -or $disks[0].DeviceName -cne $plannedDisks[0].device_name) { throw 'Live launch-template root disk differs.' }
  $ebs = Read-InstanceList $plannedDisks[0] 'ebs' 'Saved root disk'
  if ($ebs.Count -ne 1 -or $disks[0].Ebs.VolumeSize -ne $ebs[0].volume_size -or $disks[0].Ebs.VolumeType -cne $ebs[0].volume_type -or
      (Read-InstanceField $disks[0].Ebs 'Encrypted') -isnot [bool] -or (Read-InstanceField $disks[0].Ebs 'Encrypted') -ne $true -or
      (Read-InstanceField $disks[0].Ebs 'DeleteOnTermination') -isnot [bool] -or (Read-InstanceField $disks[0].Ebs 'DeleteOnTermination') -ne $true) { throw 'Live root disk size, encryption or cleanup differs.' }
}

$savedProfile = [Environment]::GetEnvironmentVariable('AWS_PROFILE', 'Process')
$savedEncoding = [Environment]::GetEnvironmentVariable('PYTHONIOENCODING', 'Process')
$savedConsole = [Console]::OutputEncoding
try {
  if ($ExpectedAccountId -cnotmatch '^\d{12}$' -or $ExpectedSubnetId -cnotmatch '^subnet-[a-f0-9]{8,17}$' -or $AwsProfile -cnotmatch '^[A-Za-z0-9_.-]{1,64}$') { throw 'Expected account, subnet or profile is invalid.' }
  $imagePattern = '^' + $ExpectedAccountId + '\.dkr\.ecr\.us-east-1\.amazonaws\.com/([a-z0-9][a-z0-9._/-]*)@(sha256:[a-f0-9]{64})$'
  $imageMatch = [regex]::Match($ExpectedImageUri, $imagePattern)
  if (!$imageMatch.Success) { throw 'ExpectedImageUri must be digest-pinned in the expected account and region.' }
  if ((Get-Location).Provider.Name -ne 'FileSystem' -or (Get-Location).ProviderPath -ne $PSScriptRoot) { throw 'Run this validator from its existing infra/aws directory.' }
  foreach ($name in @('TF_CLI_ARGS','TF_CLI_ARGS_show','TF_CLI_ARGS_output','TF_CLI_ARGS_workspace')) {
    if ([Environment]::GetEnvironmentVariable($name, 'Process')) { throw "Review $name before validating the saved plan." }
  }
  foreach ($tool in @('aws','terraform')) { if (!(Get-Command $tool -ErrorAction SilentlyContinue)) { throw "$tool is required." } }
  . (Join-Path $PSScriptRoot 'gpu-smoke-profile.ps1')
  $profile = Get-GpuSmokeProfile -InstanceType $ExpectedInstanceType
  if (!(Test-Path -LiteralPath $PlanPath -PathType Leaf)) { throw 'The saved migration plan does not exist.' }
  $resolvedPath = (Get-Item -LiteralPath $PlanPath).FullName
  $hash = (Get-FileHash -LiteralPath $resolvedPath -Algorithm SHA256).Hash.ToLowerInvariant()
  $env:AWS_PROFILE = $AwsProfile
  $env:PYTHONIOENCODING = 'utf-8'
  [Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
  $identity = Read-InstanceAws @('sts','get-caller-identity')
  if ((Read-InstanceField $identity 'Account') -cne $ExpectedAccountId) { throw 'Ambient AWS credentials point to the wrong account.' }
  $workspace = Read-InstanceWorkspace
  $plan = Read-InstanceJson 'terraform' @('show','-json',$resolvedPath) 'Saved migration plan inspection'
  if ((Read-InstanceField $plan 'format_version') -cnotmatch '^1\.' -or (Read-InstanceField $plan 'applyable') -isnot [bool] -or (Read-InstanceField $plan 'applyable') -ne $true -or
      (Read-InstanceField $plan 'errored') -isnot [bool] -or $plan.errored) { throw 'The migration plan must be applyable and error-free.' }
  $deferred = Read-InstanceField $plan 'deferred_changes'
  if ($null -ne $deferred -and @($deferred).Count -ne 0) { throw 'Deferred changes are not permitted.' }
  $entries = Read-InstanceList $plan 'resource_changes' 'Saved plan'
  $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
  $changed = @{}
  foreach ($entry in $entries) {
    if (!$seen.Add([string]$entry.address)) { throw 'Duplicate saved resource address.' }
    if ((Read-InstanceField $entry 'previous_address') -or $null -ne (Read-InstanceField $entry.change 'importing')) { throw 'Resource moves and imports are not permitted.' }
    $action = $entry.change.actions -join ','
    if ($entry.mode -ceq 'data' -and $action -cne 'no-op') { throw 'Deferred data-source reads are not permitted.' }
    if ($action -ceq 'no-op') {
      if ((Test-InstanceUnknown (Read-InstanceField $entry.change 'after_unknown')) -or !(Compare-InstanceValue $entry.change.before $entry.change.after)) { throw 'A no-op dependency is unknown or inconsistent.' }
    } elseif ($entry.mode -ceq 'managed') { $changed[[string]$entry.address] = $entry }
    else { throw 'Unexpected resource action or mode.' }
  }
  $addresses = @($asgAddress,$templateAddress,$preflightAddress,$workerAddress)
  if ($changed.Count -ne 4 -or @($changed.Keys | Where-Object { $_ -cnotin $addresses }).Count -ne 0) { throw 'Require exactly four GPU migration changes: template, ASG and two task revisions.' }
  $template = $changed[$templateAddress].change
  $asg = $changed[$asgAddress].change
  if (($template.actions -join ',') -cne 'update' -or ($asg.actions -join ',') -cne 'update') { throw 'The existing launch template and ASG must update in place.' }
  Assert-InstanceUnchanged $template.before $template.after @('instance_type','latest_version','default_version') 'launch template'
  Assert-InstanceUnknownFields (Read-InstanceField $template 'after_unknown') @('latest_version','default_version') 'launch template'
  if ($template.before.instance_type -cne 'g6f.xlarge' -or $template.after.instance_type -cne $profile.InstanceType -or
      [string]$template.before.latest_version -cnotmatch '^[1-9][0-9]*$') { throw 'Require the existing G6f template to change only to the reviewed G4dn type.' }
  $templateId = [string]$template.before.id
  $oldVersion = [string]$template.before.latest_version
  if ($templateId -cnotmatch '^lt-[a-f0-9]{8,17}$') { throw 'The existing launch-template identity is invalid.' }
  Assert-InstanceUnchanged $asg.before $asg.after @('launch_template','suspended_processes') 'ASG'
  foreach ($value in @($asg.before,$asg.after)) {
    Assert-InstanceZero $value @('min_size','max_size','desired_capacity')
    if ((Read-InstanceField $value 'protect_from_scale_in') -isnot [bool] -or $value.protect_from_scale_in) { throw 'ASG scale-in protection must remain disabled.' }
    if (!(Compare-InstanceValue (Read-InstanceField $value 'vpc_zone_identifier') @($ExpectedSubnetId))) { throw 'ASG must retain the single reviewed subnet.' }
  }
  $oldLt = Read-InstanceList $asg.before 'launch_template' 'Old ASG'
  $newLt = Read-InstanceList $asg.after 'launch_template' 'New ASG'
  if ($oldLt.Count -ne 1 -or $newLt.Count -ne 1 -or $oldLt[0].id -cne $templateId -or $newLt[0].id -cne $templateId -or [string]$oldLt[0].version -cne $oldVersion) { throw 'ASG must remain bound to the same reviewed launch template.' }
  Assert-InstanceUnchanged $oldLt[0] $newLt[0] @('version') 'ASG launch template'
  $asgUnknown = Read-InstanceField $asg 'after_unknown'
  if ($asgUnknown -isnot [pscustomobject]) { throw 'Malformed ASG unknown metadata.' }
  foreach ($property in $asgUnknown.PSObject.Properties) {
    if ($property.Name -ceq 'launch_template') { continue }
    if (Test-InstanceUnknown $property.Value) { throw "Unknown ASG safety field: $($property.Name)" }
  }
  $versionUnknown = $false
  if (Test-InstanceUnknown (Read-InstanceField $asgUnknown 'launch_template')) {
    $unknownLt = Read-InstanceList $asgUnknown 'launch_template' 'ASG unknown metadata'
    if ($unknownLt.Count -ne 1) { throw 'ASG computed launch-template version is ambiguous.' }
    Assert-InstanceUnknownFields $unknownLt[0] @('version') 'ASG launch template'
    $versionUnknown = (Read-InstanceField $unknownLt[0] 'version') -eq $true
  }
  $latestUnknown = (Read-InstanceField (Read-InstanceField $template 'after_unknown') 'latest_version') -eq $true
  if ($versionUnknown -ne $latestUnknown) { throw 'ASG and launch-template computed versions must be correlated.' }
  if (!$versionUnknown -and ([string]$newLt[0].version -cnotmatch '^[1-9][0-9]*$' -or [string]$newLt[0].version -cne [string]$template.after.latest_version -or [long]$newLt[0].version -le [long]$oldVersion)) { throw 'The ASG must select the new concrete template version.' }
  $oldProcesses = @($asg.before.suspended_processes | Sort-Object)
  $newProcesses = @($asg.after.suspended_processes | Sort-Object)
  if (($oldProcesses -join ',') -cnotin @('AZRebalance,ReplaceUnhealthy','AZRebalance,Launch,ReplaceUnhealthy') -or ($newProcesses -join ',') -cne 'AZRebalance,ReplaceUnhealthy') { throw 'Only the Launch cleanup latch may be removed at zero capacity.' }
  Assert-InstanceTaskPlan $changed[$preflightAddress] 'gpu-preflight'
  Assert-InstanceTaskPlan $changed[$workerAddress] 'paid-gpu-worker'
  $expectedInputs = [ordered]@{
    aws_region = $region; gpu_smoke_instance_type = $profile.InstanceType
    enable_gpu = $true; gpu_smoke_mode = $true; gpu_smoke_approval = $profile.Approval
    enable_gpu_image_repository = $true; enable_paid_gpu_queue_scaffold = $false
    enable_cpu_smoke_queue = $false; gpu_subnet_id = $ExpectedSubnetId
    gpu_s3_route_table_ids = @(); gpu_worker_image_uri = $ExpectedImageUri
  }
  foreach ($name in $expectedInputs.Keys) {
    if (!(Compare-InstanceValue (Read-InstanceField (Read-InstanceField $plan.variables $name) 'value') $expectedInputs[$name])) { throw "Unexpected effective Terraform input: $name" }
  }
  Read-InstanceCaller
  $plannedOutputs = Read-InstanceField $plan.planned_values 'outputs'
  foreach ($pair in @(@('gpu_smoke_subnet_id',$ExpectedSubnetId),@('gpu_smoke_instance_type',$profile.InstanceType),@('gpu_smoke_gpu_resource',$profile.GpuResource))) {
    if ((Read-InstanceField (Read-InstanceField $plannedOutputs $pair[0]) 'value') -cne $pair[1]) { throw "Planned output must match the reviewed migration: $($pair[0])" }
  }
  $outputs = Read-InstanceJson 'terraform' @('output','-json') 'Current Terraform output inspection'
  $asgName = Read-InstanceOutput 'gpu_smoke_asg_name'
  $cluster = Read-InstanceOutput 'gpu_smoke_ecs_cluster'
  $currentVersion = Read-InstanceOutput 'gpu_smoke_launch_template_version'
  $preflightArn = Read-InstanceOutput 'gpu_smoke_task_definition'
  $ami = Read-InstanceOutput 'gpu_smoke_ami_id'
  if ($asgName -cnotmatch '^strokesense-[a-z0-9-]+-gpu-one-instance$' -or $cluster -cnotmatch ('^arn:aws:ecs:us-east-1:' + $ExpectedAccountId + ':cluster/strokesense-[a-z0-9-]+-gpu$') -or
      (Read-InstanceOutput 'gpu_smoke_launch_template_id') -cne $templateId -or (Read-InstanceOutput 'gpu_smoke_subnet_id') -cne $ExpectedSubnetId -or
      $currentVersion -cnotmatch '^[1-9][0-9]*$' -or $ami -cne $template.before.image_id) { throw 'Current Terraform outputs differ from the reviewed stack.' }
  if ($asg.before.name -cne $asgName -or $asg.before.id -cne $asgName -or $asg.before.arn -cnotmatch ('^arn:aws:autoscaling:us-east-1:' + $ExpectedAccountId + ':autoScalingGroup:[a-f0-9-]{36}:autoScalingGroupName/' + [regex]::Escape($asgName) + '$')) { throw 'Saved ASG identity does not match the expected account/stack.' }
  if ($VerifyApplied) {
    if ((Read-InstanceOutput 'gpu_smoke_instance_type') -cne $profile.InstanceType -or (Read-InstanceOutput 'gpu_smoke_gpu_resource') -cne $profile.GpuResource -or [long]$currentVersion -le [long]$oldVersion -or
        (!$versionUnknown -and $currentVersion -cne [string]$newLt[0].version)) { throw 'Applied instance type, GPU allocation or template version does not match the migration.' }
    $workerArn = Read-InstanceOutput 'gpu_smoke_worker_task_definition'
    foreach ($pair in @(@($preflightArn,$changed[$preflightAddress].change),@($workerArn,$changed[$workerAddress].change))) {
      if ($pair[0] -ceq $pair[1].before.arn -or $pair[0] -cnotmatch ':[1-9][0-9]*$' -or [long](($pair[0] -split ':')[-1]) -le [long]$pair[1].before.revision) { throw 'Applied GPU task revisions must advance from the reviewed old definitions.' }
      $knownArn = Read-InstanceField $pair[1].after 'arn'
      if ($knownArn -and $knownArn -cne $pair[0]) { throw 'Applied task ARN differs from the saved plan.' }
    }
    Assert-InstanceLiveTemplate $template.after $currentVersion $profile.InstanceType
    Assert-InstanceLiveTask $preflightArn $changed[$preflightAddress].change.after 'gpu-preflight' $profile.GpuResource
    Assert-InstanceLiveTask $workerArn $changed[$workerAddress].change.after 'paid-gpu-worker' $profile.GpuResource
    $expectedProcesses = $newProcesses
  } else {
    if ($currentVersion -cne $oldVersion -or $preflightArn -cne $changed[$preflightAddress].change.before.arn) { throw 'Current template or preflight revision differs from the saved before-state.' }
    $workerArn = [string]$changed[$workerAddress].change.before.arn
    Assert-InstanceLiveTemplate $template.before $oldVersion 'g6f.xlarge'
    Assert-InstanceLiveTask $preflightArn $changed[$preflightAddress].change.before 'gpu-preflight' '0.125'
    Assert-InstanceLiveTask $workerArn $changed[$workerAddress].change.before 'paid-gpu-worker' '0.125'
    $expectedProcesses = $oldProcesses
  }
  $groups = Read-InstanceList (Read-InstanceAws @('autoscaling','describe-auto-scaling-groups','--auto-scaling-group-names',$asgName)) 'AutoScalingGroups' 'Live ASG'
  if ($groups.Count -ne 1) { throw 'Expected exactly one live GPU ASG.' }
  $group = $groups[0]
  Assert-InstanceZero $group @('MinSize','MaxSize','DesiredCapacity')
  Assert-InstanceEmpty $group 'Instances' 'Live ASG instances'
  if ($group.AutoScalingGroupName -cne $asgName -or $group.AutoScalingGroupARN -cne $asg.before.arn -or $group.VPCZoneIdentifier -cne $ExpectedSubnetId -or
      $group.LaunchTemplate.LaunchTemplateId -cne $templateId -or [string]$group.LaunchTemplate.Version -cne $currentVersion -or
      (Read-InstanceField $group 'NewInstancesProtectedFromScaleIn') -isnot [bool] -or $group.NewInstancesProtectedFromScaleIn) { throw 'Live ASG identity, placement or concrete template binding differs.' }
  $processes = @((Read-InstanceList $group 'SuspendedProcesses' 'Live ASG') | ForEach-Object { $_.ProcessName } | Sort-Object)
  if (!(Compare-InstanceValue $processes $expectedProcesses)) { throw 'Live ASG process suspensions differ from the reviewed stage.' }
  Assert-InstanceEmpty (Read-InstanceAws @('ec2','describe-instances','--filters',("Name=tag:aws:autoscaling:groupName,Values=" + $asgName),'Name=instance-state-name,Values=pending,running,shutting-down,stopping,stopped')) 'Reservations' 'Tagged nonterminated GPU instances'
  $activities = Read-InstanceList (Read-InstanceAws @('autoscaling','describe-scaling-activities','--auto-scaling-group-name',$asgName)) 'Activities' 'Scaling history'
  foreach ($activity in $activities) {
    if ($activity.AutoScalingGroupName -cne $asgName -or $activity.StatusCode -cnotin @('Successful','Failed','Cancelled')) { throw 'A scaling activity is unresolved or belongs to another group.' }
  }
  Assert-InstanceEmpty (Read-InstanceAws @('ecs','list-services','--cluster',$cluster)) 'serviceArns' 'GPU ECS services'
  Assert-InstanceEmpty (Read-InstanceAws @('ecs','list-tasks','--cluster',$cluster,'--desired-status','RUNNING')) 'taskArns' 'GPU ECS running/pending tasks'
  Assert-InstanceEmpty (Read-InstanceAws @('ecs','list-container-instances','--cluster',$cluster)) 'containerInstanceArns' 'GPU ECS container instances'
  $stopped = Read-InstanceList (Read-InstanceAws @('ecs','list-tasks','--cluster',$cluster,'--desired-status','STOPPED')) 'taskArns' 'Previous GPU tasks'
  for ($offset=0; $offset -lt $stopped.Count; $offset+=100) {
    $batch = @($stopped | Select-Object -Skip $offset -First 100)
    $details = Read-InstanceAws (@('ecs','describe-tasks','--cluster',$cluster,'--tasks') + $batch)
    Assert-InstanceEmpty $details 'failures' 'Previous task lookup failures'
    $tasks = Read-InstanceList $details 'tasks' 'Previous task details'
    if ($tasks.Count -ne $batch.Count -or @($tasks | Where-Object { $_.lastStatus -cne 'STOPPED' }).Count -ne 0 -or (Compare-Object $batch @($tasks | ForEach-Object { $_.taskArn }))) { throw 'A previous task is still stopping or cannot be verified.' }
  }
  $subnets = Read-InstanceList (Read-InstanceAws @('ec2','describe-subnets','--subnet-ids',$ExpectedSubnetId)) 'Subnets' 'Reviewed subnet'
  if ($subnets.Count -ne 1 -or $subnets[0].SubnetId -cne $ExpectedSubnetId -or $subnets[0].OwnerId -cne $ExpectedAccountId -or $subnets[0].State -cne 'available' -or
      $subnets[0].VpcId -cnotmatch '^vpc-[a-f0-9]{8,17}$' -or $subnets[0].AvailableIpAddressCount -lt 2) { throw 'Reviewed subnet ownership, state, VPC or available addresses are invalid.' }
  $securityIds = @($template.before.network_interfaces[0].security_groups)
  $securityGroups = Read-InstanceList (Read-InstanceAws (@('ec2','describe-security-groups','--group-ids') + $securityIds)) 'SecurityGroups' 'GPU host security groups'
  if ($securityGroups.Count -ne $securityIds.Count -or (Compare-Object $securityIds @($securityGroups | ForEach-Object { $_.GroupId })) -or
      @($securityGroups | Where-Object { $_.OwnerId -cne $ExpectedAccountId -or $_.VpcId -cne $subnets[0].VpcId }).Count -ne 0) { throw 'GPU security groups and reviewed subnet must retain the same owned VPC.' }
  $published = Read-InstanceList (Read-InstanceAws @('ecr','describe-images','--repository-name',$imageMatch.Groups[1].Value,'--image-ids',('imageDigest=' + $imageMatch.Groups[2].Value))) 'imageDetails' 'Published image'
  if ($published.Count -ne 1 -or $published[0].registryId -cne $ExpectedAccountId -or $published[0].imageDigest -cne $imageMatch.Groups[2].Value) { throw 'The selected ECR digest is not verified.' }
  if ((Read-InstanceWorkspace) -cne $workspace) { throw 'Terraform workspace changed during validation.' }
  if ((Get-FileHash -LiteralPath $resolvedPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $hash) { throw 'The saved plan changed during validation.' }
  if ($VerifyApplied) { Write-Host 'INSTANCE MIGRATION VERIFIED: G4dn template and full-GPU task revisions applied; ASG remains 0/0/0.' }
  else { Write-Host 'INSTANCE PLAN VERIFIED: only G6f-to-G4dn template, idle ASG binding and two GPU task revisions change.' }
  [pscustomobject]@{
    ReadyForApply = !$VerifyApplied; ReadyForSmoke = [bool]$VerifyApplied
    PlanPath = $resolvedPath; PlanHash = $hash; Workspace = $workspace
    SubnetId = $ExpectedSubnetId; ImageUri = $ExpectedImageUri; InstanceType = $profile.InstanceType
    AsgName = $asgName; LaunchTemplateId = $templateId; LaunchTemplateVersion = $currentVersion
    PreflightTaskDefinition = $preflightArn; WorkerTaskDefinition = $workerArn
  }
} finally {
  [Console]::OutputEncoding = $savedConsole
  foreach ($entry in @(@{ Name='AWS_PROFILE'; Value=$savedProfile },@{ Name='PYTHONIOENCODING'; Value=$savedEncoding })) {
    if ($null -eq $entry.Value) { Remove-Item -LiteralPath ("Env:" + $entry.Name) -ErrorAction SilentlyContinue }
    else { [Environment]::SetEnvironmentVariable($entry.Name,$entry.Value,'Process') }
  }
}
