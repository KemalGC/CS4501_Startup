# Offline behaviour tests. The in-memory aws fake never accesses AWS.
# powershell -NoProfile -File infra/aws/test-prepare-gpu-smoke.ps1
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:Under = Join-Path $PSScriptRoot 'prepare-gpu-smoke.ps1'
$script:Digest = 'sha256:' + ('a' * 64)
$script:ExpectedUri = '851226124502.dkr.ecr.us-east-1.amazonaws.com/strokesense-aws-dev-gpu-worker@' + $script:Digest
$script:failures = 0

function New-ReadinessWorld([string]$Scenario) {
  $global:ReadinessWorld = @{
    Scenario = $Scenario; Calls = New-Object System.Collections.ArrayList
    RequestCalls = 0; QuotaReads = 0
  }
}
function Get-FakeRequest([string]$Status, [int]$Desired = 4) {
  return @{ Id = 'request-123'; Status = $Status; DesiredValue = $Desired
    ServiceCode = 'ec2'; QuotaCode = 'L-DB2E81BA'; CaseId = 'case-123'; Created = '2026-11-22T00:00:00Z' }
}
function global:aws {
  $a = @($args | ForEach-Object { "$_" })
  $op = $a[0] + ' ' + $a[1]
  [void]$ReadinessWorld.Calls.Add(($a -join ' '))
  $global:LASTEXITCODE = 0
  $scenario = $ReadinessWorld.Scenario
  switch ($op) {
    'sts get-caller-identity' {
      if ($scenario -eq 'wrong-account') { return '{"Account":"111111111111"}' }
      if ($scenario -eq 'native-error') { $global:LASTEXITCODE = 254; return 'An error occurred (ExpiredToken) when calling GetCallerIdentity' }
      return '{"Account":"851226124502"}'
    }
    'ecr describe-images' {
      if ($scenario -eq 'missing-image') { $global:LASTEXITCODE = 254; return 'ImageNotFoundException' }
      if ($scenario -eq 'invalid-json') { return 'not JSON' }
      if ($scenario -eq 'null-json') { return 'null' }
      $digest = 'sha256:' + ('a' * 64)
      if ($scenario -eq 'invalid-digest') { $digest = 'sha256:123' }
      if ($scenario -eq 'digest-mismatch') { $digest = 'sha256:' + ('b' * 64) }
      $account = '851226124502'; if ($scenario -eq 'image-account') { $account = '111111111111' }
      $tag = 'gpu-smoke-20261120211125'; if ($scenario -eq 'image-tag') { $tag = 'different-tag' }
      return (@{ imageDetails = @(@{ registryId = $account; repositoryName = 'strokesense-aws-dev-gpu-worker'
        imageTags = @($tag); imageDigest = $digest }) } | ConvertTo-Json -Depth 5)
    }
    'service-quotas get-service-quota' {
      $ReadinessWorld.QuotaReads++
      $value = 0
      if ($scenario -eq 'ready' -or ($scenario -eq 'quota-race' -and $ReadinessWorld.QuotaReads -ge 2)) { $value = 4 }
      if ($scenario -eq 'quota-null') { return '{"Quota":{"ServiceCode":"ec2","QuotaCode":"L-DB2E81BA","Value":null}}' }
      return (@{ Quota = @{ ServiceCode = 'ec2'; QuotaCode = 'L-DB2E81BA'; Value = $value; Adjustable = $true } } | ConvertTo-Json)
    }
    'service-quotas list-requested-service-quota-change-history-by-quota' {
      if ($scenario -eq 'history-null') { return '{"RequestedQuotas":null}' }
      if ($scenario -eq 'history-incomplete') { return '{"RequestedQuotas":[],"NextToken":"more"}' }
      $requests = @()
      if ($scenario -eq 'pending') { $requests = @(Get-FakeRequest 'CASE_OPENED') }
      if ($scenario -eq 'pending-different') { $requests = @(Get-FakeRequest 'PENDING' 2) }
      if ($scenario -eq 'approved-not-applied') { $requests = @(Get-FakeRequest 'APPROVED') }
      if ($scenario -eq 'unknown-status') { $requests = @(Get-FakeRequest 'NEW_REVIEW_STATUS') }
      return (@{ RequestedQuotas = @($requests) } | ConvertTo-Json -Depth 5)
    }
    'service-quotas request-service-quota-increase' {
      $ReadinessWorld.RequestCalls++
      $desiredIndex = [array]::IndexOf($a, '--desired-value')
      if ($desiredIndex -lt 0 -or $a[$desiredIndex + 1] -ne '4') { throw 'Helper requested something other than 4 total vCPUs.' }
      if ($scenario -eq 'request-error') { $global:LASTEXITCODE = 255; return 'Read timeout; request outcome unknown' }
      return (@{ RequestedQuota = (Get-FakeRequest 'PENDING') } | ConvertTo-Json -Depth 5)
    }
    default { throw "Unexpected operation in readiness helper: $op" }
  }
}

