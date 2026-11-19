# Offline, zero-AWS-write preflight for the AWS Batch CPU container.
# Example from the repository root:
#   .\infra\aws\benchmark-cpu-worker.ps1 -VideoPath 'C:\Users\kemal\Videos\my-real-clip.mp4'
param(
    [Parameter(Mandatory = $true)]
    [string]$VideoPath,

    [string]$ImageTag = 'strokesense-aws-cpu:smoke'
)

$ErrorActionPreference = 'Stop'

$sample = Get-Item -LiteralPath $VideoPath -ErrorAction Stop
if ($sample.PSIsContainer) {
    throw 'VideoPath must identify a video file, not a directory.'
}
if ($sample.Extension.ToLowerInvariant() -notin @('.mp4', '.mov', '.webm')) {
    throw 'Only MP4, MOV and WebM clips are supported.'
}
if ($sample.Length -le 0 -or $sample.Length -gt 100000000) {
    throw 'The real-video CPU benchmark requires a nonempty file no larger than 100 MB.'
}

$strokesenseDir = (Resolve-Path (Join-Path $PSScriptRoot '..\..\strokesense')).Path
$reportDir = Join-Path $env:TEMP ("strokesense-cpu-benchmark-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $reportDir | Out-Null

$dockerOs = docker info --format '{{.OSType}}'
if ($LASTEXITCODE -ne 0 -or $dockerOs.Trim() -ne 'linux') {
    throw 'Start Docker Desktop in Linux-container mode before benchmarking.'
}

Write-Host 'Building the CPU image for AWS Fargate linux/amd64...'
docker build --platform linux/amd64 -f (Join-Path $strokesenseDir 'Dockerfile.aws-cpu') -t $ImageTag $strokesenseDir
if ($LASTEXITCODE -ne 0) {
    throw 'Docker image build failed. Do not push an unverified image to ECR.'
}

$inputMount = "type=bind,source=$($sample.DirectoryName),target=/input,readonly"
$outputMount = "type=bind,source=$reportDir,target=/output"

Write-Host 'Running real-video inference with AWS Batch limits (2 vCPUs, 4 GiB)...'
$watch = [System.Diagnostics.Stopwatch]::StartNew()
docker run --rm --platform linux/amd64 --cpus=2 --memory=4g --pids-limit=256 `
    --mount $inputMount --mount $outputMount `
    --entrypoint python $ImageTag -m strokesense.cli "/input/$($sample.Name)" `
    --out /output --fps 10 --dominant-crew --threads 2 --fresh --bounded-media
$runExit = $LASTEXITCODE
$watch.Stop()
if ($runExit -ne 0) {
    throw "The container exited $runExit after $([int]$watch.Elapsed.TotalSeconds) seconds. Do not publish it. Diagnostic output is in $reportDir."
}

$reports = @(Get-ChildItem -LiteralPath $reportDir -Recurse -File -Filter 'report.html')
if ($reports.Count -ne 1) {
    throw "Expected exactly one report.html, found $($reports.Count). Do not publish the image."
}
$metricsPath = Join-Path $reports[0].DirectoryName 'metrics.json'
if (-not (Test-Path -LiteralPath $metricsPath -PathType Leaf)) {
    throw 'The CLI did not generate metrics.json. Do not publish the image.'
}

# Invoke exactly the same validation that the real Batch worker executes
# before writing report.json to S3 (bounds, metrics shape, nonzero strokes).
$validateCode = "from pathlib import Path; from aws_app.worker import _report_payload; payload = _report_payload(Path('/output'), '0' * 32); print('Validated worker JSON bytes:', len(payload))"
docker run --rm --platform linux/amd64 --cpus=2 --memory=4g `
    --mount $outputMount --entrypoint python $ImageTag -c $validateCode
if ($LASTEXITCODE -ne 0) {
    throw 'The real AWS worker rejected the generated report. Do not publish the image.'
}

$metrics = Get-Content -LiteralPath $metricsPath -Raw | ConvertFrom-Json
$usableStrokeCount = 0
foreach ($rower in $metrics.rowers) {
    if ($null -ne $rower.strokes) {
        $usableStrokeCount += @($rower.strokes).Count
    }
}
if ($usableStrokeCount -le 0) {
    throw 'The real clip produced no usable strokes. Try a clear, permission-cleared rowing clip.'
}

Write-Host 'CPU container benchmark PASSED.'
Write-Host "Elapsed seconds: $([math]::Round($watch.Elapsed.TotalSeconds, 1))"
Write-Host "Usable strokes: $usableStrokeCount"
Write-Host "Image tag: $ImageTag"
Write-Host "Reports: $reportDir"
Write-Host 'No AWS resources were created or charged by this script.'
