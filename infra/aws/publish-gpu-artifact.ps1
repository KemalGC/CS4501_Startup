# Publish the already-tested OCI archive through the Windows AWS CLI. This avoids
# Docker Desktop's upload proxy; it does not build an image or allocate a GPU.
[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][ValidatePattern('^\d{12}$')][string]$ExpectedAccountId,
  [ValidatePattern('^[A-Za-z0-9_.-]{1,64}$')][string]$AwsProfile = 'strokesense-admin',
  [string]$ArtifactDirectory = (Join-Path $env:USERPROFILE 'Downloads\strokesense-gpu-8cbcda3'),
  [ValidatePattern('^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$')][string]$ImageTag = 'gpu-8cbcda3-45085705233-1',
  [ValidatePattern('^[a-f0-9]{40}$')][string]$ExpectedSourceCommit = '8cbcda3ee68a973f67e8617275cc7aa4f2cd8ba0',
  [ValidatePattern('^[a-f0-9]{64}$')][string]$ExpectedArchiveSha256 = '9827ce7430ff29fd775e71647ff9f4e9fb654159bb734d52c892ba0441a9fe16',
  [long]$ExpectedArchiveSizeBytes = 2708980929,
  [ValidatePattern('^sha256:[a-f0-9]{64}$')][string]$ExpectedIndexDigest = 'sha256:060542a493c83413a45832e6975857bbb2da6c0e5b25919fe85155f5760815f1',
  [ValidatePattern('^sha256:[a-f0-9]{64}$')][string]$ExpectedManifestDigest = 'sha256:cc21a77a44f767fa61ff347ba91e748b3d2acc0914f24a10de54a4a4dc74df16',
  [ValidatePattern('^sha256:[a-f0-9]{64}$')][string]$ExpectedConfigDigest = 'sha256:04759f652c8952314ed496f5c0ef464ec472b44f29d92c3b8ddab9c442ce941c'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Remove-Item Env:TF_VAR_gpu_worker_image_uri -ErrorAction SilentlyContinue
$region = 'us-east-1'
$repository = 'strokesense-aws-dev-gpu-worker'
$temporaryDirectory = $null
$utf8 = New-Object System.Text.UTF8Encoding($false, $true)