function Invoke-ReadinessCase([string]$Scenario, [bool]$Request, [bool]$ExpectThrow, [scriptblock]$Check) {
  New-ReadinessWorld $Scenario
  $env:TF_VAR_gpu_worker_image_uri = 'stale-invalid-uri@'
  $env:TF_VAR_enable_cpu_analysis = 'true'
  $beforeEncoding = $env:PYTHONIOENCODING
  $result = $null; $threw = $null
  try {
    $result = & $script:Under -ExpectedAccountId 851226124502 -AwsProfile fake -ExpectedImageDigest $script:Digest -RequestQuotaIncrease:$Request 3>$null 6>$null
  } catch { $threw = $_.Exception.Message }
  $expectedError = (($null -ne $threw) -eq $ExpectThrow)
  $specific = & $Check $result $threw
  $untouched = ($env:TF_VAR_enable_cpu_analysis -eq 'true' -and $env:PYTHONIOENCODING -eq $beforeEncoding)
  $correctTarget = @($ReadinessWorld.Calls | Where-Object { $_ -notlike '*--profile fake --region us-east-1*' }).Count -eq 0
  if ($expectedError -and $specific -and $untouched -and $correctTarget) { Write-Host "PASS $Scenario" }
  else {
    Write-Host "FAIL $Scenario error=[$threw] expected=$expectedError specific=$specific untouched=$untouched target=$correctTarget"
    $script:failures++
  }
}

try {
  Invoke-ReadinessCase 'ready' $true $false { param($r, $e)
    $r.ReadyForPlan -and $r.Status -eq 'READY_TO_PLAN' -and $ReadinessWorld.RequestCalls -eq 0 -and
    $env:TF_VAR_gpu_worker_image_uri -eq $script:ExpectedUri }
  Invoke-ReadinessCase 'request-needed' $false $false { param($r, $e)
    !$r.ReadyForPlan -and $r.Status -eq 'QUOTA_REQUEST_NEEDED' -and $ReadinessWorld.RequestCalls -eq 0 }
  Invoke-ReadinessCase 'request' $true $false { param($r, $e)
    !$r.ReadyForPlan -and $r.QuotaRequestSubmitted -and $r.QuotaRequestId -eq 'request-123' -and
    $r.SupportCaseId -eq 'case-123' -and $ReadinessWorld.RequestCalls -eq 1 }
  foreach ($scenario in @('pending','pending-different','approved-not-applied','unknown-status')) {
    Invoke-ReadinessCase $scenario $true $false { param($r, $e)
      !$r.ReadyForPlan -and $r.Status -eq 'QUOTA_PENDING' -and $r.QuotaRequestId -eq 'request-123' -and
      !$r.QuotaRequestSubmitted -and $ReadinessWorld.RequestCalls -eq 0 }
  }
  Invoke-ReadinessCase 'quota-race' $true $false { param($r, $e)
    $r.ReadyForPlan -and $r.Status -eq 'READY_TO_PLAN' -and $ReadinessWorld.RequestCalls -eq 0 }
  foreach ($scenario in @('wrong-account','native-error','missing-image','invalid-json','null-json','invalid-digest','digest-mismatch','image-account','image-tag')) {
    Invoke-ReadinessCase $scenario $true $true { param($r, $e)
      $ReadinessWorld.RequestCalls -eq 0 -and !(Test-Path Env:TF_VAR_gpu_worker_image_uri) }
  }
  foreach ($scenario in @('quota-null','history-null','history-incomplete')) {
    Invoke-ReadinessCase $scenario $true $true { param($r, $e) $ReadinessWorld.RequestCalls -eq 0 }
  }
  Invoke-ReadinessCase 'request-error' $true $true { param($r, $e)
    $ReadinessWorld.RequestCalls -eq 1 -and $e -like '*request-service-quota-increase failed*' }
} finally {
  Remove-Item Function:\aws -ErrorAction SilentlyContinue
  Remove-Item Env:TF_VAR_gpu_worker_image_uri -ErrorAction SilentlyContinue
  Remove-Item Env:TF_VAR_enable_cpu_analysis -ErrorAction SilentlyContinue
}
if ($script:failures) { throw "$script:failures GPU readiness scenario(s) failed." }
Write-Host 'All GPU readiness scenarios passed.'
# Intentional fake AWS failures leave a nonzero native exit code. GitHub's
# PowerShell wrapper propagates LASTEXITCODE; reset it only after all assertions
# pass, so a real test exception still terminates the step with a failure.
$global:LASTEXITCODE = 0
