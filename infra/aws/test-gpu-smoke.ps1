# Offline behaviour tests for gpu-smoke.ps1. No AWS calls: `aws`, `terraform`
# and Start-Sleep are replaced by in-memory fakes that model ASG/ECS/EC2 state.
#   powershell -NoProfile -File infra/aws/test-gpu-smoke.ps1
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:Under = Join-Path $PSScriptRoot 'gpu-smoke.ps1'
$Image = '851226124502.dkr.ecr.us-east-1.amazonaws.com/strokesense-aws-dev-gpu-worker@sha256:' + ('a' * 64)
$failures = 0

function New-World([string]$Scenario) {
  $global:W = @{
    scenario = $Scenario; calls = New-Object System.Collections.ArrayList
    asg = @{ min = 0; max = 0; desired = 0; instances = @(); suspended = @('AZRebalance','ReplaceUnhealthy') }
    actions = @(); instState = $null; tasks = @(); runTaskCalls = 0; tokens = @()
    clock = [datetime]::UtcNow; logReads = 0; instanceReads = 0
    scaledOut = $false; lateObserved = $false; suspendCalls = 0; evidence = $null; cleanupActivityReads = 0
  }
  if ($Scenario -eq 'retrylatched') { $W.asg.suspended += 'Launch' }
  if ($Scenario -in @('stale-cutoff','cutoff-recurring','cutoff-foreign','cutoff-capacity','cutoff-asg')) {
    $action = @{ ScheduledActionName = 'strokesense-gpu-smoke-cutoff'; AutoScalingGroupName = 'strokesense-aws-dev-gpu-one-instance'
      StartTime = $W.clock.AddHours(-1).ToString('o'); MinSize = 0; MaxSize = 0; DesiredCapacity = 0 }
    if ($Scenario -eq 'cutoff-recurring') { $action.Recurrence = '0 * * * *' }
    if ($Scenario -eq 'cutoff-foreign') { $action.ScheduledActionName = 'different-action' }
    if ($Scenario -eq 'cutoff-capacity') { $action.MaxSize = 1 }
    if ($Scenario -eq 'cutoff-asg') { $action.AutoScalingGroupName = 'different-asg' }
    $W.actions = @($action)
  }
}
function global:Get-Date { return $W.clock }
function global:Start-Sleep { param([int]$Seconds, [int]$Milliseconds) $W.clock = $W.clock.AddSeconds($Seconds).AddMilliseconds($Milliseconds) }
function global:terraform {
  $name = $args[-1]
  $global:LASTEXITCODE = 0
  switch ($name) {
    'gpu_smoke_asg_name' { 'strokesense-aws-dev-gpu-one-instance' }
    'gpu_smoke_ecs_cluster' { 'arn:aws:ecs:us-east-1:851226124502:cluster/strokesense-aws-dev-gpu' }
    'gpu_smoke_capacity_provider' { 'strokesense-aws-dev-gpu-asg' }
    'gpu_smoke_task_definition' { 'arn:aws:ecs:us-east-1:851226124502:task-definition/strokesense-aws-dev-gpu-preflight:1' }
    'gpu_smoke_subnet_id' { 'subnet-0f3c6534cee511e6a' }
    'gpu_smoke_task_security_group' { 'sg-0123456789abcdef0' }
    'gpu_smoke_log_group' { '/ecs/strokesense-aws-dev/paid-gpu' }
    'gpu_smoke_ami_id' { 'ami-0b8f7c7154f9e8f8b' }
    'gpu_smoke_launch_template_id' { 'lt-0123456789abcdef0' }
    'gpu_smoke_launch_template_version' { '5' }
    default { $global:LASTEXITCODE = 1; 'missing' }
  }
}
function Get-Arg([object[]]$A, [string]$Flag) { $i = [array]::IndexOf($A, $Flag); if ($i -ge 0) { return $A[$i + 1] } return $null }
function global:aws {
  $a = @($args | ForEach-Object { "$_" })
  [void]$W.calls.Add(($a[0..1] -join ' ') + ' ' + (($a | Select-Object -Skip 2) -join ' '))
  $global:LASTEXITCODE = 0
  $op = $a[0] + ' ' + $a[1]
  $asg = $W.asg
  switch ($op) {
    'sts get-caller-identity' { return '{"Account":"851226124502"}' }
    'ecr describe-images' {
      if ($W.scenario -eq 'missingimage') { return '{"imageDetails":[]}' }
      return ('{"imageDetails":[{"imageDigest":"sha256:' + ('a' * 64) + '"}]}')
    }
    'service-quotas get-service-quota' { return '{"Quota":{"Value":4.0}}' }
    'autoscaling describe-auto-scaling-groups' {
      $lateCase = $W.scenario -in @('latehost','latevolumeaccess','latevolumemissing','latevolumeleft','lateactivity')
      if ($asg.desired -ge 1 -and $asg.max -ge 1 -and $asg.instances.Count -eq 0 -and $asg.suspended -notcontains 'Launch' -and
          $W.scenario -notin @('capacity','activityblocked') -and !$lateCase) {
        $asg.instances = @('i-0abc'); $W.instState = 'running'
      }
      $justAppeared = $false
      if ($lateCase -and $W.scaledOut -and $asg.desired -eq 0 -and !$W.lateObserved -and
          ($W.scenario -ne 'lateactivity' -or $W.cleanupActivityReads -gt 1)) {
        # An EC2 request accepted before cleanup only becomes visible now.
        $asg.instances = @('i-0abc'); $W.instState = 'running'; $W.lateObserved = $true; $justAppeared = $true
      }
      if ($asg.desired -eq 0 -and $asg.instances.Count -gt 0 -and $W.scenario -ne 'terminationblocked' -and !$justAppeared) { $asg.instances = @(); $W.instState = 'terminated' }
      $inst = @($asg.instances | ForEach-Object { @{ InstanceId = $_ } })
      $version = '5'; if ($W.scenario -eq 'wrongtemplate') { $version = '$Latest' }
      $subnet = 'subnet-0f3c6534cee511e6a'
      if ($W.scenario -eq 'wrongsubnet') { $subnet = 'subnet-0123456789abcdef0' }
      if ($W.scenario -eq 'manysubnets') { $subnet += ',subnet-0123456789abcdef0' }
      return (@{ AutoScalingGroups = @(@{ MinSize = $asg.min; MaxSize = $asg.max; DesiredCapacity = $asg.desired
        LaunchTemplate = @{ LaunchTemplateId = 'lt-0123456789abcdef0'; Version = $version }; NewInstancesProtectedFromScaleIn = $false
        VPCZoneIdentifier = $subnet; Instances = $inst; SuspendedProcesses = @($asg.suspended | ForEach-Object { @{ ProcessName = $_ } }) }) } | ConvertTo-Json -Depth 6)
    }
    'autoscaling describe-lifecycle-hooks' { return '{"LifecycleHooks":[]}' }
    'autoscaling put-scheduled-update-group-action' {
      $W.actions = @(@{ ScheduledActionName = (Get-Arg $a '--scheduled-action-name'); AutoScalingGroupName = (Get-Arg $a '--auto-scaling-group-name')
        StartTime = (Get-Arg $a '--start-time'); MinSize = 0; MaxSize = 0; DesiredCapacity = 0 })
      if ($W.scenario -eq 'cutoff-put-recurring') { $W.actions[0].Recurrence = '0 * * * *' }
      if ($W.scenario -eq 'cutoff-not-updated') { $W.actions[0].StartTime = $W.clock.AddHours(-1).ToString('o') }
      return '' }
    'autoscaling describe-scheduled-actions' { return (@{ ScheduledUpdateGroupActions = @($W.actions) } | ConvertTo-Json -Depth 5) }
    'autoscaling update-auto-scaling-group' {
      $asg.min = [int](Get-Arg $a '--min-size'); $asg.max = [int](Get-Arg $a '--max-size'); $asg.desired = [int](Get-Arg $a '--desired-capacity')
      if ($asg.desired -eq 1) { $W.scaledOut = $true }
      return '' }
    'autoscaling suspend-processes' {
      $W.suspendCalls++
      if ($W.scenario -eq 'suspendfailure' -or ($W.scenario -eq 'cleanup-suspendfailure' -and $W.suspendCalls -gt 1)) {
        $global:LASTEXITCODE = 254; return 'An error occurred (AccessDenied) when calling SuspendProcesses'
      }
      if ($W.scenario -ne 'suspend-noeffect') { $asg.suspended += (Get-Arg $a '--scaling-processes') }
      return '' }
    'autoscaling describe-scaling-activities' {
      if ($W.scenario -eq 'activeactivity') {
        return '{"Activities":[{"AutoScalingGroupName":"strokesense-aws-dev-gpu-one-instance","StatusCode":"InProgress"}]}'
      }
      if ($W.scenario -eq 'foreignactivity') { return '{"Activities":[{"AutoScalingGroupName":"different-group","StatusCode":"Failed"}]}' }
      if ($W.scenario -eq 'incompleteactivity') { return '{"Activities":[],"NextToken":"more"}' }
      if ($W.scaledOut -and $asg.desired -eq 0) {
        $W.cleanupActivityReads++
        if ($W.scenario -eq 'activityaccess' -and $W.cleanupActivityReads -eq 1) {
          $global:LASTEXITCODE = 254; return 'An error occurred (AccessDenied) when calling DescribeScalingActivities'
        }
      }
      if ($W.scaledOut -and ($W.scenario -eq 'activityblocked' -or
          ($W.scenario -eq 'lateactivity' -and !$W.lateObserved))) {
        return '{"Activities":[{"AutoScalingGroupName":"strokesense-aws-dev-gpu-one-instance","StatusCode":"InProgress","StatusMessage":"Waiting for an accepted launch request"}]}'
      }
      if ($W.scaledOut -and $W.scenario -in @('capacity','latehost','latevolumeaccess','latevolumemissing','latevolumeleft','lateactivity')) {
        return '{"Activities":[{"AutoScalingGroupName":"strokesense-aws-dev-gpu-one-instance","StatusCode":"Failed","StatusMessage":"InsufficientInstanceCapacity in the selected Availability Zone"}]}'
      }
      return '{"Activities":[]}' }
    'ec2 describe-launch-template-versions' {
      $ami = 'ami-0b8f7c7154f9e8f8b'; if ($W.scenario -eq 'wrongami') { $ami = 'ami-0123456789abcdef0' }
      $userData = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("ECS_ENABLE_GPU_SUPPORT=true`nECS_AWSVPC_BLOCK_IMDS=true"))
      return (@{ LaunchTemplateVersions = @(@{ LaunchTemplateData = @{ ImageId=$ami; InstanceType='g6f.xlarge';
        UserData=$userData; MetadataOptions=@{HttpTokens='required'} } }) } | ConvertTo-Json -Depth 6)
    }
    'ec2 describe-instances' {
      if ((Get-Arg $a '--filters') -like 'Name=instance-type*') { return '[]' }
      if ((Get-Arg $a '--filters') -like 'Name=tag:*') { if ($W.instState -and $W.instState -ne 'terminated') { return '["i-0abc"]' } return '[]' }
      if ((Get-Arg $a '--query') -like '*State.Name*') {
        if ($W.scenario -eq 'missinginstancestate') { return '[]' }
        return ('["' + $W.instState + '"]')
      }
      if ($W.scenario -eq 'latevolumeaccess') { $global:LASTEXITCODE = 254; return 'An error occurred (UnauthorizedOperation) when calling DescribeInstances' }
      $W.instanceReads++
      $instance = @{InstanceId='i-0abc';InstanceType='g6f.xlarge';ImageId='ami-0b8f7c7154f9e8f8b';LaunchTime='2026-11-21T04:00:00Z'
        Placement=@{AvailabilityZone='us-east-1a'};SubnetId='subnet-0f3c6534cee511e6a';RootDeviceName='/dev/xvda';
        BlockDeviceMappings=@(@{DeviceName='/dev/xvda';Ebs=@{VolumeId='vol-0abc';DeleteOnTermination=$true}})}
      if ($W.scenario -in @('missingvolume','latevolumemissing') -or ($W.scenario -eq 'pendingvolume' -and $W.instanceReads -eq 1)) { $instance.BlockDeviceMappings = @() }
      if ($W.scenario -eq 'wronginstancesubnet') { $instance.SubnetId = 'subnet-0123456789abcdef0' }
      return (@{Reservations=@(@{Instances=@($instance)})} | ConvertTo-Json -Depth 8)
    }
    'ec2 describe-volumes' {
      if ($W.scenario -eq 'volumeaccess') { $global:LASTEXITCODE = 254; return 'An error occurred (UnauthorizedOperation) when calling the DescribeVolumes operation' }
      if ($W.scenario -in @('volumeleft','latevolumeleft')) { return '{"Volumes":[{"VolumeId":"vol-0abc","State":"available"}]}' }
      return '{"Volumes":[]}'
    }
    'ecs describe-capacity-providers' { return '{"capacityProviders":[{"autoScalingGroupProvider":{"autoScalingGroupArn":"arn:aws:autoscaling:us-east-1:851226124502:autoScalingGroup:x:autoScalingGroupName/strokesense-aws-dev-gpu-one-instance","managedScaling":{"status":"DISABLED"},"managedTerminationProtection":"DISABLED","managedDraining":"DISABLED"}}]}' }
    'ecs list-services' {
      if ($W.scenario -eq 'existingservice') { return '{"serviceArns":["service-existing"]}' }
      return '{"serviceArns":[]}' }
    'ecs list-tasks' {
      if ($W.scenario -eq 'existingtask') { return '{"taskArns":["task-existing"]}' }
      if ((Get-Arg $a '--desired-status') -eq 'STOPPED' -and $W.scenario -in @('existingstopping','completedhistory','stopstatusmissing')) {
        return '{"taskArns":["task-prior"]}'
      }
      if ($W.scenario -eq 'losttwice' -and $W.runTaskCalls -eq 1) { return '{"taskArns":[]}' }
      return (@{ taskArns = @($W.tasks) } | ConvertTo-Json)
    }
    'ecs list-container-instances' { if ($asg.instances.Count -or $W.scenario -eq 'existingcontainer') { return '{"containerInstanceArns":["arn:aws:ecs:us-east-1:851226124502:container-instance/x/1"]}' } return '{"containerInstanceArns":[]}' }
    'ecs describe-container-instances' {
      $res = '[{"name":"GPU","type":"STRINGSET","stringSetValue":["GPU-1"]},{"name":"CPU","type":"INTEGER","integerValue":4096}]'
      if ($W.scenario -eq 'nogpu') { $res = '[{"name":"CPU","type":"INTEGER","integerValue":4096}]' }
      return ('{"containerInstances":[{"ec2InstanceId":"i-0abc","agentConnected":true,"status":"ACTIVE","versionInfo":{"agentVersion":"1.108.3"},"registeredResources":' + $res + '}]}') }
    'ecs describe-task-definition' { return ('{"taskDefinition":{"revision":1,"networkMode":"awsvpc","requiresCompatibilities":["EC2"],"containerDefinitions":[{"name":"gpu-preflight","image":"' + $Image + '","command":["python3","-m","aws_app.gpu_preflight","--model","/app/models/yolo11n-pose.onnx"],"resourceRequirements":[{"type":"GPU","value":"0.125"}],"mountPoints":[],"environment":[]}],"volumes":[]}}') }
    'ecs run-task' {
      $W.runTaskCalls++
      $payload = (Get-Content ((Get-Arg $a '--cli-input-json') -replace '^file://','') -Raw) | ConvertFrom-Json
      $W.tokens += $payload.clientToken
      $W.tasks = @('arn:aws:ecs:us-east-1:851226124502:task/strokesense-aws-dev-gpu/t1')
      if ($W.scenario -eq 'losttwice') { $global:LASTEXITCODE = 255; return 'Read timeout on endpoint URL' }
      if ($W.scenario -eq 'lostresponse' -and $W.runTaskCalls -eq 1) { $global:LASTEXITCODE = 255; return 'Read timeout on endpoint URL' }
      return '{"tasks":[{"taskArn":"arn:aws:ecs:us-east-1:851226124502:task/strokesense-aws-dev-gpu/t1"}],"failures":[]}'
    }
    'ecs describe-tasks' {
      if ((Get-Arg $a '--tasks') -eq 'task-prior') {
        if ($W.scenario -eq 'existingstopping') { return '{"tasks":[{"taskArn":"task-prior","lastStatus":"STOPPING"}],"failures":[]}' }
        if ($W.scenario -eq 'stopstatusmissing') { return '{"tasks":[],"failures":[{"arn":"task-prior","reason":"MISSING"}]}' }
        return '{"tasks":[{"taskArn":"task-prior","lastStatus":"STOPPED"}],"failures":[]}'
      }
      $code = 0; if ($W.scenario -eq 'exit2') { $code = 2 }
      $digest = 'sha256:' + ('a' * 64); if ($W.scenario -eq 'digestmissing') { $digest = '' }
      return ('{"tasks":[{"lastStatus":"STOPPED","startedAt":"s","stoppedAt":"e","stopCode":"EssentialContainerExited","stoppedReason":"Essential container in task exited","taskDefinitionArn":"td:1","containers":[{"name":"gpu-preflight","exitCode":' + $code + ',"imageDigest":"' + $digest + '"}]}]}') }
    'ecs stop-task' { return '{}' }
    'logs get-log-events' {
      $W.logReads++
      if ($W.scenario -eq 'nologs' -or ($W.scenario -eq 'delayedlogs' -and $W.logReads -lt 3)) { return '{"events":[]}' }
      $result = @{ provider = 'CUDAExecutionProvider'; active_providers = @('CUDAExecutionProvider'); model_loaded = $true
        cpu_ep_fallback_disabled = $true; outputs_finite = $true; warmup_runs = 3; inference_runs = 20
        model_sha256_verified = '93e2866b0ce678f99b4dd88af0c12e9ea2edf079a361dc2ecbc6226b77ff6408'
        output_shapes = @(,@(1,56,8400)); gpu_memory_total_mib = 3072; gpu_memory_used_after_inference_mib = 512
        latency_ms_p50 = 2.0; latency_ms_p95 = 2.5; latency_ms_max = 3.0 }
      if ($W.scenario -eq 'badlog') { $result.outputs_finite = $false }
      return (@{events=@(@{message=('STROKESENSE_GPU_PREFLIGHT ' + ($result | ConvertTo-Json -Depth 5 -Compress))})} | ConvertTo-Json -Depth 5)
    }
    default { $global:LASTEXITCODE = 255; return "unexpected fake call: $op" }
  }
}

