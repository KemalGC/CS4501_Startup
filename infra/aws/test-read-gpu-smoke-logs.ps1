# Offline tests: every AWS invocation is replaced by an in-memory read fake.
# powershell -NoProfile -File infra/aws/test-read-gpu-smoke-logs.ps1
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Under = Join-Path $PSScriptRoot 'read-gpu-smoke-logs.ps1'
$testDir = Join-Path ([System.IO.Path]::GetTempPath()) ('strokesense-log-reader-test-' + [guid]::NewGuid().ToString('N'))
[void](New-Item -ItemType Directory -Path $testDir)
$account = '851226124502'
$instanceId = 'i-0dc5562bfd9372cf4'
$taskId = 'a' * 32
$failures = 0
$checks = 0
$previousPythonEncoding = [System.Environment]::GetEnvironmentVariable('PYTHONIOENCODING', 'Process')
$previousConsoleEncoding = [Console]::OutputEncoding

function New-Record {
  return @{ region = 'us-east-1'; instance_ids = @($instanceId); instance = @{ id = $instanceId }
    cluster = "arn:aws:ecs:us-east-1:${account}:cluster/strokesense-aws-dev-paid-gpu"
    task_arn = "arn:aws:ecs:us-east-1:${account}:task/strokesense-aws-dev-paid-gpu/$taskId"
    log_group = '/ecs/strokesense-aws-dev/paid-gpu'; log_stream = "gpu-preflight/gpu-preflight/$taskId"
    terminated_verified = $false; task = @{ exit_code = 2 } }
}
function New-Page([string[]]$Messages, [string]$Token) {
  return @{ events = @($Messages | ForEach-Object { @{ message = $_ } }); nextForwardToken = $Token }
}
function New-World {
  $global:LogWorld = @{ calls = @(); account = $account; failRead = $false; page = 0
    pages = @((New-Page @('first') 't1'), (New-Page @() 't1')) }
}
function Get-Argument([object[]]$Arguments, [string]$Name) {
  $position = [array]::IndexOf($Arguments, $Name)
  if ($position -ge 0) { return $Arguments[$position + 1] }
  return $null
}
function global:aws {
  $arguments = @($args)
  $LogWorld.calls += ,$arguments
  $global:LASTEXITCODE = 0
  $operation = $arguments[0..1] -join ' '
  if ($operation -eq 'sts get-caller-identity') { return (@{ Account = $LogWorld.account } | ConvertTo-Json) }
  if ($operation -ne 'logs get-log-events') { throw "Unexpected AWS operation: $operation" }
  if ($LogWorld.failRead) { $global:LASTEXITCODE = 255; return 'Connection closed by endpoint' }
  if ($LogWorld.page -ge $LogWorld.pages.Count) { throw 'Unexpected extra log page read' }
  $response = $LogWorld.pages[$LogWorld.page]
  $LogWorld.page++
  return ($response | ConvertTo-Json -Depth 8)
}
function Write-Record($Record, [string]$Name = 'gpu-smoke-current.json') {
  $path = Join-Path $testDir $Name
  [System.IO.File]::WriteAllText($path, ($Record | ConvertTo-Json -Depth 8))
  return $path
}
function Assert-True([bool]$Condition, [string]$Message) {
  if (!$Condition) { throw $Message }
}
function Run-Reader([hashtable]$Extra = @{}) {
  $parameters = @{ ExpectedAccountId = $account; AwsProfile = 'strokesense-admin'; EvidencePath = $script:evidencePath }
  foreach ($key in $Extra.Keys) { $parameters[$key] = $Extra[$key] }
  return (& $Under @parameters 6>$null)
}
function Expect-Rejection([string]$Pattern, [hashtable]$Extra = @{}) {
  try { [void](Run-Reader $Extra) } catch {
    if ($_.Exception.Message -notmatch $Pattern) { throw "Wrong rejection: $($_.Exception.Message)" }
    return
  }
  throw 'Expected rejection, but helper returned successfully.'
}
function Case([string]$Name, [scriptblock]$Body) {
  $script:checks++
  New-World
  $script:record = New-Record
  $script:evidencePath = Write-Record $script:record
  try { & $Body; Write-Host "PASS: $Name" }
  catch { $script:failures++; Write-Host "FAIL: $Name -- $($_.Exception.Message)" }
}

