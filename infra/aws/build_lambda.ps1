# Build the StrokeSense AWS API Lambda ZIP from Windows PowerShell.
# This prepares a local artifact only: it never changes AWS or Vercel.
param(
    [string]$PythonCommand = "python"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$sourceDir = Join-Path $repoRoot "strokesense/aws_app"
$distDir = Join-Path $PSScriptRoot "dist"
$archive = Join-Path $distDir "strokesense-api-lambda.zip"
$stage = Join-Path ([System.IO.Path]::GetTempPath()) ("strokesense-api-" + [guid]::NewGuid().ToString("N"))

New-Item -ItemType Directory -Path $stage -Force | Out-Null
try {
    New-Item -ItemType Directory -Path (Join-Path $stage "aws_app") -Force | Out-Null

    & $PythonCommand -m pip install --disable-pip-version-check `
        -r (Join-Path $sourceDir "requirements.txt") -t $stage
    if ($LASTEXITCODE -ne 0) {
        throw "Could not install Python Lambda dependencies."
    }

    Get-ChildItem -LiteralPath $sourceDir -File -Filter "*.py" |
        Where-Object { $_.Name -notlike "test_*" } |
        ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $stage "aws_app") }

    New-Item -ItemType Directory -Path $distDir -Force | Out-Null
    Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $archive -Force
    Write-Output "Built AWS API Lambda ZIP: $archive"
}
finally {
    # The only recursive deletion targets the unique temporary directory this
    # invocation just created. Existing AWS state and infrastructure are safe.
    if (Test-Path -LiteralPath $stage) {
        Remove-Item -LiteralPath $stage -Recurse -Force
    }
}
