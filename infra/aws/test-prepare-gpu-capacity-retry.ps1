# Offline checks: aws and terraform are in-memory fakes. Every AWS mutation,
# Terraform plan/apply, or unexpected operation is rejected by the fakes.
# Run under Windows PowerShell 5.1 and PowerShell 7.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:Under = Join-Path $PSScriptRoot 'prepare-gpu-capacity-retry.ps1'
$script:Account = '851226124502'
$script:Digest = 'sha256:' + ('a' * 64)
$script:Image = "$($script:Account).dkr.ecr.us-east-1.amazonaws.com/strokesense-aws-dev-gpu-worker@$($script:Digest)"
$script:OldSubnet = 'subnet-0f3c6534cee511e6a'
$script:SubnetA = 'subnet-01111111111111111'
$script:SubnetB = 'subnet-02222222222222222'
$script:Vpc = 'vpc-0793c6d459d5f8e89'
$script:HostGroup = 'sg-01111111111111111'
$script:TaskGroup = 'sg-09b37852c1df0cc04'
$script:Asg = 'strokesense-aws-dev-gpu-one-instance'
$script:Cluster = "arn:aws:ecs:us-east-1:$($script:Account):cluster/strokesense-aws-dev-paid-gpu"
$script:Task = "arn:aws:ecs:us-east-1:$($script:Account):task-definition/strokesense-aws-dev-gpu-preflight:1"
$script:Template = 'lt-005c322e797a51386'
$script:Ami = 'ami-0b8f7c7154f9e8f8b'
$script:Gateway = 'igw-01111111111111111'
$script:SecretCanary = 'TEST_ONLY_PRIVATE_INPUT_MUST_NOT_BE_PRINTED'
$script:Failures = 0
$script:CaseCount = 0
$script:OriginalLocation = Get-Location
$script:Root = Join-Path ([IO.Path]::GetTempPath()) ('strokesense-capacity-tests-' + [guid]::NewGuid().ToString('N'))
[void](New-Item -ItemType Directory -Path $script:Root)
$script:EnvironmentNames = @(
  'AWS_PROFILE','AWS_ACCESS_KEY_ID','PYTHONIOENCODING','TF_CLI_ARGS','TF_CLI_ARGS_output',
  'TF_VAR_worker_image_tag','TF_VAR_enable_cpu_analysis','TF_VAR_enable_gpu','TF_VAR_gpu_worker_image_uri',
  'TF_VAR_gpu_smoke_instance_type','TF_VAR_gpu_smoke_approval',
  'TF_VAR_gpu_subnet_id','TF_VAR_premium_owner_sub','TF_VAR_admin_cognito_subs','STROKESENSE_GPU_PLAN_PATH'
)
$script:SavedEnvironment = @{}
foreach ($name in $script:EnvironmentNames) { $script:SavedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }

