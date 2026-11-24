# Offline publication tests for Windows PowerShell 5.1 and PowerShell 7.
# aws and tar.exe are in-memory fakes. Blob and part files contain real bytes;
# no AWS, Docker, network request, or external archive command is performed.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:Under = Join-Path $PSScriptRoot 'publish-gpu-artifact.ps1'
$script:Failures = 0
$script:FixtureSource = '8cbcda3ee68a973f67e8617275cc7aa4f2cd8ba0'
$script:Account = '851226124502'
$script:Repository = 'strokesense-aws-dev-gpu-worker'
$script:Tag = 'gpu-offline-fixture'
$script:Utf8 = New-Object System.Text.UTF8Encoding($false)
$script:TestRoot = Join-Path ([IO.Path]::GetTempPath()) ('strokesense-publish-test-' + [guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($script:TestRoot)
$script:SavedEnvironment = @{}
foreach ($name in @('TEMP','TMP','TMPDIR','AWS_PROFILE','AWS_REGION','AWS_DEFAULT_REGION',
    'AWS_MAX_ATTEMPTS','AWS_PAGER','PYTHONIOENCODING','AWS_CLI_FILE_ENCODING','DOCKER_CONFIG',
    'TF_VAR_enable_cpu_analysis','TF_VAR_gpu_worker_image_uri')) {
  $script:SavedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

function Get-BytesHash([byte[]]$Bytes) {
  $hash = [Security.Cryptography.SHA256]::Create()
  try { return ([BitConverter]::ToString($hash.ComputeHash($Bytes))).Replace('-', '').ToLowerInvariant() }
  finally { $hash.Dispose() }
}
function Get-JsonBytes($Value) {
  return ,$script:Utf8.GetBytes(($Value | ConvertTo-Json -Depth 20 -Compress))
}
function Get-Argument([string[]]$Arguments, [string]$Name) {
  $index = [array]::IndexOf($Arguments, $Name)
  if ($index -lt 0 -or $index + 1 -ge $Arguments.Count) { throw "Missing fake argument: $Name" }
  return $Arguments[$index + 1]
}
function Assert-Publish([bool]$Condition, [string]$Message) {
  if (!$Condition) { throw $Message }
}
function New-ServiceError([string]$Code, [hashtable]$Fields = @{}, [switch]$NativeStderr) {
  $record = @{ Code = $Code; Message = 'Offline service diagnostic' }
  foreach ($key in $Fields.Keys) { $record[$key] = $Fields[$key] }
  if ($NativeStderr) {
    # PS5 native stderr is a sequence of ErrorRecords. In particular, an
    # empty RemoteException.Message used to make ErrorRecord.ToString() emit
    # a type name. Emulate that fallback on PS7 too, so the same test proves
    # the helper unwraps native Exception.Message instead of parsing a
    # spurious "System.Management.Automation.RemoteException" JSON prefix.
    $json = $record | ConvertTo-Json -Depth 10
    $lines = @('') + @($json -split '\r?\n') + @('')
    for ($i = 0; $i -lt $lines.Count; $i++) {
      $id = 'NativeCommandErrorMessage'; if ($i -eq 0) { $id = 'NativeCommandError' }
      $errorRecord = [System.Management.Automation.ErrorRecord]::new(
        [System.Management.Automation.RemoteException]::new($lines[$i]), $id,
        [System.Management.Automation.ErrorCategory]::NotSpecified, 'aws')
      if ($lines[$i] -eq '') {
        $errorRecord | Add-Member -MemberType ScriptMethod -Name ToString -Value { 'System.Management.Automation.RemoteException' } -Force
      }
      $errorRecord
    }
    return
  }
  # A nonempty native stderr line remains JSON when unwrapped. Formatting it
  # with Out-String would add non-JSON PowerShell error metadata.
  $message = $record | ConvertTo-Json -Depth 10 -Compress
  return [System.Management.Automation.ErrorRecord]::new(
    [Exception]::new($message), 'NativeCommandError',
    [System.Management.Automation.ErrorCategory]::NotSpecified, 'aws')
}

# A little over the ECR minimum 5 MiB part size exercises the final short part.
# Generate once, reuse across cases, and never print the binary content.
$script:LargeBlob = New-Object byte[] (5 * 1024 * 1024 + 4096)
$random = New-Object System.Random(91)
$random.NextBytes($script:LargeBlob)
$script:LargeBlob[0] = 0x1f
$script:LargeBlob[1] = 0x8b
$script:LargeDigest = 'sha256:' + (Get-BytesHash $script:LargeBlob)

function New-PublishFixture([string]$Scenario) {
  $directory = Join-Path $script:TestRoot $Scenario
  [void][IO.Directory]::CreateDirectory($directory)
  $temp = Join-Path $directory 'temp'
  [void][IO.Directory]::CreateDirectory($temp)
  $baseBlob = $script:Utf8.GetBytes('offline base layer already available')
  $baseDigest = 'sha256:' + (Get-BytesHash $baseBlob)
  $architecture = 'amd64'; if ($Scenario -eq 'wrong-platform') { $architecture = 'arm64' }
  $revision = $script:FixtureSource; if ($Scenario -eq 'wrong-source') { $revision = 'b' * 40 }
  $configBytes = Get-JsonBytes ([ordered]@{
    architecture = $architecture; os = 'linux'
    config = @{ User = '10001:10001'; Labels = @{ 'org.opencontainers.image.revision' = $revision }
      Cmd = @('python3','-m','aws_app.gpu_worker') }
    rootfs = @{ type = 'layers'; diff_ids = @($baseDigest, $script:LargeDigest) }
  })
  $configDigest = 'sha256:' + (Get-BytesHash $configBytes)
  $manifestBytes = Get-JsonBytes ([ordered]@{
    schemaVersion = 2; mediaType = 'application/vnd.oci.image.manifest.v1+json'
    config = @{ mediaType = 'application/vnd.oci.image.config.v1+json'; digest = $configDigest; size = $configBytes.Length }
    layers = @(
      @{ mediaType = 'application/vnd.oci.image.layer.v1.tar+gzip'; digest = $baseDigest; size = $baseBlob.Length },
      @{ mediaType = 'application/vnd.oci.image.layer.v1.tar+gzip'; digest = $script:LargeDigest; size = $script:LargeBlob.Length }
    )
  })
  $manifestDigest = 'sha256:' + (Get-BytesHash $manifestBytes)
  $indexBytes = Get-JsonBytes (@{
    schemaVersion = 2; mediaType = 'application/vnd.oci.image.index.v1+json'
    manifests = @(@{ mediaType = 'application/vnd.oci.image.manifest.v1+json'; digest = $manifestDigest
      size = $manifestBytes.Length; platform = @{ architecture = 'amd64'; os = 'linux' } })
  })
  $indexDigest = 'sha256:' + (Get-BytesHash $indexBytes)
  $outerIndexBytes = Get-JsonBytes (@{
    schemaVersion = 2; manifests = @(@{ mediaType = 'application/vnd.oci.image.index.v1+json'
      digest = $indexDigest; size = $indexBytes.Length })
  })
  $members = @{
    'oci-layout' = (Get-JsonBytes @{ imageLayoutVersion = '1.0.0' })
    'index.json' = $outerIndexBytes
  }
  $members['blobs/sha256/' + $indexDigest.Substring(7)] = $indexBytes
  $members['blobs/sha256/' + $manifestDigest.Substring(7)] = $manifestBytes
  $members['blobs/sha256/' + $configDigest.Substring(7)] = $configBytes
  $members['blobs/sha256/' + $baseDigest.Substring(7)] = $baseBlob
  $members['blobs/sha256/' + $script:LargeDigest.Substring(7)] = $script:LargeBlob
  # tar.exe is mocked, so the outer archive is an opaque binary fixture. The
  # helper must still check its actual bytes, declared length, and checksum.
  $archiveBytes = [byte[]](0x1f, 0x8b, 0, 255, 128, 13, 10, 42, 0, 77)
  $archive = Join-Path $directory 'strokesense-gpu-image.tar.gz'
  [IO.File]::WriteAllBytes($archive, $archiveBytes)
  $archiveHash = Get-BytesHash $archiveBytes
  $metadata = [ordered]@{
    schema_version = 1; source_repository = 'https://github.com/KemalGC/CS4501_Startup'
    source_commit = $script:FixtureSource; image_tag = 'strokesense-gpu:' + $script:FixtureSource
    image_id = $indexDigest; platform = 'linux/amd64'; archive_file = 'strokesense-gpu-image.tar.gz'
    archive_sha256 = $archiveHash; archive_size_bytes = $archiveBytes.Length
    base_image = 'nvidia/cuda@sha256:5f0d2d827f6436b3cb7468fd8acbdc8c1d41261614e579ae49afe6141da51133'
    validation = @{ gpu_unit_tests = 'passed_with_mocked_hardware'; runtime_package_and_model_checks = 'passed'
      cpu_host_preflight = 'nvidia_driver_unavailable_as_expected'; default_worker = 'gpu_worker_disabled_as_expected'
      real_gpu_inference_verified = $false; vulnerability_scan_performed = $false; published_to_ecr = $false }
  }
  [IO.File]::WriteAllBytes((Join-Path $directory 'image-manifest.json'), (Get-JsonBytes $metadata))
  [IO.File]::WriteAllText((Join-Path $directory 'SHA256SUMS'), "$archiveHash  strokesense-gpu-image.tar.gz`n", $script:Utf8)
  $parameters = @{
    ExpectedAccountId = $script:Account; AwsProfile = 'offline'; ArtifactDirectory = $directory; ImageTag = $script:Tag
    ExpectedSourceCommit = $script:FixtureSource; ExpectedArchiveSha256 = $archiveHash
    ExpectedArchiveSizeBytes = [long]$archiveBytes.Length; ExpectedIndexDigest = $indexDigest
    ExpectedManifestDigest = $manifestDigest; ExpectedConfigDigest = $configDigest
    CheckpointDirectory = (Join-Path $directory 'checkpoints'); UploadPartAttempts = 3
  }
  if ($Scenario -eq 'wrong-archive') { [IO.File]::WriteAllBytes($archive, [byte[]](9, 8, 7, 6)) }
  if ($Scenario -eq 'wrong-manifest-digest') { $parameters.ExpectedManifestDigest = 'sha256:' + ('f' * 64) }
  $global:PublishWorld = @{
    Scenario = $Scenario; Directory = $directory; Temp = $temp; Archive = $archive; Members = $members
    Parameters = $parameters; ConfigDigest = $configDigest; ManifestDigest = $manifestDigest
    ManifestBytes = $manifestBytes; BaseDigest = $baseDigest; LargeDigest = $script:LargeDigest
    Calls = New-Object System.Collections.ArrayList; ExtractRoots = New-Object System.Collections.ArrayList
    Ranges = New-Object System.Collections.ArrayList; Phase = 1; AmbiguousAvailabilityFailed = $false
    Parts = @{}; PartAttempts = @{}; InitCalls = 0; PartCalls = 0; CompleteCalls = 0; PutCalls = 0
    Published = ($Scenario -in @('existing-match','existing-inconsistent'))
    Complete = ($Scenario -eq 'existing-match'); ManifestChecked = $false
    UploadId = '11111111-2222-3333-4444-555555555555'
  }
}

function global:tar.exe {
  $a = @($args | ForEach-Object { "$_" })
  $global:LASTEXITCODE = 0
  if ($a[0] -eq '-tf') { return @($PublishWorld.Members.Keys | Sort-Object) }
  if ($a[0] -ne '-xf') { throw "Unexpected offline tar operation: $($a -join ' ')" }
  $destination = Get-Argument $a '-C'
  if (!$PublishWorld.ExtractRoots.Contains($destination)) { [void]$PublishWorld.ExtractRoots.Add($destination) }
  foreach ($member in $a | Where-Object { $_ -match '^(?:\./)?(?:oci-layout|index\.json|blobs/sha256/[a-f0-9]{64})$' }) {
    $key = $member -replace '^\./', ''
    if (!$PublishWorld.Members.ContainsKey($key)) { $global:LASTEXITCODE = 1; return 'Fixture member is missing' }
    $target = Join-Path $destination ($key -replace '/', [IO.Path]::DirectorySeparatorChar)
    [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target))
    [IO.File]::WriteAllBytes($target, $PublishWorld.Members[$key])
  }
}
function global:Start-Sleep { param($Seconds, $Milliseconds) }
function global:aws {
  $a = @($args | ForEach-Object { "$_" })
  $operation = $a[0] + ' ' + $a[1]
  [void]$PublishWorld.Calls.Add(($a -join ' '))
  $global:LASTEXITCODE = 0
  Assert-Publish ((Get-Argument $a '--profile') -eq 'offline') 'AWS profile was not explicitly selected'
  Assert-Publish ((Get-Argument $a '--region') -eq 'us-east-1') 'Unexpected AWS region'
  switch ($operation) {
    'sts get-caller-identity' {
      if ($PublishWorld.Scenario -eq 'unsupported-cli') {
        $global:LASTEXITCODE = 252
        return 'aws: error: argument --cli-error-format: invalid option'
      }
      return '{"Account":"851226124502"}'
    }
    'ecr describe-images' {
      if (!$PublishWorld.Published -and $PublishWorld.Scenario -ne 'existing-conflict') {
        $global:LASTEXITCODE = 254
        return (New-ServiceError 'ImageNotFoundException')
      }
      $digest = $PublishWorld.ManifestDigest
      if ($PublishWorld.Scenario -eq 'existing-conflict') { $digest = 'sha256:' + ('e' * 64) }
      return (@{ imageDetails = @(@{ registryId = '851226124502'; repositoryName = 'strokesense-aws-dev-gpu-worker'
        imageTags = @('gpu-offline-fixture'); imageDigest = $digest }) } | ConvertTo-Json -Depth 8 -Compress)
    }
    'ecr batch-check-layer-availability' {
      if ($PublishWorld.Scenario -eq 'resume-completion' -and $PublishWorld.Phase -eq 1 -and
          $PublishWorld.Complete -and !$PublishWorld.AmbiguousAvailabilityFailed) {
        $PublishWorld.AmbiguousAvailabilityFailed = $true
        $global:LASTEXITCODE = 255
        return 'aws: [ERROR]: Connection was closed before we received a valid response from endpoint URL'
      }
      $start = [array]::IndexOf($a, '--layer-digests') + 1
      $layers = @(); $failures = @()
      $missingDigest = $PublishWorld.LargeDigest
      if ($PublishWorld.Scenario -eq 'config-missing') { $missingDigest = $PublishWorld.ConfigDigest }
      for ($i = $start; $i -lt $a.Count -and !$a[$i].StartsWith('--'); $i++) {
        $available = ($a[$i] -ne $missingDigest -or $PublishWorld.Complete)
        if (!$available -and $PublishWorld.Scenario -eq 'missing-layer-failure') {
          $failures += @{ layerDigest = $a[$i]; failureCode = 'MissingLayerDigest'; failureReason = 'Blob is not present' }
          continue
        }
        $blobName = 'blobs/sha256/' + $a[$i].Substring(7)
        $layers += @{ layerDigest = $a[$i]; layerAvailability = $(if ($available) { 'AVAILABLE' } else { 'UNAVAILABLE' })
          layerSize = $PublishWorld.Members[$blobName].LongLength }
      }
      return (@{ layers = @($layers); failures = @($failures) } | ConvertTo-Json -Depth 8 -Compress)
    }
    'ecr initiate-layer-upload' {
      $PublishWorld.InitCalls++
      return (@{ registryId = '851226124502'; repositoryName = 'strokesense-aws-dev-gpu-worker'
        uploadId = $PublishWorld.UploadId; partSize = 5242880 } | ConvertTo-Json -Compress)
    }
    'ecr upload-layer-part' {
      $PublishWorld.PartCalls++
      $start = [long](Get-Argument $a '--part-first-byte')
      $end = [long](Get-Argument $a '--part-last-byte')
      $uploadId = Get-Argument $a '--upload-id'
      [void]$PublishWorld.Ranges.Add(@{ Start = $start; End = $end; UploadId = $uploadId; Phase = $PublishWorld.Phase })
      $blobArg = Get-Argument $a '--layer-part-blob'
      Assert-Publish ($blobArg.StartsWith('fileb://')) 'Part must use binary file input'
      $bytes = [IO.File]::ReadAllBytes($blobArg.Substring(8))
      Assert-Publish ($bytes.LongLength -eq $end - $start + 1) 'Part byte range was not inclusive'
      Assert-Publish ($uploadId -eq $PublishWorld.UploadId) 'Upload changed its ID'
      if (!$PublishWorld.PartAttempts.ContainsKey($start)) { $PublishWorld.PartAttempts[$start] = 0 }
      $PublishWorld.PartAttempts[$start]++
      if ($PublishWorld.Scenario -eq 'resume-expired' -and $PublishWorld.Phase -eq 2) {
        $global:LASTEXITCODE = 254
        return (New-ServiceError 'UploadNotFoundException')
      }
      if ($PublishWorld.Scenario -eq 'upload-fails' -or
          ($PublishWorld.Phase -eq 1 -and $start -gt 0 -and $PublishWorld.Scenario -in @(
            'resume-parts','resume-binding','resume-offset','resume-expired','adopt-to-auto'))) {
        $global:LASTEXITCODE = 255
        return 'aws: [ERROR]: Connection was closed before we received a valid response from endpoint URL'
      }
      $PublishWorld.Parts[$start] = $bytes
      if ($PublishWorld.Scenario -eq 'resume-lost-ack' -and $start -eq 0) {
        if ($PublishWorld.Phase -eq 1) {
          $global:LASTEXITCODE = 255
          return 'aws: [ERROR]: Connection was closed before we received a valid response from endpoint URL'
        }
        $global:LASTEXITCODE = 254
        return (New-ServiceError 'InvalidLayerPartException' @{
          registryId = '851226124502'; repositoryName = 'strokesense-aws-dev-gpu-worker'
          uploadId = $uploadId; lastValidByteReceived = $end
        } -NativeStderr)
      }
      if ($PublishWorld.Scenario -in @('lost-ack','wrong-resume-identity') -and $start -eq 0) {
        if ($PublishWorld.PartAttempts[$start] -eq 1) {
          $global:LASTEXITCODE = 255
          return 'aws: [ERROR]: Connection was closed before we received a valid response from endpoint URL'
        }
        $replyId = $uploadId
        if ($PublishWorld.Scenario -eq 'wrong-resume-identity') { $replyId = '99999999-2222-3333-4444-555555555555' }
        $global:LASTEXITCODE = 254
        return (New-ServiceError 'InvalidLayerPartException' @{
          registryId = '851226124502'; repositoryName = 'strokesense-aws-dev-gpu-worker'
          uploadId = $replyId; lastValidByteReceived = $end
        } -NativeStderr)
      }
      $ackEnd = $end
      if ($PublishWorld.Scenario -eq 'wrong-part-ack') { $ackEnd-- }
      return (@{ registryId = '851226124502'; repositoryName = 'strokesense-aws-dev-gpu-worker'
        uploadId = $uploadId; firstByteReceived = $start; lastByteReceived = $ackEnd } | ConvertTo-Json -Compress)
    }
    'ecr complete-layer-upload' {
      $PublishWorld.CompleteCalls++
      $buffer = New-Object IO.MemoryStream
      try {
        foreach ($offset in @($PublishWorld.Parts.Keys | Sort-Object { [long]$_ })) {
          Assert-Publish ($buffer.Length -eq [long]$offset) 'Uploaded parts overlap or have a gap'
          $part = $PublishWorld.Parts[$offset]
          $buffer.Write($part, 0, $part.Length)
        }
        $digest = 'sha256:' + (Get-BytesHash $buffer.ToArray())
        Assert-Publish ($digest -eq (Get-Argument $a '--layer-digests')) 'Uploaded bytes do not match the completed digest'
      } finally { $buffer.Dispose() }
      $PublishWorld.Complete = $true
      if ($PublishWorld.Scenario -eq 'resume-completion' -and $PublishWorld.Phase -eq 1) {
        $global:LASTEXITCODE = 255
        return 'aws: [ERROR]: Connection was closed before we received a valid response from endpoint URL'
      }
      return (@{ registryId = '851226124502'; repositoryName = 'strokesense-aws-dev-gpu-worker'
        uploadId = $PublishWorld.UploadId; layerDigest = $digest } | ConvertTo-Json -Compress)
    }
    'ecr put-image' {
      $PublishWorld.PutCalls++
      $file = Get-Argument $a '--image-manifest'
      Assert-Publish ($file.StartsWith('file://')) 'Image manifest must come from the preserved file'
      $bytes = [IO.File]::ReadAllBytes($file.Substring(7))
      Assert-Publish (!($bytes.Length -ge 3 -and $bytes[0] -eq 0xef -and $bytes[1] -eq 0xbb -and $bytes[2] -eq 0xbf)) 'UTF-8 BOM was added to the manifest'
      Assert-Publish (('sha256:' + (Get-BytesHash $bytes)) -eq $PublishWorld.ManifestDigest) 'Manifest bytes changed before publication'
      Assert-Publish ($PublishWorld.Complete) 'Manifest was published before its missing blob completed'
      $PublishWorld.ManifestChecked = $true
      if ($PublishWorld.Scenario -eq 'put-access-denied') {
        $global:LASTEXITCODE = 254
        return (New-ServiceError 'AccessDeniedException' @{ Message = 'Offline IAM denies ecr:PutImage' })
      }
      $PublishWorld.Published = $true
      $digest = $PublishWorld.ManifestDigest
      return (@{ image = @{ registryId = '851226124502'; repositoryName = 'strokesense-aws-dev-gpu-worker'
        imageId = @{ imageTag = 'gpu-offline-fixture'; imageDigest = $digest }
        imageManifest = $script:Utf8.GetString($PublishWorld.ManifestBytes)
        imageManifestMediaType = 'application/vnd.oci.image.manifest.v1+json' } } | ConvertTo-Json -Depth 8 -Compress)
    }
    'ecr batch-get-image' {
      if (!$PublishWorld.Published -and $PublishWorld.Scenario -ne 'existing-conflict') {
        return (@{ images = @(); failures = @(@{ failureCode = 'ImageNotFound'
          imageId = @{ imageTag = 'gpu-offline-fixture' }; failureReason = 'Offline missing image' }) } | ConvertTo-Json -Depth 8 -Compress)
      }
      $digest = $PublishWorld.ManifestDigest
      if ($PublishWorld.Scenario -eq 'existing-conflict') { $digest = 'sha256:' + ('e' * 64) }
      $manifestText = $script:Utf8.GetString($PublishWorld.ManifestBytes)
      if ($PublishWorld.Scenario -eq 'wrong-readback-manifest') { $manifestText += ' ' }
      return (@{ images = @(@{ registryId = '851226124502'; repositoryName = 'strokesense-aws-dev-gpu-worker'
        imageId = @{ imageTag = 'gpu-offline-fixture'; imageDigest = $digest }
        imageManifest = $manifestText
        imageManifestMediaType = 'application/vnd.oci.image.manifest.v1+json' }); failures = @() } | ConvertTo-Json -Depth 8 -Compress)
    }
    'service-quotas get-service-quota' {
      $value = 4; if ($PublishWorld.Scenario -eq 'quota-not-ready') { $value = 0 }
      return (@{ Quota = @{ ServiceCode = 'ec2'; QuotaCode = 'L-DB2E81BA'; Value = $value; Adjustable = $true } } | ConvertTo-Json -Compress)
    }
    'service-quotas list-requested-service-quota-change-history-by-quota' { return '{"RequestedQuotas":[]}' }
    default { throw "Unexpected offline AWS operation: $operation" }
  }
}

function Invoke-FixturePublisher([bool]$ExpectThrow) {
  $env:TEMP = $PublishWorld.Temp; $env:TMP = $PublishWorld.Temp; $env:TMPDIR = $PublishWorld.Temp
  $env:AWS_PROFILE = 'caller-profile'; $env:AWS_REGION = 'caller-region'; $env:AWS_DEFAULT_REGION = 'caller-default'
  $env:AWS_MAX_ATTEMPTS = '7'; $env:AWS_PAGER = 'caller-pager'; $env:PYTHONIOENCODING = 'utf-8'
  $env:AWS_CLI_FILE_ENCODING = 'caller-encoding'
  $env:DOCKER_CONFIG = 'caller-docker-config'; $env:TF_VAR_enable_cpu_analysis = 'true'
  $env:TF_VAR_gpu_worker_image_uri = 'stale-invalid-uri@'
  $archiveBefore = Get-BytesHash ([IO.File]::ReadAllBytes($PublishWorld.Archive))
  $consoleBefore = [Console]::OutputEncoding.CodePage
  $caught = $null; $result = $null
  try {
    $invokeParameters = $PublishWorld.Parameters
    $result = & $script:Under @invokeParameters 3>$null 6>$null
  } catch { $caught = $_.Exception.Message }
  Assert-Publish (($null -ne $caught) -eq $ExpectThrow) "Unexpected result: $caught"
  Assert-Publish ($env:AWS_PROFILE -eq 'caller-profile' -and $env:AWS_REGION -eq 'caller-region' -and
    $env:AWS_DEFAULT_REGION -eq 'caller-default' -and $env:AWS_MAX_ATTEMPTS -eq '7' -and
    $env:AWS_PAGER -eq 'caller-pager' -and $env:PYTHONIOENCODING -eq 'utf-8' -and $env:AWS_CLI_FILE_ENCODING -eq 'caller-encoding' -and
    $env:DOCKER_CONFIG -eq 'caller-docker-config' -and $env:TF_VAR_enable_cpu_analysis -eq 'true' -and
    [Console]::OutputEncoding.CodePage -eq $consoleBefore) 'Caller environment or console encoding was changed'
  Assert-Publish ((Get-BytesHash ([IO.File]::ReadAllBytes($PublishWorld.Archive))) -eq $archiveBefore) 'Input archive was changed'
  foreach ($path in $PublishWorld.ExtractRoots) { Assert-Publish (!(Test-Path -LiteralPath $path)) 'Owned extraction directory was not cleaned up' }
  if ($ExpectThrow) { Assert-Publish (!(Test-Path Env:TF_VAR_gpu_worker_image_uri)) 'Failure left a Terraform image URI set' }
  else {
    $uri = '851226124502.dkr.ecr.us-east-1.amazonaws.com/strokesense-aws-dev-gpu-worker@' + $PublishWorld.ManifestDigest
    Assert-Publish ($env:TF_VAR_gpu_worker_image_uri -eq $uri) 'Ready image URI was not set exactly'
  }
  return [pscustomobject]@{ Result = $result; Error = $caught }
}
function Get-FixtureCheckpoint {
  $name = $PublishWorld.LargeDigest.Substring(7) + '.json'
  $files = @(Get-ChildItem -LiteralPath $PublishWorld.Parameters.CheckpointDirectory -Filter $name -File -Recurse)
  Assert-Publish ($files.Count -eq 1) 'Expected exactly one persistent checkpoint for the incomplete blob'
  return $files[0].FullName
}
function Assert-NoFixtureCheckpoint {
  $files = @(Get-ChildItem -LiteralPath $PublishWorld.Parameters.CheckpointDirectory -Filter '*.json' -File -Recurse)
  Assert-Publish ($files.Count -eq 0) 'Verified available blob retained a stale upload checkpoint'
}
function Invoke-PublishCase([string]$Scenario, [bool]$ExpectThrow, [scriptblock]$Check, [scriptblock]$Setup) {
  $caught = $null
  try {
    New-PublishFixture $Scenario
    if ($Setup) { & $Setup }
    $outcome = Invoke-FixturePublisher $ExpectThrow
    $caught = $outcome.Error
    & $Check $outcome.Result $caught
    Write-Host "PASS $Scenario"
  } catch {
    $script:Failures++
    Write-Host "FAIL $Scenario : $($_.Exception.Message) [helper: $caught]"
  }
}

try {
  Invoke-PublishCase 'new-image' $false { param($r, $e)
    Assert-Publish ($PublishWorld.InitCalls -eq 1 -and $PublishWorld.PartCalls -eq 2 -and
      $PublishWorld.CompleteCalls -eq 1 -and $PublishWorld.PutCalls -eq 1 -and $PublishWorld.ManifestChecked) 'New-image upload did not skip existing blobs or preserve its two parts'
  }
  Invoke-PublishCase 'existing-match' $false { param($r, $e)
    Assert-Publish ($PublishWorld.InitCalls -eq 0 -and $PublishWorld.PutCalls -eq 0) 'Matching immutable tag caused an upload'
  }
  Invoke-PublishCase 'missing-layer-failure' $false { param($r, $e)
    Assert-Publish ($PublishWorld.InitCalls -eq 1 -and $PublishWorld.PartCalls -eq 2 -and
      $PublishWorld.CompleteCalls -eq 1 -and $PublishWorld.PutCalls -eq 1) 'MissingLayerDigest failure was not treated as a missing blob'
  }
  Invoke-PublishCase 'config-missing' $false { param($r, $e)
    Assert-Publish ($PublishWorld.InitCalls -eq 1 -and $PublishWorld.PartCalls -eq 1 -and
      $PublishWorld.CompleteCalls -eq 1 -and $PublishWorld.PutCalls -eq 1) 'Tiny config blob did not upload as one final part'
    Assert-Publish (('sha256:' + (Get-BytesHash $PublishWorld.Parts[[long]0])) -eq $PublishWorld.ConfigDigest) 'Config upload used the wrong bytes'
  }
  foreach ($scenario in @('existing-conflict','existing-inconsistent','wrong-archive','wrong-manifest-digest','wrong-source','wrong-platform','unsupported-cli')) {
    Invoke-PublishCase $scenario $true { param($r, $e)
      Assert-Publish ($PublishWorld.InitCalls -eq 0 -and $PublishWorld.PartCalls -eq 0 -and
        $PublishWorld.CompleteCalls -eq 0 -and $PublishWorld.PutCalls -eq 0) 'Invalid input or immutable-tag conflict reached an AWS write'
      if ($PublishWorld.Scenario -eq 'existing-inconsistent') {
        Assert-Publish ($e -like '*existing image tag references unavailable blobs*') 'Inconsistent published-image evidence was not rejected explicitly'
      }
    }
  }
  Invoke-PublishCase 'wrong-part-ack' $true { param($r, $e)
    Assert-Publish ($PublishWorld.PartCalls -eq 1 -and $PublishWorld.CompleteCalls -eq 0 -and $PublishWorld.PutCalls -eq 0) 'Invalid acknowledgement was accepted'
  }
  Invoke-PublishCase 'lost-ack' $false { param($r, $e)
    Assert-Publish ($PublishWorld.InitCalls -eq 1 -and $PublishWorld.PartCalls -eq 3 -and
      $PublishWorld.CompleteCalls -eq 1 -and $PublishWorld.PutCalls -eq 1) 'Lost acknowledgement did not retry only the same part'
  }
  Invoke-PublishCase 'wrong-resume-identity' $true { param($r, $e)
    Assert-Publish ($PublishWorld.InitCalls -eq 1 -and $PublishWorld.CompleteCalls -eq 0 -and $PublishWorld.PutCalls -eq 0) 'Wrong upload identity was accepted for resume'
  }
  Invoke-PublishCase 'upload-fails' $true { param($r, $e)
    Assert-Publish ($PublishWorld.InitCalls -eq 1 -and $PublishWorld.PartCalls -eq 3 -and
      $PublishWorld.CompleteCalls -eq 0 -and $PublishWorld.PutCalls -eq 0) 'Upload retry was unbounded or published incomplete content'
    $checkpoint = Get-Content -LiteralPath (Get-FixtureCheckpoint) -Raw | ConvertFrom-Json
    Assert-Publish ($checkpoint.next_byte -eq 0 -and $checkpoint.upload_id -eq $PublishWorld.UploadId) 'Failed first part lost its upload ID or advanced the checkpoint'
  }
  Invoke-PublishCase 'resume-parts' $true { param($r, $e)
    $checkpointPath = Get-FixtureCheckpoint
    $checkpoint = Get-Content -LiteralPath $checkpointPath -Raw | ConvertFrom-Json
    Assert-Publish ($checkpoint.next_byte -eq 5MB -and $checkpoint.part_size -eq 5MB -and
      $checkpoint.upload_id -eq $PublishWorld.UploadId -and $checkpoint.layer_size -eq $script:LargeBlob.LongLength) 'Last acknowledged byte range was not checkpointed'
    $PublishWorld.Phase = 2
    [void](Invoke-FixturePublisher $false)
    $resumed = @($PublishWorld.Ranges | Where-Object { $_.Phase -eq 2 })
    Assert-Publish ($PublishWorld.InitCalls -eq 1 -and $resumed.Count -eq 1 -and
      $resumed[0].Start -eq 5MB -and $resumed[0].End -eq $script:LargeBlob.LongLength - 1 -and
      $PublishWorld.PartAttempts[[long]0] -eq 1 -and $PublishWorld.CompleteCalls -eq 1) 'Rerun restarted the layer or failed to seek to the saved range'
    Assert-NoFixtureCheckpoint
  }
  Invoke-PublishCase 'resume-lost-ack' $true { param($r, $e)
    $checkpoint = Get-Content -LiteralPath (Get-FixtureCheckpoint) -Raw | ConvertFrom-Json
    Assert-Publish ($checkpoint.next_byte -eq 0 -and $PublishWorld.Parts.ContainsKey([long]0)) 'Ambiguous part advanced its checkpoint or was not retained by the mock server'
    $PublishWorld.Phase = 2
    [void](Invoke-FixturePublisher $false)
    $resumed = @($PublishWorld.Ranges | Where-Object { $_.Phase -eq 2 })
    Assert-Publish ($PublishWorld.InitCalls -eq 1 -and $resumed.Count -eq 2 -and
      $resumed[0].Start -eq 0 -and $resumed[0].End -eq 5MB - 1 -and
      $resumed[1].Start -eq 5MB -and $PublishWorld.CompleteCalls -eq 1) 'Lost acknowledgement was not reconciled by retrying the exact uncertain part'
    Assert-NoFixtureCheckpoint
  }
  Invoke-PublishCase 'resume-completion' $true { param($r, $e)
    $checkpoint = Get-Content -LiteralPath (Get-FixtureCheckpoint) -Raw | ConvertFrom-Json
    Assert-Publish ($checkpoint.next_byte -eq $script:LargeBlob.LongLength -and
      $PublishWorld.Complete -and $PublishWorld.AmbiguousAvailabilityFailed -and $PublishWorld.PutCalls -eq 0) 'Uncertain completion did not retain its fully acknowledged checkpoint'
    $PublishWorld.Phase = 2
    [void](Invoke-FixturePublisher $false)
    Assert-Publish ($PublishWorld.InitCalls -eq 1 -and $PublishWorld.PartCalls -eq 2 -and
      $PublishWorld.CompleteCalls -eq 1 -and $PublishWorld.PutCalls -eq 1) 'A now-available blob was uploaded or completed again after ambiguous completion'
    Assert-NoFixtureCheckpoint
  }
  foreach ($scenario in @('resume-binding','resume-offset')) {
    Invoke-PublishCase $scenario $true { param($r, $e)
      $path = Get-FixtureCheckpoint
      $checkpoint = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
      if ($PublishWorld.Scenario -eq 'resume-binding') { $checkpoint.manifest_digest = 'sha256:' + ('f' * 64) }
      else { $checkpoint.next_byte = [long]$script:LargeBlob.LongLength + 1 }
      [IO.File]::WriteAllBytes($path, (Get-JsonBytes $checkpoint))
      $before = Get-BytesHash ([IO.File]::ReadAllBytes($path))
      $partsBefore = $PublishWorld.PartCalls
      $PublishWorld.Phase = 2
      [void](Invoke-FixturePublisher $true)
      Assert-Publish ($PublishWorld.InitCalls -eq 1 -and $PublishWorld.PartCalls -eq $partsBefore -and
        $PublishWorld.CompleteCalls -eq 0 -and $PublishWorld.PutCalls -eq 0) 'Invalid checkpoint reached a write or silently started a new upload'
      Assert-Publish ((Get-BytesHash ([IO.File]::ReadAllBytes($path))) -eq $before) 'Invalid checkpoint was silently overwritten or deleted'
    }
  }
  Invoke-PublishCase 'resume-expired' $true { param($r, $e)
    $path = Get-FixtureCheckpoint
    $before = Get-BytesHash ([IO.File]::ReadAllBytes($path))
    $PublishWorld.Phase = 2
    $outcome = Invoke-FixturePublisher $true
    Assert-Publish ($outcome.Error -like '*UploadNotFoundException*' -and $PublishWorld.InitCalls -eq 1 -and
      $PublishWorld.CompleteCalls -eq 0 -and $PublishWorld.PutCalls -eq 0) 'Missing upload ID was restarted or its diagnostic was lost'
    Assert-Publish ((Get-BytesHash ([IO.File]::ReadAllBytes($path))) -eq $before) 'Missing upload ID destroyed the retained checkpoint'
  }
  Invoke-PublishCase 'adopt-to-auto' $true { param($r, $e)
    $checkpoint = Get-Content -LiteralPath (Get-FixtureCheckpoint) -Raw | ConvertFrom-Json
    Assert-Publish ($PublishWorld.InitCalls -eq 0 -and $checkpoint.upload_id -eq $PublishWorld.UploadId -and
      $checkpoint.next_byte -eq 5MB) 'Explicit adoption did not preserve the existing upload and acknowledged offset'
    foreach ($key in @('ResumeLayerDigest','ResumeUploadId','ResumeOffset','ResumePartSize')) { $PublishWorld.Parameters.Remove($key) }
    $PublishWorld.Phase = 2
    [void](Invoke-FixturePublisher $false)
    $resumed = @($PublishWorld.Ranges | Where-Object { $_.Phase -eq 2 })
    Assert-Publish ($PublishWorld.InitCalls -eq 0 -and $resumed.Count -eq 1 -and $resumed[0].Start -eq 5MB -and
      $PublishWorld.CompleteCalls -eq 1 -and $PublishWorld.PutCalls -eq 1) 'Adopted upload required repeated adoption flags or restarted from zero'
    Assert-NoFixtureCheckpoint
  } -Setup {
    $prefix = New-Object byte[] (5MB)
    [Array]::Copy($script:LargeBlob, 0, $prefix, 0, $prefix.Length)
    $PublishWorld.Parts[[long]0] = $prefix
    $PublishWorld.Parameters.ResumeLayerDigest = $PublishWorld.LargeDigest
    $PublishWorld.Parameters.ResumeUploadId = $PublishWorld.UploadId
    $PublishWorld.Parameters.ResumeOffset = [long](5MB)
    $PublishWorld.Parameters.ResumePartSize = [long](5MB)
  }
  Invoke-PublishCase 'wrong-readback-manifest' $true { param($r, $e)
    Assert-Publish ($PublishWorld.PutCalls -eq 1 -and $PublishWorld.ManifestChecked) 'Changed remote manifest bytes were not checked after exact-byte publication'
  }
  Invoke-PublishCase 'put-access-denied' $true { param($r, $e)
    Assert-Publish ($PublishWorld.PutCalls -eq 1 -and !$PublishWorld.Published) 'Denied PutImage was retried or marked published'
    Assert-Publish ($e -like '*AccessDeniedException*' -and $e -like '*Offline IAM denies ecr:PutImage*') 'Independent readback failure hid the original IAM error'
  }
  Invoke-PublishCase 'quota-not-ready' $true { param($r, $e)
    Assert-Publish ($PublishWorld.Published -and $PublishWorld.PutCalls -eq 1) 'Quota readiness was not checked after publishing'
    Assert-Publish (@($PublishWorld.Calls | Where-Object { $_ -like 'service-quotas request-*' }).Count -eq 0) 'Publisher requested a quota increase'
  }
} finally {
  foreach ($name in $script:SavedEnvironment.Keys) {
    [Environment]::SetEnvironmentVariable($name, $script:SavedEnvironment[$name], 'Process')
  }
  Remove-Item Function:\aws -ErrorAction SilentlyContinue
  Remove-Item Function:\tar.exe -ErrorAction SilentlyContinue
  Remove-Item Function:\Start-Sleep -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $script:TestRoot -Recurse -Force -ErrorAction SilentlyContinue
  Remove-Variable PublishWorld -Scope Global -ErrorAction SilentlyContinue
}
if ($script:Failures) { throw "$script:Failures GPU publication scenario(s) failed." }
Write-Host 'All offline GPU publication scenarios passed.'
$global:LASTEXITCODE = 0
