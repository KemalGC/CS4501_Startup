# StrokeSense: single manual GPU preflight. Never launches a paid job.
# After a reviewed Terraform apply: .\gpu-smoke.ps1 -ExpectedAccountId 123456789012 -AwsProfile strokesense-admin -ApproveCharge
[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][ValidatePattern('^\d{12}$')][string]$ExpectedAccountId,
  [switch]$ApproveCharge,
  [ValidateRange(20,60)][int]$HardStopMinutes = 45,
  [ValidateRange(3,15)][int]$BootWaitMinutes = 10,
  [ValidatePattern('^[A-Za-z0-9_.-]{1,64}$')][string]$AwsProfile
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$region = 'us-east-1'
$asgVerified = $false
$asgName = $null
$cluster = $null
$taskArn = $null
$taskStopped = $false
$payloadFile = $null
$logGroup = $null
$t0 = $null
$timings = [ordered]@{}
$profileArgs = @()
if ($AwsProfile) { $profileArgs = @('--profile', $AwsProfile) }

function Invoke-Aws {
  param([Parameter(Mandatory=$true)][string[]]$Arguments)
  $raw = & aws @Arguments @profileArgs --region $region --no-cli-pager 2>&1
  if ($LASTEXITCODE -ne 0) {
    throw "AWS command failed: $($Arguments[0]) $($Arguments[1]). Inspect CLI stderr locally."
  }
  return ($raw | Out-String).Trim()
}

function Get-TerraformOutput {
  param([Parameter(Mandatory=$true)][string]$Name)
  $out = & terraform "-chdir=$PSScriptRoot" output -raw $Name 2>&1
  if ($LASTEXITCODE -ne 0) { throw "Terraform output $Name missing; apply reviewed smoke infrastructure first." }
  $value = ($out | Out-String).Trim()
  if (!$value -or $value -eq 'null') { throw "GPU smoke output $Name is empty." }
  return $value
}

if (!$ApproveCharge) { throw 'Explicit -ApproveCharge required after reviewing real AWS GPU charges.' }
if (!(Get-Command aws -ErrorAction SilentlyContinue) -or
    !(Get-Command terraform -ErrorAction SilentlyContinue)) {
  throw 'Install/configure AWS CLI v2 and Terraform before running a GPU smoke.'
}