function Invoke-Case([string]$Scenario, [bool]$ExpectThrow, [scriptblock]$Check, [bool]$ExpectLaunch = $true) {
  New-World $Scenario
  $threw = $null
  $caseEvidence = Join-Path ([IO.Path]::GetTempPath()) ('ss-gpu-smoke-test-' + [guid]::NewGuid().ToString('N'))
  try {
    & $script:Under -ExpectedAccountId 851226124502 -ExpectedImageUri $Image -ApproveCharge -AwsProfile fake `
      -EvidenceDir $caseEvidence *> $null
  } catch { $threw = $_.Exception.Message }
  $W.failure = $threw
  if (Test-Path -LiteralPath $caseEvidence) {
    $files = @(Get-ChildItem -LiteralPath $caseEvidence -Filter 'gpu-smoke-*.json')
    if ($files.Count -eq 1) { $W.evidence = [IO.File]::ReadAllText($files[0].FullName) | ConvertFrom-Json }
    Remove-Item -LiteralPath $caseEvidence -Recurse -Force
  }
  $ok = (($null -ne $threw) -eq $ExpectThrow)
  $calls = @($W.calls)
  $idx = { param($p) for ($i = 0; $i -lt $calls.Count; $i++) { if ($calls[$i] -like $p) { return $i } } return -1 }
  $last = $calls | Where-Object { $_ -like 'autoscaling update-auto-scaling-group*' } | Select-Object -Last 1
  $common = ((& $idx 'autoscaling put-scheduled-update-group-action*') -ge 0 -and
    (& $idx 'autoscaling put-scheduled-update-group-action*') -lt (& $idx '*--desired-capacity 1*') -and
    $last -like '*--min-size 0 --max-size 0 --desired-capacity 0*')
  if (!$ExpectLaunch) { $common = ((& $idx '*--desired-capacity 1*') -lt 0 -and $W.runTaskCalls -eq 0 -and $W.asg.instances.Count -eq 0) }
  $specific = & $Check $calls $idx
  if ($ok -and $common -and $specific) { Write-Host "PASS $Scenario" }
  else { Write-Host "FAIL $Scenario threw=[$threw] ok=$ok common=$common specific=$specific"; $calls | ForEach-Object { Write-Host "   $_" }; $script:failures++ }
}

Invoke-Case 'happy' $false { param($c, $idx)
  $W.runTaskCalls -eq 1 -and $W.tokens[0] -like 'ss-gpu-smoke-*' -and
  (& $idx 'autoscaling suspend-processes*Launch*') -gt (& $idx '*--desired-capacity 1*') -and
  (& $idx 'autoscaling suspend-processes*Launch*') -lt (& $idx 'ecs run-task*') -and
  (& $idx 'ecs stop-task*') -lt 0 }
Invoke-Case 'nogpu' $true { param($c, $idx) $W.runTaskCalls -eq 0 }
Invoke-Case 'lostresponse' $false { param($c, $idx) $W.runTaskCalls -eq 1 }
Invoke-Case 'exit2' $true { param($c, $idx) $W.runTaskCalls -eq 1 }
Invoke-Case 'missingimage' $true { $true } $false
Invoke-Case 'wrongtemplate' $true { $true } $false
Invoke-Case 'wrongami' $true { $true } $false
Invoke-Case 'nologs' $true { $W.runTaskCalls -eq 1 -and $W.instState -eq 'terminated' }
Invoke-Case 'badlog' $true { $W.runTaskCalls -eq 1 -and $W.instState -eq 'terminated' }
Invoke-Case 'delayedlogs' $false { $W.logReads -ge 3 -and $W.instState -eq 'terminated' }
Invoke-Case 'digestmissing' $true { $W.instState -eq 'terminated' }
Invoke-Case 'volumeaccess' $true { $W.instState -eq 'terminated' }
Invoke-Case 'volumeleft' $true { $W.instState -eq 'terminated' }
Invoke-Case 'terminationblocked' $true { $W.asg.desired -eq 0 -and $W.instState -eq 'running' }
Invoke-Case 'losttwice' $true { param($c, $idx) $W.runTaskCalls -eq 2 -and $W.tokens[0] -eq $W.tokens[1] -and (& $idx 'ecs stop-task*') -ge 0 -and $W.instState -eq 'terminated' }
Invoke-Case 'pendingvolume' $false { param($c, $idx) $W.instanceReads -ge 2 -and (& $idx 'ec2 describe-volumes*') -ge 0 }
Invoke-Case 'missingvolume' $true { $W.runTaskCalls -eq 0 -and $W.instState -eq 'terminated' }
Invoke-Case 'missinginstancestate' $true { $W.runTaskCalls -eq 1 -and $W.asg.desired -eq 0 }
Invoke-Case 'capacity' $true { param($c, $idx)
  $W.runTaskCalls -eq 0 -and $W.asg.suspended -contains 'Launch' -and
  $W.evidence.launch_suspended_verified -eq $true -and $W.evidence.terminated_verified -eq $true -and
  $W.evidence.no_instance_observed -eq $true -and $W.evidence.instance_termination_status -eq 'NO_INSTANCE_OBSERVED' -and
  @($W.evidence.instance_ids).Count -eq 0 -and @($W.evidence.cleanup_errors).Count -eq 0 -and
  $W.evidence.error -like '*InsufficientInstanceCapacity*' -and
  (& $idx 'autoscaling suspend-processes*Launch*') -lt (& $idx 'autoscaling update-auto-scaling-group*--min-size 0 --max-size 0 --desired-capacity 0*') }
Invoke-Case 'latehost' $true { param($c, $idx)
  $W.runTaskCalls -eq 0 -and $W.lateObserved -and $W.instState -eq 'terminated' -and
  $W.evidence.instance_ids -contains 'i-0abc' -and $W.evidence.observed_volume_ids -contains 'vol-0abc' -and
  $W.evidence.no_instance_observed -eq $false -and $W.evidence.launch_suspended_verified -eq $true -and
  @($W.evidence.cleanup_errors).Count -eq 0 -and (& $idx 'ec2 describe-volumes*') -ge 0 -and
  $W.failure -like '*InsufficientInstanceCapacity*' }
Invoke-Case 'lateactivity' $true { param($c, $idx)
  $W.cleanupActivityReads -ge 3 -and $W.runTaskCalls -eq 0 -and $W.lateObserved -and $W.instState -eq 'terminated' -and
  $W.evidence.instance_ids -contains 'i-0abc' -and $W.evidence.observed_volume_ids -contains 'vol-0abc' -and
  $W.evidence.scaling_activities_terminal_verified -eq $true -and $W.evidence.no_instance_observed -eq $false -and
  @($W.evidence.cleanup_errors).Count -eq 0 -and (& $idx 'ec2 describe-volumes*') -ge 0 -and
  $W.failure -like '*Waiting for an accepted launch request*' }
Invoke-Case 'activityblocked' $true {
  $W.cleanupActivityReads -gt 1 -and $W.runTaskCalls -eq 0 -and $W.asg.desired -eq 0 -and
  $W.evidence.launch_suspended_verified -eq $true -and $W.evidence.terminated_verified -eq $false -and
  $W.evidence.scaling_activities_terminal_verified -eq $false -and $W.failure -like '*terminal scaling activities*' }
Invoke-Case 'activityaccess' $true {
  $W.cleanupActivityReads -ge 2 -and $W.runTaskCalls -eq 1 -and $W.instState -eq 'terminated' -and
  $W.evidence.terminated_verified -eq $true -and $W.evidence.scaling_activities_terminal_verified -eq $true -and
  ($W.evidence.cleanup_errors -join ' ') -like '*Cleanup scaling activity verification failed*AccessDenied*' -and
  $W.failure -like '*Cleanup scaling activity verification failed*AccessDenied*' }
foreach ($scenario in @('latevolumeaccess','latevolumemissing')) {
  Invoke-Case $scenario $true {
    $W.runTaskCalls -eq 0 -and $W.lateObserved -and $W.instState -eq 'terminated' -and
    ($W.evidence.cleanup_errors -join ' ') -like '*Root-volume discovery failed*' -and
    $W.failure -like '*Root-volume discovery failed*' }
}
Invoke-Case 'latevolumeleft' $true {
  $W.instState -eq 'terminated' -and $W.evidence.observed_volume_ids -contains 'vol-0abc' -and
  ($W.evidence.remaining_volumes -join ' ') -like '*vol-0abc=available*' -and $W.failure -like '*not deleted*' }
Invoke-Case 'suspendfailure' $true {
  $W.suspendCalls -ge 2 -and $W.runTaskCalls -eq 0 -and $W.instState -eq 'terminated' -and
  $W.asg.desired -eq 0 -and $W.evidence.launch_suspended_verified -eq $false -and
  $W.evidence.terminated_verified -eq $false -and $W.failure -like '*Launch suspension request failed*' }
Invoke-Case 'suspend-noeffect' $true {
  $W.runTaskCalls -eq 1 -and $W.instState -eq 'terminated' -and $W.asg.desired -eq 0 -and
  $W.evidence.launch_suspended_verified -eq $false -and $W.failure -like '*Launch suspension NOT verified*' }
Invoke-Case 'cleanup-suspendfailure' $true {
  $W.runTaskCalls -eq 1 -and $W.instState -eq 'terminated' -and $W.asg.desired -eq 0 -and
  $W.evidence.launch_suspended_verified -eq $true -and $W.failure -like '*Launch suspension request failed*' }
Invoke-Case 'stale-cutoff' $false {
  $W.actions.Count -eq 1 -and ([datetime]$W.actions[0].StartTime).ToUniversalTime() -gt $W.clock.ToUniversalTime() -and $W.runTaskCalls -eq 1 }
foreach ($scenario in @('cutoff-recurring','cutoff-foreign','cutoff-capacity','cutoff-asg')) {
  Invoke-Case $scenario $true { $W.failure -like '*Existing smoke shutdown action*' } $false
}
foreach ($scenario in @('cutoff-put-recurring','cutoff-not-updated')) {
  Invoke-Case $scenario $true {
    $W.failure -like '*Cloud-side GPU cutoff not confirmed*' -and $W.asg.suspended -contains 'Launch' -and
    $W.evidence.launch_suspended_verified -eq $true } $false
}
foreach ($scenario in @('wrongsubnet','manysubnets')) {
  Invoke-Case $scenario $true { $W.failure -like '*exactly the one reviewed Terraform smoke subnet*' } $false
}
Invoke-Case 'wronginstancesubnet' $true {
  $W.runTaskCalls -eq 0 -and $W.instState -eq 'terminated' -and $W.failure -like '*subnet differs*' }
Invoke-Case 'retrylatched' $true { $W.failure -like '*Launch is suspended*' -and $W.suspendCalls -eq 0 } $false
Invoke-Case 'activeactivity' $true { $W.failure -like '*scaling operation is still in progress*' } $false
Invoke-Case 'foreignactivity' $true { $W.failure -like '*scaling activity does not identify*' } $false
Invoke-Case 'incompleteactivity' $true { $W.failure -like '*Complete ASG scaling activity history*' } $false
foreach ($scenario in @('existingservice','existingtask','existingcontainer')) {
  Invoke-Case $scenario $true { $W.failure -like '*Smoke cluster must have no services*' } $false
}
foreach ($scenario in @('existingstopping','stopstatusmissing')) {
  Invoke-Case $scenario $true { $W.failure -like '*previous ECS task is still stopping*' } $false
}
Invoke-Case 'completedhistory' $false { $W.runTaskCalls -eq 1 -and $W.instState -eq 'terminated' }

if ($failures) { Write-Host "$failures scenario(s) failed"; exit 1 }
Write-Host 'all gpu-smoke.ps1 scenarios passed'
