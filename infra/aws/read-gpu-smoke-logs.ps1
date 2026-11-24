# Read the complete CloudWatch stream for an existing GPU smoke attempt.
# This helper never launches a task, changes AWS resources, or changes evidence.
[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][ValidatePattern('^\d{12}$')][string]$ExpectedAccountId,
  [Parameter(Mandatory=$true)][ValidatePattern('^[A-Za-z0-9_.-]{1,64}$')][string]$AwsProfile,
  [string]$EvidencePath,
  [ValidatePattern('^i-[0-9a-f]{8,17}$')][string]$ExpectedInstanceId,
  [string]$EvidenceDir = (Join-Path ([System.IO.Path]::GetTempPath()) 'strokesense-gpu-smoke'),
  [ValidateRange(1,100)][int]$MaxPages = 40
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$region = 'us-east-1'

function Get-LogProperty($Object, [string]$Name) {
  if ($null -ne $Object -and $Object.PSObject.Properties[$Name]) { return $Object.$Name }
  return $null
}
function Test-LogInstance($Record, [string]$Id) {
  return (@(Get-LogProperty $Record 'instance_ids') -ccontains $Id -or
    (Get-LogProperty (Get-LogProperty $Record 'instance') 'id') -ceq $Id)
}
function Invoke-LogAwsJson([string[]]$Arguments) {
  # Windows PowerShell 5.1 wraps redirected native stderr in ErrorRecords.
  $previousPreference = $ErrorActionPreference
  try {
    $ErrorActionPreference = 'Continue'
    $raw = & aws @Arguments --profile $AwsProfile --region $region --output json --no-cli-pager --no-paginate --cli-connect-timeout 10 --cli-read-timeout 30 2>&1
    $nativeExit = $LASTEXITCODE
  } finally { $ErrorActionPreference = $previousPreference }
  $text = (@($raw) | ForEach-Object { $_.ToString() }) -join "`n"
  if ($nativeExit -ne 0) {
    $detail = ($text -replace '\s+', ' ').Trim()
    if ($detail.Length -gt 500) { $detail = $detail.Substring(0,500) }
    throw "AWS $($Arguments[0]) $($Arguments[1]) failed (exit ${nativeExit}): $detail"
  }
  try { return ($text | ConvertFrom-Json) }
  catch { throw "AWS $($Arguments[0]) $($Arguments[1]) returned invalid JSON." }
}

if (!$EvidencePath) {
  if (!$ExpectedInstanceId) { throw 'Supply -EvidencePath or -ExpectedInstanceId; an unrelated latest run will not be selected.' }
  $candidates = @()
  foreach ($file in @(Get-ChildItem -LiteralPath $EvidenceDir -Filter 'gpu-smoke-*.json' -File)) {
    try { $record = [System.IO.File]::ReadAllText($file.FullName) | ConvertFrom-Json }
    catch { continue } # A different smoke may still be writing its evidence.
    if (Test-LogInstance $record $ExpectedInstanceId) { $candidates += $file }
  }
  if ($candidates.Count -eq 0) { throw "No saved GPU smoke evidence identifies $ExpectedInstanceId in $EvidenceDir. Supply its printed -EvidencePath." }
  $EvidencePath = ($candidates | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1).FullName
}
$EvidencePath = (Get-Item -LiteralPath $EvidencePath).FullName
$evidence = [System.IO.File]::ReadAllText($EvidencePath) | ConvertFrom-Json
if ($ExpectedInstanceId -and !(Test-LogInstance $evidence $ExpectedInstanceId)) {
  throw 'The selected evidence does not identify the expected EC2 instance.'
}
if ((Get-LogProperty $evidence 'region') -cne $region) { throw 'Evidence is not from the expected us-east-1 region.' }
$taskArn = Get-LogProperty $evidence 'task_arn'
if ($taskArn -isnot [string] -or $taskArn -cnotmatch "^arn:aws:ecs:${region}:${ExpectedAccountId}:task/([A-Za-z0-9_-]+)/([a-f0-9]{32})$") {
  throw 'Evidence must identify an ECS task in the expected account and region.'
}
$clusterName = $Matches[1]
$taskId = $Matches[2]
if ((Get-LogProperty $evidence 'cluster') -cne "arn:aws:ecs:${region}:${ExpectedAccountId}:cluster/$clusterName") {
  throw 'The evidence cluster and task ARN do not match.'
}
$logGroup = Get-LogProperty $evidence 'log_group'
$logStream = Get-LogProperty $evidence 'log_stream'
if ($logGroup -isnot [string] -or $logGroup -cnotmatch '^/ecs/strokesense-[a-z0-9-]+/paid-gpu$' -or
    $logStream -cne "gpu-preflight/gpu-preflight/$taskId") {
  throw 'Evidence does not identify the matching GPU preflight log group and task stream.'
}
if (!(Get-Command aws -ErrorAction SilentlyContinue)) { throw 'AWS CLI v2 is required to read the existing log stream.' }

