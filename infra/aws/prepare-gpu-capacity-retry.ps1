# Read-only preparation for moving the idle GPU smoke ASG to one reviewed AZ.
# Writes a separate GPU-only varfile; never plans/applies Terraform, changes
# AWS resources, or launches EC2/ECS. Run the reviewed plan/smoke separately.
[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][ValidatePattern('^[0-9]{12}$')][string]$ExpectedAccountId,
  [Parameter(Mandatory=$true)][string]$ExpectedImageUri,
  [ValidatePattern('^[A-Za-z0-9_.-]{1,64}$')][string]$AwsProfile = 'strokesense-admin',
  [ValidateSet('us-east-1b','us-east-1c','us-east-1d')][string]$AvailabilityZone = 'us-east-1b',
  [string]$OutputPath = 'gpu-capacity-retry.tfvars.json'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$region = 'us-east-1'
$savedProfile = [Environment]::GetEnvironmentVariable('AWS_PROFILE', 'Process')
$savedPythonEncoding = [Environment]::GetEnvironmentVariable('PYTHONIOENCODING', 'Process')
$savedConsoleEncoding = [Console]::OutputEncoding

function Get-RetryField($Object, [string]$Name) {
  if ($null -ne $Object -and $Object.PSObject.Properties[$Name]) { return ,$Object.$Name }
  return $null
}
function Get-RetryList($Object, [string]$Name) {
  $value = Get-RetryField $Object $Name
  if ($null -eq $value -or $value -isnot [array]) { throw "Missing or malformed AWS collection: $Name." }
  # Preserve [] and single-element arrays on Windows PowerShell 5.1 and PS7.
  return ,$value
}
function Test-RetryInteger($Value) {
  return ($null -ne $Value -and $Value -is [ValueType] -and $Value -isnot [bool] -and
    ![double]::IsNaN([double]$Value) -and ![double]::IsInfinity([double]$Value) -and
    [double]$Value -ge 0 -and [math]::Floor([double]$Value) -eq [double]$Value)
}
function Test-RetryTrue($Value) { return ($Value -is [bool] -and $Value -eq $true) }
function Restore-RetryEnvironment([string]$Name, $Value) {
  if ($null -eq $Value) { Remove-Item "Env:$Name" -ErrorAction SilentlyContinue }
  else { [Environment]::SetEnvironmentVariable($Name, $Value, 'Process') }
}
function Invoke-RetryNative([string]$Command, [string[]]$Arguments) {
  $savedPreference = $ErrorActionPreference
  try {
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
function Convert-RetryObject([string]$Text, [string]$Operation) {
  # An envelope preserves root [] / null semantics on both supported shells.
  # Parser exceptions can include their input, so never forward them.
  try { $envelope = ConvertFrom-Json -InputObject ('{"value":' + $Text + '}') -ErrorAction Stop }
  catch { throw "$Operation returned invalid JSON." }
  $value = Get-RetryField $envelope 'value'
  if ($null -eq $value -or $value -isnot [pscustomobject]) { throw "$Operation returned an invalid JSON object." }
  return $value
}
function Read-RetryAws([string[]]$Arguments) {
  $operation = $Arguments[0] + ' ' + $Arguments[1]
  $allowed = @(
    'sts get-caller-identity', 'autoscaling describe-auto-scaling-groups',
    'ec2 describe-instances', 'ec2 describe-subnets', 'ec2 describe-launch-template-versions',
    'ec2 describe-security-groups', 'ec2 describe-instance-type-offerings',
    'ec2 describe-route-tables', 'ec2 describe-internet-gateways',
    'ec2 describe-vpc-attribute', 'ec2 describe-network-acls',
    'ecs describe-clusters', 'ecs list-services', 'ecs list-tasks',
    'ecs list-container-instances', 'ecs describe-task-definition',
    'ecr describe-images', 'service-quotas get-service-quota'
  )
  if ($operation -cnotin $allowed) { throw "Read-only helper refused operation: $operation." }
  # Keep the same ambient credential chain as Terraform. --profile would
  # bypass credential environment variables that Terraform may still use.
  $result = Invoke-RetryNative 'aws' ($Arguments + @(
    '--region', $region, '--output', 'json', '--no-cli-pager', '--no-cli-auto-prompt',
    '--cli-connect-timeout', '10', '--cli-read-timeout', '30'
  ))
  if ($result.Code -ne 0) {
    $detail = ($result.Text -replace '\s+', ' ').Trim()
    if ($detail.Length -gt 400) { $detail = $detail.Substring(0, 400) }
    throw "AWS $operation failed (exit $($result.Code)): $detail"
  }
  $value = Convert-RetryObject $result.Text "AWS $operation"
  if ((Get-RetryField $value 'NextToken') -or (Get-RetryField $value 'nextToken')) {
    throw "AWS $operation returned incomplete pagination; no readiness result accepted."
  }
  return $value
}
function Read-RetryOutput([string]$Name) {
  $entry = Get-RetryField $outputs $Name
  $value = Get-RetryField $entry 'value'
  if ($null -eq $entry -or $value -isnot [string] -or !$value -or
      (Get-RetryField $entry 'sensitive') -ne $false) {
    throw "Terraform output $Name is missing, sensitive, or malformed. Apply the existing smoke infrastructure first."
  }
  return $value
}
function Assert-RetryArn($Arn, [string]$Service, [string]$ArnRegion, [string]$ResourcePattern) {
  $pattern = '^arn:aws:{0}:{1}:{2}:{3}$' -f $Service, $ArnRegion, $ExpectedAccountId, $ResourcePattern
  if ($Arn -isnot [string] -or $Arn -cnotmatch $pattern) { throw "Unexpected account, region, or resource in $Service ARN." }
}
function Assert-RetryIdleGroup($Group) {
  if ((Get-RetryField $Group 'AutoScalingGroupName') -cne $asgName) { throw 'Live ASG name differs from Terraform output.' }
  Assert-RetryArn (Get-RetryField $Group 'AutoScalingGroupARN') 'autoscaling' $region ('autoScalingGroup:[a-f0-9-]+:autoScalingGroupName/' + [regex]::Escape($asgName))
  foreach ($field in @('MinSize','MaxSize','DesiredCapacity')) {
    $value = Get-RetryField $Group $field
    if (!(Test-RetryInteger $value) -or $value -ne 0) { throw 'GPU ASG must be idle at min/max/desired 0/0/0 before preparing a retry.' }
  }
  $members = Get-RetryList $Group 'Instances'
  if ($members.Count -ne 0) { throw 'GPU ASG still has instances; finish and verify cleanup first.' }
  if ((Get-RetryField $Group 'VPCZoneIdentifier') -cne $oldSubnetId) { throw 'Live ASG subnet differs from the Terraform subnet output.' }
  $template = Get-RetryField $Group 'LaunchTemplate'
  if ((Get-RetryField $template 'LaunchTemplateId') -cne $templateId -or
      [string](Get-RetryField $template 'Version') -cne $templateVersion -or
      (Get-RetryField $Group 'MixedInstancesPolicy') -or (Get-RetryField $Group 'LaunchConfigurationName')) {
    throw 'Live ASG does not use the reviewed numeric launch-template version.'
  }
  $protection = Get-RetryField $Group 'NewInstancesProtectedFromScaleIn'
  if ($protection -isnot [bool] -or $protection) { throw 'GPU smoke instances must allow scale-in cleanup.' }
  $processes = Get-RetryList $Group 'SuspendedProcesses'
  $names = @($processes | ForEach-Object { Get-RetryField $_ 'ProcessName' })
  # Cleanup intentionally latches Launch off. The separately reviewed idle
  # subnet plan may remove that latch; preparation never resumes a process.
  foreach ($process in $names) {
    if ($process -cnotin @('AZRebalance','ReplaceUnhealthy','Launch')) {
      throw "Unexpected suspended ASG process $process; review cleanup before preparing another attempt."
    }
  }
  if (@($names | Select-Object -Unique).Count -ne $names.Count) {
    throw 'ASG suspended-process list contains duplicate entries.'
  }
  foreach ($process in @('AZRebalance','ReplaceUnhealthy')) {
    if ($names -cnotcontains $process) { throw "ASG process $process must remain suspended for the single-host smoke." }
  }
}
function Assert-RetryNoTaggedInstances {
  $response = Read-RetryAws @('ec2','describe-instances','--filters',
    "Name=tag:aws:autoscaling:groupName,Values=$asgName",
    'Name=instance-state-name,Values=pending,running,shutting-down,stopping,stopped')
  $reservations = Get-RetryList $response 'Reservations'
  foreach ($reservation in $reservations) {
    if ((Get-RetryField $reservation 'OwnerId') -cne $ExpectedAccountId) { throw 'Tagged EC2 instance ownership is unexpected.' }
    $instances = Get-RetryList $reservation 'Instances'
    if ($instances.Count -ne 0) { throw 'A nonterminated EC2 instance is still tagged to this ASG; verify cleanup first.' }
  }
}
function Assert-RetryClusterIdle {
  $response = Read-RetryAws @('ecs','describe-clusters','--clusters',$cluster)
  $failures = Get-RetryList $response 'failures'
  $clusters = Get-RetryList $response 'clusters'
  if ($failures.Count -ne 0 -or $clusters.Count -ne 1 -or
      (Get-RetryField $clusters[0] 'clusterArn') -cne $cluster -or
      (Get-RetryField $clusters[0] 'status') -cne 'ACTIVE') { throw 'GPU cluster identity or status is invalid.' }
  foreach ($field in @('registeredContainerInstancesCount','runningTasksCount','pendingTasksCount','activeServicesCount')) {
    $value = Get-RetryField $clusters[0] $field
    if (!(Test-RetryInteger $value) -or $value -ne 0) { throw 'GPU cluster must have no container instances, tasks, or services.' }
  }
  $services = Get-RetryList (Read-RetryAws @('ecs','list-services','--cluster',$cluster)) 'serviceArns'
  $containers = Get-RetryList (Read-RetryAws @('ecs','list-container-instances','--cluster',$cluster)) 'containerInstanceArns'
  if ($services.Count -ne 0 -or $containers.Count -ne 0) { throw 'GPU cluster still has services or container instances.' }
  foreach ($desired in @('RUNNING','PENDING')) {
    # Desired RUNNING includes tasks whose lastStatus is PENDING. The cluster
    # pending counter above also protects against overlooking those tasks.
    $tasks = Get-RetryList (Read-RetryAws @('ecs','list-tasks','--cluster',$cluster,'--desired-status',$desired)) 'taskArns'
    if ($tasks.Count -ne 0) { throw 'GPU cluster still has running or pending tasks.' }
  }
}
function Assert-RetrySubnet($Subnet, [string]$RequiredId, [string]$RequiredAz) {
  $id = Get-RetryField $Subnet 'SubnetId'
  $ips = Get-RetryField $Subnet 'AvailableIpAddressCount'
  if ($id -isnot [string] -or $id -cnotmatch '^subnet-[a-f0-9]{8,17}$' -or
      ($RequiredId -and $id -cne $RequiredId) -or
      (Get-RetryField $Subnet 'OwnerId') -cne $ExpectedAccountId -or
      (Get-RetryField $Subnet 'VpcId') -cne $vpcId -or
      (Get-RetryField $Subnet 'State') -cne 'available' -or
      !(Test-RetryInteger $ips) -or $ips -lt 2 -or
      ($RequiredAz -and (Get-RetryField $Subnet 'AvailabilityZone') -cne $RequiredAz) -or
      (Get-RetryField $Subnet 'Ipv6Native') -eq $true) {
    throw 'Subnet identity, VPC, owner, state, Availability Zone, or available IPv4 addresses failed verification.'
  }
}
function Assert-RetryPublicRouting([string]$SubnetId) {
  $response = Read-RetryAws @('ec2','describe-route-tables','--filters',"Name=association.subnet-id,Values=$SubnetId")
  $tables = Get-RetryList $response 'RouteTables'
  $explicit = $tables.Count -gt 0
  if (!$explicit) {
    $response = Read-RetryAws @('ec2','describe-route-tables','--filters',"Name=vpc-id,Values=$vpcId",'Name=association.main,Values=true')
    $tables = Get-RetryList $response 'RouteTables'
  }
  if ($tables.Count -ne 1 -or (Get-RetryField $tables[0] 'VpcId') -cne $vpcId -or
      (Get-RetryField $tables[0] 'OwnerId') -cne $ExpectedAccountId) { throw 'Cannot determine one same-VPC effective route table.' }
  $associations = Get-RetryList $tables[0] 'Associations'
  $matching = @($associations | Where-Object {
    ($explicit -and (Get-RetryField $_ 'SubnetId') -ceq $SubnetId) -or
    (!$explicit -and (Test-RetryTrue (Get-RetryField $_ 'Main')))
  })
  if ($matching.Count -ne 1 -or (Get-RetryField (Get-RetryField $matching[0] 'AssociationState') 'State') -cne 'associated') {
    throw 'Effective route-table association is missing or not associated.'
  }
  $routes = Get-RetryList $tables[0] 'Routes'
  $defaults = @($routes | Where-Object { (Get-RetryField $_ 'DestinationCidrBlock') -ceq '0.0.0.0/0' })
  if ($defaults.Count -ne 1 -or (Get-RetryField $defaults[0] 'State') -cne 'active' -or
      (Get-RetryField $defaults[0] 'GatewayId') -cnotmatch '^igw-[a-f0-9]{8,17}$') { throw 'Subnet needs an active IPv4 default route to an Internet Gateway.' }
  $gatewayId = Get-RetryField $defaults[0] 'GatewayId'
  $gateways = Get-RetryList (Read-RetryAws @('ec2','describe-internet-gateways','--internet-gateway-ids',$gatewayId)) 'InternetGateways'
  if ($gateways.Count -ne 1 -or (Get-RetryField $gateways[0] 'InternetGatewayId') -cne $gatewayId -or
      (Get-RetryField $gateways[0] 'OwnerId') -cne $ExpectedAccountId) { throw 'Internet Gateway identity or ownership is unexpected.' }
  $attachments = Get-RetryList $gateways[0] 'Attachments'
  if ($attachments.Count -ne 1 -or (Get-RetryField $attachments[0] 'VpcId') -cne $vpcId -or
      (Get-RetryField $attachments[0] 'State') -cne 'available') { throw 'Internet Gateway is not attached to the selected VPC.' }
}
function Assert-RetryAcl([string]$SubnetId) {
  $acls = Get-RetryList (Read-RetryAws @('ec2','describe-network-acls','--filters',"Name=association.subnet-id,Values=$SubnetId")) 'NetworkAcls'
  if ($acls.Count -ne 1 -or (Get-RetryField $acls[0] 'VpcId') -cne $vpcId -or
      (Get-RetryField $acls[0] 'OwnerId') -cne $ExpectedAccountId) { throw 'Subnet network ACL identity or ownership is unexpected.' }
  $associations = Get-RetryList $acls[0] 'Associations'
  if (@($associations | Where-Object { (Get-RetryField $_ 'SubnetId') -ceq $SubnetId }).Count -ne 1) { throw 'Network ACL is not associated with the candidate subnet.' }
  $entries = Get-RetryList $acls[0] 'Entries'
  foreach ($egress in @($false,$true)) {
    $ipv4 = @($entries | Where-Object {
      $direction = Get-RetryField $_ 'Egress'
      (Get-RetryField $_ 'CidrBlock') -and $direction -is [bool] -and $direction -eq $egress
    } | Sort-Object -Property RuleNumber)
    if ($ipv4.Count -eq 0) { throw 'Network ACL has no reviewed IPv4 rules for both directions.' }
    foreach ($entry in $ipv4) {
      if (!(Test-RetryInteger (Get-RetryField $entry 'RuleNumber'))) { throw 'Network ACL contains an invalid rule priority.' }
    }
    # Conservative by design: custom port/CIDR/deny combinations need separate
    # review. A first allow-all IPv4 rule proves HTTPS and return traffic pass.
    $first = $ipv4[0]
    if ((Get-RetryField $first 'CidrBlock') -cne '0.0.0.0/0' -or
        [string](Get-RetryField $first 'Protocol') -cne '-1' -or
        (Get-RetryField $first 'RuleAction') -cne 'allow') {
      throw 'Unsupported custom network ACL: first IPv4 rule in each direction must allow all traffic for this automatic check.'
    }
  }
}

try {
  if ($ExpectedImageUri -cnotmatch ('^' + $ExpectedAccountId + '\.dkr\.ecr\.us-east-1\.amazonaws\.com/([a-z0-9._/-]+)@(sha256:[a-f0-9]{64})$')) {
    throw 'ExpectedImageUri must be a reviewed us-east-1 ECR digest in the expected account.'
  }
  $repositoryName = $Matches[1]; $imageDigest = $Matches[2]
  if ($AvailabilityZone -cnotin @('us-east-1b','us-east-1c','us-east-1d')) { throw 'Select exactly us-east-1b, us-east-1c, or us-east-1d.' }
  if (!(Get-Command aws -ErrorAction SilentlyContinue) -or !(Get-Command terraform -ErrorAction SilentlyContinue)) { throw 'AWS CLI v2 and Terraform are required.' }
  foreach ($name in @('TF_CLI_ARGS','TF_CLI_ARGS_output')) {
    if (![string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name, 'Process'))) { throw "Review and clear $name before preparing the capacity retry." }
  }
  $resolvedPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputPath)
  $fileName = [IO.Path]::GetFileName($resolvedPath)
  if ($fileName -notmatch '\.tfvars\.json$' -or $fileName -match '(?i)premium|\.auto\.tfvars\.json$|^terraform\.tfvars\.json$|^gpu-smoke\.tfvars\.json$' -or
      ![IO.Directory]::Exists([IO.Path]::GetDirectoryName($resolvedPath))) {
    throw 'OutputPath must be a separate explicit GPU retry .tfvars.json file in an existing directory; original, Premium, and auto-loaded input files are protected.'
  }
  $env:AWS_PROFILE = $AwsProfile
  $env:PYTHONIOENCODING = 'utf-8'
  [Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)

  $identity = Read-RetryAws @('sts','get-caller-identity')
  if ((Get-RetryField $identity 'Account') -cne $ExpectedAccountId) { throw 'Ambient AWS credentials point to the wrong account.' }
  Assert-RetryArn (Get-RetryField $identity 'Arn') '(?:iam|sts)' '' '.+'
  $nativeOutputs = Invoke-RetryNative 'terraform' @("-chdir=$PSScriptRoot",'output','-json','-no-color')
  if ($nativeOutputs.Code -ne 0) { throw "Terraform output failed (exit $($nativeOutputs.Code)); existing state could not be inspected." }
  $outputs = Convert-RetryObject $nativeOutputs.Text 'Terraform output'
  if ((Read-RetryOutput 'aws_region') -cne $region) { throw 'Terraform outputs are not for us-east-1.' }
  $asgName = Read-RetryOutput 'gpu_smoke_asg_name'
  $cluster = Read-RetryOutput 'gpu_smoke_ecs_cluster'
  $templateId = Read-RetryOutput 'gpu_smoke_launch_template_id'
  $templateVersion = Read-RetryOutput 'gpu_smoke_launch_template_version'
  $amiId = Read-RetryOutput 'gpu_smoke_ami_id'
  $oldSubnetId = Read-RetryOutput 'gpu_smoke_subnet_id'
  $taskDefinition = Read-RetryOutput 'gpu_smoke_task_definition'
  $taskGroup = Read-RetryOutput 'gpu_smoke_task_security_group'
  $repository = Read-RetryOutput 'gpu_worker_ecr_repository'
  if ($asgName -cnotmatch '^[A-Za-z0-9_-]{1,255}$' -or $templateId -cnotmatch '^lt-[a-f0-9]{8,17}$' -or
      $templateVersion -cnotmatch '^[1-9][0-9]*$' -or $amiId -cnotmatch '^ami-[a-f0-9]{8,17}$' -or
      $oldSubnetId -cnotmatch '^subnet-[a-f0-9]{8,17}$' -or $taskGroup -cnotmatch '^sg-[a-f0-9]{8,17}$' -or
      $repository -cne ($ExpectedImageUri -split '@')[0]) { throw 'Terraform GPU output identifiers or repository are inconsistent.' }
  Assert-RetryArn $cluster 'ecs' $region 'cluster/[A-Za-z0-9_-]+'
  Assert-RetryArn $taskDefinition 'ecs' $region 'task-definition/[A-Za-z0-9_-]+:[1-9][0-9]*'

  $groups = Get-RetryList (Read-RetryAws @('autoscaling','describe-auto-scaling-groups','--auto-scaling-group-names',$asgName)) 'AutoScalingGroups'
  if ($groups.Count -ne 1) { throw 'Expected exactly one existing GPU ASG.' }
  Assert-RetryIdleGroup $groups[0]
  Assert-RetryNoTaggedInstances
  Assert-RetryClusterIdle

  $versions = Get-RetryList (Read-RetryAws @('ec2','describe-launch-template-versions','--launch-template-id',$templateId,'--versions',$templateVersion)) 'LaunchTemplateVersions'
  if ($versions.Count -ne 1 -or (Get-RetryField $versions[0] 'LaunchTemplateId') -cne $templateId -or
      [string](Get-RetryField $versions[0] 'VersionNumber') -cne $templateVersion) { throw 'Reviewed launch-template version is missing or changed.' }
  Assert-RetryArn (Get-RetryField $versions[0] 'CreatedBy') '(?:iam|sts)' '' '.+'
  $hostConfig = Get-RetryField $versions[0] 'LaunchTemplateData'
  $interfaces = Get-RetryList $hostConfig 'NetworkInterfaces'
  if ((Get-RetryField $hostConfig 'InstanceType') -cne 'g6f.xlarge' -or (Get-RetryField $hostConfig 'ImageId') -cne $amiId -or
      (Get-RetryField (Get-RetryField $hostConfig 'MetadataOptions') 'HttpTokens') -cne 'required' -or
      $interfaces.Count -ne 1 -or (Get-RetryField $interfaces[0] 'DeviceIndex') -ne 0 -or
      !(Test-RetryTrue (Get-RetryField $interfaces[0] 'AssociatePublicIpAddress')) -or
      !(Test-RetryTrue (Get-RetryField $interfaces[0] 'DeleteOnTermination')) -or
      (Get-RetryField $interfaces[0] 'NetworkInterfaceId') -or (Get-RetryField $interfaces[0] 'SubnetId') -or
      (Get-RetryField (Get-RetryField $hostConfig 'Placement') 'AvailabilityZone') -or
      (Get-RetryField $hostConfig 'InstanceMarketOptions')) { throw 'Reviewed host type, AMI, interface, placement, or IMDS configuration does not match the isolated smoke.' }
  Assert-RetryArn (Get-RetryField (Get-RetryField $hostConfig 'IamInstanceProfile') 'Arn') 'iam' '' 'instance-profile/[A-Za-z0-9_+=,.@/-]+'
  $hostGroups = Get-RetryList $interfaces[0] 'Groups'
  if ($hostGroups.Count -ne 1 -or $hostGroups[0] -cnotmatch '^sg-[a-f0-9]{8,17}$' -or $hostGroups[0] -ceq $taskGroup) { throw 'Expected one separate GPU host security group.' }
  $clusterName = ($cluster -split '/')[-1]
  try { $userData = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String((Get-RetryField $hostConfig 'UserData'))) }
  catch { throw 'Reviewed launch-template bootstrap is not valid base64.' }
  foreach ($line in @("echo ECS_CLUSTER=$clusterName >> /etc/ecs/ecs.config", 'echo ECS_ENABLE_GPU_SUPPORT=true >> /etc/ecs/ecs.config', 'echo ECS_AWSVPC_BLOCK_IMDS=true >> /etc/ecs/ecs.config')) {
    if ($userData -cnotmatch ('(?m)^' + [regex]::Escape($line) + '\r?$')) { throw 'Reviewed launch template lacks the expected ECS/GPU/IMDS bootstrap.' }
  }

  $old = Get-RetryList (Read-RetryAws @('ec2','describe-subnets','--subnet-ids',$oldSubnetId)) 'Subnets'
  if ($old.Count -ne 1) { throw 'Original GPU subnet is missing or ambiguous.' }
  $vpcId = Get-RetryField $old[0] 'VpcId'
  if ($vpcId -isnot [string] -or $vpcId -cnotmatch '^vpc-[a-f0-9]{8,17}$') { throw 'Original GPU subnet VPC is invalid.' }
  Assert-RetrySubnet $old[0] $oldSubnetId ''
  $oldZones = Get-RetryList $groups[0] 'AvailabilityZones'
  if ($oldZones.Count -ne 1 -or $oldZones[0] -cne (Get-RetryField $old[0] 'AvailabilityZone')) { throw 'Original subnet and live ASG Availability Zone disagree.' }
  $securityGroups = Get-RetryList (Read-RetryAws @('ec2','describe-security-groups','--group-ids',$hostGroups[0],$taskGroup)) 'SecurityGroups'
  if ($securityGroups.Count -ne 2) { throw 'Expected both reviewed GPU host and task security groups.' }
  foreach ($id in @($hostGroups[0],$taskGroup)) {
    $selected = @($securityGroups | Where-Object { (Get-RetryField $_ 'GroupId') -ceq $id })
    if ($selected.Count -ne 1 -or (Get-RetryField $selected[0] 'VpcId') -cne $vpcId -or
        (Get-RetryField $selected[0] 'OwnerId') -cne $ExpectedAccountId) { throw 'GPU security-group VPC or ownership does not match the original subnet.' }
    $incoming = Get-RetryList $selected[0] 'IpPermissions'
    if ($incoming.Count -ne 0) { throw 'GPU host and task security groups must have no incoming rules for this smoke.' }
    if ($id -ceq $hostGroups[0]) {
      $outgoing = Get-RetryList $selected[0] 'IpPermissionsEgress'
      $https = @($outgoing | Where-Object {
        $rule = $_
        $ranges = Get-RetryList $rule 'IpRanges'
        $public = @($ranges | Where-Object { (Get-RetryField $_ 'CidrIp') -ceq '0.0.0.0/0' }).Count -gt 0
        $protocol = Get-RetryField $rule 'IpProtocol'
        $public -and ($protocol -ceq '-1' -or ($protocol -ceq 'tcp' -and
          (Get-RetryField $rule 'FromPort') -le 443 -and (Get-RetryField $rule 'ToPort') -ge 443))
      })
      if ($https.Count -eq 0) { throw 'GPU host security group does not permit outbound HTTPS for ECS/ECR/logging.' }
    }
  }
  foreach ($attribute in @('enableDnsSupport','enableDnsHostnames')) {
    $response = Read-RetryAws @('ec2','describe-vpc-attribute','--vpc-id',$vpcId,'--attribute',$attribute)
    if ((Get-RetryField $response 'VpcId') -cne $vpcId -or
        !(Test-RetryTrue (Get-RetryField (Get-RetryField $response $attribute) 'Value'))) { throw "VPC $attribute must be enabled." }
  }

  $definition = Get-RetryField (Read-RetryAws @('ecs','describe-task-definition','--task-definition',$taskDefinition)) 'taskDefinition'
  $containers = Get-RetryList $definition 'containerDefinitions'
  $compatibilities = Get-RetryList $definition 'requiresCompatibilities'
  if ((Get-RetryField $definition 'taskDefinitionArn') -cne $taskDefinition -or
      (Get-RetryField $definition 'status') -cne 'ACTIVE' -or (Get-RetryField $definition 'networkMode') -cne 'awsvpc' -or
      $compatibilities.Count -ne 1 -or $compatibilities[0] -cne 'EC2' -or $containers.Count -ne 1 -or
      (Get-RetryField $definition 'taskRoleArn')) { throw 'Existing preflight task is not the reviewed EC2/awsvpc task without customer credentials.' }
  Assert-RetryArn (Get-RetryField $definition 'executionRoleArn') 'iam' '' 'role/[A-Za-z0-9_+=,.@/-]+'
  $container = $containers[0]
  $requirements = Get-RetryList $container 'resourceRequirements'
  $command = Get-RetryList $container 'command'
  if ((Get-RetryField $container 'name') -cne 'gpu-preflight' -or (Get-RetryField $container 'image') -cne $ExpectedImageUri -or
      ($command -join ' ') -cne 'python3 -m aws_app.gpu_preflight --model /app/models/yolo11n-pose.onnx' -or
      $requirements.Count -ne 1 -or (Get-RetryField $requirements[0] 'type') -cne 'GPU' -or
      [string](Get-RetryField $requirements[0] 'value') -cne '0.125' -or (Get-RetryField $container 'privileged') -eq $true) {
    throw 'Existing preflight image digest, command, or GPU requirement differs from the reviewed smoke.'
  }
  foreach ($field in @('environment','secrets','mountPoints','entryPoint')) {
    $value = Get-RetryField $container $field
    if ($null -ne $value -and @($value).Count -ne 0) { throw "Preflight must not contain $field overrides." }
  }
  $volumes = Get-RetryField $definition 'volumes'
  if ($null -ne $volumes -and @($volumes).Count -ne 0) { throw 'Preflight must not contain mounted volumes.' }
  $images = Get-RetryList (Read-RetryAws @('ecr','describe-images','--registry-id',$ExpectedAccountId,
    '--repository-name',$repositoryName,'--image-ids',"imageDigest=$imageDigest")) 'imageDetails'
  if ($images.Count -ne 1 -or (Get-RetryField $images[0] 'registryId') -cne $ExpectedAccountId -or
      (Get-RetryField $images[0] 'repositoryName') -cne $repositoryName -or
      (Get-RetryField $images[0] 'imageDigest') -cne $imageDigest) { throw 'Reviewed image digest is not present in the expected ECR repository.' }
  $quota = Get-RetryField (Read-RetryAws @('service-quotas','get-service-quota','--service-code','ec2','--quota-code','L-DB2E81BA')) 'Quota'
  $quotaValue = Get-RetryField $quota 'Value'
  if ((Get-RetryField $quota 'ServiceCode') -cne 'ec2' -or (Get-RetryField $quota 'QuotaCode') -cne 'L-DB2E81BA' -or
      !(Test-RetryInteger $quotaValue) -or $quotaValue -lt 4) { throw 'Applied EC2 G/VT quota must still cover 4 vCPUs; no quota request was made.' }

  $offerings = Get-RetryList (Read-RetryAws @('ec2','describe-instance-type-offerings','--location-type','availability-zone',
    '--filters','Name=instance-type,Values=g6f.xlarge',"Name=location,Values=$AvailabilityZone")) 'InstanceTypeOfferings'
  if (@($offerings | Where-Object {
    (Get-RetryField $_ 'InstanceType') -ceq 'g6f.xlarge' -and (Get-RetryField $_ 'LocationType') -ceq 'availability-zone' -and
    (Get-RetryField $_ 'Location') -ceq $AvailabilityZone
  }).Count -ne 1) { throw "g6f.xlarge is not reported as offered in $AvailabilityZone for this account. Select another allowed AZ explicitly." }
  $candidates = Get-RetryList (Read-RetryAws @('ec2','describe-subnets','--filters',"Name=vpc-id,Values=$vpcId", "Name=availability-zone,Values=$AvailabilityZone")) 'Subnets'
  $valid = New-Object System.Collections.ArrayList
  $rejected = New-Object System.Collections.ArrayList
  foreach ($candidate in @($candidates | Sort-Object -Property SubnetId)) {
    $candidateId = Get-RetryField $candidate 'SubnetId'
    try {
      Assert-RetrySubnet $candidate '' $AvailabilityZone
      if ($candidateId -ceq $oldSubnetId) { throw 'Candidate is already the current subnet; no placement recovery would occur.' }
      Assert-RetryPublicRouting $candidateId
      Assert-RetryAcl $candidateId
      [void]$valid.Add($candidateId)
    } catch { [void]$rejected.Add("${candidateId}: $($_.Exception.Message)") }
  }
  if ($valid.Count -eq 0) {
    $detail = if ($rejected.Count) { $rejected -join ' | ' } else { 'No existing subnets were returned in that AZ and VPC.' }
    throw "No reviewed public subnet is eligible in ${AvailabilityZone}. $detail"
  }
  $subnetId = [string]$valid[0]
  foreach ($reason in $rejected) { Write-Host "Skipped candidate $reason" }
  # Recheck idle state after network reads; preparing inputs never adopts an
  # instance or task started by another operator while these checks ran.
  $groups = Get-RetryList (Read-RetryAws @('autoscaling','describe-auto-scaling-groups','--auto-scaling-group-names',$asgName)) 'AutoScalingGroups'
  if ($groups.Count -ne 1) { throw 'GPU ASG changed during preparation.' }
  Assert-RetryIdleGroup $groups[0]
  Assert-RetryNoTaggedInstances
  Assert-RetryClusterIdle

  $inputs = [ordered]@{
    enable_gpu = $true
    gpu_smoke_mode = $true
    gpu_smoke_approval = 'I_APPROVE_ONE_G6F_SMOKE_INSTANCE'
    enable_gpu_image_repository = $true
    enable_paid_gpu_queue_scaffold = $false
    enable_cpu_smoke_queue = $false
    gpu_subnet_id = $subnetId
    gpu_s3_route_table_ids = @()
    gpu_worker_image_uri = $ExpectedImageUri
  }
  $content = (ConvertTo-Json -InputObject $inputs -Depth 5) + [Environment]::NewLine
  $encoding = New-Object Text.UTF8Encoding($false)
  $bytes = $encoding.GetBytes($content)
  if ([IO.File]::Exists($resolvedPath)) {
    if ([IO.File]::ReadAllText($resolvedPath) -cne $content) { throw 'OutputPath already contains different content. Choose a new retry filename; existing inputs were not overwritten.' }
  } else {
    # CreateNew refuses a file that appeared after the existence check.
    $stream = [IO.File]::Open($resolvedPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $stream.Write($bytes, 0, $bytes.Length) }
    finally { $stream.Dispose() }
  }
  $hash = (Get-FileHash -LiteralPath $resolvedPath -Algorithm SHA256).Hash.ToLowerInvariant()
  Write-Host "Reviewed retry subnet: $subnetId ($AvailabilityZone), replacing $oldSubnetId in the same VPC."
  Write-Host 'The launch template explicitly supplies the host public IP; the subnet auto-assignment default is not changed.'
  Write-Host 'Offerings confirm support, not spare capacity. Review a new saved subnet-only plan before another bounded smoke attempt.'
  Write-Host "GPU-only inputs retained: $resolvedPath"
  [pscustomobject][ordered]@{
    ReadyForPlan = $true
    InputsPath = $resolvedPath
    InputsHash = $hash
    OldSubnetId = $oldSubnetId
    SubnetId = $subnetId
    AvailabilityZone = $AvailabilityZone
    AsgName = $asgName
    LaunchTemplateId = $templateId
    LaunchTemplateVersion = $templateVersion
    ImageUri = $ExpectedImageUri
  }
} finally {
  Restore-RetryEnvironment 'AWS_PROFILE' $savedProfile
  Restore-RetryEnvironment 'PYTHONIOENCODING' $savedPythonEncoding
  [Console]::OutputEncoding = $savedConsoleEncoding
}
