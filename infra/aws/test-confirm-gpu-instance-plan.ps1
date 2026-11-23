# Offline tests for G6f -> G4dn migration review. Every AWS/Terraform operation
# is replaced; unexpected commands fail rather than reaching a real account.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:Under = Join-Path $PSScriptRoot 'confirm-gpu-instance-plan.ps1'
$script:Account = '851226124502'
$script:Subnet = 'subnet-0123456789abcdef0'
$script:Vpc = 'vpc-0793c6d459d5f8e89'
$script:HostGroup = 'sg-07d81508d9c012a22'
$script:Asg = 'strokesense-aws-dev-gpu-one-instance'
$script:AsgArn = 'arn:aws:autoscaling:us-east-1:851226124502:autoScalingGroup:11111111-1111-4111-8111-111111111111:autoScalingGroupName/' + $script:Asg
$script:Lt = 'lt-005c322e797a51386'
$script:Ami = 'ami-0b8f7c7154f9e8f8b'
$script:Cluster = 'arn:aws:ecs:us-east-1:851226124502:cluster/strokesense-aws-dev-paid-gpu'
$script:Digest = 'sha256:' + ('a' * 64)
$script:Image = '851226124502.dkr.ecr.us-east-1.amazonaws.com/strokesense-aws-dev-gpu-worker@' + $script:Digest
$script:Canary = 'PRIVATE_PLAN_CANARY_MUST_NOT_APPEAR'
$script:Cases = 0
$script:Failures = 0
$script:OriginalLocation = Get-Location
$script:Directory = Join-Path ([IO.Path]::GetTempPath()) ('strokesense-instance-tests-' + [guid]::NewGuid().ToString('N'))
[void](New-Item -ItemType Directory -Path $script:Directory)
$script:PlanPath = Join-Path $script:Directory 'instance migration plan.tfplan'
$script:EnvironmentNames = @('AWS_PROFILE','AWS_ACCESS_KEY_ID','PYTHONIOENCODING','TF_CLI_ARGS','TF_CLI_ARGS_show','TF_CLI_ARGS_output','TF_CLI_ARGS_workspace','TF_VAR_worker_image_tag','TF_VAR_enable_cpu_analysis')
$script:SavedEnvironment = @{}
foreach ($name in $script:EnvironmentNames) { $script:SavedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name,'Process') }