function Restore-TestEnvironment([string]$Name, $Value) {
  if ($null -eq $Value) { Remove-Item "Env:$Name" -ErrorAction SilentlyContinue }
  else { [Environment]::SetEnvironmentVariable($Name, $Value, 'Process') }
}
function New-TestSubnet([string]$Id, [string]$Az) {
  return @{ SubnetId = $Id; OwnerId = $script:Account; VpcId = $script:Vpc; State = 'available'
    AvailabilityZone = $Az; AvailabilityZoneId = 'use1-az2'; AvailableIpAddressCount = 100
    MapPublicIpOnLaunch = $false; Ipv6Native = $false }
}
function New-TestRoute([string]$SubnetId = '') {
  $association = @{ Main = !$SubnetId; AssociationState = @{ State = 'associated' } }
  if ($SubnetId) { $association.SubnetId = $SubnetId }
  return @{ RouteTableId = 'rtb-01111111111111111'; VpcId = $script:Vpc; OwnerId = $script:Account
    Associations = @($association)
    Routes = @(@{ DestinationCidrBlock = '0.0.0.0/0'; GatewayId = $script:Gateway; State = 'active' }) }
}
function New-TestAcl([string]$SubnetId) {
  return @{ NetworkAclId = 'acl-01111111111111111'; VpcId = $script:Vpc; OwnerId = $script:Account
    Associations = @(@{ SubnetId = $SubnetId }); Entries = @(
      @{ Egress = $false; CidrBlock = '0.0.0.0/0'; RuleNumber = 100; Protocol = '-1'; RuleAction = 'allow' },
      @{ Egress = $true; CidrBlock = '0.0.0.0/0'; RuleNumber = 100; Protocol = '-1'; RuleAction = 'allow' },
      @{ Egress = $false; CidrBlock = '0.0.0.0/0'; RuleNumber = 32767; Protocol = '-1'; RuleAction = 'deny' },
      @{ Egress = $true; CidrBlock = '0.0.0.0/0'; RuleNumber = 32767; Protocol = '-1'; RuleAction = 'deny' }
    ) }
}
function New-CapacityWorld([string]$Case) {
  $values = @{
    aws_region = 'us-east-1'; gpu_smoke_asg_name = $script:Asg; gpu_smoke_ecs_cluster = $script:Cluster
    gpu_smoke_launch_template_id = $script:Template; gpu_smoke_launch_template_version = '1'
    gpu_smoke_ami_id = $script:Ami; gpu_smoke_subnet_id = $script:OldSubnet
    gpu_smoke_task_definition = $script:Task; gpu_smoke_task_security_group = $script:TaskGroup
    gpu_worker_ecr_repository = ($script:Image -split '@')[0]
  }
  $outputs = @{}
  foreach ($name in $values.Keys) { $outputs[$name] = @{ sensitive = $false; type = 'string'; value = $values[$name] } }
  $outputs.private_test_output = @{ sensitive = $true; type = 'string'; value = $script:SecretCanary }
  $bootstrap = "#!/bin/bash`necho ECS_CLUSTER=strokesense-aws-dev-paid-gpu >> /etc/ecs/ecs.config`necho ECS_ENABLE_GPU_SUPPORT=true >> /etc/ecs/ecs.config`necho ECS_AWSVPC_BLOCK_IMDS=true >> /etc/ecs/ecs.config`n"
  $global:CapacityWorld = @{
    Case = $Case; Calls = (New-Object System.Collections.ArrayList); GroupReads = 0
    ExpectedAccount = $script:Account; ExpectedDigest = $script:Digest; Vpc = $script:Vpc
    SecretCanary = $script:SecretCanary; InfraDirectory = $PSScriptRoot
    Az = 'us-east-1b'; ExpectedSubnet = $script:SubnetA; OutputName = 'gpu-capacity-retry.tfvars.json'
    RequestedType = ''; ExpectedType = 'g6f.xlarge'; ExpectedCurrentType = 'g6f.xlarge'
    ExpectedGpuResource = '0.125'; ExpectedTypeChange = $false; Repeat = $false
    Identity = @{ Account = $script:Account; Arn = "arn:aws:iam::$($script:Account):user/kemal-strokesense-admin" }
    Outputs = $outputs
    Group = @{ AutoScalingGroupName = $script:Asg
      AutoScalingGroupARN = "arn:aws:autoscaling:us-east-1:$($script:Account):autoScalingGroup:11111111-1111-4111-8111-111111111111:autoScalingGroupName/$($script:Asg)"
      MinSize = 0; MaxSize = 0; DesiredCapacity = 0; Instances = @(); VPCZoneIdentifier = $script:OldSubnet
      AvailabilityZones = @('us-east-1a'); NewInstancesProtectedFromScaleIn = $false
      SuspendedProcesses = @(@{ ProcessName = 'AZRebalance' }, @{ ProcessName = 'ReplaceUnhealthy' })
      LaunchTemplate = @{ LaunchTemplateId = $script:Template; Version = '1' } }
    Reservations = @()
    Cluster = @{ clusterArn = $script:Cluster; status = 'ACTIVE'; registeredContainerInstancesCount = 0
      runningTasksCount = 0; pendingTasksCount = 0; activeServicesCount = 0 }
    Services = @(); ContainerInstances = @(); RunningTasks = @(); PendingTasks = @()
    Template = @{ LaunchTemplateId = $script:Template; VersionNumber = 1
      CreatedBy = "arn:aws:iam::$($script:Account):user/kemal-strokesense-admin"
      LaunchTemplateData = @{ InstanceType = 'g6f.xlarge'; ImageId = $script:Ami
        MetadataOptions = @{ HttpTokens = 'required' }
        NetworkInterfaces = @(@{ DeviceIndex = 0; AssociatePublicIpAddress = $true; DeleteOnTermination = $true; Groups = @($script:HostGroup) })
        IamInstanceProfile = @{ Arn = "arn:aws:iam::$($script:Account):instance-profile/strokesense-aws-dev-gpu-instance" }
        UserData = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($bootstrap)) } }
    OldSubnet = (New-TestSubnet $script:OldSubnet 'us-east-1a')
    Candidates = @((New-TestSubnet $script:SubnetB 'us-east-1b'), (New-TestSubnet $script:SubnetA 'us-east-1b'))
    Groups = @(
      @{ GroupId = $script:HostGroup; OwnerId = $script:Account; VpcId = $script:Vpc; IpPermissions = @()
        IpPermissionsEgress = @(@{ IpProtocol = '-1'; IpRanges = @(@{ CidrIp = '0.0.0.0/0' }) }) },
      @{ GroupId = $script:TaskGroup; OwnerId = $script:Account; VpcId = $script:Vpc; IpPermissions = @(); IpPermissionsEgress = @() }
    )
    DnsSupport = $true; DnsHostnames = $true
    Task = @{ taskDefinitionArn = $script:Task; status = 'ACTIVE'; networkMode = 'awsvpc'; requiresCompatibilities = @('EC2')
      executionRoleArn = "arn:aws:iam::$($script:Account):role/strokesense-aws-dev-batch-execution"
      volumes = @(); containerDefinitions = @(@{ name = 'gpu-preflight'; image = $script:Image
        command = @('python3','-m','aws_app.gpu_preflight','--model','/app/models/yolo11n-pose.onnx')
        resourceRequirements = @(@{ type = 'GPU'; value = '0.125' }); mountPoints = @(); environment = @(); secrets = @() }) }
    Images = @(@{ registryId = $script:Account; repositoryName = 'strokesense-aws-dev-gpu-worker'; imageDigest = $script:Digest })
    Quota = @{ ServiceCode = 'ec2'; QuotaCode = 'L-DB2E81BA'; Value = 4.0 }
    Offerings = @(@{ InstanceType = 'g6f.xlarge'; LocationType = 'availability-zone'; Location = 'us-east-1b' })
    ExplicitRoutes = @{}; MainRoute = (New-TestRoute)
    Gateway = @{ InternetGatewayId = $script:Gateway; OwnerId = $script:Account
      Attachments = @(@{ VpcId = $script:Vpc; State = 'available' }) }
    Acls = @{ $script:SubnetA = (New-TestAcl $script:SubnetA); $script:SubnetB = (New-TestAcl $script:SubnetB); $script:OldSubnet = (New-TestAcl $script:OldSubnet) }
  }
}
function Read-FakeArgument([string[]]$Arguments, [string]$Name) {
  $index = [array]::IndexOf($Arguments, $Name)
  if ($index -lt 0 -or $index + 1 -ge $Arguments.Count) { return $null }
  return $Arguments[$index + 1]
}
function global:terraform {
  $a = @($args | ForEach-Object { [string]$_ })
  [void]$global:CapacityWorld.Calls.Add('terraform ' + ($a -join ' '))
  $global:LASTEXITCODE = 0
  if ($a.Count -ne 4 -or $a[0] -cne "-chdir=$($global:CapacityWorld.InfraDirectory)" -or $a[1] -cne 'output' -or $a[2] -cne '-json' -or $a[3] -cne '-no-color') {
    throw 'Unexpected Terraform operation: read-only output is the only permitted command.'
  }
  if ($global:CapacityWorld.Case -eq 'terraform-failure') { $global:LASTEXITCODE = 1; return $global:CapacityWorld.SecretCanary }
  if ($global:CapacityWorld.Case -eq 'terraform-invalid-json') { return ('{"private":"' + $global:CapacityWorld.SecretCanary + '",broken') }
  return (ConvertTo-Json -InputObject $global:CapacityWorld.Outputs -Depth 20 -Compress)
}
function global:aws {
  $a = @($args | ForEach-Object { [string]$_ })
  $op = $a[0] + ' ' + $a[1]
  [void]$global:CapacityWorld.Calls.Add('aws ' + ($a -join ' '))
  if ($env:AWS_PROFILE -cne 'capacity-test-profile' -or $a -contains '--profile' -or
      (Read-FakeArgument $a '--region') -cne 'us-east-1' -or
      (Read-FakeArgument $a '--output') -cne 'json') { throw 'Credential chain or region changed unexpectedly.' }
  $global:LASTEXITCODE = 0
  $w = $global:CapacityWorld
  if ($op -eq 'sts get-caller-identity') {
    switch ($w.Case) {
      'native-error' { $global:LASTEXITCODE = 255; Write-Error 'Your session has expired' -ErrorAction Continue; return }
      'root-empty-array' { return '[]' }
      'root-single-array' { return '[{"Account":"851226124502"}]' }
      'root-null' { return 'null' }
      'aws-invalid-json' { return 'broken' }
    }
  }
  $data = $null
  switch -Exact ($op) {
    'sts get-caller-identity' { $data = $w.Identity }
    'autoscaling describe-auto-scaling-groups' {
      $w.GroupReads++
      if ($w.Case -eq 'asg-race' -and $w.GroupReads -gt 1) { $w.Group.DesiredCapacity = 1 }
      $data = @{ AutoScalingGroups = @($w.Group) }
    }
    'ec2 describe-instances' { $data = @{ Reservations = $w.Reservations } }
    'ecs describe-clusters' { $data = @{ clusters = @($w.Cluster); failures = @() } }
    'ecs list-services' { $data = @{ serviceArns = $w.Services } }
    'ecs list-container-instances' { $data = @{ containerInstanceArns = $w.ContainerInstances } }
    'ecs list-tasks' {
      $desired = Read-FakeArgument $a '--desired-status'
      $data = @{ taskArns = $(if ($desired -ceq 'RUNNING') { $w.RunningTasks } else { $w.PendingTasks }) }
      # $(...) enumerates empty arrays, so preserve the actual collection.
      if ($desired -ceq 'RUNNING') { $data.taskArns = $w.RunningTasks } else { $data.taskArns = $w.PendingTasks }
      if ($w.Case -eq 'incomplete-pagination') { $data.nextToken = 'more' }
      if ($w.Case -eq 'null-tasks') { $data.taskArns = $null }
    }
    'ec2 describe-launch-template-versions' { $data = @{ LaunchTemplateVersions = @($w.Template) } }
    'ec2 describe-subnets' {
      if ($a -contains '--subnet-ids') { $data = @{ Subnets = @($w.OldSubnet) } }
      else { $data = @{ Subnets = $w.Candidates } }
    }
    'ec2 describe-security-groups' { $data = @{ SecurityGroups = $w.Groups } }
    'ec2 describe-vpc-attribute' {
      $attribute = Read-FakeArgument $a '--attribute'
      $data = @{ VpcId = $w.Vpc }
      $data[$attribute] = @{ Value = $(if ($attribute -ceq 'enableDnsSupport') { $w.DnsSupport } else { $w.DnsHostnames }) }
    }
    'ecs describe-task-definition' { $data = @{ taskDefinition = $w.Task } }
    'ecr describe-images' {
      if ((Read-FakeArgument $a '--image-ids') -cne "imageDigest=$($w.ExpectedDigest)" -or
          (Read-FakeArgument $a '--registry-id') -cne $w.ExpectedAccount) { throw 'Image lookup was not scoped to the reviewed digest and registry.' }
      $data = @{ imageDetails = $w.Images }
    }
    'service-quotas get-service-quota' { $data = @{ Quota = $w.Quota } }
    'ec2 describe-instance-type-offerings' {
      if ($a -cnotcontains "Name=location,Values=$($w.Az)") { throw 'Helper tried another AZ without an explicit selection.' }
      if ($a -cnotcontains "Name=instance-type,Values=$($w.ExpectedType)") { throw 'Helper queried offerings for an unselected instance type.' }
      $data = @{ InstanceTypeOfferings = $w.Offerings }
    }
    'ec2 describe-route-tables' {
      $filter = Read-FakeArgument $a '--filters'
      if ($filter -like 'Name=association.subnet-id,*') {
        $subnet = $filter.Substring($filter.IndexOf('Values=') + 7)
        $data = @{ RouteTables = @() }
        if ($w.ExplicitRoutes.ContainsKey($subnet)) { $data.RouteTables = @($w.ExplicitRoutes[$subnet]) }
      } else { $data = @{ RouteTables = @($w.MainRoute) } }
    }
    'ec2 describe-internet-gateways' { $data = @{ InternetGateways = @($w.Gateway) } }
    'ec2 describe-network-acls' {
      $filter = Read-FakeArgument $a '--filters'
      $subnet = $filter.Substring($filter.IndexOf('Values=') + 7)
      $data = @{ NetworkAcls = @($w.Acls[$subnet]) }
    }
    default { throw "Unexpected AWS mutation/operation in read-only helper: $op" }
  }
  return (ConvertTo-Json -InputObject $data -Depth 25 -Compress)
}
function Expected-TestInputs {
  return [ordered]@{
    enable_gpu = $true; gpu_smoke_mode = $true; gpu_smoke_instance_type = $global:CapacityWorld.ExpectedType
    gpu_smoke_approval = $(if ($global:CapacityWorld.ExpectedType -ceq 'g4dn.xlarge') { 'I_APPROVE_ONE_G4DN_SMOKE_INSTANCE' } else { 'I_APPROVE_ONE_G6F_SMOKE_INSTANCE' })
    enable_gpu_image_repository = $true; enable_paid_gpu_queue_scaffold = $false; enable_cpu_smoke_queue = $false
    gpu_subnet_id = $global:CapacityWorld.ExpectedSubnet; gpu_s3_route_table_ids = @(); gpu_worker_image_uri = $script:Image
  }
}
function Use-G4dnTypeChangeFixture {
  $global:CapacityWorld.RequestedType = 'g4dn.xlarge'
  $global:CapacityWorld.ExpectedType = 'g4dn.xlarge'
  $global:CapacityWorld.ExpectedGpuResource = '1'
  $global:CapacityWorld.ExpectedTypeChange = $true
  $global:CapacityWorld.ExpectedSubnet = $script:OldSubnet
  $global:CapacityWorld.OldSubnet.AvailabilityZone = 'us-east-1b'
  $global:CapacityWorld.Group.AvailabilityZones = @('us-east-1b')
  $global:CapacityWorld.Group.SuspendedProcesses += @{ ProcessName = 'Launch' }
  $global:CapacityWorld.Offerings[0].InstanceType = 'g4dn.xlarge'
  $global:CapacityWorld.OutputName = 'gpu-g4dn-retry.tfvars.json'
}
function Use-DeployedG4dnFixture {
  $global:CapacityWorld.ExpectedType = 'g4dn.xlarge'
  $global:CapacityWorld.ExpectedCurrentType = 'g4dn.xlarge'
  $global:CapacityWorld.ExpectedGpuResource = '1'
  $global:CapacityWorld.Template.LaunchTemplateData.InstanceType = 'g4dn.xlarge'
  $global:CapacityWorld.Task.containerDefinitions[0].resourceRequirements[0].value = '1'
  $global:CapacityWorld.Offerings[0].InstanceType = 'g4dn.xlarge'
}
function Invoke-CapacityCase([string]$Case, [bool]$ExpectFailure, [scriptblock]$Mutate = {}, [string]$ExpectedError = '') {
  $script:CaseCount++
  New-CapacityWorld $Case
  $directory = Join-Path $script:Root $Case
  [void](New-Item -ItemType Directory -Path $directory)
  Set-Location $directory
  [IO.File]::WriteAllText((Join-Path $directory 'premium-owner.tfvars.json'), $script:SecretCanary)
  [IO.File]::WriteAllText((Join-Path $directory 'api.zip'), 'preserve-api-package')
  $env:AWS_PROFILE = 'previous-profile'; $env:AWS_ACCESS_KEY_ID = 'TEST_ONLY_AMBIENT_CREDENTIAL_CANARY'
  $env:PYTHONIOENCODING = 'ascii'; $env:TF_VAR_worker_image_tag = 'live-cpu-image'; $env:TF_VAR_enable_cpu_analysis = 'true'
  $env:TF_VAR_enable_gpu = 'false'; $env:TF_VAR_gpu_worker_image_uri = 'original-image-value'
  $env:TF_VAR_gpu_smoke_instance_type = 'original-type-value'; $env:TF_VAR_gpu_smoke_approval = 'original-approval-value'
  $env:TF_VAR_gpu_subnet_id = $script:OldSubnet; $env:TF_VAR_premium_owner_sub = 'original-owner-sub'
  $env:TF_VAR_admin_cognito_subs = '["original-admin"]'; $env:STROKESENSE_GPU_PLAN_PATH = 'existing-reviewed-plan'
  Remove-Item Env:TF_CLI_ARGS,Env:TF_CLI_ARGS_output -ErrorAction SilentlyContinue
  & $Mutate
  $output = Join-Path $directory $global:CapacityWorld.OutputName
  if ($Case -eq 'existing-different') { [IO.File]::WriteAllText($output, 'preserve-existing-gpu-inputs') }
  if ($Case -eq 'existing-identical') {
    $json = (ConvertTo-Json -InputObject (Expected-TestInputs) -Depth 5) + [Environment]::NewLine
    [IO.File]::WriteAllText($output, $json, (New-Object Text.UTF8Encoding($false)))
    [IO.File]::SetLastWriteTimeUtc($output, [datetime]'2020-01-01T00:00:00Z')
    $existingWrite = [IO.File]::GetLastWriteTimeUtc($output)
  }
  $before = @{}
  foreach ($name in $script:EnvironmentNames) { $before[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
  $messages = New-Object System.Collections.ArrayList
  $failure = $null
  $repeatOkay = $true
  try {
    $invoke = @{ ExpectedAccountId = $script:Account; ExpectedImageUri = $script:Image; AwsProfile = 'capacity-test-profile'
      AvailabilityZone = $global:CapacityWorld.Az; OutputPath = $output }
    if ($global:CapacityWorld.RequestedType) { $invoke.InstanceType = $global:CapacityWorld.RequestedType }
    & $script:Under @invoke *>&1 |
      ForEach-Object { [void]$messages.Add($_) }
    if ($Case -eq 'ready-repeat-same-output' -or $global:CapacityWorld.Repeat) {
      $firstHash = (Get-FileHash -LiteralPath $output -Algorithm SHA256).Hash
      $firstWrite = [IO.File]::GetLastWriteTimeUtc($output)
      $messages.Clear()
      & $script:Under @invoke *>&1 |
        ForEach-Object { [void]$messages.Add($_) }
      $repeatOkay = $firstHash -ceq (Get-FileHash -LiteralPath $output -Algorithm SHA256).Hash -and
        $firstWrite -eq [IO.File]::GetLastWriteTimeUtc($output)
    }
  } catch { $failure = $_.Exception.Message }
  $results = @($messages | Where-Object { $null -ne $_ -and $_.PSObject.Properties['ReadyForPlan'] })
  $outcome = (($null -ne $failure) -eq $ExpectFailure)
  $specific = !$ExpectedError -or ($failure -like "*$ExpectedError*")
  $environmentOkay = $true
  foreach ($name in $script:EnvironmentNames) {
    if ([Environment]::GetEnvironmentVariable($name, 'Process') -cne $before[$name]) { $environmentOkay = $false }
  }
  $untouched = [IO.File]::ReadAllText((Join-Path $directory 'premium-owner.tfvars.json')) -ceq $script:SecretCanary -and
    [IO.File]::ReadAllText((Join-Path $directory 'api.zip')) -ceq 'preserve-api-package' -and
    !(Test-Path -LiteralPath (Join-Path $directory 'gpu-smoke.tfvars.json'))
  $safeMessages = (($messages | Out-String) + $failure) -notlike "*$($script:SecretCanary)*"
  $resultOkay = $false
  if (!$ExpectFailure -and $results.Count -eq 1) {
    $result = $results[0]
    $content = [IO.File]::ReadAllText($output) | ConvertFrom-Json
    $expected = Expected-TestInputs
    $expectedNames = @($expected.Keys | Sort-Object)
    $actualNames = @($content.PSObject.Properties.Name | Sort-Object)
    $resultOkay = $result.ReadyForPlan -eq $true -and $result.InputsPath -ceq $output -and
      $result.InputsHash -ceq (Get-FileHash -LiteralPath $output -Algorithm SHA256).Hash.ToLowerInvariant() -and
      $result.OldSubnetId -ceq $script:OldSubnet -and $result.SubnetId -ceq $global:CapacityWorld.ExpectedSubnet -and
      $result.AvailabilityZone -ceq $global:CapacityWorld.Az -and $result.AsgName -ceq $script:Asg -and
      $result.LaunchTemplateId -ceq $script:Template -and $result.LaunchTemplateVersion -ceq '1' -and
      $result.CurrentInstanceType -ceq $global:CapacityWorld.ExpectedCurrentType -and
      $result.InstanceType -ceq $global:CapacityWorld.ExpectedType -and
      $result.IsInstanceTypeChange -eq $global:CapacityWorld.ExpectedTypeChange -and
      $result.GpuResource -ceq $global:CapacityWorld.ExpectedGpuResource -and
      $result.ImageUri -ceq $script:Image -and ($actualNames -join ',') -ceq ($expectedNames -join ',')
    foreach ($name in $expected.Keys) {
      if ((ConvertTo-Json -InputObject $content.$name -Depth 5 -Compress) -cne
          (ConvertTo-Json -InputObject $expected[$name] -Depth 5 -Compress)) { $resultOkay = $false }
    }
    if ($Case -eq 'existing-identical') { $resultOkay = $resultOkay -and ([IO.File]::GetLastWriteTimeUtc($output) -eq $existingWrite) }
  } elseif ($ExpectFailure) {
    $resultOkay = $results.Count -eq 0
    if ($Case -eq 'existing-different') { $resultOkay = $resultOkay -and ([IO.File]::ReadAllText($output) -ceq 'preserve-existing-gpu-inputs') }
    elseif ($global:CapacityWorld.OutputName -notin @('premium-owner.tfvars.json','api.zip')) { $resultOkay = $resultOkay -and !(Test-Path -LiteralPath $output) }
  }
  if ($outcome -and $specific -and $environmentOkay -and $untouched -and $safeMessages -and $resultOkay -and $repeatOkay) { Write-Host "PASS $Case" }
  else {
    Write-Host "FAIL $Case error=[$failure] expected=$outcome specific=$specific environment=$environmentOkay untouched=$untouched safe=$safeMessages result=$resultOkay"
    $script:Failures++
  }
}

try {
  Invoke-CapacityCase 'ready-main-route-map-public-false' $false
  Invoke-CapacityCase 'ready-launch-latched' $false {
    $global:CapacityWorld.Group.SuspendedProcesses += @{ ProcessName = 'Launch' }
  }
  Invoke-CapacityCase 'ready-repeat-same-output' $false
  Invoke-CapacityCase 'ready-g4dn-type-change-same-subnet' $false { Use-G4dnTypeChangeFixture }
  Invoke-CapacityCase 'ready-g4dn-type-change-repeat' $false { Use-G4dnTypeChangeFixture; $global:CapacityWorld.Repeat = $true }
  Invoke-CapacityCase 'ready-g4dn-type-change-explicit-route' $false {
    Use-G4dnTypeChangeFixture
    $global:CapacityWorld.ExplicitRoutes[$script:OldSubnet] = New-TestRoute $script:OldSubnet
  }
  Invoke-CapacityCase 'ready-deployed-g4dn-subnet-inferred' $false { Use-DeployedG4dnFixture }
  Invoke-CapacityCase 'ready-deployed-g4dn-subnet-explicit' $false {
    Use-DeployedG4dnFixture
    $global:CapacityWorld.RequestedType = 'g4dn.xlarge'
    $global:CapacityWorld.Outputs.gpu_smoke_instance_type = @{ value = 'g4dn.xlarge'; sensitive = $false; type = 'string' }
  }
  Invoke-CapacityCase 'type-change-keeps-existing-az' $true {
    Use-G4dnTypeChangeFixture
    $global:CapacityWorld.Az = 'us-east-1c'
  } 'must retain the existing subnet'
  Invoke-CapacityCase 'type-change-checks-current-gpu-count' $true {
    Use-G4dnTypeChangeFixture
    $global:CapacityWorld.Task.containerDefinitions[0].resourceRequirements[0].value = '1'
  } 'GPU requirement'
  Invoke-CapacityCase 'deployed-g4dn-rejects-fractional-task' $true {
    Use-DeployedG4dnFixture
    $global:CapacityWorld.Task.containerDefinitions[0].resourceRequirements[0].value = '0.125'
  } 'GPU requirement'
  Invoke-CapacityCase 'type-change-offering-must-match-target' $true {
    Use-G4dnTypeChangeFixture
    $global:CapacityWorld.Offerings[0].InstanceType = 'g6f.xlarge'
  } 'not reported as offered'
  Invoke-CapacityCase 'type-change-current-subnet-route-required' $true {
    Use-G4dnTypeChangeFixture
    $global:CapacityWorld.MainRoute.Routes = @()
  } 'active IPv4 default'
  Invoke-CapacityCase 'deployed-type-output-mismatch' $true {
    $global:CapacityWorld.Outputs.gpu_smoke_instance_type = @{ value = 'g4dn.xlarge'; sensitive = $false; type = 'string' }
  } 'type output differs'
  Invoke-CapacityCase 'unsupported-requested-type' $true { $global:CapacityWorld.RequestedType = 'g5.xlarge' }
  Invoke-CapacityCase 'same-type-same-subnet-is-not-recovery' $true {
    $global:CapacityWorld.OldSubnet.AvailabilityZone = 'us-east-1b'
    $global:CapacityWorld.Group.AvailabilityZones = @('us-east-1b')
    $global:CapacityWorld.Candidates = @($global:CapacityWorld.OldSubnet)
  } 'already the current subnet'
  Invoke-CapacityCase 'ready-explicit-route' $false {
    $global:CapacityWorld.ExplicitRoutes[$script:SubnetA] = New-TestRoute $script:SubnetA
  }
  Invoke-CapacityCase 'ready-skip-ineligible-first-subnet' $false {
    $global:CapacityWorld.Candidates[1].AvailableIpAddressCount = 1
    $global:CapacityWorld.ExpectedSubnet = $script:SubnetB
  }
  Invoke-CapacityCase 'ready-skip-private-first-subnet' $false {
    $route = New-TestRoute $script:SubnetA; $route.Routes = @()
    $global:CapacityWorld.ExplicitRoutes[$script:SubnetA] = $route
    $global:CapacityWorld.ExpectedSubnet = $script:SubnetB
  }
  Invoke-CapacityCase 'ready-selected-c-only' $false {
    $global:CapacityWorld.Az = 'us-east-1c'
    $global:CapacityWorld.Offerings[0].Location = 'us-east-1c'
    foreach ($candidate in $global:CapacityWorld.Candidates) { $candidate.AvailabilityZone = 'us-east-1c' }
  }
  Invoke-CapacityCase 'profile-originally-absent' $false { Remove-Item Env:AWS_PROFILE,Env:PYTHONIOENCODING -ErrorAction SilentlyContinue }
  Invoke-CapacityCase 'existing-identical' $false
  Invoke-CapacityCase 'existing-different' $true {} 'already contains different'
  Invoke-CapacityCase 'wrong-account' $true { $global:CapacityWorld.Identity.Account = '111111111111' } 'wrong account'
  Invoke-CapacityCase 'wrong-caller-arn' $true { $global:CapacityWorld.Identity.Arn = 'arn:aws:iam::111111111111:user/other' } 'ARN'
  foreach ($case in @('native-error','root-empty-array','root-single-array','root-null','aws-invalid-json','terraform-failure','terraform-invalid-json')) {
    Invoke-CapacityCase $case $true
  }
  Invoke-CapacityCase 'unsafe-cli-args' $true { $env:TF_CLI_ARGS_output = '-state=other-state' } 'TF_CLI_ARGS_output'
  Invoke-CapacityCase 'missing-output' $true { [void]$global:CapacityWorld.Outputs.Remove('gpu_smoke_subnet_id') } 'gpu_smoke_subnet_id'
  Invoke-CapacityCase 'foreign-output-arn' $true { $global:CapacityWorld.Outputs.gpu_smoke_ecs_cluster.value = 'arn:aws:ecs:us-east-1:111111111111:cluster/other' } 'ARN'
  Invoke-CapacityCase 'mutable-template-version' $true { $global:CapacityWorld.Outputs.gpu_smoke_launch_template_version.value = '$Latest' } 'identifiers'
  Invoke-CapacityCase 'wrong-output-repo' $true { $global:CapacityWorld.Outputs.gpu_worker_ecr_repository.value = '851226124502.dkr.ecr.us-east-1.amazonaws.com/other' } 'repository'
  Invoke-CapacityCase 'asg-not-idle' $true { $global:CapacityWorld.Group.MaxSize = 1 } '0/0/0'
  foreach ($process in @('Terminate','ScheduledActions','AlarmNotification')) {
    Invoke-CapacityCase "asg-unexpected-suspension-$process" $true {
      $global:CapacityWorld.Group.SuspendedProcesses += @{ ProcessName = $process }
    } 'Unexpected suspended ASG process'
  }
  Invoke-CapacityCase 'asg-missing-replacement-latch' $true {
    $global:CapacityWorld.Group.SuspendedProcesses = @(@{ ProcessName = 'AZRebalance' })
  } 'ReplaceUnhealthy must remain suspended'
  Invoke-CapacityCase 'asg-duplicate-latch' $true {
    $global:CapacityWorld.Group.SuspendedProcesses += @{ ProcessName = 'AZRebalance' }
  } 'duplicate'
  Invoke-CapacityCase 'asg-has-member' $true { $global:CapacityWorld.Group.Instances = @(@{ InstanceId = 'i-01111111111111111' }) } 'still has instances'
  Invoke-CapacityCase 'asg-foreign-arn' $true { $global:CapacityWorld.Group.AutoScalingGroupARN = $global:CapacityWorld.Group.AutoScalingGroupARN.Replace($script:Account,'111111111111') } 'ARN'
  Invoke-CapacityCase 'asg-subnet-drift' $true { $global:CapacityWorld.Group.VPCZoneIdentifier = $script:SubnetB } 'subnet differs'
  Invoke-CapacityCase 'asg-template-drift' $true { $global:CapacityWorld.Group.LaunchTemplate.Version = '2' } 'launch-template'
  Invoke-CapacityCase 'asg-race' $true {} '0/0/0'
  Invoke-CapacityCase 'leftover-tagged-instance' $true { $global:CapacityWorld.Reservations = @(@{ OwnerId = $script:Account; Instances = @(@{ InstanceId = 'i-01111111111111111' }) }) } 'nonterminated'
  Invoke-CapacityCase 'cluster-has-pending-count' $true { $global:CapacityWorld.Cluster.pendingTasksCount = 1 } 'cluster must have no'
  Invoke-CapacityCase 'cluster-has-service' $true { $global:CapacityWorld.Services = @('service') } 'still has services'
  Invoke-CapacityCase 'cluster-running-desired-task' $true { $global:CapacityWorld.RunningTasks = @('task') } 'running or pending'
  Invoke-CapacityCase 'cluster-pending-desired-task' $true { $global:CapacityWorld.PendingTasks = @('task') } 'running or pending'
  Invoke-CapacityCase 'incomplete-pagination' $true {} 'pagination'
  Invoke-CapacityCase 'null-tasks' $true {} 'collection'
  Invoke-CapacityCase 'changed-ami' $true { $global:CapacityWorld.Template.LaunchTemplateData.ImageId = 'ami-01111111111111111' } 'host type'
  Invoke-CapacityCase 'wrong-host-type' $true { $global:CapacityWorld.Template.LaunchTemplateData.InstanceType = 'g6.xlarge' } 'host type'
  Invoke-CapacityCase 'no-host-public-ip' $true { $global:CapacityWorld.Template.LaunchTemplateData.NetworkInterfaces[0].AssociatePublicIpAddress = $false } 'interface'
  Invoke-CapacityCase 'string-public-ip' $true { $global:CapacityWorld.Template.LaunchTemplateData.NetworkInterfaces[0].AssociatePublicIpAddress = 'false' } 'interface'
  Invoke-CapacityCase 'pinned-existing-eni' $true { $global:CapacityWorld.Template.LaunchTemplateData.NetworkInterfaces[0].NetworkInterfaceId = 'eni-01111111111111111' } 'interface'
  Invoke-CapacityCase 'pinned-host-subnet' $true { $global:CapacityWorld.Template.LaunchTemplateData.NetworkInterfaces[0].SubnetId = $script:OldSubnet } 'placement'
  Invoke-CapacityCase 'metadata-not-required' $true { $global:CapacityWorld.Template.LaunchTemplateData.MetadataOptions.HttpTokens = 'optional' } 'IMDS'
  Invoke-CapacityCase 'missing-gpu-bootstrap' $true { $global:CapacityWorld.Template.LaunchTemplateData.UserData = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes('#!/bin/bash')) } 'bootstrap'
  Invoke-CapacityCase 'foreign-host-profile' $true { $global:CapacityWorld.Template.LaunchTemplateData.IamInstanceProfile.Arn = 'arn:aws:iam::111111111111:instance-profile/other' } 'ARN'
  Invoke-CapacityCase 'foreign-security-group' $true { $global:CapacityWorld.Groups[0].VpcId = 'vpc-01111111111111111' } 'security-group VPC'
  Invoke-CapacityCase 'missing-host-https' $true { $global:CapacityWorld.Groups[0].IpPermissionsEgress = @() } 'outbound HTTPS'
  Invoke-CapacityCase 'dns-disabled' $true { $global:CapacityWorld.DnsSupport = $false } 'enableDnsSupport'
  Invoke-CapacityCase 'dns-hostnames-disabled' $true { $global:CapacityWorld.DnsHostnames = $false } 'enableDnsHostnames'
  Invoke-CapacityCase 'preflight-image-mismatch' $true { $global:CapacityWorld.Task.containerDefinitions[0].image = $script:Image.Replace('sha256:a','sha256:b') } 'preflight image'
  Invoke-CapacityCase 'preflight-customer-role' $true { $global:CapacityWorld.Task.taskRoleArn = "arn:aws:iam::$($script:Account):role/customer" } 'customer credentials'
  Invoke-CapacityCase 'preflight-extra-environment' $true { $global:CapacityWorld.Task.containerDefinitions[0].environment = @(@{ name = 'X'; value = 'Y' }) } 'environment overrides'
  Invoke-CapacityCase 'ecr-image-missing' $true { $global:CapacityWorld.Images = @() } 'digest is not present'
  Invoke-CapacityCase 'ecr-foreign-registry' $true { $global:CapacityWorld.Images[0].registryId = '111111111111' } 'digest is not present'
  Invoke-CapacityCase 'insufficient-quota' $true { $global:CapacityWorld.Quota.Value = 0 } 'quota'
  Invoke-CapacityCase 'az-not-offered' $true { $global:CapacityWorld.Offerings = @() } 'not reported as offered'
  Invoke-CapacityCase 'no-candidate-subnets' $true { $global:CapacityWorld.Candidates = @() } 'No existing subnets'
  Invoke-CapacityCase 'wrong-candidate-vpc' $true { foreach ($candidate in $global:CapacityWorld.Candidates) { $candidate.VpcId = 'vpc-01111111111111111' } } 'Subnet identity'
  Invoke-CapacityCase 'wrong-candidate-az' $true { foreach ($candidate in $global:CapacityWorld.Candidates) { $candidate.AvailabilityZone = 'us-east-1d' } } 'Availability Zone'
  Invoke-CapacityCase 'wrong-candidate-owner' $true { foreach ($candidate in $global:CapacityWorld.Candidates) { $candidate.OwnerId = '111111111111' } } 'owner'
  Invoke-CapacityCase 'no-active-default-route' $true { $global:CapacityWorld.MainRoute.Routes[0].State = 'blackhole' } 'active IPv4 default'
  Invoke-CapacityCase 'private-nat-route' $true { $global:CapacityWorld.MainRoute.Routes[0].GatewayId = 'nat-01111111111111111' } 'Internet Gateway'
  Invoke-CapacityCase 'route-vpc-mismatch' $true { $global:CapacityWorld.MainRoute.VpcId = 'vpc-01111111111111111' } 'effective route table'
  Invoke-CapacityCase 'detached-internet-gateway' $true { $global:CapacityWorld.Gateway.Attachments = @() } 'not attached'
  Invoke-CapacityCase 'gateway-other-vpc' $true { $global:CapacityWorld.Gateway.Attachments[0].VpcId = 'vpc-01111111111111111' } 'not attached'
  Invoke-CapacityCase 'restrictive-acl' $true {
    foreach ($id in @($script:SubnetA,$script:SubnetB)) { $global:CapacityWorld.Acls[$id].Entries[0].RuleAction = 'deny' }
  } 'Unsupported custom network ACL'
  Invoke-CapacityCase 'acl-port-specific-unreviewed' $true {
    foreach ($id in @($script:SubnetA,$script:SubnetB)) { $global:CapacityWorld.Acls[$id].Entries[1].Protocol = '6' }
  } 'Unsupported custom network ACL'
  Invoke-CapacityCase 'protected-original-input-name' $true { $global:CapacityWorld.OutputName = 'gpu-smoke.tfvars.json' } 'protected'
  Invoke-CapacityCase 'protected-premium-input-name' $true { $global:CapacityWorld.OutputName = 'premium-owner.tfvars.json' } 'protected'
  Invoke-CapacityCase 'protected-api-package-name' $true { $global:CapacityWorld.OutputName = 'api.zip' } 'protected'
  Invoke-CapacityCase 'protected-auto-loaded-input-name' $true { $global:CapacityWorld.OutputName = 'gpu-capacity-retry.auto.tfvars.json' } 'protected'
} finally {
  Set-Location $script:OriginalLocation
  Remove-Item Function:\aws,Function:\terraform -ErrorAction SilentlyContinue
  foreach ($name in $script:EnvironmentNames) { Restore-TestEnvironment $name $script:SavedEnvironment[$name] }
  Remove-Item -LiteralPath $script:Root -Recurse -Force -ErrorAction SilentlyContinue
}
if ($script:Failures -ne 0) { throw "$script:Failures of $script:CaseCount GPU capacity preparation scenarios failed." }
Write-Host "All $script:CaseCount GPU capacity preparation scenarios passed."
$global:LASTEXITCODE = 0
