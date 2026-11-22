# Verify the published image and GPU quota before preparing a Terraform plan.
# No Terraform, EC2 launch, ECS task, Docker login, or customer-data operations.
# A quota request is the only AWS write, and requires -RequestQuotaIncrease.
[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][ValidatePattern('^\d{12}$')][string]$ExpectedAccountId,
  [ValidatePattern('^[A-Za-z0-9_.-]{1,64}$')][string]$AwsProfile = 'strokesense-admin',
  [ValidatePattern('^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$')][string]$ImageTag = 'gpu-smoke-20261120211125',
  [ValidatePattern('^[a-z0-9][a-z0-9._/-]{0,254}[a-z0-9]$')][string]$RepositoryName = 'strokesense-aws-dev-gpu-worker',
  [ValidatePattern('^sha256:[a-f0-9]{64}$')][string]$ExpectedImageDigest,
  [switch]$RequestQuotaIncrease
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$region = 'us-east-1'
$quotaCode = 'L-DB2E81BA'
$requiredVcpus = 4

function Get-Field($Object, [string]$Name) {
  if ($null -ne $Object -and $Object.PSObject.Properties[$Name]) { return $Object.$Name }
  return $null
}

function Invoke-ReadinessAwsJson {
  param([Parameter(Mandatory=$true)][string[]]$Arguments)
  # Windows PowerShell 5.1 can turn native stderr into ErrorRecord objects.
  # Check the native exit code ourselves instead of losing the AWS diagnostic
  # to the shell's terminating NativeCommandError behaviour.
  $savedPreference = $ErrorActionPreference
  try {
    $ErrorActionPreference = 'Continue'
    $raw = & aws @Arguments --profile $AwsProfile --region $region --output json --no-cli-pager --no-cli-auto-prompt --cli-connect-timeout 10 --cli-read-timeout 30 2>&1
    $code = $LASTEXITCODE
  } finally { $ErrorActionPreference = $savedPreference }
  $text = ($raw | Out-String).Trim()
  if ($code -ne 0) {
    $message = ($text -replace '\s+', ' ').Trim()
    if ($message.Length -gt 400) { $message = $message.Substring(0, 400) }
    throw "AWS $($Arguments[0]) $($Arguments[1]) failed (exit $code): $message"
  }
  try { $value = $text | ConvertFrom-Json -ErrorAction Stop }
  catch { throw "AWS $($Arguments[0]) $($Arguments[1]) returned invalid JSON; no readiness result accepted." }
  if ($null -eq $value) { throw "AWS $($Arguments[0]) $($Arguments[1]) returned null; no readiness result accepted." }
  return $value
}

function Read-AppliedGpuQuota {
  $response = Invoke-ReadinessAwsJson @('service-quotas','get-service-quota','--service-code','ec2','--quota-code',$quotaCode)
  $quota = Get-Field $response 'Quota'
  $value = Get-Field $quota 'Value'
  if ((Get-Field $quota 'QuotaCode') -ne $quotaCode -or (Get-Field $quota 'ServiceCode') -ne 'ec2' -or
      $null -eq $value -or $value -isnot [ValueType] -or
      [double]::IsNaN([double]$value) -or [double]::IsInfinity([double]$value) -or [double]$value -lt 0) {
    throw 'AWS did not return a valid applied EC2 G/VT quota. No quota request submitted.'
  }
  return $quota
}

function Read-QuotaRequests {
  # Leave AWS CLI auto-pagination enabled: a pending request on another page
  # must prevent another request, even if it asks for a different value.
  $history = Invoke-ReadinessAwsJson @('service-quotas','list-requested-service-quota-change-history-by-quota',
    '--service-code','ec2','--quota-code',$quotaCode)
  if (!$history.PSObject.Properties['RequestedQuotas'] -or $null -eq $history.RequestedQuotas -or
      (Get-Field $history 'NextToken')) {
    throw 'Incomplete GPU quota request history; refusing to create a duplicate request.'
  }
  foreach ($request in @($history.RequestedQuotas)) {
    if ((Get-Field $request 'QuotaCode') -ne $quotaCode -or (Get-Field $request 'ServiceCode') -ne 'ec2' -or
        !(Get-Field $request 'Id') -or !(Get-Field $request 'Status') -or
        $null -eq (Get-Field $request 'DesiredValue')) {
      throw 'Malformed GPU quota request history; refusing to create a duplicate request.'
    }
    $request
  }
}

# Do not leave an old/malformed image URI available after a failed lookup.
Remove-Item Env:TF_VAR_gpu_worker_image_uri -ErrorAction SilentlyContinue
if (!(Get-Command aws -ErrorAction SilentlyContinue)) { throw 'AWS CLI v2 is required.' }

