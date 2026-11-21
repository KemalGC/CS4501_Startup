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
  }
}
function global:Start-Sleep { param([int]$Seconds, [int]$Milliseconds) }
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
    'service-quotas get-service-quota' { return '{"Quota":{"Value":4.0}}' }
    'autoscaling describe-auto-scaling-groups' {
      if ($asg.desired -ge 1 -and $asg.max -ge 1 -and $asg.instances.Count -eq 0 -and $asg.suspended -notcontains 'Launch') {
        $asg.instances = @('i-0abc'); $W.instState = 'running'
      }
      if ($asg.desired -eq 0 -and $asg.instances.Count -gt 0) { $asg.instances = @(); $W.instState = 'terminated' }
      $inst = @($asg.instances | ForEach-Object { @{ InstanceId = $_ } })
      return (@{ AutoScalingGroups = @(@{ MinSize = $asg.min; MaxSize = $asg.max; DesiredCapacity = $asg.desired
        Instances = $inst; SuspendedProcesses = @($asg.suspended | ForEach-Object { @{ ProcessName = $_ } }) }) } | ConvertTo-Json -Depth 6)
    }
    'autoscaling describe-lifecycle-hooks' { return '{"LifecycleHooks":[]}' }
    'autoscaling put-scheduled-update-group-action' {
      $W.actions = @(@{ ScheduledActionName = (Get-Arg $a '--scheduled-action-name'); AutoScalingGroupName = (Get-Arg $a '--auto-scaling-group-name')
        StartTime = (Get-Arg $a '--start-time'); MinSize = 0; MaxSize = 0; DesiredCapacity = 0 }); return '' }
    'autoscaling describe-scheduled-actions' { return (@{ ScheduledUpdateGroupActions = @($W.actions) } | ConvertTo-Json -Depth 5) }
    'autoscaling update-auto-scaling-group' {
      $asg.min = [int](Get-Arg $a '--min-size'); $asg.max = [int](Get-Arg $a '--max-size'); $asg.desired = [int](Get-Arg $a '--desired-capacity'); return '' }
    'autoscaling suspend-processes' { $asg.suspended += (Get-Arg $a '--scaling-processes'); return '' }
    'autoscaling describe-scaling-activities' { return '{"Activities":[]}' }
    'ec2 describe-instances' {
      if ((Get-Arg $a '--filters') -like 'Name=instance-type*') { return '[]' }
      if ((Get-Arg $a '--filters') -like 'Name=tag:*') { if ($W.instState -and $W.instState -ne 'terminated') { return '["i-0abc"]' } return '[]' }
      if ((Get-Arg $a '--query') -like '*State.Name*') { return ('["' + $W.instState + '"]') }
      return '{"Reservations":[{"Instances":[{"InstanceId":"i-0abc","InstanceType":"g6f.xlarge","ImageId":"ami-0b8f7c7154f9e8f8b","LaunchTime":"2026-11-21T04:00:00Z","Placement":{"AvailabilityZone":"us-east-1a"},"BlockDeviceMappings":[{"Ebs":{"VolumeId":"vol-0abc"}}]}]}]}'
    }
    'ec2 describe-volumes' { $global:LASTEXITCODE = 254; return 'An error occurred (InvalidVolume.NotFound) when calling the DescribeVolumes operation' }
    'ecs describe-capacity-providers' { return '{"capacityProviders":[{"autoScalingGroupProvider":{"autoScalingGroupArn":"arn:aws:autoscaling:us-east-1:851226124502:autoScalingGroup:x:autoScalingGroupName/strokesense-aws-dev-gpu-one-instance","managedScaling":{"status":"DISABLED"},"managedTerminationProtection":"DISABLED","managedDraining":"DISABLED"}}]}' }
    'ecs list-services' { return '{"serviceArns":[]}' }
    'ecs list-tasks' { return (@{ taskArns = @($W.tasks) } | ConvertTo-Json) }
    'ecs list-container-instances' { if ($asg.instances.Count) { return '{"containerInstanceArns":["arn:aws:ecs:us-east-1:851226124502:container-instance/x/1"]}' } return '{"containerInstanceArns":[]}' }
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
      if ($W.scenario -eq 'lostresponse' -and $W.runTaskCalls -eq 1) { $global:LASTEXITCODE = 255; return 'Read timeout on endpoint URL' }
      return '{"tasks":[{"taskArn":"arn:aws:ecs:us-east-1:851226124502:task/strokesense-aws-dev-gpu/t1"}],"failures":[]}'
    }
    'ecs describe-tasks' {
      $code = 0; if ($W.scenario -eq 'exit2') { $code = 2 }
      return ('{"tasks":[{"lastStatus":"STOPPED","startedAt":"s","stoppedAt":"e","stopCode":"EssentialContainerExited","stoppedReason":"Essential container in task exited","taskDefinitionArn":"td:1","containers":[{"name":"gpu-preflight","exitCode":' + $code + ',"imageDigest":"sha256:' + ('a' * 64) + '"}]}]}') }
    'ecs stop-task' { return '{}' }
    'logs get-log-events' { return '{"events":[{"message":"STROKESENSE_GPU_PREFLIGHT {\"provider\":\"CUDAExecutionProvider\"}"}]}' }
    default { $global:LASTEXITCODE = 255; return "unexpected fake call: $op" }
  }
}

function Invoke-Case([string]$Scenario, [bool]$ExpectThrow, [scriptblock]$Check) {
  New-World $Scenario
  $threw = $null
  try {
    & $script:Under -ExpectedAccountId 851226124502 -ExpectedImageUri $Image -ApproveCharge -AwsProfile fake `
      -EvidenceDir (Join-Path ([IO.Path]::GetTempPath()) 'ss-gpu-smoke-test') *> $null
  } catch { $threw = $_.Exception.Message }
  $ok = (($null -ne $threw) -eq $ExpectThrow)
  $calls = @($W.calls)
  $idx = { param($p) for ($i = 0; $i -lt $calls.Count; $i++) { if ($calls[$i] -like $p) { return $i } } return -1 }
  $last = $calls | Where-Object { $_ -like 'autoscaling update-auto-scaling-group*' } | Select-Object -Last 1
  $common = ((& $idx 'autoscaling put-scheduled-update-group-action*') -ge 0 -and
    (& $idx 'autoscaling put-scheduled-update-group-action*') -lt (& $idx '*--desired-capacity 1*') -and
    $last -like '*--min-size 0 --max-size 0 --desired-capacity 0*' -and $W.asg.instances.Count -eq 0)
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

if ($failures) { Write-Host "$failures scenario(s) failed"; exit 1 }
Write-Host 'all gpu-smoke.ps1 scenarios passed'
