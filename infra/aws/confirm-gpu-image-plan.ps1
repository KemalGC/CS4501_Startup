# Read-only review of a replacement image on the existing idle G4dn stack.
# Reuse the migration validator's strict plan/live-state checks in image mode.
[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$PlanPath,
  [Parameter(Mandatory=$true)][string]$ExpectedAccountId,
  [Parameter(Mandatory=$true)][string]$ExpectedSubnetId,
  [Parameter(Mandatory=$true)][string]$ExpectedPreviousImageUri,
  [Parameter(Mandatory=$true)][string]$ExpectedImageUri,
  [string]$AwsProfile = 'strokesense-admin',
  [switch]$VerifyApplied
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'confirm-gpu-instance-plan.ps1') @PSBoundParameters -ChangeKind Image -ExpectedInstanceType g4dn.xlarge