$savedPythonEncoding = $env:PYTHONIOENCODING
$savedConsoleEncoding = [Console]::OutputEncoding
try {
  # AWS CLI's Python runtime otherwise may fail to print Unicode on Windows.
  $env:PYTHONIOENCODING = 'utf-8'
  [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)

  $identity = Invoke-ReadinessAwsJson @('sts','get-caller-identity')
  if ((Get-Field $identity 'Account') -ne $ExpectedAccountId) {
    throw 'Wrong AWS account. No quota request submitted and no Terraform image variable set.'
  }

  $imageResponse = Invoke-ReadinessAwsJson @('ecr','describe-images','--registry-id',$ExpectedAccountId,
    '--repository-name',$RepositoryName,'--image-ids',"imageTag=$ImageTag")
  $images = @(Get-Field $imageResponse 'imageDetails')
  if ($images.Count -ne 1 -or $null -eq $images[0]) { throw 'Exactly one published image must match the selected tag.' }
  $image = $images[0]
  $digest = Get-Field $image 'imageDigest'
  if ((Get-Field $image 'registryId') -ne $ExpectedAccountId -or
      (Get-Field $image 'repositoryName') -ne $RepositoryName -or
      @(Get-Field $image 'imageTags') -notcontains $ImageTag -or
      $digest -isnot [string] -or $digest -cnotmatch '^sha256:[a-f0-9]{64}$') {
    throw 'ECR returned an unexpected repository, tag, or incomplete image digest.'
  }
  if ($ExpectedImageDigest -and $digest -cne $ExpectedImageDigest) {
    throw 'ECR image digest does not match the expected reviewed digest.'
  }
  $imageUri = "${ExpectedAccountId}.dkr.ecr.${region}.amazonaws.com/${RepositoryName}@${digest}"
  $env:TF_VAR_gpu_worker_image_uri = $imageUri

  $quota = Read-AppliedGpuQuota
  $requests = @(Read-QuotaRequests)
  $request = $null
  $requestSubmitted = $false
  $status = 'READY_TO_PLAN'
  if ([double]$quota.Value -lt $requiredVcpus) {
    # Unknown status is treated as open. An APPROVED request for enough quota
    # also blocks resubmission while the applied quota has not caught up.
    $terminalStatuses = @('DENIED','CASE_CLOSED','NOT_APPROVED','INVALID_REQUEST')
    $blocking = @($requests | Where-Object {
      $_.Status -notin $terminalStatuses -and
      ($_.Status -ne 'APPROVED' -or [double]$_.DesiredValue -ge $requiredVcpus)
    } | Sort-Object -Property Created -Descending)
    if ($blocking.Count -gt 0) {
      $request = $blocking[0]
      $status = 'QUOTA_PENDING'
    } elseif ($RequestQuotaIncrease) {
      if ((Get-Field $quota 'Adjustable') -ne $true) { throw 'GPU quota is not reported adjustable; no request submitted.' }
      # Re-read the applied value immediately before the only AWS write.
      $quota = Read-AppliedGpuQuota
      if ([double]$quota.Value -lt $requiredVcpus) {
        $submitted = Invoke-ReadinessAwsJson @('service-quotas','request-service-quota-increase',
          '--service-code','ec2','--quota-code',$quotaCode,'--desired-value',"$requiredVcpus")
        $request = Get-Field $submitted 'RequestedQuota'
        if ((Get-Field $request 'QuotaCode') -ne $quotaCode -or (Get-Field $request 'ServiceCode') -ne 'ec2' -or
            !(Get-Field $request 'Id') -or !(Get-Field $request 'Status') -or
            (Get-Field $request 'DesiredValue') -ne $requiredVcpus) {
          throw 'Quota request response could not be verified. Re-read request history before any retry.'
        }
        $requestSubmitted = $true
        $status = 'QUOTA_PENDING'
        $quota = Read-AppliedGpuQuota
        if ([double]$quota.Value -ge $requiredVcpus) { $status = 'READY_TO_PLAN' }
      }
    } else { $status = 'QUOTA_REQUEST_NEEDED' }
  }

  $resume = ".\prepare-gpu-smoke.ps1 -ExpectedAccountId $ExpectedAccountId -AwsProfile $AwsProfile -RepositoryName $RepositoryName -ImageTag $ImageTag -ExpectedImageDigest $digest"
  $result = [pscustomobject][ordered]@{
    AccountId = $ExpectedAccountId
    Region = $region
    Status = $status
    ReadyForPlan = ([double]$quota.Value -ge $requiredVcpus)
    ImageUri = $imageUri
    AppliedGpuVcpuQuota = [double]$quota.Value
    RequiredGpuVcpus = $requiredVcpus
    QuotaRequestSubmitted = $requestSubmitted
    QuotaRequestId = Get-Field $request 'Id'
    QuotaRequestStatus = Get-Field $request 'Status'
    QuotaRequestDesiredValue = Get-Field $request 'DesiredValue'
    SupportCaseId = Get-Field $request 'CaseId'
    ResumeCommand = $resume
  }

  Write-Host "Published image verified: $imageUri"
  Write-Host "Applied G/VT quota in ${region}: $($quota.Value) vCPUs; this test needs $requiredVcpus."
  if ($result.ReadyForPlan) {
    Write-Host 'Image and applied quota checks passed. Review the real-state Terraform plan next; hardware is NOT validated.'
    Write-Host 'The smoke runner rechecks available capacity and the host/task configuration before launch.'
  } else {
    if ($request) {
      Write-Warning "Waiting for applied GPU quota. Request $($result.QuotaRequestId): $($result.QuotaRequestStatus), desired $($result.QuotaRequestDesiredValue), support case $($result.SupportCaseId)."
      Write-Host "Resume without submitting another request: $resume"
    } else {
      Write-Warning 'GPU quota is insufficient. No increase requested; use -RequestQuotaIncrease to authorize one request for 4 total vCPUs.'
      Write-Host "Request command: $resume -RequestQuotaIncrease"
    }
    Write-Host 'No Terraform apply, instance launch, or ECS task was performed.'
  }
  $result
} finally {
  $env:PYTHONIOENCODING = $savedPythonEncoding
  [Console]::OutputEncoding = $savedConsoleEncoding
}
