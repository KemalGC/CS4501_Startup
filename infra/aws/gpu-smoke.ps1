# StrokeSense: single manual GPU preflight. Never launches a paid job.
# After a reviewed Terraform apply:
#   .\gpu-smoke.ps1 -ExpectedAccountId 123456789012 -AwsProfile <profile> `
#     -ExpectedImageUri <ecr-repo>@sha256:<digest> -ApproveCharge
# G4dn additionally requires -ExpectedInstanceType g4dn.xlarge; the legacy
# default remains g6f.xlarge so changing deployed hardware cannot go unnoticed.
# One invocation = at most ONE EC2 host and ONE ECS task. Never re-run after a
# failure without a new, separate approval.
[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][ValidatePattern('^\d{12}$')][string]$ExpectedAccountId,
  [Parameter(Mandatory=$true)][ValidatePattern('^\d{12}\.dkr\.ecr\.us-east-1\.amazonaws\.com/[a-z0-9._/-]+@sha256:[a-f0-9]{64}$')][string]$ExpectedImageUri,
  [string]$ExpectedInstanceType = 'g6f.xlarge',
  [switch]$ApproveCharge,
  [ValidateRange(20,45)][int]$HardStopMinutes = 45,
  [ValidateRange(3,15)][int]$BootWaitMinutes = 12,
  [ValidatePattern('^[A-Za-z0-9_.-]{1,64}$')][string]$AwsProfile,
  [string]$EvidenceDir = (Join-Path ([System.IO.Path]::GetTempPath()) 'strokesense-gpu-smoke')
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'gpu-smoke-profile.ps1')
$hardware = Get-GpuSmokeProfile -InstanceType $ExpectedInstanceType
$region = 'us-east-1'
$runId = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8)
$startedBy = "ss-gpu-$runId"
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
$volumeInstancesChecked = New-Object 'System.Collections.Generic.HashSet[string]'
$failure = $null
$cleanupErrors = @()
$launchRequested = $false
$expectedModelSha256 = '93e2866b0ce678f99b4dd88af0c12e9ea2edf079a361dc2ecbc6226b77ff6408'
$evidence = [ordered]@{ run_id = $runId; region = $region; timings_utc = [ordered]@{}
  expected_instance_type = $hardware.InstanceType; expected_gpu_resource = $hardware.GpuResource
  minimum_gpu_memory_mib = $hardware.MinGpuMemoryMiB }
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
  # Windows PowerShell 5.1 turns redirected native stderr into ErrorRecords.
  # Capture those without losing the actual CLI exit code or cleanup path.
  $previousPreference = $ErrorActionPreference
  try {
    $ErrorActionPreference = 'Continue'
    $raw = & aws @Arguments @profileArgs --region $region --no-cli-pager --cli-connect-timeout 10 --cli-read-timeout 30 2>&1
    $nativeExit = $LASTEXITCODE
  } finally { $ErrorActionPreference = $previousPreference }
  if ($nativeExit -ne 0) {
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

function Test-ScalingActivitiesTerminal($Response) {
  # Keep CLI pagination enabled. A partial or unidentified history cannot
  # establish that an earlier launch has finished becoming visible.
  if (!$Response -or !$Response.PSObject.Properties['Activities'] -or
      $Response.Activities -isnot [array] -or (Get-Prop $Response 'NextToken')) {
    throw 'Complete ASG scaling activity history could not be verified.'
  }
  $terminal = $true
  foreach ($activity in $Response.Activities) {
    if ((Get-Prop $activity 'AutoScalingGroupName') -cne $asgName) {
      throw 'ASG scaling activity does not identify the reviewed group.'
    }
    if ((Get-Prop $activity 'StatusCode') -cnotin @('Successful','Failed','Cancelled')) { $terminal = $false }
  }
  return $terminal
}

function Read-PreflightEvidence([string]$Stream) {
  # CloudWatch delivery can lag ECS STOPPED. Read a bounded number of times;
  # absent or malformed evidence is a failed verification, never a pass.
  for ($attempt = 0; $attempt -lt 4; $attempt++) {
    try {
      $events = Invoke-AwsJson @('logs','get-log-events','--log-group-name',$logGroup,'--log-stream-name',$Stream,'--start-from-head')
      $lines = @(@($events.events) | ForEach-Object { $_.message } | Where-Object { $_ -match '^STROKESENSE_GPU_PREFLIGHT ' })
      if ($lines.Count -gt 1) { throw 'Multiple preflight evidence records found in one task stream.' }
      if ($lines.Count -eq 1) {
        $result = $lines[0].Substring('STROKESENSE_GPU_PREFLIGHT '.Length) | ConvertFrom-Json
        foreach ($flag in @('model_loaded','cpu_ep_fallback_disabled','outputs_finite')) {
          $value = Get-Prop $result $flag
          if ($value -isnot [bool] -or !$value) { throw "Preflight evidence did not confirm $flag." }
        }
        $providers = @(Get-Prop $result 'active_providers')
        if ((Get-Prop $result 'provider') -ne 'CUDAExecutionProvider' -or
            $providers.Count -eq 0 -or $providers[0] -ne 'CUDAExecutionProvider' -or
            (Get-Prop $result 'model_sha256_verified') -ne $expectedModelSha256 -or
            (Get-Prop $result 'warmup_runs') -ne 3 -or (Get-Prop $result 'inference_runs') -ne 20 -or
            (Get-Count (Get-Prop $result 'output_shapes')) -eq 0) {
          throw 'Preflight evidence does not match the pinned model and 23 CUDA inference runs.'
        }
        foreach ($metric in @('latency_ms_p50','latency_ms_p95','latency_ms_max','gpu_memory_total_mib','gpu_memory_used_after_inference_mib')) {
          $value = Get-Prop $result $metric
          if ($null -eq $value -or $value -is [string] -or $value -is [bool] -or
              [double]::IsNaN([double]$value) -or [double]::IsInfinity([double]$value) -or [double]$value -lt 0) {
            throw "Invalid preflight evidence metric $metric."
          }
        }
        if ([double]$result.gpu_memory_total_mib -lt $hardware.MinGpuMemoryMiB) {
          throw "Preflight reported less than the expected GPU memory ($($hardware.MinGpuMemoryMiB) MiB for $($hardware.InstanceType))."
        }
        $evidence.log_lines = $lines
        $evidence.preflight = $result
        return $result
      }
    } catch {
      if ($attempt -eq 3) { throw }
      $evidence.log_read_error = $_.Exception.Message
    }
    if ($attempt -lt 3) { Start-Sleep -Seconds 3 }
  }
  throw 'No machine-readable CUDA inference evidence arrived in the task log stream.'
}

if (!$ApproveCharge) { throw 'Explicit -ApproveCharge required after reviewing real AWS GPU charges.' }
if (!(Get-Command aws -ErrorAction SilentlyContinue) -or !(Get-Command terraform -ErrorAction SilentlyContinue)) {
  throw 'Install/configure AWS CLI v2 and Terraform before running a GPU smoke.'
}

try {
  # ---------- identity, ownership and idle-state checks (no mutation) ----------
  $identity = Invoke-AwsJson @('sts','get-caller-identity')
  if ($identity.Account -ne $ExpectedAccountId) { throw 'Wrong AWS account; no GPU resources changed.' }
  $registryPrefix = "$ExpectedAccountId.dkr.ecr.us-east-1.amazonaws.com/"
  if (!$ExpectedImageUri.StartsWith($registryPrefix)) { throw 'The image must belong to the expected AWS account.' }
  $imageParts = $ExpectedImageUri.Substring($registryPrefix.Length).Split('@')
  $published = (Invoke-AwsJson @('ecr','describe-images','--repository-name',$imageParts[0],'--image-ids',"imageDigest=$($imageParts[1])")).imageDetails
  if ((Get-Count $published) -ne 1 -or $published[0].imageDigest -ne $imageParts[1]) { throw 'Approved image digest is not published in ECR.' }

  $asgName = Get-TerraformOutput 'gpu_smoke_asg_name'
  $cluster = Get-TerraformOutput 'gpu_smoke_ecs_cluster'
  $provider = Get-TerraformOutput 'gpu_smoke_capacity_provider'
  $taskDefinition = Get-TerraformOutput 'gpu_smoke_task_definition'
  $subnet = Get-TerraformOutput 'gpu_smoke_subnet_id'
  $sg = Get-TerraformOutput 'gpu_smoke_task_security_group'
  $logGroup = Get-TerraformOutput 'gpu_smoke_log_group'
  $expectedAmi = Get-TerraformOutput 'gpu_smoke_ami_id'
  $templateId = Get-TerraformOutput 'gpu_smoke_launch_template_id'
  $templateVersion = Get-TerraformOutput 'gpu_smoke_launch_template_version'
  $acct = [regex]::Escape($ExpectedAccountId)
  if ($asgName -notmatch '^strokesense-[a-z0-9-]+-gpu-one-instance$' -or
      $cluster -notmatch "^arn:aws:ecs:us-east-1:${acct}:cluster/strokesense-[a-z0-9-]+-gpu" -or
      $taskDefinition -notmatch "^arn:aws:ecs:us-east-1:${acct}:task-definition/strokesense-[a-z0-9-]+-gpu-preflight:\d+$" -or
      $provider -notmatch '^strokesense-[a-z0-9-]+-gpu-asg$' -or
      $subnet -notmatch '^subnet-[0-9a-f]{8,17}$' -or $sg -notmatch '^sg-[0-9a-f]{8,17}$' -or
      $logGroup -notmatch '^/ecs/strokesense-[a-z0-9-]+/paid-gpu$' -or
      $expectedAmi -notmatch '^ami-[0-9a-f]{8,17}$' -or $templateId -notmatch '^lt-[0-9a-f]{8,17}$' -or
      $templateVersion -notmatch '^[1-9][0-9]*$') {
    throw 'Terraform outputs are not the isolated StrokeSense us-east-1 GPU smoke resources.'
  }
  $evidence.cluster = $cluster; $evidence.asg = $asgName; $evidence.capacity_provider = $provider
  $evidence.task_definition = $taskDefinition; $evidence.log_group = $logGroup
  $evidence.expected_ami = $expectedAmi
  $evidence.launch_template = [ordered]@{ id = $templateId; version = $templateVersion }

  $quota = Invoke-AwsJson @('service-quotas','get-service-quota','--service-code','ec2','--quota-code','L-DB2E81BA')
  $liveG = Invoke-AwsJson @('ec2','describe-instances','--filters','Name=instance-type,Values=g*,vt*',
    'Name=instance-state-name,Values=pending,running,stopping','--query','Reservations[].Instances[].InstanceId')
  if ([double]$quota.Quota.Value -lt $hardware.Vcpus -or (Get-Count $liveG) -ne 0) {
    throw "Applied G/VT quota ($($quota.Quota.Value)) < $($hardware.Vcpus) or other G/VT instances are running; not launching."
  }

  $group = (Invoke-AwsJson @('autoscaling','describe-auto-scaling-groups','--auto-scaling-group-names',$asgName)).AutoScalingGroups
  if (@($group).Count -ne 1) { throw 'Expected exactly one smoke ASG.' }
  $group = $group[0]
  if ((Get-Prop $group 'VPCZoneIdentifier') -cne $subnet) {
    throw 'ASG must use exactly the one reviewed Terraform smoke subnet.'
  }
  $groupTemplate = Get-Prop $group 'LaunchTemplate'
  if (!$groupTemplate -or $groupTemplate.LaunchTemplateId -ne $templateId -or
      [string]$groupTemplate.Version -ne $templateVersion -or (Get-Prop $group 'NewInstancesProtectedFromScaleIn') -eq $true) {
    throw 'ASG does not use the reviewed numeric launch-template version, or new instances are protected from shutdown.'
  }
  $versions = (Invoke-AwsJson @('ec2','describe-launch-template-versions','--launch-template-id',$templateId,'--versions',$templateVersion)).LaunchTemplateVersions
  if ((Get-Count $versions) -ne 1) { throw 'Reviewed launch-template version is missing.' }
  $hostConfig = $versions[0].LaunchTemplateData
  $userData = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($hostConfig.UserData))
  if ($hostConfig.ImageId -ne $expectedAmi -or $hostConfig.InstanceType -cne $hardware.InstanceType -or
      $hostConfig.MetadataOptions.HttpTokens -ne 'required' -or
      $userData -notmatch 'ECS_ENABLE_GPU_SUPPORT=true' -or $userData -notmatch 'ECS_AWSVPC_BLOCK_IMDS=true') {
    throw "Launch template does not match the reviewed $($hardware.InstanceType) type, AMI, GPU support, and metadata isolation."
  }
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
  # Do not reuse an idle-looking group while a previous scaling operation is
  # unresolved. Leave CLI pagination enabled so later activity pages are read.
  $activities = Invoke-AwsJson @('autoscaling','describe-scaling-activities','--auto-scaling-group-name',$asgName)
  if (!(Test-ScalingActivitiesTerminal $activities)) {
    throw 'A previous ASG scaling operation is still in progress or could not be verified; not launching.'
  }
  $existingActions = Invoke-AwsJson @('autoscaling','describe-scheduled-actions','--auto-scaling-group-name',$asgName)
  foreach ($action in @($existingActions.ScheduledUpdateGroupActions)) {
    if ($action.ScheduledActionName -cne $scheduledName -or
        $action.AutoScalingGroupName -cne $asgName -or
        $action.MinSize -ne 0 -or $action.MaxSize -ne 0 -or $action.DesiredCapacity -ne 0 -or
        (Get-Prop $action 'Recurrence')) {
      throw 'Existing smoke shutdown action must be the single nonrecurring zero-capacity cutoff on the reviewed ASG.'
    }
  }
  if (@($existingActions.ScheduledUpdateGroupActions).Count -gt 1) {
    throw 'More than one scheduled action was returned for the smoke ASG.'
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
  # A task whose desired status is STOPPED can still be stopping. Historical
  # completed tasks are fine; every task still returned must actually be done.
  $prior = Invoke-AwsJson @('ecs','list-tasks','--cluster',$cluster,'--desired-status','STOPPED')
  if (!$prior.PSObject.Properties['taskArns'] -or $prior.taskArns -isnot [array] -or (Get-Prop $prior 'nextToken')) {
    throw 'Complete previous ECS task state could not be verified.'
  }
  $priorArns = @($prior.taskArns)
  for ($offset = 0; $offset -lt $priorArns.Count; $offset += 100) {
    $batch = @($priorArns | Select-Object -Skip $offset -First 100)
    $details = Invoke-AwsJson (@('ecs','describe-tasks','--cluster',$cluster,'--tasks') + $batch)
    $oldTasks = @(Get-Prop $details 'tasks')
    if ((Get-Count (Get-Prop $details 'failures')) -ne 0 -or $oldTasks.Count -ne $batch.Count -or
        @($oldTasks | Where-Object { (Get-Prop $_ 'lastStatus') -cne 'STOPPED' }).Count -ne 0 -or
        (Compare-Object $batch @($oldTasks | ForEach-Object { $_.taskArn }))) {
      throw 'A previous ECS task is still stopping or its completed state could not be verified.'
    }
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
      $gpuReq.Count -ne 1 -or $gpuReq[0].value -cne $hardware.GpuResource -or
      (Get-Prop $c0 'privileged') -eq $true -or (Get-Count (Get-Prop $c0 'mountPoints')) -ne 0 -or
      (Get-Count (Get-Prop $def 'volumes')) -ne 0 -or (Get-Count (Get-Prop $c0 'secrets')) -ne 0 -or
      (Get-Count (Get-Prop $c0 'environment')) -ne 0) {
    throw "Preflight task definition must be EC2/awsvpc, the exact approved image digest and command, $($hardware.GpuResource) GPU for $($hardware.InstanceType), NO customer task role, and no secrets, env, mounts or privilege."
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
      $actions[0].ScheduledActionName -cne $scheduledName -or (Get-Prop $actions[0] 'Recurrence') -or
      $actions[0].MinSize -ne 0 -or $actions[0].MaxSize -ne 0 -or $actions[0].DesiredCapacity -ne 0 -or
      [Math]::Abs(([datetime]$actions[0].StartTime).ToUniversalTime().Subtract($deadline.ToUniversalTime()).TotalSeconds) -gt 90) {
    throw 'Cloud-side GPU cutoff not confirmed; refusing to start host.'
  }
  $evidence.cloud_cutoff_utc = $cutoffUtc
  Write-Host "AWS GPU shutdown action (min/max/desired 0) confirmed for $cutoffUtc; termination still requires verification."

  # ---------- exactly one host ----------
  $t0 = Get-Date
  if ((Get-Remaining) -lt (($BootWaitMinutes + 8) * 60)) { throw 'Insufficient time remains for host startup and verified cleanup; not launching.' }
  Add-Mark 'scale_out_requested'
  $launchRequested = $true
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
  if ($inst.InstanceType -cne $hardware.InstanceType -or $inst.ImageId -ne $expectedAmi -or
      (Get-Prop $inst 'SubnetId') -cne $subnet) { throw 'Actual instance type, AMI, or subnet differs from the reviewed smoke configuration.' }
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
        if ($gpuRes.Count -eq 0) { throw 'ECS agent registered no GPU resource. Inspect the selected AMI, NVIDIA driver and ECS agent startup logs; not launching the task.' }
        $ready = $true
      }
    }
    if (!$ready) { Start-Sleep -Seconds 10 }
  }
  if (!$ready) { throw 'GPU EC2 host did not register with ECS in time.' }
  # ASG can expose a pending instance before its EBS mapping is populated.
  # Re-read after ECS registration so an empty initial mapping cannot produce
  # a false claim that all test volumes were deleted.
  $booted = (Invoke-AwsJson @('ec2','describe-instances','--instance-ids',$instanceIds[0])).Reservations[0].Instances[0]
  $mappings = @(Get-Prop $booted 'BlockDeviceMappings')
  $rootDevice = Get-Prop $booted 'RootDeviceName'
  $rootVolumes = @($mappings | Where-Object { $_ -and (Get-Prop $_ 'DeviceName') -eq $rootDevice -and (Get-Prop $_ 'Ebs') })
  if (!$rootDevice -or $rootVolumes.Count -ne 1 -or !$rootVolumes[0].Ebs.VolumeId -or
      (Get-Prop $rootVolumes[0].Ebs 'DeleteOnTermination') -ne $true -or
      $booted.InstanceType -cne $hardware.InstanceType -or $booted.ImageId -ne $expectedAmi -or
      (Get-Prop $booted 'SubnetId') -cne $subnet) {
    throw 'The ready host has no verified delete-on-termination root volume or differs from the reviewed instance.'
  }
  $volumeIds = @($mappings | ForEach-Object { $disk = Get-Prop $_ 'Ebs'; if ($disk) { $disk.VolumeId } } | Sort-Object -Unique)
  $evidence.instance.volumes = $volumeIds
  $evidence.instance.root_volume_id = $rootVolumes[0].Ebs.VolumeId
  $evidence.root_volume_identified = $true
  [void]$volumeInstancesChecked.Add($instanceIds[0])
  Add-Mark 'host_registered'

  # ---------- exactly one task (idempotent) ----------
  $clientToken = "ss-gpu-smoke-$runId"
  $evidence.client_token = $clientToken
  $evidence.started_by = $startedBy
  Save-Evidence
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
      if (!$evidence.task.image_digest -or $ExpectedImageUri -notlike "*@$($evidence.task.image_digest)") {
        throw "Task ran image $($evidence.task.image_digest), not the approved digest."
      }
      if ($exit -ne 0) {
        throw "CUDA preflight failed (exit=$exit, stopCode=$($evidence.task.stop_code), reason=$($evidence.task.stopped_reason) / $($evidence.task.container_reason))."
      }
      [void](Read-PreflightEvidence $stream)
      Add-Mark 'inference_evidence_verified'
      Write-Host 'CUDA inference evidence verified; checking host shutdown next.'
      break
    }
    Start-Sleep -Seconds 10
  }
  if (!$taskStopped) { throw 'GPU preflight timed out before the cleanup margin; enforcing shutdown.' }
}
catch {
  $failure = $_.Exception.Message
  $evidence.error = $failure
  Write-Warning $evidence.error
}
finally {
  if ($payloadFile -and (Test-Path $payloadFile)) { Remove-Item -LiteralPath $payloadFile -Force -ErrorAction SilentlyContinue }
  if ($asgVerified) {
    # Insufficient-capacity failures occur before the first host is observed.
    # Lock this path as well, and still attempt scale-to-zero if locking fails.
    try {
      [void](Invoke-Aws -Arguments @('autoscaling','suspend-processes','--auto-scaling-group-name',$asgName,'--scaling-processes','Launch'))
      Add-Mark 'cleanup_launch_suspension_requested'
    } catch {
      $cleanupErrors += "Launch suspension request failed: $($_.Exception.Message)"
      Write-Warning 'Launch suspension failed; still requesting zero capacity and checking the observed lock.'
    }
    # A second lost RunTask response can leave an owned task without a local
    # ARN. The unique startedBy value prevents adopting another operator's run.
    if (!$taskArn -and $evidence.Contains('client_token')) {
      try {
        $owned = @((Invoke-AwsJson @('ecs','list-tasks','--cluster',$cluster,'--started-by',$startedBy)).taskArns)
        foreach ($ownedArn in $owned) {
          [void](Invoke-Aws -Arguments @('ecs','stop-task','--cluster',$cluster,'--task',$ownedArn,'--reason','Smoke response recovery cleanup'))
        }
        if ($owned.Count -eq 1) { $taskArn = $owned[0] }
        if ($owned.Count -gt 1) { $cleanupErrors += 'Multiple tasks were found for the single-attempt client token; inspect their stop states.' }
        $evidence.recovered_task_arns = $owned
      } catch { $cleanupErrors += "Task-response reconciliation failed: $($_.Exception.Message)" }
    }
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
        # Read activity completion before the fresh instance snapshot. A launch
        # that was still pending at this point needs another bounded poll even
        # if the ASG currently looks empty.
        $scalingTerminal = $false
        try {
          $cleanupActivities = Invoke-AwsJson @('autoscaling','describe-scaling-activities','--auto-scaling-group-name',$asgName)
          $scalingTerminal = Test-ScalingActivitiesTerminal $cleanupActivities
        } catch {
          $activityError = "Cleanup scaling activity verification failed: $($_.Exception.Message)"
          if ($cleanupErrors -notcontains $activityError) { $cleanupErrors += $activityError }
          Write-Warning $activityError
        }
        $evidence.scaling_activities_terminal_verified = $scalingTerminal
        $g = (Invoke-AwsJson @('autoscaling','describe-auto-scaling-groups','--auto-scaling-group-names',$asgName)).AutoScalingGroups[0]
        $live = Invoke-AwsJson @('ec2','describe-instances','--filters',"Name=tag:aws:autoscaling:groupName,Values=$asgName",
          'Name=instance-state-name,Values=pending,running,shutting-down,stopping,stopped','--query','Reservations[].Instances[].InstanceId')
        if ($launchRequested) {
          $instanceIds = @(@($instanceIds) + @($g.Instances | ForEach-Object { $_.InstanceId }) + @($live) | Where-Object { $_ } | Sort-Object -Unique)
          $evidence.instance_ids = $instanceIds
          if ($instanceIds.Count -gt 1 -and !$failure) { $failure = 'More than one EC2 instance was observed for this single-attempt smoke.' }
        }
        foreach ($id in $instanceIds) {
          if ($volumeInstancesChecked.Add($id)) {
            try {
              # A launch may appear only after shutdown was requested. Its
              # root disk still needs verification; an empty earlier list
              # must not become a claim that every volume was deleted.
              $lateResponse = Invoke-AwsJson @('ec2','describe-instances','--instance-ids',$id)
              $lateInstances = @($lateResponse.Reservations | ForEach-Object { $_.Instances })
              if ($lateInstances.Count -ne 1 -or $lateInstances[0].InstanceId -cne $id) {
                throw 'Expected exactly the discovered EC2 instance.'
              }
              $late = $lateInstances[0]
              $lateRoot = Get-Prop $late 'RootDeviceName'
              $lateMappings = @(Get-Prop $late 'BlockDeviceMappings')
              $lateRootMappings = @($lateMappings | Where-Object {
                $_ -and (Get-Prop $_ 'DeviceName') -ceq $lateRoot -and (Get-Prop $_ 'Ebs')
              })
              $discoveredVolumes = @($lateMappings | ForEach-Object {
                $disk = Get-Prop $_ 'Ebs'; if ($disk -and (Get-Prop $disk 'VolumeId')) { $disk.VolumeId }
              })
              $volumeIds = @(@($volumeIds) + $discoveredVolumes | Sort-Object -Unique)
              if (!$lateRoot -or $lateRootMappings.Count -ne 1 -or !(Get-Prop $lateRootMappings[0].Ebs 'VolumeId')) {
                throw 'Root volume identity was not returned; deletion cannot be certified.'
              }
            } catch {
              $cleanupErrors += "Root-volume discovery failed for ${id}: $($_.Exception.Message)"
            }
          }
        }
        $evidence.observed_volume_ids = $volumeIds
        $cleanupSuspended = @($g.SuspendedProcesses | ForEach-Object { $_.ProcessName })
        $launchSuspended = $cleanupSuspended -contains 'Launch'
        $evidence.launch_suspended_verified = $launchSuspended
        $mine = $true
        $stateList = @()
        if (@($instanceIds).Count -gt 0) {
          $stateList = @(Invoke-AwsJson (@('ec2','describe-instances','--instance-ids') + $instanceIds + @('--query','Reservations[].Instances[].State.Name')))
          $mine = ($stateList.Count -eq $instanceIds.Count -and @($stateList | Where-Object { $_ -ne 'terminated' }).Count -eq 0)
        }
        if ($taskArn -and !$taskStopped) {
          $remainingTask = (Invoke-AwsJson @('ecs','describe-tasks','--cluster',$cluster,'--tasks',$taskArn)).tasks
          $taskStopped = (Get-Count $remainingTask) -eq 1 -and $remainingTask[0].lastStatus -eq 'STOPPED'
        }
        if ($g.MinSize -eq 0 -and $g.MaxSize -eq 0 -and $g.DesiredCapacity -eq 0 -and (Get-Count $g.Instances) -eq 0 -and (Get-Count $live) -eq 0 -and $mine -and (!$taskArn -or $taskStopped) -and $launchSuspended -and $scalingTerminal) {
          $terminated = $true; break
        }
      } catch { Write-Warning "Termination check failed: $($_.Exception.Message); retrying." }
      Start-Sleep -Seconds 15
    }
    if ($terminated) {
      Add-Mark 'instances_terminated_observed'
      $evidence.terminated_verified = $true
      $evidence.task_stopped_verified = !$taskArn -or $taskStopped
      $evidence.no_instance_observed = ($instanceIds.Count -eq 0)
      if ($instanceIds.Count -eq 0) {
        $evidence.instance_termination_status = 'NO_INSTANCE_OBSERVED'
        Write-Host 'VERIFIED: ASG 0/0/0, Launch suspended, no instance observed and no active tagged EC2 instances.'
      } else {
        $evidence.instance_termination_status = 'TERMINATED'
        Write-Host "VERIFIED: ASG 0/0/0, Launch suspended and instance(s) $($instanceIds -join ',') TERMINATED."
      }
      $remainingVolumes = @()
      foreach ($v in $volumeIds) {
        try {
          # Filters return an empty list for a deleted volume. Permission or
          # network failures must not be mistaken for successful deletion.
          for ($attempt = 0; $attempt -lt 8; $attempt++) {
            $vs = (Invoke-AwsJson @('ec2','describe-volumes','--filters',"Name=volume-id,Values=$v")).Volumes
            if ((Get-Count $vs) -eq 0) { break }
            if ($attempt -lt 7) { Start-Sleep -Seconds 3 }
          }
          if ((Get-Count $vs) -gt 0) { $remainingVolumes += "$v=$($vs[0].State)" }
        } catch { $cleanupErrors += "Volume deletion could not be verified for ${v}: $($_.Exception.Message)" }
      }
      $evidence.remaining_volumes = $remainingVolumes
      if ($remainingVolumes.Count) { $cleanupErrors += "Root volume(s) not deleted: $($remainingVolumes -join ', ')" }
    } else {
      $evidence.terminated_verified = $false
      $cleanupErrors += 'GPU EC2/task termination, terminal scaling activities and Launch suspension NOT verified within 10 minutes; check NOW. AWS cutoff remains scheduled.'
    }
    $evidence.cleanup_errors = $cleanupErrors
    if ($failure) { $evidence.error = $failure }
    Save-Evidence
    Write-Host ('evidence: ' + (Join-Path $EvidenceDir "gpu-smoke-$runId.json"))
  }
}
if ($cleanupErrors.Count -gt 0) {
  $details = $cleanupErrors -join ' | '
  if ($failure) { $details = "$failure | Cleanup: $details" }
  throw $details
}
if ($failure) { throw $failure }
Write-Host 'PASS: verified CUDA inference, stopped task, terminated host and deleted root volume.'
