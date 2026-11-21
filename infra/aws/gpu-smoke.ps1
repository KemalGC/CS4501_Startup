# StrokeSense: single manual GPU preflight. Never launches a paid job.
# After a reviewed Terraform apply:
#   .\gpu-smoke.ps1 -ExpectedAccountId 123456789012 -AwsProfile <profile> `
#     -ExpectedImageUri <ecr-repo>@sha256:<digest> -ApproveCharge
# One invocation = at most ONE EC2 host and ONE ECS task. Never re-run after a
# failure without a new, separate approval.
[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][ValidatePattern('^\d{12}$')][string]$ExpectedAccountId,
  [Parameter(Mandatory=$true)][ValidatePattern('^\d{12}\.dkr\.ecr\.us-east-1\.amazonaws\.com/[a-z0-9._/-]+@sha256:[a-f0-9]{64}$')][string]$ExpectedImageUri,
  [switch]$ApproveCharge,
  [ValidateRange(20,60)][int]$HardStopMinutes = 45,
  [ValidateRange(3,15)][int]$BootWaitMinutes = 12,
  [ValidatePattern('^[A-Za-z0-9_.-]{1,64}$')][string]$AwsProfile,
  [string]$EvidenceDir = (Join-Path ([System.IO.Path]::GetTempPath()) 'strokesense-gpu-smoke')
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$region = 'us-east-1'
$runId = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$startedBy = 'gpu-smoke-only'
$scheduledName = 'strokesense-gpu-smoke-cutoff'
$asgVerified = $false
$asgName = $null
$cluster = $null
$taskArn = $null
$taskStopped = $false
$payloadFile = $null
$logGroup = $null
$t0 = $null
$instanceIds = @()
$volumeIds = @()
$evidence = [ordered]@{ run_id = $runId; region = $region; timings_utc = [ordered]@{} }
$profileArgs = @()
if ($AwsProfile) { $profileArgs = @('--profile', $AwsProfile) }
$runStart = Get-Date
$deadline = $runStart.AddMinutes($HardStopMinutes)