function Copy-InstanceFixture($Value) { return (ConvertTo-Json -InputObject $Value -Depth 70 -Compress | ConvertFrom-Json) }
function New-TaskFixture([string]$Name, [string]$Family) {
  $command = if ($Name -ceq 'gpu-preflight') { @('python3','-m','aws_app.gpu_preflight','--model','/app/models/yolo11n-pose.onnx') } else { @('python3','-m','aws_app.gpu_worker') }
  $container = @{
    name=$Name; image=$script:Image; cpu=2048; memory=8192; essential=$true
    command=$command; resourceRequirements=@(@{type='GPU';value='0.125'})
    environment=@(); mountPoints=@(); portMappings=@(); volumesFrom=@()
    logConfiguration=@{logDriver='awslogs';options=@{'awslogs-group'='/ecs/strokesense-aws-dev/paid-gpu';'awslogs-region'='us-east-1';'awslogs-stream-prefix'=$Name};secretOptions=@()}
  }
  $arn='arn:aws:ecs:us-east-1:851226124502:task-definition/' + $Family + ':1'
  return @{
    arn=$arn; arn_without_revision=($arn -replace ':1$',''); id=$Family; family=$Family; revision=1
    network_mode='awsvpc'; requires_compatibilities=@('EC2'); cpu='2048'; memory='8192'
    execution_role_arn='arn:aws:iam::851226124502:role/strokesense-aws-dev-batch-execution'
    task_role_arn=$(if ($Name -ceq 'gpu-preflight') { '' } else { 'arn:aws:iam::851226124502:role/strokesense-aws-dev-gpu-worker' })
    container_definitions=(ConvertTo-Json -InputObject @($container) -Depth 20 -Compress)
    volume=@(); placement_constraints=@(); tags=@{}; tags_all=@{Application='StrokeSense'}
    skip_destroy=$false; track_latest=$false; pid_mode=''; ipc_mode=''; enable_fault_injection=$false
  }
}
function Task-FixtureLive($Value, [string]$Arn) {
  $wrapper = ConvertFrom-Json -InputObject ('{"items":' + $Value.container_definitions + '}')
  return @{
    taskDefinitionArn=$Arn; family=$Value.family; revision=[int](($Arn -split ':')[-1]); status='ACTIVE'
    networkMode=$Value.network_mode; requiresCompatibilities=$Value.requires_compatibilities
    cpu=$Value.cpu; memory=$Value.memory; executionRoleArn=$Value.execution_role_arn; taskRoleArn=$Value.task_role_arn
    containerDefinitions=$wrapper.items; volumes=@(); placementConstraints=@(); enableFaultInjection=$false
  }
}
function New-InstanceFixture {
  $bootstrap=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes('ECS_ENABLE_GPU_SUPPORT=true'))
  $ltBefore=@{
    id=$script:Lt; arn=('arn:aws:ec2:us-east-1:851226124502:launch-template/' + $script:Lt)
    latest_version=1; default_version=1; instance_type='g6f.xlarge'; image_id=$script:Ami
    user_data=$bootstrap; ebs_optimized='true'; update_default_version=$false
    metadata_options=@(@{http_tokens='required';http_endpoint='enabled'})
    network_interfaces=@(@{device_index=0;associate_public_ip_address='true';delete_on_termination='true';security_groups=@($script:HostGroup)})
    iam_instance_profile=@(@{arn='arn:aws:iam::851226124502:instance-profile/strokesense-aws-dev-gpu-instance'})
    block_device_mappings=@(@{device_name='/dev/xvda';ebs=@(@{volume_size=80;volume_type='gp3';encrypted='true';delete_on_termination='true'})})
    tags_all=@{Application='StrokeSense'}
  }
  $ltAfter=Copy-InstanceFixture $ltBefore
  $ltAfter.instance_type='g4dn.xlarge'; $ltAfter.latest_version=$null
  $asgBefore=@{
    id=$script:Asg;name=$script:Asg;arn=$script:AsgArn
    min_size=0;max_size=0;desired_capacity=0;protect_from_scale_in=$false
    vpc_zone_identifier=@($script:Subnet);availability_zones=@('us-east-1b')
    launch_template=@(@{id=$script:Lt;name='';version='1'})
    suspended_processes=@('Launch','ReplaceUnhealthy','AZRebalance')
    health_check_type='EC2';default_cooldown=300;capacity_rebalance=$false
    tag=@(@{key='AmazonECSManaged';value='true';propagate_at_launch=$true})
  }
  $asgAfter=Copy-InstanceFixture $asgBefore
  $asgAfter.launch_template[0].version=$null
  $asgAfter.suspended_processes=@('AZRebalance','ReplaceUnhealthy')
  $preflight=New-TaskFixture 'gpu-preflight' 'strokesense-aws-dev-gpu-preflight'
  $worker=New-TaskFixture 'paid-gpu-worker' 'strokesense-aws-dev-paid-gpu'
  $changes=@(
    @{address='aws_launch_template.gpu[0]';mode='managed';change=@{actions=@('update');before=$ltBefore;after=$ltAfter;after_unknown=@{latest_version=$true}}},
    @{address='aws_autoscaling_group.gpu[0]';mode='managed';change=@{actions=@('update');before=$asgBefore;after=$asgAfter;after_unknown=@{launch_template=@(@{version=$true})}}}
  )
  foreach ($pair in @(@('aws_ecs_task_definition.gpu_preflight[0]',$preflight),@('aws_ecs_task_definition.gpu[0]',$worker))) {
    $after=Copy-InstanceFixture $pair[1]
    $wrapper=ConvertFrom-Json -InputObject ('{"items":' + $after.container_definitions + '}')
    $wrapper.items[0].resourceRequirements[0].value='1'
    $after.container_definitions=ConvertTo-Json -InputObject $wrapper.items -Depth 20 -Compress
    $after.arn=$null; $after.arn_without_revision=$null; $after.id=$null; $after.revision=$null
    # Provider replacement plans can omit this optional disabled setting even
    # when a refresh returned false for the existing task definition.
    $after.enable_fault_injection=$null
    $changes+=@{address=$pair[0];mode='managed';change=@{actions=@('delete','create');before=$pair[1];after=$after;after_unknown=@{arn=$true;arn_without_revision=$true;id=$true;revision=$true}}}
  }
  $dependency=@{id='gpu-role';name='gpu-role'}
  $changes+=@{address='aws_iam_role.gpu_ec2_instance[0]';mode='managed';change=@{actions=@('no-op');before=$dependency;after=(Copy-InstanceFixture $dependency);after_unknown=@{}}}
  $variables=@{}
  $inputs=@{
    aws_region='us-east-1';gpu_smoke_instance_type='g4dn.xlarge';enable_gpu=$true;gpu_smoke_mode=$true
    gpu_smoke_approval='I_APPROVE_ONE_G4DN_SMOKE_INSTANCE';enable_gpu_image_repository=$true
    enable_paid_gpu_queue_scaffold=$false;enable_cpu_smoke_queue=$false;gpu_subnet_id=$script:Subnet
    gpu_s3_route_table_ids=@();gpu_worker_image_uri=$script:Image;google_oauth_client_secret=$script:Canary
    enable_cpu_analysis=$false;worker_image_tag='cpu-latest'
  }
  foreach ($name in $inputs.Keys) { $variables[$name]=@{value=$inputs[$name]} }
  $identity=@{address='data.aws_caller_identity.current';mode='data';values=@{account_id=$script:Account}}
  $plan=@{
    format_version='1.2';terraform_version='1.10.5';applyable=$true;complete=$false;errored=$false
    variables=$variables;resource_changes=$changes
    prior_state=@{values=@{root_module=@{resources=@($identity)}}}
    planned_values=@{root_module=@{resources=@()};outputs=@{
      gpu_smoke_subnet_id=@{value=$script:Subnet};gpu_smoke_instance_type=@{value='g4dn.xlarge'};gpu_smoke_gpu_resource=@{value='1'}
    }}
  }
  $outputs=@{}
  foreach ($pair in @(@('gpu_smoke_asg_name',$script:Asg),@('gpu_smoke_ecs_cluster',$script:Cluster),@('gpu_smoke_launch_template_id',$script:Lt),
    @('gpu_smoke_launch_template_version','1'),@('gpu_smoke_subnet_id',$script:Subnet),@('gpu_smoke_task_definition',$preflight.arn),@('gpu_smoke_ami_id',$script:Ami))) { $outputs[$pair[0]]=@{value=$pair[1]} }
  $liveTemplate=@{
    LaunchTemplateId=$script:Lt;VersionNumber=1;LaunchTemplateData=@{
      InstanceType='g6f.xlarge';ImageId=$script:Ami;UserData=$bootstrap;MetadataOptions=@{HttpTokens='required'}
      NetworkInterfaces=@(@{DeviceIndex=0;AssociatePublicIpAddress=$true;DeleteOnTermination=$true;Groups=@($script:HostGroup)})
      IamInstanceProfile=@{Arn=$ltBefore.iam_instance_profile[0].arn}
      BlockDeviceMappings=@(@{DeviceName='/dev/xvda';Ebs=@{VolumeSize=80;VolumeType='gp3';Encrypted=$true;DeleteOnTermination=$true}})
    }
  }
  return @{
    Plan=$plan;Outputs=$outputs;PlanPath=$script:PlanPath;Canary=$script:Canary;Scenario='';VerifyApplied=$false;WorkspaceCalls=0;Calls=(New-Object System.Collections.ArrayList)
    Account=$script:Account;Template=$liveTemplate
    TaskDefinitions=@{($preflight.arn)=(Task-FixtureLive $preflight $preflight.arn);($worker.arn)=(Task-FixtureLive $worker $worker.arn)}
    LiveAsg=@{AutoScalingGroupName=$script:Asg;AutoScalingGroupARN=$script:AsgArn;MinSize=0;MaxSize=0;DesiredCapacity=0;Instances=@()
      VPCZoneIdentifier=$script:Subnet;LaunchTemplate=@{LaunchTemplateId=$script:Lt;Version='1'};NewInstancesProtectedFromScaleIn=$false
      SuspendedProcesses=@(@{ProcessName='Launch'},@{ProcessName='AZRebalance'},@{ProcessName='ReplaceUnhealthy'})}
    Reservations=@();Activities=@(@{AutoScalingGroupName=$script:Asg;StatusCode='Failed'})
    Services=@();Tasks=@();Containers=@();StoppedTasks=@();StoppedDetails=@()
    Subnets=@(@{SubnetId=$script:Subnet;OwnerId=$script:Account;VpcId=$script:Vpc;State='available';AvailableIpAddressCount=16})
    SecurityGroups=@(@{GroupId=$script:HostGroup;OwnerId=$script:Account;VpcId=$script:Vpc})
    Published=@(@{registryId=$script:Account;imageDigest=$script:Digest})
  }
}
function Find-InstanceChange([string]$Address='aws_autoscaling_group.gpu[0]') {
  return ($global:InstanceWorld.Plan.resource_changes | Where-Object { $_.address -ceq $Address }).change
}
function Use-AppliedInstanceFixture {
  $world=$global:InstanceWorld
  $world.VerifyApplied=$true
  $world.Outputs.gpu_smoke_launch_template_version.value='2'
  $world.Outputs.gpu_smoke_instance_type=@{value='g4dn.xlarge'}
  $world.Outputs.gpu_smoke_gpu_resource=@{value='1'}
  $world.Template.VersionNumber=2;$world.Template.LaunchTemplateData.InstanceType='g4dn.xlarge'
  $world.LiveAsg.LaunchTemplate.Version='2'
  $world.LiveAsg.SuspendedProcesses=@(@{ProcessName='AZRebalance'},@{ProcessName='ReplaceUnhealthy'})
  $world.TaskDefinitions=@{}
  foreach ($pair in @(@('aws_ecs_task_definition.gpu_preflight[0]','gpu_smoke_task_definition'),@('aws_ecs_task_definition.gpu[0]','gpu_smoke_worker_task_definition'))) {
    $change=Find-InstanceChange $pair[0]
    $arn=$change.before.arn -replace ':1$',':2'
    $world.Outputs[$pair[1]]=@{value=$arn}
    $world.TaskDefinitions[$arn]=Task-FixtureLive $change.after $arn
  }
}
function Set-TaskContainerChange([string]$Address,[scriptblock]$Update) {
  $change=Find-InstanceChange $Address
  $wrapper=ConvertFrom-Json -InputObject ('{"items":' + $change.after.container_definitions + '}')
  & $Update $wrapper.items[0]
  $change.after.container_definitions=ConvertTo-Json -InputObject $wrapper.items -Depth 30 -Compress
}
function global:aws {
  $a=@($args | ForEach-Object { [string]$_ })
  $op=$a[0]+' '+$a[1]
  $world=$global:InstanceWorld
  [void]$world.Calls.Add('aws '+$op)
  if ($a -contains '--profile' -or $env:AWS_PROFILE -cne 'migration-test-profile' -or $env:AWS_ACCESS_KEY_ID -cne 'fixture-ambient-chain') { throw 'Ambient credential chain was bypassed.' }
  $global:LASTEXITCODE=0
  $payload=switch -Exact ($op) {
    'sts get-caller-identity' { @{Account=$world.Account} }
    'ec2 describe-launch-template-versions' {
      if ($a[$a.IndexOf('--versions')+1] -cne [string]$world.Template.VersionNumber) { throw 'Requested concrete template version differs.' }
      @{LaunchTemplateVersions=@($world.Template)}
    }
    'ecs describe-task-definition' {
      $arn=$a[$a.IndexOf('--task-definition')+1]
      if (!$world.TaskDefinitions.ContainsKey($arn)) { throw 'Unexpected task definition lookup.' }
      @{taskDefinition=$world.TaskDefinitions[$arn]}
    }
    'autoscaling describe-auto-scaling-groups' { @{AutoScalingGroups=@($world.LiveAsg)} }
    'autoscaling describe-scaling-activities' { @{Activities=$world.Activities} }
    'ec2 describe-instances' { @{Reservations=$world.Reservations} }
    'ecs list-services' { @{serviceArns=$world.Services} }
    'ecs list-tasks' {
      if ($a[$a.IndexOf('--desired-status')+1] -ceq 'STOPPED') { @{taskArns=$world.StoppedTasks} }
      else { @{taskArns=$world.Tasks} }
    }
    'ecs list-container-instances' { @{containerInstanceArns=$world.Containers} }
    'ecs describe-tasks' { @{tasks=$world.StoppedDetails;failures=@()} }
    'ec2 describe-subnets' { @{Subnets=$world.Subnets} }
    'ec2 describe-security-groups' { @{SecurityGroups=$world.SecurityGroups} }
    'ecr describe-images' { @{imageDetails=$world.Published} }
    default { throw "Unexpected AWS operation: $op" }
  }
  if ($world.Scenario -ceq 'incomplete-pagination' -and $op -ceq 'ecs list-services') { $payload.nextToken='unread-page' }
  return (ConvertTo-Json -InputObject $payload -Depth 60 -Compress)
}
function global:terraform {
  $a=@($args | ForEach-Object { [string]$_ })
  $world=$global:InstanceWorld
  $global:LASTEXITCODE=0
  if ($a[0] -ceq 'workspace' -and $a[1] -ceq 'show') {
    $world.WorkspaceCalls++
    if ($world.Scenario -ceq 'workspace-changed' -and $world.WorkspaceCalls -gt 1) { return 'different-workspace' }
    return 'migration-tests'
  }
  if ($a[0] -ceq 'show' -and $a[1] -ceq '-json') {
    if ($a[-1] -cne $world.PlanPath) { throw 'Wrong plan path.' }
    if ($world.Scenario -ceq 'plan-changed') { [IO.File]::AppendAllText($world.PlanPath,'changed') }
    if ($world.Scenario -ceq 'private-show-error') { $global:LASTEXITCODE=1;return $world.Canary }
    if ($world.Scenario -ceq 'private-json-error') { return ('{"secret":"' + $world.Canary + '",INVALID') }
    if ($world.Scenario -ceq 'root-array-plan') { return '[]' }
    return (ConvertTo-Json -InputObject $world.Plan -Depth 70 -Compress)
  }
  if ($a[0] -ceq 'output' -and $a[1] -ceq '-json') { return (ConvertTo-Json -InputObject $world.Outputs -Depth 30 -Compress) }
  throw 'Unexpected Terraform operation.'
}
function Invoke-InstanceCase([string]$CaseName,[string]$FailureText='',[scriptblock]$Mutate={}) {
  $script:Cases++
  $global:InstanceWorld=New-InstanceFixture
  $global:InstanceWorld.Scenario=$CaseName
  [IO.File]::WriteAllText($script:PlanPath,'private migration plan fixture')
  $env:AWS_PROFILE='original-profile';$env:AWS_ACCESS_KEY_ID='fixture-ambient-chain'
  foreach ($name in @('TF_CLI_ARGS','TF_CLI_ARGS_show','TF_CLI_ARGS_output','TF_CLI_ARGS_workspace','TF_VAR_worker_image_tag','TF_VAR_enable_cpu_analysis')) { Remove-Item -LiteralPath ("Env:"+$name) -ErrorAction SilentlyContinue }
  & $Mutate
  $profileBefore=[Environment]::GetEnvironmentVariable('AWS_PROFILE','Process')
  $encodingBefore=[Environment]::GetEnvironmentVariable('PYTHONIOENCODING','Process')
  $messages=New-Object System.Collections.ArrayList
  $failure=''
  try {
    & $script:Under -PlanPath $script:PlanPath -ExpectedAccountId $script:Account -ExpectedSubnetId $script:Subnet -ExpectedImageUri $script:Image -AwsProfile migration-test-profile -VerifyApplied:$global:InstanceWorld.VerifyApplied *>&1 | ForEach-Object { [void]$messages.Add($_) }
  } catch { $failure=$_.Exception.Message }
  $results=@($messages | Where-Object { $null -ne $_ -and $_.PSObject.Properties['ReadyForApply'] })
  $ok=if ($FailureText) { $failure.Contains($FailureText) -and $results.Count -eq 0 } else {
    !$failure -and $results.Count -eq 1 -and $results[0].ReadyForApply -eq (!$global:InstanceWorld.VerifyApplied) -and
      $results[0].ReadyForSmoke -eq $global:InstanceWorld.VerifyApplied -and $results[0].InstanceType -ceq 'g4dn.xlarge' -and
      $results[0].SubnetId -ceq $script:Subnet -and $results[0].PlanHash -cmatch '^[a-f0-9]{64}$'
  }
  if (($messages | Out-String).Contains($script:Canary) -or $failure.Contains($script:Canary) -or
      [Environment]::GetEnvironmentVariable('AWS_PROFILE','Process') -cne $profileBefore -or
      [Environment]::GetEnvironmentVariable('PYTHONIOENCODING','Process') -cne $encodingBefore -or $env:AWS_ACCESS_KEY_ID -cne 'fixture-ambient-chain') { $ok=$false }
  if (!$ok) { $script:Failures++;Write-Host "FAIL $CaseName expected [$FailureText], got [$failure]";return }
  Write-Host "PASS $CaseName"
}
try {
  Set-Location -LiteralPath $PSScriptRoot
  Invoke-InstanceCase 'valid-computed-versions'
  Invoke-InstanceCase 'valid-known-versions' '' {
    (Find-InstanceChange 'aws_launch_template.gpu[0]').after.latest_version=2
    (Find-InstanceChange 'aws_launch_template.gpu[0]').after_unknown=@{}
    (Find-InstanceChange).after.launch_template[0].version='2'
    (Find-InstanceChange).after_unknown=@{}
  }
  Invoke-InstanceCase 'valid-create-before-delete' '' { (Find-InstanceChange 'aws_ecs_task_definition.gpu[0]').actions=@('create','delete') }
  Invoke-InstanceCase 'valid-launch-already-active' '' {
    (Find-InstanceChange).before.suspended_processes=@('AZRebalance','ReplaceUnhealthy')
    $global:InstanceWorld.LiveAsg.SuspendedProcesses=@(@{ProcessName='AZRebalance'},@{ProcessName='ReplaceUnhealthy'})
  }
  Invoke-InstanceCase 'valid-empty-default-normalization' '' {
    Set-TaskContainerChange 'aws_ecs_task_definition.gpu_preflight[0]' {
      param($c)
      $c.PSObject.Properties.Remove('environment');$c.PSObject.Properties.Remove('mountPoints')
      $c.PSObject.Properties.Remove('portMappings');$c.PSObject.Properties.Remove('volumesFrom')
      $c.logConfiguration.PSObject.Properties.Remove('secretOptions')
    }
  }
  foreach ($faultBefore in @('missing','null','false')) {
    foreach ($faultAfter in @('missing','null','false')) {
      Invoke-InstanceCase ("valid-fault-default-$faultBefore-to-$faultAfter") '' {
        foreach ($address in @('aws_ecs_task_definition.gpu_preflight[0]','aws_ecs_task_definition.gpu[0]')) {
          $change=Find-InstanceChange $address
          switch ($faultBefore) {
            'missing' { $change.before.Remove('enable_fault_injection') }
            'null' { $change.before.enable_fault_injection=$null }
            'false' { $change.before.enable_fault_injection=$false }
          }
          switch ($faultAfter) {
            'missing' { $change.after.PSObject.Properties.Remove('enable_fault_injection') }
            'null' { $change.after.enable_fault_injection=$null }
            'false' { $change.after.enable_fault_injection=$false }
          }
        }
      }
    }
  }
  Invoke-InstanceCase 'valid-live-fault-default-missing' '' {
    foreach ($task in $global:InstanceWorld.TaskDefinitions.Values) { $task.Remove('enableFaultInjection') }
  }
  Invoke-InstanceCase 'valid-live-fault-default-null' '' {
    foreach ($task in $global:InstanceWorld.TaskDefinitions.Values) { $task.enableFaultInjection=$null }
  }
  Invoke-InstanceCase 'valid-unset-environment-restored' '' {
    Remove-Item Env:AWS_PROFILE -ErrorAction SilentlyContinue
    Remove-Item Env:PYTHONIOENCODING -ErrorAction SilentlyContinue
  }
  Invoke-InstanceCase 'applied-valid' '' { Use-AppliedInstanceFixture }
  Invoke-InstanceCase 'applied-valid-fault-default-missing' '' {
    Use-AppliedInstanceFixture
    foreach ($task in $global:InstanceWorld.TaskDefinitions.Values) { $task.Remove('enableFaultInjection') }
  }
  Invoke-InstanceCase 'applied-valid-fault-default-null' '' {
    Use-AppliedInstanceFixture
    foreach ($task in $global:InstanceWorld.TaskDefinitions.Values) { $task.enableFaultInjection=$null }
  }
  Invoke-InstanceCase 'applied-known-versions' '' {
    (Find-InstanceChange 'aws_launch_template.gpu[0]').after.latest_version=2
    (Find-InstanceChange 'aws_launch_template.gpu[0]').after_unknown=@{}
    (Find-InstanceChange).after.launch_template[0].version='2'
    (Find-InstanceChange).after_unknown=@{}
    Use-AppliedInstanceFixture
  }
  Invoke-InstanceCase 'wrong-account' 'wrong account' { $global:InstanceWorld.Account='111111111111' }
  Invoke-InstanceCase 'nonapplyable' 'applyable and error-free' { $global:InstanceWorld.Plan.applyable=$false }
  Invoke-InstanceCase 'string-applyable' 'applyable and error-free' { $global:InstanceWorld.Plan.applyable='true' }
  Invoke-InstanceCase 'errored' 'applyable and error-free' { $global:InstanceWorld.Plan.errored=$true }
  Invoke-InstanceCase 'deferred' 'Deferred changes' { $global:InstanceWorld.Plan.deferred_changes=@(@{reason='unknown'}) }
  Invoke-InstanceCase 'missing-change' 'exactly four' { $global:InstanceWorld.Plan.resource_changes=@($global:InstanceWorld.Plan.resource_changes | Where-Object { $_.address -cne 'aws_ecs_task_definition.gpu[0]' }) }
  Invoke-InstanceCase 'unrelated-api-change' 'exactly four' { $global:InstanceWorld.Plan.resource_changes+=@{address='aws_lambda_function.api';mode='managed';change=@{actions=@('update');before=@{};after=@{};after_unknown=@{}}} }
  Invoke-InstanceCase 'duplicate-address' 'Duplicate saved resource' { $global:InstanceWorld.Plan.resource_changes+=$global:InstanceWorld.Plan.resource_changes[0] }
  Invoke-InstanceCase 'move' 'moves and imports' { $global:InstanceWorld.Plan.resource_changes[0].previous_address='aws_launch_template.old[0]' }
  Invoke-InstanceCase 'import' 'moves and imports' { (Find-InstanceChange).importing=@{id='different'} }
  Invoke-InstanceCase 'asg-replacement' 'must update in place' { (Find-InstanceChange).actions=@('delete','create') }
  Invoke-InstanceCase 'lt-replacement' 'must update in place' { (Find-InstanceChange 'aws_launch_template.gpu[0]').actions=@('delete','create') }
  Invoke-InstanceCase 'changed-ami' 'Unexpected launch template field' { (Find-InstanceChange 'aws_launch_template.gpu[0]').after.image_id='ami-12345678' }
  Invoke-InstanceCase 'changed-bootstrap' 'Unexpected launch template field' { (Find-InstanceChange 'aws_launch_template.gpu[0]').after.user_data='changed' }
  Invoke-InstanceCase 'changed-host-profile' 'Unexpected launch template field' { (Find-InstanceChange 'aws_launch_template.gpu[0]').after.iam_instance_profile[0].arn='changed' }
  Invoke-InstanceCase 'changed-disk' 'Unexpected launch template field' { (Find-InstanceChange 'aws_launch_template.gpu[0]').after.block_device_mappings[0].ebs[0].volume_size=400 }
  Invoke-InstanceCase 'wrong-new-type' 'reviewed G4dn type' { (Find-InstanceChange 'aws_launch_template.gpu[0]').after.instance_type='g5.xlarge' }
  Invoke-InstanceCase 'wrong-old-type' 'reviewed G4dn type' { (Find-InstanceChange 'aws_launch_template.gpu[0]').before.instance_type='g5.xlarge' }
  Invoke-InstanceCase 'unknown-image' 'Unknown launch template safety' { (Find-InstanceChange 'aws_launch_template.gpu[0]').after_unknown.image_id=$true }
  Invoke-InstanceCase 'unknown-lt-id' 'Unknown launch template safety' { (Find-InstanceChange 'aws_launch_template.gpu[0]').after_unknown.id=$true }
  Invoke-InstanceCase 'uncorrelated-version' 'computed versions must be correlated' { (Find-InstanceChange).after_unknown=@{} }
  Invoke-InstanceCase 'unknown-asg-id' 'Unknown ASG launch template safety' { (Find-InstanceChange).after_unknown.launch_template[0].id=$true }
  Invoke-InstanceCase 'unknown-capacity' 'Unknown ASG safety' { (Find-InstanceChange).after_unknown.max_size=$true }
  Invoke-InstanceCase 'changed-subnet' 'Unexpected ASG field' { (Find-InstanceChange).after.vpc_zone_identifier=@('subnet-12345678') }
  Invoke-InstanceCase 'nonzero-capacity' 'known numeric zero' { (Find-InstanceChange).before.max_size=1;(Find-InstanceChange).after.max_size=1 }
  Invoke-InstanceCase 'null-capacity' 'known numeric zero' { (Find-InstanceChange).before.min_size=$null;(Find-InstanceChange).after.min_size=$null }
  Invoke-InstanceCase 'unsafe-resume' 'Only the Launch' { (Find-InstanceChange).after.suspended_processes=@() }
  Invoke-InstanceCase 'changed-template-id' 'same reviewed launch template' { (Find-InstanceChange).after.launch_template[0].id='lt-12345678' }
  Invoke-InstanceCase 'task-not-replaced' 'exactly four' { (Find-InstanceChange 'aws_ecs_task_definition.gpu[0]').actions=@('no-op');(Find-InstanceChange 'aws_ecs_task_definition.gpu[0]').after=(Find-InstanceChange 'aws_ecs_task_definition.gpu[0]').before;(Find-InstanceChange 'aws_ecs_task_definition.gpu[0]').after_unknown=@{} }
  Invoke-InstanceCase 'task-memory-change' 'Unexpected task definition field' { (Find-InstanceChange 'aws_ecs_task_definition.gpu_preflight[0]').after.memory='16384' }
  Invoke-InstanceCase 'task-role-change' 'Unexpected task definition field' { (Find-InstanceChange 'aws_ecs_task_definition.gpu_preflight[0]').after.task_role_arn='arn:aws:iam::851226124502:role/admin' }
  Invoke-InstanceCase 'task-fault-enabled-before' 'Fault injection' {
    $change=Find-InstanceChange 'aws_ecs_task_definition.gpu_preflight[0]'
    $change.before.enable_fault_injection=$true; $change.after.enable_fault_injection=$false
  }
  Invoke-InstanceCase 'task-fault-enabled-after' 'Fault injection' { (Find-InstanceChange 'aws_ecs_task_definition.gpu_preflight[0]').after.enable_fault_injection=$true }
  Invoke-InstanceCase 'task-fault-enabled-unchanged' 'Fault injection' {
    $change=Find-InstanceChange 'aws_ecs_task_definition.gpu_preflight[0]'
    $change.before.enable_fault_injection=$true; $change.after.enable_fault_injection=$true
  }
  Invoke-InstanceCase 'worker-fault-enabled-after' 'Fault injection' { (Find-InstanceChange 'aws_ecs_task_definition.gpu[0]').after.enable_fault_injection=$true }
  Invoke-InstanceCase 'task-fault-string-false' 'Fault injection' { (Find-InstanceChange 'aws_ecs_task_definition.gpu_preflight[0]').after.enable_fault_injection='false' }
  Invoke-InstanceCase 'task-fault-number-zero' 'Fault injection' { (Find-InstanceChange 'aws_ecs_task_definition.gpu_preflight[0]').after.enable_fault_injection=0 }
  Invoke-InstanceCase 'task-fault-object' 'Fault injection' { (Find-InstanceChange 'aws_ecs_task_definition.gpu_preflight[0]').after.enable_fault_injection=@{enabled=$false} }
  Invoke-InstanceCase 'task-fault-unknown' 'Unknown task definition safety' { (Find-InstanceChange 'aws_ecs_task_definition.gpu_preflight[0]').after_unknown.enable_fault_injection=$true }
  Invoke-InstanceCase 'task-unknown-command' 'Unknown task definition safety' { (Find-InstanceChange 'aws_ecs_task_definition.gpu_preflight[0]').after_unknown.container_definitions=$true }
  Invoke-InstanceCase 'task-wrong-count' 'GPU container resource requirement' { Set-TaskContainerChange 'aws_ecs_task_definition.gpu_preflight[0]' { param($c) $c.resourceRequirements[0].value='0.125' } }
  Invoke-InstanceCase 'task-wrong-image' 'GPU container name or image' { Set-TaskContainerChange 'aws_ecs_task_definition.gpu[0]' { param($c) $c.image='image:latest' } }
  Invoke-InstanceCase 'task-command-change' 'Only the GPU allocation' { Set-TaskContainerChange 'aws_ecs_task_definition.gpu_preflight[0]' { param($c) $c.command=@('sh','-c','echo bad') } }
  Invoke-InstanceCase 'task-env-change' 'Only the GPU allocation' { Set-TaskContainerChange 'aws_ecs_task_definition.gpu_preflight[0]' { param($c) $c.environment=@(@{name='ENABLE';value='true'}) } }
  Invoke-InstanceCase 'task-empty-root-array' 'exactly one container' { (Find-InstanceChange 'aws_ecs_task_definition.gpu_preflight[0]').after.container_definitions='[]' }
  Invoke-InstanceCase 'task-object-root' 'containers array' { (Find-InstanceChange 'aws_ecs_task_definition.gpu_preflight[0]').after.container_definitions='{}' }
  Invoke-InstanceCase 'task-null-root' 'containers array' { (Find-InstanceChange 'aws_ecs_task_definition.gpu_preflight[0]').after.container_definitions='null' }
  Invoke-InstanceCase 'wrong-type-input' 'Unexpected effective Terraform input' { $global:InstanceWorld.Plan.variables.gpu_smoke_instance_type.value='g6f.xlarge' }
  Invoke-InstanceCase 'old-approval-input' 'Unexpected effective Terraform input' { $global:InstanceWorld.Plan.variables.gpu_smoke_approval.value='I_APPROVE_ONE_G6F_SMOKE_INSTANCE' }
  Invoke-InstanceCase 'queue-enabled' 'Unexpected effective Terraform input' { $global:InstanceWorld.Plan.variables.enable_paid_gpu_queue_scaffold.value=$true }
  Invoke-InstanceCase 'missing-caller' 'Missing saved caller identity' { $global:InstanceWorld.Plan.prior_state.values.root_module.resources=@() }
  Invoke-InstanceCase 'wrong-caller' 'Saved caller identity' { $global:InstanceWorld.Plan.prior_state.values.root_module.resources[0].values.account_id='111111111111' }
  Invoke-InstanceCase 'duplicate-caller' 'Duplicate saved caller' { $global:InstanceWorld.Plan.prior_state.values.root_module.resources+=$global:InstanceWorld.Plan.prior_state.values.root_module.resources[0] }
  Invoke-InstanceCase 'old-output-type' 'Planned output' { $global:InstanceWorld.Plan.planned_values.outputs.gpu_smoke_instance_type.value='g6f.xlarge' }
  Invoke-InstanceCase 'old-output-gpu' 'Planned output' { $global:InstanceWorld.Plan.planned_values.outputs.gpu_smoke_gpu_resource.value='0.125' }
  Invoke-InstanceCase 'live-template-wrong-type' 'Live launch-template type' { $global:InstanceWorld.Template.LaunchTemplateData.InstanceType='g5.xlarge' }
  Invoke-InstanceCase 'live-template-wrong-ami' 'Live launch-template type' { $global:InstanceWorld.Template.LaunchTemplateData.ImageId='ami-12345678' }
  Invoke-InstanceCase 'live-template-public-ip' 'Live launch-template networking' { $global:InstanceWorld.Template.LaunchTemplateData.NetworkInterfaces[0].AssociatePublicIpAddress=$false }
  Invoke-InstanceCase 'live-template-string-public-ip' 'Live launch-template networking' { $global:InstanceWorld.Template.LaunchTemplateData.NetworkInterfaces[0].AssociatePublicIpAddress='true' }
  Invoke-InstanceCase 'live-template-root-encryption' 'Live root disk' { $global:InstanceWorld.Template.LaunchTemplateData.BlockDeviceMappings[0].Ebs.Encrypted=$false }
  Invoke-InstanceCase 'live-template-string-root-encryption' 'Live root disk' { $global:InstanceWorld.Template.LaunchTemplateData.BlockDeviceMappings[0].Ebs.Encrypted='true' }
  Invoke-InstanceCase 'live-task-fault-enabled' 'Fault injection' {
    $arn=$global:InstanceWorld.Outputs.gpu_smoke_task_definition.value
    $global:InstanceWorld.TaskDefinitions[$arn].enableFaultInjection=$true
  }
  Invoke-InstanceCase 'live-worker-fault-enabled' 'Fault injection' {
    $arn=(Find-InstanceChange 'aws_ecs_task_definition.gpu[0]').before.arn
    $global:InstanceWorld.TaskDefinitions[$arn].enableFaultInjection=$true
  }
  Invoke-InstanceCase 'live-task-fault-string-false' 'Fault injection' {
    $arn=$global:InstanceWorld.Outputs.gpu_smoke_task_definition.value
    $global:InstanceWorld.TaskDefinitions[$arn].enableFaultInjection='false'
  }
  Invoke-InstanceCase 'live-asg-busy' 'known numeric zero' { $global:InstanceWorld.LiveAsg.DesiredCapacity=1 }
  Invoke-InstanceCase 'live-asg-member' 'Live ASG instances must be empty' { $global:InstanceWorld.LiveAsg.Instances=@(@{InstanceId='i-test'}) }
  Invoke-InstanceCase 'live-asg-version-drift' 'Live ASG identity' { $global:InstanceWorld.LiveAsg.LaunchTemplate.Version='3' }
  Invoke-InstanceCase 'live-latch-drift' 'process suspensions' { $global:InstanceWorld.LiveAsg.SuspendedProcesses=@() }
  Invoke-InstanceCase 'live-tagged-host' 'Tagged nonterminated' { $global:InstanceWorld.Reservations=@(@{Instances=@(@{InstanceId='i-test'})}) }
  Invoke-InstanceCase 'unresolved-activity' 'scaling activity is unresolved' { $global:InstanceWorld.Activities[0].StatusCode='InProgress' }
  Invoke-InstanceCase 'live-service' 'GPU ECS services' { $global:InstanceWorld.Services=@('service') }
  Invoke-InstanceCase 'live-running-task' 'running/pending tasks' { $global:InstanceWorld.Tasks=@('task') }
  Invoke-InstanceCase 'live-container' 'container instances' { $global:InstanceWorld.Containers=@('container') }
  Invoke-InstanceCase 'stopping-task' 'previous task is still stopping' { $global:InstanceWorld.StoppedTasks=@('old-task');$global:InstanceWorld.StoppedDetails=@(@{taskArn='old-task';lastStatus='STOPPING'}) }
  Invoke-InstanceCase 'valid-stopped-history' '' { $global:InstanceWorld.StoppedTasks=@('old-task');$global:InstanceWorld.StoppedDetails=@(@{taskArn='old-task';lastStatus='STOPPED'}) }
  Invoke-InstanceCase 'subnet-account' 'Reviewed subnet ownership' { $global:InstanceWorld.Subnets[0].OwnerId='111111111111' }
  Invoke-InstanceCase 'subnet-no-ips' 'Reviewed subnet ownership' { $global:InstanceWorld.Subnets[0].AvailableIpAddressCount=1 }
  Invoke-InstanceCase 'security-group-vpc' 'same owned VPC' { $global:InstanceWorld.SecurityGroups[0].VpcId='vpc-12345678' }
  Invoke-InstanceCase 'unpublished-image' 'selected ECR digest' { $global:InstanceWorld.Published=@() }
  Invoke-InstanceCase 'incomplete-pagination' 'incomplete pagination'
  Invoke-InstanceCase 'applied-wrong-output-type' 'Applied instance type' { Use-AppliedInstanceFixture;$global:InstanceWorld.Outputs.gpu_smoke_instance_type.value='g6f.xlarge' }
  Invoke-InstanceCase 'applied-old-version' 'Applied instance type' { Use-AppliedInstanceFixture;$global:InstanceWorld.Outputs.gpu_smoke_launch_template_version.value='1' }
  Invoke-InstanceCase 'applied-missing-worker-output' 'Missing current Terraform output' { Use-AppliedInstanceFixture;$global:InstanceWorld.Outputs.Remove('gpu_smoke_worker_task_definition') }
  Invoke-InstanceCase 'applied-old-task-revision' 'task revisions must advance' { Use-AppliedInstanceFixture;$global:InstanceWorld.Outputs.gpu_smoke_task_definition.value=$global:InstanceWorld.Outputs.gpu_smoke_task_definition.value -replace ':2$',':1' }
  Invoke-InstanceCase 'applied-wrong-live-type' 'Live launch-template type' { Use-AppliedInstanceFixture;$global:InstanceWorld.Template.LaunchTemplateData.InstanceType='g6f.xlarge' }
  Invoke-InstanceCase 'applied-wrong-task-count' 'GPU container resource requirement' { Use-AppliedInstanceFixture;$arn=$global:InstanceWorld.Outputs.gpu_smoke_task_definition.value;$global:InstanceWorld.TaskDefinitions[$arn].containerDefinitions[0].resourceRequirements[0].value='0.125' }
  Invoke-InstanceCase 'applied-wrong-worker-image' 'GPU container name or image' { Use-AppliedInstanceFixture;$arn=$global:InstanceWorld.Outputs.gpu_smoke_worker_task_definition.value;$global:InstanceWorld.TaskDefinitions[$arn].containerDefinitions[0].image='wrong' }
  Invoke-InstanceCase 'applied-task-fault-enabled' 'Fault injection' {
    Use-AppliedInstanceFixture
    $arn=$global:InstanceWorld.Outputs.gpu_smoke_task_definition.value
    $global:InstanceWorld.TaskDefinitions[$arn].enableFaultInjection=$true
  }
  Invoke-InstanceCase 'applied-worker-fault-enabled' 'Fault injection' {
    Use-AppliedInstanceFixture
    $arn=$global:InstanceWorld.Outputs.gpu_smoke_worker_task_definition.value
    $global:InstanceWorld.TaskDefinitions[$arn].enableFaultInjection=$true
  }
  Invoke-InstanceCase 'applied-task-fault-string-false' 'Fault injection' {
    Use-AppliedInstanceFixture
    $arn=$global:InstanceWorld.Outputs.gpu_smoke_task_definition.value
    $global:InstanceWorld.TaskDefinitions[$arn].enableFaultInjection='false'
  }
  Invoke-InstanceCase 'applied-launch-still-latched' 'process suspensions' { Use-AppliedInstanceFixture;$global:InstanceWorld.LiveAsg.SuspendedProcesses+=@{ProcessName='Launch'} }
  Invoke-InstanceCase 'workspace-changed' 'workspace changed'
  Invoke-InstanceCase 'plan-changed' 'saved plan changed'
  Invoke-InstanceCase 'private-show-error' 'Saved migration plan inspection failed'
  Invoke-InstanceCase 'private-json-error' 'Saved migration plan inspection returned invalid JSON'
  Invoke-InstanceCase 'root-array-plan' 'must return a JSON object'
} finally {
  foreach ($name in $script:EnvironmentNames) {
    if ($null -eq $script:SavedEnvironment[$name]) { Remove-Item -LiteralPath ("Env:"+$name) -ErrorAction SilentlyContinue }
    else { [Environment]::SetEnvironmentVariable($name,$script:SavedEnvironment[$name],'Process') }
  }
  Set-Location -LiteralPath $script:OriginalLocation.ProviderPath
  Remove-Item Function:global:aws -ErrorAction SilentlyContinue
  Remove-Item Function:global:terraform -ErrorAction SilentlyContinue
  Remove-Variable InstanceWorld -Scope Global -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $script:Directory -Recurse -Force -ErrorAction SilentlyContinue
}
if ($script:Failures) { throw "$script:Failures of $script:Cases GPU instance migration scenarios failed." }
Write-Host "All $script:Cases GPU instance migration scenarios passed."