try {
  Case 'native messages retained and source evidence untouched' {
    $native = ([char]27) + '[1;31m2026-11-23 [E:onnxruntime:] library load failed' + ([char]27) + '[0m'
    $unicode = 'diagnostic ' + [char]0x03bb
    $LogWorld.pages = @((New-Page @($native, '******** EP Error ********', $unicode) 't1'), (New-Page @() 't1'))
    $before = [System.IO.File]::ReadAllBytes($evidencePath)
    $result = Run-Reader
    Assert-True ($result.Complete -and $result.EventCount -eq 3 -and $result.PageCount -eq 2) 'Wrong completion counts.'
    $saved = [System.IO.File]::ReadAllText($result.LogPath)
    Assert-True ($saved.Contains($native) -and $saved.Contains('******** EP Error ********') -and $saved.Contains($unicode)) 'Native or Unicode log text lost.'
    $snapshot = [System.IO.File]::ReadAllText($result.EventsPath) | ConvertFrom-Json
    Assert-True ($snapshot.complete -and $snapshot.events[0].message -ceq $native -and $snapshot.event_count -eq 3) 'Event JSON did not retain the complete original messages.'
    Assert-True ([Convert]::ToBase64String($before) -ceq [Convert]::ToBase64String([System.IO.File]::ReadAllBytes($evidencePath))) 'Original evidence changed.'
  }
  Case 'empty intermediate pages continue until the token stops' {
    $LogWorld.pages = @((New-Page @() 't1'), (New-Page @('middle') 't2'), (New-Page @() 't3'), (New-Page @('last') 't4'), (New-Page @() 't4'))
    $result = Run-Reader
    Assert-True ($result.EventCount -eq 2 -and $result.PageCount -eq 5) 'Empty pages ended the read early.'
    $reads = @($LogWorld.calls | Where-Object { $_[0] -eq 'logs' })
    Assert-True ((Get-Argument $reads[1] '--next-token') -ceq 't1') 'Forward token was not reused.'
    foreach ($call in $reads) {
      Assert-True ($call -contains '--start-from-head') 'Forward pagination omitted start-from-head.'
      Assert-True ((Get-Argument $call '--end-time') -ceq "$($result.SnapshotEndTimeMilliseconds)") 'Pages did not use one fixed end time.'
    }
  }
  Case 'empty complete snapshot can be read again without overwriting it' {
    $LogWorld.pages = @((New-Page @() 't1'), (New-Page @() 't1'))
    $first = Run-Reader
    Assert-True ($first.Complete -and $first.EventCount -eq 0) 'Empty stream did not complete at stable token.'
    $LogWorld.page = 0
    $LogWorld.pages = @((New-Page @('late delivery') 't1'), (New-Page @() 't1'))
    $second = Run-Reader
    Assert-True ($second.EventCount -eq 1 -and $first.LogPath -cne $second.LogPath) 'Re-read overwrote the prior snapshot or missed delayed output.'
    Assert-True ([System.IO.File]::ReadAllText($first.LogPath).Length -eq 0) 'First empty snapshot changed.'
  }
  Case 'exact instance selection skips newer unrelated evidence' {
    $unrelated = New-Record
    $unrelated.instance_ids = @('i-0123456789abcdef0'); $unrelated.instance.id = 'i-0123456789abcdef0'
    [void](Write-Record $unrelated 'gpu-smoke-unrelated.json')
    $result = Run-Reader @{ EvidencePath = ''; EvidenceDir = $testDir; ExpectedInstanceId = $instanceId }
    Assert-True ($result.EvidencePath -ceq $evidencePath) 'Selected unrelated evidence.'
  }
  Case 'unscoped latest-run lookup rejected' { Expect-Rejection 'Supply -EvidencePath or -ExpectedInstanceId' @{ EvidencePath = ''; EvidenceDir = $testDir } }
  Case 'missing instance evidence rejected' { Expect-Rejection 'No saved GPU smoke evidence' @{ EvidencePath = ''; EvidenceDir = $testDir; ExpectedInstanceId = 'i-09999999999999999' } }
  Case 'wrong instance rejected before AWS' {
    Expect-Rejection 'expected EC2 instance' @{ ExpectedInstanceId = 'i-09999999999999999' }
    Assert-True ($LogWorld.calls.Count -eq 0) 'Wrong instance reached AWS.'
  }
  Case 'wrong task account rejected before AWS' {
    $record.task_arn = $record.task_arn.Replace($account, '123456789012'); $script:evidencePath = Write-Record $record
    Expect-Rejection 'expected account and region'
    Assert-True ($LogWorld.calls.Count -eq 0) 'Foreign task reached AWS.'
  }
  Case 'wrong task log stream rejected before AWS' {
    $record.log_stream = 'gpu-preflight/gpu-preflight/' + ('b' * 32); $script:evidencePath = Write-Record $record
    Expect-Rejection 'matching GPU preflight'
    Assert-True ($LogWorld.calls.Count -eq 0) 'Mismatched log stream reached AWS.'
  }
  Case 'wrong task cluster rejected' {
    $record.cluster += '-other'; $script:evidencePath = Write-Record $record
    Expect-Rejection 'cluster and task ARN'
  }
  Case 'wrong region rejected' {
    $record.region = 'us-west-2'; $script:evidencePath = Write-Record $record
    Expect-Rejection 'expected us-east-1'
  }
  Case 'wrong active account rejected before log read' {
    $LogWorld.account = '123456789012'; Expect-Rejection 'wrong account'
    Assert-True ($LogWorld.page -eq 0) 'Wrong account read a log stream.'
  }
  Case 'AWS read failure reports incomplete retrieval' {
    $LogWorld.failRead = $true; Expect-Rejection 'Log retrieval incomplete.*exit 255'
  }
  Case 'missing forward token cannot report complete' {
    $LogWorld.pages = @(@{ events = @(@{ message = 'partial' }) })
    Expect-Rejection 'Log retrieval incomplete.*no forward token'
  }
  Case 'malformed events cannot report complete' {
    $LogWorld.pages = @(@{ events = $null; nextForwardToken = 't1' })
    Expect-Rejection 'events array'
  }
  Case 'page cap explicitly reports partial output' {
    $LogWorld.pages = @((New-Page @('partial') 't1'))
    $before = @(Get-ChildItem -LiteralPath $testDir -Filter '*.log' | ForEach-Object { $_.FullName })
    Expect-Rejection 'Log retrieval incomplete.*1-page limit' @{ MaxPages = 1 }
    $newLogs = @(Get-ChildItem -LiteralPath $testDir -Filter '*.log' | Where-Object { $before -cnotcontains $_.FullName })
    Assert-True ($newLogs.Count -eq 1 -and [System.IO.File]::ReadAllText($newLogs[0].FullName).Contains('partial')) 'Partial output was not retained.'
    $snapshot = [System.IO.File]::ReadAllText([System.IO.Path]::ChangeExtension($newLogs[0].FullName, '.events.json')) | ConvertFrom-Json
    Assert-True (!$snapshot.complete -and $snapshot.event_count -eq 1) 'Partial JSON claimed completion.'
  }
  Case 'encoding restored on success and error; only read APIs called' {
    $env:PYTHONIOENCODING = 'ascii'
    [void](Run-Reader)
    Assert-True ($env:PYTHONIOENCODING -ceq 'ascii') 'Successful read changed Python encoding permanently.'
    $LogWorld.failRead = $true
    Expect-Rejection 'Log retrieval incomplete'
    Assert-True ($env:PYTHONIOENCODING -ceq 'ascii') 'Failed read changed Python encoding permanently.'
    Assert-True ([Console]::OutputEncoding.CodePage -eq $previousConsoleEncoding.CodePage) 'Console encoding was not restored.'
    foreach ($call in $LogWorld.calls) {
      Assert-True (($call[0..1] -join ' ') -cin @('sts get-caller-identity','logs get-log-events')) 'Helper invoked an AWS write.'
      Assert-True ((Get-Argument $call '--profile') -ceq 'strokesense-admin') 'Expected profile missing.'
      Assert-True ((Get-Argument $call '--region') -ceq 'us-east-1') 'Expected region missing.'
    }
  }
} finally {
  Remove-Item Function:\aws -ErrorAction SilentlyContinue
  Remove-Variable LogWorld -Scope Global -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $testDir -Recurse -Force
  [Console]::OutputEncoding = $previousConsoleEncoding
  if ($null -eq $previousPythonEncoding) { Remove-Item Env:PYTHONIOENCODING -ErrorAction SilentlyContinue }
  else { $env:PYTHONIOENCODING = $previousPythonEncoding }
}
if ($failures) { throw "$failures of $checks log-reader cases failed." }
Write-Host "All $checks log-reader cases passed."