function Get-Utc { return (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') }
function Add-Mark([string]$Name) { $evidence.timings_utc[$Name] = Get-Utc; Save-Evidence }
function Save-Evidence {
  if (!(Test-Path $EvidenceDir)) { [void](New-Item -ItemType Directory -Path $EvidenceDir -Force) }
  $path = Join-Path $EvidenceDir "gpu-smoke-$runId.json"
  [System.IO.File]::WriteAllText($path, ($evidence | ConvertTo-Json -Depth 12))
}

function Invoke-Aws {
  param([Parameter(Mandatory=$true)][string[]]$Arguments)
  $raw = & aws @Arguments @profileArgs --region $region --no-cli-pager 2>&1
  if ($LASTEXITCODE -ne 0) {
    $text = ($raw | Out-String)
    $code = 'unknown'
    if ($text -match 'An error occurred \(([A-Za-z0-9.]+)\)') { $code = $Matches[1] }
    # Sanitized: operation, AWS error code and a short message; never request bodies.
    $msg = ($text -replace '\s+', ' ').Trim()
    if ($msg.Length -gt 300) { $msg = $msg.Substring(0, 300) }
    throw "AWS $($Arguments[0]) $($Arguments[1]) failed [$code]: $msg"
  }
  return ($raw | Out-String).Trim()
}
function Invoke-AwsJson { param([string[]]$Arguments) return (Invoke-Aws -Arguments ($Arguments + @('--output','json')) | ConvertFrom-Json) }

function Get-TerraformOutput {
  param([Parameter(Mandatory=$true)][string]$Name)
  $out = & terraform "-chdir=$PSScriptRoot" output -raw $Name 2>&1
  if ($LASTEXITCODE -ne 0) { throw "Terraform output $Name missing; apply reviewed smoke infrastructure first." }
  $value = ($out | Out-String).Trim()
  if (!$value -or $value -eq 'null') { throw "GPU smoke output $Name is empty." }
  return $value
}
function Get-Remaining { return [int][Math]::Floor(($deadline - (Get-Date)).TotalSeconds) }
function Get-Prop($Object, [string]$Name) {
  if ($null -ne $Object -and $Object.PSObject.Properties[$Name]) { return $Object.$Name }
  return $null
}
# Null-safe count: in PowerShell @($null).Count is 1.
function Get-Count($Value) { if ($null -eq $Value) { return 0 } return @($Value).Count }

if (!$ApproveCharge) { throw 'Explicit -ApproveCharge required after reviewing real AWS GPU charges.' }
if (!(Get-Command aws -ErrorAction SilentlyContinue) -or !(Get-Command terraform -ErrorAction SilentlyContinue)) {
  throw 'Install/configure AWS CLI v2 and Terraform before running a GPU smoke.'
}

try {
  # ---------- identity, ownership and idle-state checks (no mutation) ----------
  $identity = Invoke-AwsJson @('sts','get-caller-identity')
  if ($identity.Account -ne $ExpectedAccountId) { throw 'Wrong AWS account; no GPU resources changed.' }

  $asgName = Get-TerraformOutput 'gpu_smoke_asg_name'
  $cluster = Get-TerraformOutput 'gpu_smoke_ecs_cluster'
  $provider = Get-TerraformOutput 'gpu_smoke_capacity_provider'
  $taskDefinition = Get-TerraformOutput 'gpu_smoke_task_definition'
  $subnet = Get-TerraformOutput 'gpu_smoke_subnet_id'
  $sg = Get-TerraformOutput 'gpu_smoke_task_security_group'
  $logGroup = Get-TerraformOutput 'gpu_smoke_log_group'
  $acct = [regex]::Escape($ExpectedAccountId)
  if ($asgName -notmatch '^strokesense-[a-z0-9-]+-gpu-one-instance$' -or
      $cluster -notmatch "^arn:aws:ecs:us-east-1:${acct}:cluster/strokesense-[a-z0-9-]+-gpu" -or
      $taskDefinition -notmatch "^arn:aws:ecs:us-east-1:${acct}:task-definition/strokesense-[a-z0-9-]+-gpu-preflight:\d+$" -or
      $provider -notmatch '^strokesense-[a-z0-9-]+-gpu-asg$' -or
      $subnet -notmatch '^subnet-[0-9a-f]{8,17}$' -or $sg -notmatch '^sg-[0-9a-f]{8,17}$' -or
      $logGroup -notmatch '^/ecs/strokesense-[a-z0-9-]+/paid-gpu$') {
    throw 'Terraform outputs are not the isolated StrokeSense us-east-1 GPU smoke resources.'
  }
  $evidence.cluster = $cluster; $evidence.asg = $asgName; $evidence.capacity_provider = $provider
  $evidence.task_definition = $taskDefinition; $evidence.log_group = $logGroup

  $quota = Invoke-AwsJson @('service-quotas','get-service-quota','--service-code','ec2','--quota-code','L-DB2E81BA')
  $liveG = Invoke-AwsJson @('ec2','describe-instances','--filters','Name=instance-type,Values=g*,vt*',
    'Name=instance-state-name,Values=pending,running,stopping','--query','Reservations[].Instances[].InstanceId')
  if ([double]$quota.Quota.Value -lt 4 -or (Get-Count $liveG) -ne 0) {
    throw "Applied G/VT quota ($($quota.Quota.Value)) < 4 or other G/VT instances are running; not launching."
  }

  $group = (Invoke-AwsJson @('autoscaling','describe-auto-scaling-groups','--auto-scaling-group-names',$asgName)).AutoScalingGroups
  if (@($group).Count -ne 1) { throw 'Expected exactly one smoke ASG.' }
  $group = $group[0]
  $suspended = @($group.SuspendedProcesses | ForEach-Object { $_.ProcessName })
  if ($group.MinSize -ne 0 -or $group.DesiredCapacity -ne 0 -or $group.MaxSize -gt 1 -or (Get-Count $group.Instances) -ne 0) {
    throw 'GPU ASG must be idle (min=0, desired=0, max<=1, no instances).'
  }
  foreach ($p in @('Launch','Terminate','ScheduledActions')) {
    if ($suspended -contains $p) { throw "ASG process $p is suspended; a previous attempt left it locked. Review before any new approval." }
  }
  foreach ($p in @('ReplaceUnhealthy','AZRebalance')) {
    if ($suspended -notcontains $p) { throw "ASG process $p must be suspended so no replacement host can launch." }
  }
  $hooks = Invoke-AwsJson @('autoscaling','describe-lifecycle-hooks','--auto-scaling-group-name',$asgName)
  if (@($hooks.LifecycleHooks).Count -ne 0) { throw 'Smoke ASG has lifecycle hooks (e.g. managed draining); termination could be delayed.' }
  $existingActions = Invoke-AwsJson @('autoscaling','describe-scheduled-actions','--auto-scaling-group-name',$asgName)
  if (@($existingActions.ScheduledUpdateGroupActions | Where-Object { $_.ScheduledActionName -ne $scheduledName }).Count -ne 0) {
    throw 'Unexpected scheduled actions on the smoke ASG could scale it up.'
  }

  $cp = (Invoke-AwsJson @('ecs','describe-capacity-providers','--capacity-providers',$provider)).capacityProviders
  if (@($cp).Count -ne 1) { throw 'Smoke capacity provider not found.' }
  $asgp = $cp[0].autoScalingGroupProvider
  if ($asgp.managedScaling.status -ne 'DISABLED' -or $asgp.managedTerminationProtection -ne 'DISABLED' -or
      (Get-Prop $asgp 'managedDraining') -ne 'DISABLED' -or $asgp.autoScalingGroupArn -notmatch [regex]::Escape(":autoScalingGroupName/$asgName")) {
    throw 'Capacity provider must be bound to the smoke ASG with managed scaling, termination protection and draining DISABLED.'
  }
  $services = Invoke-AwsJson @('ecs','list-services','--cluster',$cluster)
  $existingTasks = (Invoke-AwsJson @('ecs','list-tasks','--cluster',$cluster,'--desired-status','RUNNING')).taskArns
  $containerInstances = Invoke-AwsJson @('ecs','list-container-instances','--cluster',$cluster)
  if ((Get-Count $services.serviceArns) -ne 0 -or (Get-Count $existingTasks) -ne 0 -or (Get-Count $containerInstances.containerInstanceArns) -ne 0) {
    throw 'Smoke cluster must have no services, running tasks or container instances; refusing to adopt them.'
  }

  $def = (Invoke-AwsJson @('ecs','describe-task-definition','--task-definition',$taskDefinition)).taskDefinition
  $containers = @($def.containerDefinitions)
  $c0 = $containers[0]
  $gpuReq = @(@(Get-Prop $c0 'resourceRequirements') | Where-Object { $_.type -eq 'GPU' })
  if ($containers.Count -ne 1 -or $c0.name -ne 'gpu-preflight' -or
      @($def.requiresCompatibilities) -notcontains 'EC2' -or $def.networkMode -ne 'awsvpc' -or
      (Get-Prop $def 'taskRoleArn') -or
      $c0.image -ne $ExpectedImageUri -or
      ($c0.command -join ' ') -ne 'python3 -m aws_app.gpu_preflight --model /app/models/yolo11n-pose.onnx' -or
      $gpuReq.Count -ne 1 -or $gpuReq[0].value -ne '0.125' -or
      (Get-Prop $c0 'privileged') -eq $true -or (Get-Count (Get-Prop $c0 'mountPoints')) -ne 0 -or
      (Get-Count (Get-Prop $def 'volumes')) -ne 0 -or (Get-Count (Get-Prop $c0 'secrets')) -ne 0 -or
      (Get-Count (Get-Prop $c0 'environment')) -ne 0) {
    throw 'Preflight task definition must be EC2/awsvpc, the exact approved image digest and command, 1/8 GPU, NO customer task role, and no secrets, env, mounts or privilege.'
  }
  $evidence.task_definition_revision = $def.revision
  $evidence.image = $ExpectedImageUri
  $asgVerified = $true

  # ---------- AWS-side cutoff BEFORE any capacity exists ----------
  $cutoffUtc = $deadline.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
  [void](Invoke-Aws -Arguments @('autoscaling','put-scheduled-update-group-action',
    '--auto-scaling-group-name',$asgName,'--scheduled-action-name',$scheduledName,
    '--start-time',$cutoffUtc,'--min-size','0','--max-size','0','--desired-capacity','0'))
  $actions = @((Invoke-AwsJson @('autoscaling','describe-scheduled-actions','--auto-scaling-group-name',$asgName,'--scheduled-action-names',$scheduledName)).ScheduledUpdateGroupActions)
  if ($actions.Count -ne 1 -or $actions[0].AutoScalingGroupName -ne $asgName -or
      $actions[0].MinSize -ne 0 -or $actions[0].MaxSize -ne 0 -or $actions[0].DesiredCapacity -ne 0 -or
      [Math]::Abs(([datetime]$actions[0].StartTime).ToUniversalTime().Subtract($deadline.ToUniversalTime()).TotalSeconds) -gt 90) {
    throw 'Cloud-side GPU cutoff not confirmed; refusing to start host.'
  }
  $evidence.cloud_cutoff_utc = $cutoffUtc
  Write-Host "AWS GPU hard cutoff (min/max/desired 0) confirmed for $cutoffUtc."

  # ---------- exactly one host ----------
  $t0 = Get-Date
  Add-Mark 'scale_out_requested'
  [void](Invoke-Aws -Arguments @('autoscaling','update-auto-scaling-group','--auto-scaling-group-name',$asgName,'--min-size','0','--max-size','1','--desired-capacity','1'))

  $bootDeadline = $t0.AddMinutes($BootWaitMinutes)
  while ((Get-Date) -lt $bootDeadline -and @($instanceIds).Count -eq 0) {
    $g = (Invoke-AwsJson @('autoscaling','describe-auto-scaling-groups','--auto-scaling-group-names',$asgName)).AutoScalingGroups[0]
    $instanceIds = @($g.Instances | ForEach-Object { $_.InstanceId })
    if (@($instanceIds).Count -eq 0) { Start-Sleep -Seconds 10 }
  }
  if (@($instanceIds).Count -eq 0) {
    $acts = Invoke-AwsJson @('autoscaling','describe-scaling-activities','--auto-scaling-group-name',$asgName,'--max-items','3')
    $why = (@($acts.Activities) | ForEach-Object { "$($_.StatusCode): $($_.StatusMessage)" }) -join ' | '
    throw "No GPU instance launched within $BootWaitMinutes min. ASG activity: $why"
  }
  # Lock the ASG to this single host: no replacement or second paid instance.
  [void](Invoke-Aws -Arguments @('autoscaling','suspend-processes','--auto-scaling-group-name',$asgName,'--scaling-processes','Launch'))
  Add-Mark 'instance_seen_launch_suspended'
  $evidence.instance_ids = $instanceIds
  if (@($instanceIds).Count -ne 1) { throw "Expected one instance, saw $(@($instanceIds).Count); cleaning up." }
  $inst = (Invoke-AwsJson @('ec2','describe-instances','--instance-ids',$instanceIds[0])).Reservations[0].Instances[0]
  $volumeIds = @($inst.BlockDeviceMappings | ForEach-Object { $_.Ebs.VolumeId })
  $evidence.instance = [ordered]@{ id = $inst.InstanceId; type = $inst.InstanceType; ami = $inst.ImageId;
    launch_time = $inst.LaunchTime; az = $inst.Placement.AvailabilityZone; volumes = $volumeIds }
  Save-Evidence
  if ($inst.InstanceType -ne 'g6f.xlarge') { throw "Unexpected instance type $($inst.InstanceType)." }
  Write-Host "Instance $($inst.InstanceId) ($($inst.InstanceType), $($inst.ImageId)) launched $($inst.LaunchTime)."

  $ready = $false
  while ((Get-Date) -lt $bootDeadline -and !$ready) {
    $ci = Invoke-AwsJson @('ecs','list-container-instances','--cluster',$cluster)
    foreach ($arn in @($ci.containerInstanceArns)) {
      $d = (Invoke-AwsJson @('ecs','describe-container-instances','--cluster',$cluster,'--container-instances',$arn)).containerInstances[0]
      if ($d.ec2InstanceId -ne $instanceIds[0]) { throw 'Unknown container instance joined the smoke cluster.' }
      if ($d.agentConnected -eq $true -and $d.status -eq 'ACTIVE') {
        $gpuRes = @($d.registeredResources | Where-Object { $_.name -eq 'GPU' })
        $evidence.container_instance = [ordered]@{ arn = $arn; agent = $d.versionInfo.agentVersion;
          gpu_registered = $gpuRes | ConvertTo-Json -Depth 5 -Compress }
        if ($gpuRes.Count -eq 0) { throw 'ECS agent registered no GPU resource on the g6f host (known g6f issue); not launching the task.' }
        $ready = $true
      }
    }
    if (!$ready) { Start-Sleep -Seconds 10 }
  }
  if (!$ready) { throw 'GPU EC2 host did not register with ECS in time.' }
  Add-Mark 'host_registered'

  # ---------- exactly one task (idempotent) ----------
  $clientToken = "ss-gpu-smoke-$runId"
  $request = @{
    cluster = $cluster; taskDefinition = $taskDefinition; count = 1; startedBy = $startedBy
    clientToken = $clientToken
    capacityProviderStrategy = @(@{capacityProvider=$provider;weight=1})
    networkConfiguration = @{awsvpcConfiguration = @{ subnets=@($subnet); securityGroups=@($sg); assignPublicIp='DISABLED' }}
  }
  $payloadFile = Join-Path ([System.IO.Path]::GetTempPath()) "strokesense-gpu-smoke-runtask-$runId.json"
  [System.IO.File]::WriteAllText($payloadFile, ($request | ConvertTo-Json -Depth 12))
  $runArgs = @('ecs','run-task','--cli-input-json',('file://' + $payloadFile.Replace('\','/')))
  $launch = $null
  try { $launch = Invoke-AwsJson $runArgs }
  catch {
    Write-Warning "RunTask response lost/failed: $($_.Exception.Message). Reconciling before any retry."
    $seen = @((Invoke-AwsJson @('ecs','list-tasks','--cluster',$cluster,'--started-by',$startedBy)).taskArns)
    if ($seen.Count -eq 0) { $launch = Invoke-AwsJson $runArgs }  # same clientToken: idempotent
    elseif ($seen.Count -eq 1) { $taskArn = $seen[0] }
    else { throw 'More than one smoke task found; stopping.' }
  }
  if (!$taskArn) {
    if ((Get-Count $launch.failures) -ne 0 -or (Get-Count $launch.tasks) -ne 1) {
      $f = (@($launch.failures) | ForEach-Object { "$($_.arn) $($_.reason) $(Get-Prop $_ 'detail')" }) -join ' | '
      throw "No preflight task launched. ECS failures: $f"
    }
    $taskArn = $launch.tasks[0].taskArn
  }
  if ($taskArn -notmatch "^arn:aws:ecs:us-east-1:${acct}:task/") { throw 'Unexpected task identity.' }
  $evidence.task_arn = $taskArn
  Add-Mark 'task_submitted'

  $taskDeadline = $deadline.AddMinutes(-8)
  while ((Get-Date) -lt $taskDeadline) {
    $status = Invoke-AwsJson @('ecs','describe-tasks','--cluster',$cluster,'--tasks',$taskArn)
    if (@($status.tasks).Count -ne 1) { throw 'Preflight ECS task status unavailable.' }
    $task = $status.tasks[0]
    if ($task.lastStatus -eq 'STOPPED') {
      $taskStopped = $true
      Add-Mark 'task_stopped'
      $worker = @($task.containers | Where-Object { $_.name -eq 'gpu-preflight' })
      $exit = $null; if ($worker.Count -eq 1) { $exit = Get-Prop $worker[0] 'exitCode' }
      $evidence.task = [ordered]@{ started_at = Get-Prop $task 'startedAt'; stopped_at = Get-Prop $task 'stoppedAt';
        stop_code = Get-Prop $task 'stopCode'; stopped_reason = Get-Prop $task 'stoppedReason'; exit_code = $exit;
        container_reason = $(if ($worker.Count -eq 1) { Get-Prop $worker[0] 'reason' } else { $null });
        image_digest = $(if ($worker.Count -eq 1) { Get-Prop $worker[0] 'imageDigest' } else { $null });
        task_definition_arn = $task.taskDefinitionArn }
      Save-Evidence
      $taskId = ($taskArn -split '/')[-1]
      $stream = "gpu-preflight/gpu-preflight/$taskId"
      $evidence.log_stream = $stream
      try {
        $events = Invoke-AwsJson @('logs','get-log-events','--log-group-name',$logGroup,'--log-stream-name',$stream,'--start-from-head')
        $evidence.log_lines = @(@($events.events) | ForEach-Object { $_.message } | Where-Object { $_ -match '^(STROKESENSE_GPU_PREFLIGHT |INFO:|ERROR:|WARNING:|Traceback|\S+Error)' } | Select-Object -First 40)
        foreach ($line in $evidence.log_lines) { Write-Host "log: $line" }
      } catch { Write-Warning "Could not read preflight log stream: $($_.Exception.Message)" }
      Save-Evidence
      if ($evidence.task.image_digest -and $ExpectedImageUri -notlike "*@$($evidence.task.image_digest)") {
        throw "Task ran image $($evidence.task.image_digest), not the approved digest."
      }
      if ($exit -ne 0) {
        throw "CUDA preflight failed (exit=$exit, stopCode=$($evidence.task.stop_code), reason=$($evidence.task.stopped_reason) / $($evidence.task.container_reason))."
      }
      Write-Host 'CUDA preflight passed: task stopped with exit code 0.'
      break
    }
    Start-Sleep -Seconds 10
  }
  if (!$taskStopped) { throw 'GPU preflight timed out before the cleanup margin; enforcing shutdown.' }
}
catch {
  $evidence.error = $_.Exception.Message
  Write-Warning $evidence.error
  throw
}
finally {
  if ($payloadFile -and (Test-Path $payloadFile)) { Remove-Item -LiteralPath $payloadFile -Force -ErrorAction SilentlyContinue }
  if ($asgVerified) {
    if ($taskArn -and !$taskStopped) {
      try { [void](Invoke-Aws -Arguments @('ecs','stop-task','--cluster',$cluster,'--task',$taskArn,'--reason','Operator smoke cutoff')) ; Add-Mark 'task_stop_requested' }
      catch { Write-Warning "Could not stop ECS task: $($_.Exception.Message). Cloud cutoff remains scheduled." }
    }
    try {
      # Only ever lowers capacity; never re-arms it.
      [void](Invoke-Aws -Arguments @('autoscaling','update-auto-scaling-group','--auto-scaling-group-name',$asgName,'--min-size','0','--max-size','0','--desired-capacity','0'))
      Add-Mark 'shutdown_requested'
      Write-Host 'GPU ASG set to min=0, max=0, desired=0. Verifying EC2 termination...'
    } catch { Write-Warning "Immediate ASG scale-to-zero failed: $($_.Exception.Message). AWS cutoff remains scheduled." }
    $terminated = $false
    $termDeadline = (Get-Date).AddMinutes(10)
    while ((Get-Date) -lt $termDeadline) {
      try {
        $g = (Invoke-AwsJson @('autoscaling','describe-auto-scaling-groups','--auto-scaling-group-names',$asgName)).AutoScalingGroups[0]
        $live = Invoke-AwsJson @('ec2','describe-instances','--filters',"Name=tag:aws:autoscaling:groupName,Values=$asgName",
          'Name=instance-state-name,Values=pending,running,shutting-down,stopping,stopped','--query','Reservations[].Instances[].InstanceId')
        $mine = $true
        $stateList = @()
        if (@($instanceIds).Count -gt 0) {
          $stateList = @(Invoke-AwsJson (@('ec2','describe-instances','--instance-ids') + $instanceIds + @('--query','Reservations[].Instances[].State.Name')))
          $mine = (@($stateList | Where-Object { $_ -ne 'terminated' }).Count -eq 0)
        }
        if ($g.MinSize -eq 0 -and $g.MaxSize -eq 0 -and $g.DesiredCapacity -eq 0 -and (Get-Count $g.Instances) -eq 0 -and (Get-Count $live) -eq 0 -and $mine) {
          $terminated = $true; break
        }
      } catch { Write-Warning "Termination check failed: $($_.Exception.Message); retrying." }
      Start-Sleep -Seconds 15
    }
    if ($terminated) {
      Add-Mark 'instances_terminated_observed'
      $evidence.terminated_verified = $true
      Write-Host "VERIFIED: ASG 0/0/0 and instance(s) $($instanceIds -join ',') TERMINATED."
      $remainingVolumes = @()
      foreach ($v in $volumeIds) {
        $vr = & aws ec2 describe-volumes --volume-ids $v @profileArgs --region $region --no-cli-pager --output json 2>&1
        if ($LASTEXITCODE -eq 0) { $vs = ($vr | Out-String | ConvertFrom-Json).Volumes; if (@($vs).Count -gt 0 -and $vs[0].State -ne 'deleted') { $remainingVolumes += "$v=$($vs[0].State)" } }
      }
      $evidence.remaining_volumes = $remainingVolumes
      if ($remainingVolumes.Count) { Write-Warning "Root volume(s) not yet deleted: $($remainingVolumes -join ', ')" }
    } else {
      $evidence.terminated_verified = $false
      Write-Warning 'GPU EC2 termination NOT verified within 10 minutes; check NOW. AWS cutoff remains scheduled.'
    }
    Save-Evidence
    Write-Host ('evidence: ' + (Join-Path $EvidenceDir "gpu-smoke-$runId.json"))
  }
}