function Get-Field($Object, [string]$Name) {
  if ($null -ne $Object -and $Object.PSObject.Properties[$Name]) { return $Object.$Name }
  return $null
}
function Invoke-PublishNative([string]$Command, [string[]]$Arguments) {
  $savedPreference = $ErrorActionPreference
  try {
    $ErrorActionPreference = 'Continue'
    $raw = & $Command @Arguments 2>&1
    $code = $LASTEXITCODE
  } finally { $ErrorActionPreference = $savedPreference }
  # Out-String formats PS5.1 NativeCommandError records and corrupts stderr JSON.
  $text = (@($raw | ForEach-Object { $_.ToString() }) -join "`n").Trim()
  [pscustomobject]@{ ExitCode = $code; Text = $text }
}
function Invoke-PublishAws([string[]]$Arguments) {
  $native = Invoke-PublishNative 'aws' ($Arguments + @('--profile',$AwsProfile,'--region',$region,
    '--output','json','--no-cli-pager','--no-cli-auto-prompt','--cli-error-format','json',
    '--cli-connect-timeout','10','--cli-read-timeout','60'))
  $value = $null
  try { $value = $native.Text | ConvertFrom-Json -ErrorAction Stop }
  catch { if ($native.ExitCode -eq 0) { throw 'AWS returned invalid JSON; no successful result accepted.' } }
  if ($native.ExitCode -eq 0 -and $null -eq $value) { throw 'AWS returned an empty result.' }
  [pscustomobject]@{ ExitCode = $native.ExitCode; Data = $value; Diagnostic = $native.Text }
}
function Assert-AwsSuccess($Response, [string]$Action) {
  if ($Response.ExitCode -ne 0) {
    if ($Action -eq 'sts get-caller-identity' -and
        $Response.Diagnostic -match '(?is)(?:(unknown options|unrecognized arguments|invalid option).*--cli-error-format|--cli-error-format.*invalid choice)') {
      throw 'Update AWS CLI v2 to a version supporting --cli-error-format json, then rerun. No upload was attempted.'
    }
    $detail = ($Response.Diagnostic -replace '\s+', ' ').Trim()
    if ($detail.Length -gt 500) { $detail = $detail.Substring(0, 500) }
    throw "AWS $Action failed (exit $($Response.ExitCode)): $detail"
  }
}
function Read-PublishAws([string[]]$Arguments) {
  $response = Invoke-PublishAws $Arguments
  Assert-AwsSuccess $response ($Arguments[0] + ' ' + $Arguments[1])
  return $response.Data
}
function Get-Utf8Digest([string]$Text) {
  $hasher = [System.Security.Cryptography.SHA256]::Create()
  try { return 'sha256:' + [BitConverter]::ToString($hasher.ComputeHash($utf8.GetBytes($Text))).Replace('-','').ToLowerInvariant() }
  finally { $hasher.Dispose() }
}
function Read-JsonFile([string]$Path) {
  return ([System.IO.File]::ReadAllText($Path, $utf8) | ConvertFrom-Json -ErrorAction Stop)
}
function Assert-PositiveInteger($Value, [string]$Name) {
  if ($null -eq $Value -or $Value -isnot [ValueType] -or $Value -is [bool] -or
      [double]::IsNaN([double]$Value) -or [double]::IsInfinity([double]$Value) -or
      [double]$Value -le 0 -or [Math]::Floor([double]$Value) -ne [double]$Value) { throw "Invalid $Name." }
}
function Get-BlobPath([string]$Digest) {
  return Join-Path $temporaryDirectory ('blobs/sha256/' + $Digest.Substring(7))
}
function Assert-Blob([string]$Digest, [long]$Size = -1) {
  $path = Get-BlobPath $Digest
  $item = Get-Item -LiteralPath $path -ErrorAction Stop
  if ($item.PSIsContainer -or ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -or
      ($Size -ge 0 -and $item.Length -ne $Size) -or
      ('sha256:' + (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()) -cne $Digest) {
    throw "Extracted blob size/type/SHA256 mismatch: $Digest"
  }
}
function Expand-Blobs([string[]]$Digests) {
  $selected = @()
  foreach ($digest in $Digests) {
    if (Test-Path -LiteralPath (Get-BlobPath $digest)) { Assert-Blob $digest; continue }
    if (!$archiveEntries.ContainsKey($digest)) { throw "Exact OCI blob missing from archive: $digest. No recompression or rebuild attempted." }
    $selected += $archiveEntries[$digest]
  }
  if ($selected.Count -gt 0) {
    Write-Host "Extracting $($selected.Count) exact OCI blobs; reading the compressed archive can take a few minutes..."
    $result = Invoke-PublishNative 'tar.exe' (@('-xf',$archive,'-C',$temporaryDirectory) + $selected)
    if ($result.ExitCode -ne 0) { throw "Cannot extract selected OCI blobs: $($result.Text)" }
    foreach ($digest in $Digests) { Assert-Blob $digest }
  }
}
function Read-RemoteImage([string]$ImageId, [switch]$AllowMissing) {
  $response = Read-PublishAws @('ecr','batch-get-image','--registry-id',$ExpectedAccountId,
    '--repository-name',$repository,'--image-ids',$ImageId,'--accepted-media-types','application/vnd.oci.image.manifest.v1+json')
  if (!$response.PSObject.Properties['images'] -or $null -eq $response.images -or
      !$response.PSObject.Properties['failures'] -or $null -eq $response.failures) { throw 'Incomplete ECR image lookup.' }
  if (@($response.images).Count -eq 0 -and $AllowMissing -and @($response.failures).Count -eq 1 -and
      (Get-Field $response.failures[0] 'failureCode') -eq 'ImageNotFound' -and
      (Get-Field (Get-Field $response.failures[0] 'imageId') 'imageTag') -ceq $ImageTag) { return $null }
  if (@($response.images).Count -ne 1 -or @($response.failures).Count -ne 0) { throw 'ECR did not return exactly one complete image.' }
  $image = $response.images[0]
  if ((Get-Field $image 'registryId') -ne $ExpectedAccountId -or (Get-Field $image 'repositoryName') -ne $repository -or
      (Get-Field (Get-Field $image 'imageId') 'imageDigest') -cne $ExpectedManifestDigest) { throw 'ECR image identity/digest differs from the tested amd64 manifest.' }
  if ($ImageId.StartsWith('imageTag=') -and (Get-Field $image.imageId 'imageTag') -cne $ImageTag) { throw 'ECR returned a different image tag.' }
  return $image
}
function Get-MissingBlobs([object[]]$Descriptors) {
  $wanted = @{}
  foreach ($descriptor in $Descriptors) { $wanted[$descriptor.digest] = $descriptor }
  $response = Read-PublishAws (@('ecr','batch-check-layer-availability','--registry-id',$ExpectedAccountId,
    '--repository-name',$repository,'--layer-digests') + @($wanted.Keys))
  if (!$response.PSObject.Properties['layers'] -or $null -eq $response.layers -or
      !$response.PSObject.Properties['failures'] -or $null -eq $response.failures) { throw 'Incomplete ECR blob availability response.' }
  $seen = @{}; $missing = @()
  foreach ($layer in @($response.layers)) {
    $digest = Get-Field $layer 'layerDigest'
    if (!$digest -or !$wanted.ContainsKey($digest) -or $seen.ContainsKey($digest)) { throw 'Unexpected or duplicate ECR blob availability entry.' }
    $seen[$digest] = $true
    switch (Get-Field $layer 'layerAvailability') {
      'AVAILABLE' {
        $size = Get-Field $layer 'layerSize'; Assert-PositiveInteger $size 'ECR blob size'
        if ($size -ne $wanted[$digest].size) { throw "ECR blob size mismatch: $digest" }
      }
      'UNAVAILABLE' { $missing += $wanted[$digest] }
      default { throw "ECR blob is not usable: $digest ($($layer.layerAvailability))." }
    }
  }
  foreach ($failure in @($response.failures)) {
    $digest = Get-Field $failure 'layerDigest'
    if (!$digest -or !$wanted.ContainsKey($digest) -or $seen.ContainsKey($digest) -or
        (Get-Field $failure 'failureCode') -ne 'MissingLayerDigest') { throw 'Unexpected ECR blob availability failure.' }
    $seen[$digest] = $true; $missing += $wanted[$digest]
  }
  if ($seen.Count -ne $wanted.Count) { throw 'ECR omitted a requested blob from its availability response.' }
  return $missing
}
function Test-UploadIdentity($Value, [string]$UploadId) {
  return ((Get-Field $Value 'registryId') -eq $ExpectedAccountId -and
    (Get-Field $Value 'repositoryName') -eq $repository -and (Get-Field $Value 'uploadId') -eq $UploadId)
}
function Test-ByteOffset($Value, [long]$Expected) {
  return (($Value -is [int] -or $Value -is [long]) -and $Value -ge 0 -and $Value -eq $Expected)
}
function Test-TransientFailure($Response) {
  $code = Get-Field $Response.Data 'Code'
  if ($code) { return $code -in @('ServerException','ThrottlingException','TooManyRequestsException','RequestTimeout','ServiceUnavailableException','InternalFailure') }
  # AWS CLI generic/transport exceptions remain plain text even with JSON errors.
  return $Response.Diagnostic -match '(?i)(connection (was )?(closed|reset|aborted)|read timed? ?out|connect timed? ?out|could not connect to the endpoint|remote end closed|broken pipe|EOF occurred in violation of protocol)'
}
function Send-Blob($Descriptor) {
  $digest = $Descriptor.digest; $length = [long]$Descriptor.size
  Assert-Blob $digest $length
  Write-Host "Uploading $digest ($length bytes) through the AWS CLI..."
  $started = Read-PublishAws @('ecr','initiate-layer-upload','--registry-id',$ExpectedAccountId,'--repository-name',$repository)
  $uploadId = Get-Field $started 'uploadId'; $partSize = Get-Field $started 'partSize'
  Assert-PositiveInteger $partSize 'ECR upload part size'
  # The API schema says 20 MiB; ECR's direct-upload quota says 10 MiB. Stay within both.
  if ($uploadId -notmatch '^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$' -or $partSize -lt 5MB -or $partSize -gt 10MB) { throw 'Unsupported ECR upload ID or part size; no layer parts sent.' }
  $stream = [System.IO.File]::OpenRead((Get-BlobPath $digest))
  $partPath = Join-Path $temporaryDirectory 'upload-part.bin'
  try {
    [long]$offset = 0
    while ($offset -lt $length) {
      $count = [int][Math]::Min([long]$partSize, $length - $offset)
      $buffer = New-Object byte[] $count
      $read = 0
      while ($read -lt $count) {
        $received = $stream.Read($buffer, $read, $count - $read)
        if ($received -eq 0) { throw 'Unexpected end of verified blob.' }
        $read += $received
      }
      [System.IO.File]::WriteAllBytes($partPath, $buffer)
      $last = $offset + $count - 1
      $partArgs = @('ecr','upload-layer-part','--registry-id',$ExpectedAccountId,'--repository-name',$repository,
        '--upload-id',$uploadId,'--part-first-byte',"$offset",'--part-last-byte',"$last",'--layer-part-blob',"fileb://$partPath")
      for ($attempt = 1; $attempt -le 3; $attempt++) {
        $reply = Invoke-PublishAws $partArgs
        if ($reply.ExitCode -eq 0) {
          if (!(Test-UploadIdentity $reply.Data $uploadId) -or !(Test-ByteOffset (Get-Field $reply.Data 'lastByteReceived') $last)) {
            throw "Invalid ECR part acknowledgement for upload $uploadId, bytes $offset-$last."
          }
          break
        }
        if ((Get-Field $reply.Data 'Code') -eq 'InvalidLayerPartException' -and (Test-UploadIdentity $reply.Data $uploadId) -and
            (Test-ByteOffset (Get-Field $reply.Data 'lastValidByteReceived') $last)) { break }
        if ($attempt -eq 3 -or !(Test-TransientFailure $reply)) { Assert-AwsSuccess $reply "upload-layer-part ($uploadId, bytes $offset-$last)" }
        Start-Sleep -Seconds (2 * $attempt)
      }
      $offset += $count
      Write-Host ("Uploaded {0}/{1} bytes of {2}" -f $offset, $length, $digest)
    }
  } finally { $stream.Dispose(); Remove-Item -LiteralPath $partPath -Force -ErrorAction SilentlyContinue }
  $completed = Invoke-PublishAws @('ecr','complete-layer-upload','--registry-id',$ExpectedAccountId,
    '--repository-name',$repository,'--upload-id',$uploadId,'--layer-digests',$digest)
  if ($completed.ExitCode -eq 0 -and (!(Test-UploadIdentity $completed.Data $uploadId) -or
      (Get-Field $completed.Data 'layerDigest') -cne $digest)) { throw 'Unexpected ECR completion acknowledgement.' }
  $stillMissing = @(Get-MissingBlobs @($Descriptor))
  if ($stillMissing.Count -ne 0) {
    Assert-AwsSuccess $completed 'complete-layer-upload'
    throw "Completed blob is not available in ECR: $digest"
  }
}

$savedEnvironment = @{}
foreach ($name in @('PYTHONIOENCODING','AWS_CLI_FILE_ENCODING','AWS_MAX_ATTEMPTS')) { $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
$savedConsoleEncoding = [Console]::OutputEncoding
try {
  $env:PYTHONIOENCODING = 'utf-8'; $env:AWS_CLI_FILE_ENCODING = 'UTF-8'; $env:AWS_MAX_ATTEMPTS = '1'
  [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
  foreach ($command in @('aws','tar.exe')) { if (!(Get-Command $command -ErrorAction SilentlyContinue)) { throw "$command is required." } }
  $identity = Read-PublishAws @('sts','get-caller-identity')
  if ((Get-Field $identity 'Account') -ne $ExpectedAccountId) { throw 'Wrong AWS account; no upload attempted.' }
  $archive = Join-Path $ArtifactDirectory 'strokesense-gpu-image.tar.gz'
  $metadata = Read-JsonFile (Join-Path $ArtifactDirectory 'image-manifest.json')
  if ($ExpectedArchiveSizeBytes -le 0 -or $metadata.source_commit -cne $ExpectedSourceCommit -or
      $metadata.source_repository -cne 'https://github.com/KemalGC/CS4501_Startup' -or
      $metadata.image_id -cne $ExpectedIndexDigest -or $metadata.platform -cne 'linux/amd64' -or
      $metadata.archive_file -cne 'strokesense-gpu-image.tar.gz' -or
      $metadata.archive_sha256 -cne $ExpectedArchiveSha256 -or $metadata.archive_size_bytes -ne $ExpectedArchiveSizeBytes) { throw 'Artifact provenance does not match the reviewed build.' }
  Write-Host 'Verifying the downloaded archive checksum...'
  if ((Get-Item -LiteralPath $archive).Length -ne $ExpectedArchiveSizeBytes -or
      (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -cne $ExpectedArchiveSha256) { throw 'Archive size/SHA256 mismatch.' }
  Write-Host 'Checking OCI archive entries; this reads the compressed archive...'
  $listed = Invoke-PublishNative 'tar.exe' @('-tf',$archive)
  if ($listed.ExitCode -ne 0) { throw "Cannot list the verified archive: $($listed.Text)" }
  $archiveEntries = @{}
  foreach ($entry in ($listed.Text -split "`n")) {
    $entry = $entry.TrimEnd("`r")
    if ($entry -cmatch '^(?:\./)?blobs/sha256/([a-f0-9]{64})$') {
      $digest = 'sha256:' + $Matches[1]
      if ($archiveEntries.ContainsKey($digest)) { throw "Duplicate OCI archive member: $digest" }
      $archiveEntries[$digest] = $entry
    }
  }
  $temporaryDirectory = Join-Path ([System.IO.Path]::GetTempPath()) ('strokesense-ecr-recovery-' + [guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Path $temporaryDirectory | Out-Null
  Expand-Blobs @($ExpectedIndexDigest,$ExpectedManifestDigest,$ExpectedConfigDigest)
  $index = Read-JsonFile (Get-BlobPath $ExpectedIndexDigest)
  $manifest = Read-JsonFile (Get-BlobPath $ExpectedManifestDigest)
  $configuration = Read-JsonFile (Get-BlobPath $ExpectedConfigDigest)
  $amd64 = @($index.manifests | Where-Object { (Get-Field $_ 'digest') -ceq $ExpectedManifestDigest -and
    (Get-Field (Get-Field $_ 'platform') 'os') -ceq 'linux' -and (Get-Field (Get-Field $_ 'platform') 'architecture') -ceq 'amd64' })
  if ($index.schemaVersion -ne 2 -or $amd64.Count -ne 1 -or $manifest.schemaVersion -ne 2 -or
      $manifest.mediaType -cne 'application/vnd.oci.image.manifest.v1+json' -or $manifest.config.digest -cne $ExpectedConfigDigest -or
      $configuration.os -cne 'linux' -or $configuration.architecture -cne 'amd64' -or
      $configuration.config.User -cne '10001:10001' -or $configuration.config.Labels.'org.opencontainers.image.revision' -cne $ExpectedSourceCommit) { throw 'OCI index/manifest/config do not identify the expected non-root amd64 worker.' }
  Assert-PositiveInteger $amd64[0].size 'manifest descriptor size'
  Assert-Blob $ExpectedManifestDigest ([long]$amd64[0].size)
  $descriptors = @($manifest.config) + @($manifest.layers)
  if (@($manifest.layers).Count -eq 0 -or @($manifest.layers).Count -ne @($configuration.rootfs.diff_ids).Count) { throw 'Image layer/diffID count mismatch.' }
  $unique = @{}
  foreach ($descriptor in $descriptors) {
    if ($descriptor.digest -cnotmatch '^sha256:[a-f0-9]{64}$') { throw 'Invalid OCI blob digest.' }
    Assert-PositiveInteger $descriptor.size 'OCI descriptor size'
    if ($unique.ContainsKey($descriptor.digest) -and $unique[$descriptor.digest].size -ne $descriptor.size) { throw 'Conflicting OCI blob descriptors.' }
    $unique[$descriptor.digest] = $descriptor
  }
  Assert-Blob $ExpectedConfigDigest ([long]$manifest.config.size)
  $existing = Read-RemoteImage "imageTag=$ImageTag" -AllowMissing
  $put = $null
  if ($null -eq $existing) {
    $missing = @(Get-MissingBlobs @($unique.Values))
    Write-Host "$($missing.Count) referenced blobs need upload; existing ECR blobs will be reused."
    Expand-Blobs @($missing | ForEach-Object { $_.digest })
    foreach ($descriptor in $missing) {
      if ((Get-Item -LiteralPath (Get-BlobPath $descriptor.digest)).Length -ne $descriptor.size) {
        throw "Extracted OCI blob size mismatch: $($descriptor.digest). No uploads started."
      }
    }
    foreach ($descriptor in $missing) { Send-Blob $descriptor }
    if (@(Get-MissingBlobs @($unique.Values)).Count -ne 0) { throw 'An image blob is still unavailable; no manifest published.' }
    $put = Invoke-PublishAws @('ecr','put-image','--registry-id',$ExpectedAccountId,'--repository-name',$repository,
      '--image-tag',$ImageTag,'--image-manifest',('file://' + (Get-BlobPath $ExpectedManifestDigest)),
      '--image-manifest-media-type',$manifest.mediaType,'--image-digest',$ExpectedManifestDigest)
    # A lost response or an immutable-tag race is resolved by the independent readback below.
    if ($put.ExitCode -ne 0) { Write-Warning 'PutImage did not acknowledge success; verifying the exact destination before accepting publication.' }
  } else { Write-Host 'The target tag already has the expected manifest; verifying it without another upload.' }
  try {
    $null = Read-RemoteImage "imageTag=$ImageTag"
    $published = Read-RemoteImage "imageDigest=$ExpectedManifestDigest"
    $rawManifest = Get-Field $published 'imageManifest'
    if ($rawManifest -isnot [string] -or (Get-Utf8Digest $rawManifest) -cne $ExpectedManifestDigest -or
        ($rawManifest | ConvertFrom-Json).config.digest -cne $ExpectedConfigDigest) { throw 'ECR manifest bytes/config differ from the reviewed artifact.' }
  } catch {
    if ($null -ne $put -and $put.ExitCode -ne 0) { Assert-AwsSuccess $put 'put-image (independent readback also failed)' }
    throw
  }
  Write-Host "Published tag: $ImageTag"
  Write-Host "Verified ECR digest: $ExpectedManifestDigest"
  $ready = & (Join-Path $PSScriptRoot 'prepare-gpu-smoke.ps1') -ExpectedAccountId $ExpectedAccountId -AwsProfile $AwsProfile -ImageTag $ImageTag -ExpectedImageDigest $ExpectedManifestDigest
  $expectedUri = "${ExpectedAccountId}.dkr.ecr.${region}.amazonaws.com/${repository}@${ExpectedManifestDigest}"
  if ((Get-Field $ready 'ReadyForPlan') -ne $true -or (Get-Field $ready 'ImageUri') -cne $expectedUri -or
      $env:TF_VAR_gpu_worker_image_uri -cne $expectedUri) { throw 'Image published, but readiness checks are incomplete; Terraform image variable cleared.' }
  $ready
} catch {
  Remove-Item Env:TF_VAR_gpu_worker_image_uri -ErrorAction SilentlyContinue
  throw
} finally {
  foreach ($name in $savedEnvironment.Keys) { [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process') }
  [Console]::OutputEncoding = $savedConsoleEncoding
  if ($temporaryDirectory -and (Test-Path -LiteralPath $temporaryDirectory)) {
    try { Remove-Item -LiteralPath $temporaryDirectory -Recurse -Force }
    catch { Remove-Item Env:TF_VAR_gpu_worker_image_uri -ErrorAction SilentlyContinue; throw }
  }
}