$previousPythonEncoding = [System.Environment]::GetEnvironmentVariable('PYTHONIOENCODING', 'Process')
$previousConsoleEncoding = [Console]::OutputEncoding
$previousOutputEncoding = $OutputEncoding
$utf8 = New-Object System.Text.UTF8Encoding($false)
$writer = $null
$captureId = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ') + '-' + [guid]::NewGuid().ToString('N').Substring(0,6)
$logName = [System.IO.Path]::GetFileNameWithoutExtension($EvidencePath) + ".cloudwatch-$captureId.log"
$logPath = Join-Path ([System.IO.Path]::GetDirectoryName($EvidencePath)) $logName
$eventsPath = [System.IO.Path]::ChangeExtension($logPath, '.events.json')
$eventRecords = New-Object 'System.Collections.Generic.List[object]'
$snapshotEndTime = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
$logCreated = $false
$eventCount = 0
$pageCount = 0
$complete = $false
try {
  $env:PYTHONIOENCODING = 'utf-8'
  [Console]::OutputEncoding = $utf8
  $OutputEncoding = $utf8
  $identity = Invoke-LogAwsJson @('sts','get-caller-identity')
  if ((Get-LogProperty $identity 'Account') -cne $ExpectedAccountId) { throw 'The AWS profile resolves to the wrong account.' }
  $writer = New-Object System.IO.StreamWriter($logPath, $false, $utf8)
  $logCreated = $true
  Write-Host "Reading existing task: $taskArn"
  Write-Host "Evidence: $EvidencePath"
  $token = $null
  for ($pageCount = 1; $pageCount -le $MaxPages; $pageCount++) {
    $arguments = @('logs','get-log-events','--log-group-name',$logGroup,'--log-stream-name',$logStream,'--start-from-head','--end-time',"$snapshotEndTime")
    if ($token) { $arguments += @('--next-token',$token) }
    $response = Invoke-LogAwsJson $arguments
    $eventProperty = $response.PSObject.Properties['events']
    if ($null -eq $eventProperty -or $eventProperty.Value -isnot [array]) { throw 'CloudWatch response is missing its events array.' }
    $events = $eventProperty.Value
    foreach ($event in @($events)) {
      if ($null -eq $event) { continue }
      $message = Get-LogProperty $event 'message'
      if ($message -isnot [string]) { throw 'CloudWatch returned a log event without a string message.' }
      $writer.WriteLine($message)
      $eventRecords.Add($event)
      # Keep native timestamps and ANSI bytes in the saved file. Only remove
      # terminal colour sequences from the console display, never whole lines.
      Write-Host ([regex]::Replace($message, '\x1B\[[0-?]*[ -/]*[@-~]', ''))
      $eventCount++
    }
    $writer.Flush()
    $nextToken = Get-LogProperty $response 'nextForwardToken'
    if ($nextToken -isnot [string] -or !$nextToken) { throw 'CloudWatch returned no forward token; completeness cannot be established.' }
    if ($token -and $nextToken -ceq $token) { $complete = $true; break }
    $token = $nextToken # Empty pages can still advance, so continue reading.
  }
  if (!$complete) { throw "Reached the $MaxPages-page limit before the end of the stream. Increase -MaxPages only after inspecting the partial log." }
} catch {
  if ($logCreated) { throw "Log retrieval incomplete; $logPath contains only the pages retrieved so far. $($_.Exception.Message)" }
  throw
} finally {
  try {
    if ($null -ne $writer) { $writer.Dispose() }
    if ($logCreated) {
      $snapshot = [ordered]@{ complete = $complete; end_time_milliseconds = $snapshotEndTime;
        task_arn = $taskArn; log_group = $logGroup; log_stream = $logStream;
        event_count = $eventCount; events = @($eventRecords.ToArray()) }
      [System.IO.File]::WriteAllText($eventsPath, ($snapshot | ConvertTo-Json -Depth 8), $utf8)
    }
  } finally {
    [Console]::OutputEncoding = $previousConsoleEncoding
    $OutputEncoding = $previousOutputEncoding
    if ($null -eq $previousPythonEncoding) { Remove-Item Env:PYTHONIOENCODING -ErrorAction SilentlyContinue }
    else { $env:PYTHONIOENCODING = $previousPythonEncoding }
  }
}
Write-Host "Complete log snapshot saved: $logPath"
if ($eventCount -eq 0) { Write-Host 'No events were available in this snapshot. You can re-read after CloudWatch delivery catches up.' }
[pscustomobject]@{ Complete = $complete; EventCount = $eventCount; PageCount = $pageCount;
  EvidencePath = $EvidencePath; LogPath = $logPath; EventsPath = $eventsPath;
  SnapshotEndTimeMilliseconds = $snapshotEndTime; TaskArn = $taskArn }