try {
  $identity = Invoke-Aws -Arguments @('sts','get-caller-identity','--output','json') | ConvertFrom-Json
  if ($identity.Account -ne $ExpectedAccountId) { throw 'Wrong AWS account; no GPU resources changed.' }

  $asgName = Get-TerraformOutput 'gpu_smoke_asg_name'
  $cluster = Get-TerraformOutput 'gpu_smoke_ecs_cluster'
  $provider = Get-TerraformOutput 'gpu_smoke_capacity_provider'
  $taskDefinition = Get-TerraformOutput 'gpu_smoke_task_definition'
  $subnet = Get-TerraformOutput 'gpu_smoke_subnet_id'
  $sg = Get-TerraformOutput 'gpu_smoke_task_security_group'
  $logGroup = Get-TerraformOutput 'gpu_smoke_log_group'
  if ($asgName -notmatch '^strokesense-[a-z0-9-]+-gpu-one-instance$' -or
      $cluster -notmatch '^arn:aws:ecs:us-east-1:[0-9]{12}:cluster/' -or
      $taskDefinition -notmatch '^arn:aws:ecs:us-east-1:[0-9]{12}:task-definition/' -or
      $subnet -notmatch '^subnet-[0-9a-f]{8,17}$' -or
      $sg -notmatch '^sg-[0-9a-f]{8,17}$') {
    throw 'Expected the isolated StrokeSense us-east-1 GPU smoke resource names.'
  }

  $groupInfo = Invoke-Aws -Arguments @('autoscaling','describe-auto-scaling-groups','--auto-scaling-group-names',$asgName,'--output','json') | ConvertFrom-Json
  if (@($groupInfo.AutoScalingGroups).Count -ne 1) { throw 'Expected exactly one ASG.' }
  $group = $groupInfo.AutoScalingGroups[0]
  if ($group.MinSize -ne 0 -or $group.DesiredCapacity -ne 0 -or
      $group.MaxSize -gt 1 -or @($group.Instances).Count -ne 0) {
    throw 'GPU ASG must be idle with min=0, desired=0, max<=1, and no existing hosts.'
  }
  $asgVerified = $true

  $definition = Invoke-Aws -Arguments @('ecs','describe-task-definition','--task-definition',$taskDefinition,'--output','json') | ConvertFrom-Json
  $def = $definition.taskDefinition
  $containers = @($def.containerDefinitions)
  if ($containers.Count -ne 1 -or $containers[0].name -ne 'gpu-preflight' -or
      @($def.requiresCompatibilities) -notcontains 'EC2' -or
      ($def.PSObject.Properties['taskRoleArn'] -and $def.taskRoleArn) -or
      $containers[0].image -notmatch '@sha256:[a-f0-9]{64}$' -or
      @($containers[0].resourceRequirements | Where-Object { $_.type -eq 'GPU' -and $_.value -eq '0.125' }).Count -ne 1) {
    throw 'Preflight must use EC2, a digest-pinned image, 1/8 GPU and NO customer task role.'
  }

  # AWS-side scheduled action runs even if this PowerShell process disconnects.
  $cutoff = (Get-Date).ToUniversalTime().AddMinutes($HardStopMinutes).ToString('yyyy-MM-ddTHH:mm:ssZ')
  [void](Invoke-Aws -Arguments @(
    'autoscaling','put-scheduled-update-group-action',
    '--auto-scaling-group-name',$asgName,'--scheduled-action-name','strokesense-gpu-smoke-cutoff',
    '--start-time',$cutoff,'--min-size','0','--max-size','0','--desired-capacity','0'))
  $scheduled = Invoke-Aws -Arguments @('autoscaling','describe-scheduled-actions','--auto-scaling-group-name',$asgName,'--scheduled-action-names','strokesense-gpu-smoke-cutoff','--output','json') | ConvertFrom-Json
  if (@($scheduled.ScheduledUpdateGroupActions).Count -ne 1 -or
      $scheduled.ScheduledUpdateGroupActions[0].MaxSize -ne 0) {
    throw 'Cloud-side GPU cutoff not confirmed; refusing to start host.'
  }
  Write-Host "AWS GPU hard cutoff scheduled for $cutoff."
  $t0 = Get-Date
  [void](Invoke-Aws -Arguments @('autoscaling','update-auto-scaling-group','--auto-scaling-group-name',$asgName,'--min-size','0','--max-size','1','--desired-capacity','1'))

  $ready = $false
  $bootDeadline = (Get-Date).AddMinutes($BootWaitMinutes)
  while ((Get-Date) -lt $bootDeadline) {
    $instances = Invoke-Aws -Arguments @('ecs','list-container-instances','--cluster',$cluster,'--output','json') | ConvertFrom-Json
    foreach ($instanceArn in @($instances.containerInstanceArns)) {
      $description = Invoke-Aws -Arguments @('ecs','describe-container-instances','--cluster',$cluster,'--container-instances',$instanceArn,'--output','json') | ConvertFrom-Json
      if ($description.containerInstances[0].agentConnected -eq $true -and
          $description.containerInstances[0].status -eq 'ACTIVE') { $ready = $true; break }
    }
    if ($ready) { break }
    Start-Sleep -Seconds 15
  }
  if (!$ready) { throw 'GPU EC2 host did not register with ECS in time.' }
  $timings['host_registered_seconds'] = [int]((Get-Date) - $t0).TotalSeconds

  $request = @{
    cluster = $cluster
    taskDefinition = $taskDefinition
    capacityProviderStrategy = @(@{capacityProvider=$provider;weight=1})
    count = 1
    startedBy = 'gpu-smoke-only'
    networkConfiguration = @{awsvpcConfiguration = @{
      subnets=@($subnet);securityGroups=@($sg);assignPublicIp='DISABLED'
    }}
  }
  $payloadFile = Join-Path ([System.IO.Path]::GetTempPath()) 'strokesense-gpu-smoke-runtask.json'
  [System.IO.File]::WriteAllText($payloadFile, ($request | ConvertTo-Json -Depth 12))
  $launch = Invoke-Aws -Arguments @('ecs','run-task','--cli-input-json',('file://' + $payloadFile.Replace('\','/')),'--output','json') | ConvertFrom-Json
  if (@($launch.failures).Count -ne 0 -or @($launch.tasks).Count -ne 1) {
    throw 'No approved GPU preflight task was launched.'
  }
  $taskArn = $launch.tasks[0].taskArn
  if ($taskArn -notmatch '^arn:aws:ecs:us-east-1:[0-9]{12}:task/') { throw 'Unexpected task identity.' }

  $deadline = (Get-Date).AddMinutes([Math]::Min(20,$HardStopMinutes-5))
  while ((Get-Date) -lt $deadline) {
    $status = Invoke-Aws -Arguments @('ecs','describe-tasks','--cluster',$cluster,'--tasks',$taskArn,'--output','json') | ConvertFrom-Json
    if (@($status.tasks).Count -ne 1) { throw 'Preflight ECS task status unavailable.' }
    if ($status.tasks[0].lastStatus -eq 'STOPPED') {
      $taskStopped = $true
      $worker = @($status.tasks[0].containers | Where-Object { $_.name -eq 'gpu-preflight' })
      $timings['task_stopped_seconds'] = [int]((Get-Date) - $t0).TotalSeconds
      $taskId = ($taskArn -split '/')[-1]
      try {
        $events = Invoke-Aws -Arguments @('logs','get-log-events','--log-group-name',$logGroup,
          '--log-stream-name',"gpu-preflight/gpu-preflight/$taskId",'--start-from-head','--output','json') | ConvertFrom-Json
        foreach ($e in @($events.events)) {
          if ($e.message -match '^(STROKESENSE_GPU_PREFLIGHT |GPU preflight|INFO:|ERROR:)') { Write-Host "log: $($e.message)" }
        }
      } catch { Write-Warning 'Could not read preflight CloudWatch log stream.' }
      $exit = $null
      if ($worker.Count -eq 1 -and $worker[0].PSObject.Properties['exitCode']) { $exit = $worker[0].exitCode }
      if ($worker.Count -ne 1 -or $exit -ne 0) {
        $reason = if ($status.tasks[0].PSObject.Properties['stoppedReason']) { $status.tasks[0].stoppedReason } else { 'n/a' }
        throw "CUDA preflight failed (exit=$exit, stoppedReason=$reason); inspect private CloudWatch task logs."
      }
      Write-Host 'CUDA preflight passed: task stopped with exit code 0.'
      break
    }
    Start-Sleep -Seconds 15
  }
  if (!$taskStopped) { throw 'GPU preflight timed out; enforcing shutdown.' }
}
finally {
  if ($payloadFile -and (Test-Path $payloadFile)) {
    Remove-Item -LiteralPath $payloadFile -Force -ErrorAction SilentlyContinue
  }
  if ($asgVerified) {
    if ($taskArn -and !$taskStopped) {
      try { [void](Invoke-Aws -Arguments @('ecs','stop-task','--cluster',$cluster,'--task',$taskArn,'--reason','Operator smoke cutoff','--output','json')) }
      catch { Write-Warning 'Could not stop ECS task; cloud-side ASG cutoff remains scheduled.' }
    }
    try {
      [void](Invoke-Aws -Arguments @('autoscaling','update-auto-scaling-group',
        '--auto-scaling-group-name',$asgName,'--min-size','0','--max-size','0','--desired-capacity','0'))
      Write-Host 'GPU ASG set to min=0, max=0, desired=0. Waiting for EC2 termination...'
    } catch { Write-Warning 'Immediate GPU cleanup failed; verify AWS scheduled cutoff and EC2 status.' }
    # Verify actual termination, not merely a requested scale-in.
    $terminated = $false
    $termDeadline = (Get-Date).AddMinutes(10)
    while ((Get-Date) -lt $termDeadline) {
      try {
        $g = (Invoke-Aws -Arguments @('autoscaling','describe-auto-scaling-groups','--auto-scaling-group-names',$asgName,'--output','json') | ConvertFrom-Json).AutoScalingGroups
        $live = Invoke-Aws -Arguments @('ec2','describe-instances','--filters',"Name=tag:aws:autoscaling:groupName,Values=$asgName",
          'Name=instance-state-name,Values=pending,running,shutting-down,stopping,stopped','--query','Reservations[].Instances[].InstanceId','--output','json') | ConvertFrom-Json
        if (@($g).Count -eq 1 -and @($g[0].Instances).Count -eq 0 -and @($live).Count -eq 0) { $terminated = $true; break }
      } catch { Write-Warning 'Termination check failed; retrying.' }
      Start-Sleep -Seconds 15
    }
    if ($t0) { $timings['host_terminated_seconds'] = [int]((Get-Date) - $t0).TotalSeconds }
    if ($terminated) { Write-Host 'VERIFIED: no GPU EC2 instance remains (all TERMINATED).' }
    else { Write-Warning 'GPU EC2 termination NOT verified within 10 minutes; check the console NOW. Cloud cutoff remains scheduled.' }
    if ($timings.Count) { Write-Host ('timings: ' + ($timings | ConvertTo-Json -Compress)) }
  }
}
