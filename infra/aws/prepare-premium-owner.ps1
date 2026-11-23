# Resolve the verified Premium owner and prepare only the two identity inputs.
# Reads AWS configuration; -EnsureAdminGroup additionally permits adding this
# verified existing user to the existing strokesense-admin group. No Terraform,
# entitlement database writes, GPU launches, billing, or compute flags change.
[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][ValidatePattern('^[0-9]{12}$')][string]$ExpectedAccountId,
  [ValidatePattern('^[A-Za-z0-9_.-]{1,64}$')][string]$AwsProfile = 'strokesense-admin',
  [ValidatePattern('^[a-z]{2}(-[a-z]+)+-[0-9]+$')][string]$Region = 'us-east-1',
  [ValidatePattern('^[a-z0-9-]+_[A-Za-z0-9]+$')][string]$ExpectedUserPoolId = 'us-east-1_SACxYjDH5',
  [string]$OwnerEmail = 'kemalgcortuk@gmail.com',
  [ValidatePattern('^[A-Za-z0-9_-]{1,64}$')][string]$ApiFunctionName = 'strokesense-aws-dev-api',
  [switch]$EnsureAdminGroup
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$adminGroup = 'strokesense-admin'
$uuidPattern = '^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$'
$temporaryDirectory = $null
$savedOwnerSub = [Environment]::GetEnvironmentVariable('TF_VAR_premium_owner_sub', 'Process')
$savedAdminSubs = [Environment]::GetEnvironmentVariable('TF_VAR_admin_cognito_subs', 'Process')
$savedPythonEncoding = [Environment]::GetEnvironmentVariable('PYTHONIOENCODING', 'Process')
$savedConsoleEncoding = [Console]::OutputEncoding
$inputsAssigned = $false
$completed = $false

function Get-PremiumField($Object, [string]$Name) {
  if ($null -ne $Object -and $Object.PSObject.Properties[$Name]) { return $Object.$Name }
  return $null
}

function Restore-PremiumEnvironment([string]$Name, $Value) {
  # PowerShell 7.5+ can preserve empty environment variables. Passing $null
  # through a .NET string argument can otherwise restore an absent value as
  # an empty one; preserve absence explicitly on every supported shell.
  if ($null -eq $Value) { Remove-Item "Env:$Name" -ErrorAction SilentlyContinue }
  else { [Environment]::SetEnvironmentVariable($Name, $Value, 'Process') }
}

function Invoke-PremiumAwsJson {
  param([Parameter(Mandatory=$true)][string[]]$Arguments, [switch]$AllowEmpty)
  $savedPreference = $ErrorActionPreference
  try {
    # PS5.1 wraps native stderr in ErrorRecords. Read the exit code ourselves;
    # do not let a nonterminating stderr line hide the original AWS failure.
    $ErrorActionPreference = 'Continue'
    $raw = & aws @Arguments --profile $AwsProfile --region $Region --output json --no-cli-pager --no-cli-auto-prompt --cli-connect-timeout 10 --cli-read-timeout 30 2>&1
    $code = $LASTEXITCODE
  } finally { $ErrorActionPreference = $savedPreference }
  $text = (@($raw | ForEach-Object {
    if ($_ -is [System.Management.Automation.ErrorRecord]) { [string]$_.Exception.Message }
    else { [string]$_ }
  }) -join "`n").Trim()
  if ($code -ne 0) {
    $detail = ($text -replace '\s+', ' ').Trim()
    if ($detail.Length -gt 400) { $detail = $detail.Substring(0, 400) }
    throw "AWS $($Arguments[0]) $($Arguments[1]) failed (exit $code): $detail"
  }
  if (!$text -and $AllowEmpty) { return [pscustomobject]@{} }
  try { $value = $text | ConvertFrom-Json -ErrorAction Stop }
  catch { throw "AWS $($Arguments[0]) $($Arguments[1]) returned invalid JSON." }
  if ($null -eq $value -or $value -isnot [pscustomobject]) {
    throw "AWS $($Arguments[0]) $($Arguments[1]) returned an invalid object."
  }
  return $value
}

function Invoke-PremiumCognito {
  param([string]$Action, [hashtable]$InputData, [switch]$AllowEmpty)
  # A file avoids PowerShell 5.1/7 differences in native embedded-quote
  # handling. It contains only lookup/group request fields, never credentials.
  $path = Join-Path $temporaryDirectory ([guid]::NewGuid().ToString('N') + '.json')
  try {
    $json = ConvertTo-Json -InputObject $InputData -Depth 6 -Compress
    [IO.File]::WriteAllText($path, $json, (New-Object Text.UTF8Encoding($false)))
    return Invoke-PremiumAwsJson -Arguments @('cognito-idp', $Action, '--cli-input-json', ('file://' + $path), '--no-paginate') -AllowEmpty:$AllowEmpty
  } finally {
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force }
  }
}

function Get-PremiumAttributes($User, [string]$FieldName) {
  if (!$User.PSObject.Properties[$FieldName] -or $User.$FieldName -isnot [array]) {
    throw 'Cognito returned missing or invalid user attributes.'
  }
  $attributes = @{}
  foreach ($attribute in @($User.$FieldName)) {
    $name = Get-PremiumField $attribute 'Name'
    $value = Get-PremiumField $attribute 'Value'
    if ($name -isnot [string] -or !$name -or $value -isnot [string] -or $attributes.ContainsKey($name)) {
      throw 'Cognito returned malformed or duplicate user attributes.'
    }
    $attributes[$name] = $value
  }
  return $attributes
}

function Assert-PremiumVerifiedUser($User, [string]$FieldName, [string]$ExpectedSub = '') {
  $attributes = Get-PremiumAttributes $User $FieldName
  $enabled = Get-PremiumField $User 'Enabled'
  $username = Get-PremiumField $User 'Username'
  if ($enabled -isnot [bool] -or !$enabled -or
      $username -isnot [string] -or !$username -or $username.Length -gt 128 -or $username -match '[\s\p{C}]' -or
      !$attributes.ContainsKey('email') -or $attributes.email -ine $OwnerEmail -or
      !$attributes.ContainsKey('email_verified') -or $attributes.email_verified -cne 'true' -or
      !$attributes.ContainsKey('sub') -or $attributes.sub -cnotmatch $uuidPattern) {
    throw 'The owner must be an enabled Cognito user with the exact verified email and a valid stable sub.'
  }
  if ($ExpectedSub -and $attributes.sub -ine $ExpectedSub) {
    throw 'Cognito identity changed between discovery and verification; no owner inputs were prepared.'
  }
  return [pscustomobject]@{ Username = $username; Sub = $attributes.sub.ToLowerInvariant() }
}

function Read-PremiumOwner {
  $users = New-Object System.Collections.ArrayList
  $seenTokens = New-Object 'System.Collections.Generic.HashSet[string]'
  $token = $null
  do {
    $filterEmail = $OwnerEmail.Replace('\', '\\').Replace('"', '\"')
    $inputData = @{ UserPoolId = $ExpectedUserPoolId; Filter = ('email = "' + $filterEmail + '"'); Limit = 60 }
    if ($token) { $inputData.PaginationToken = $token }
    $page = Invoke-PremiumCognito 'list-users' $inputData
    if (!$page.PSObject.Properties['Users'] -or $page.Users -isnot [array]) {
      throw 'Cognito user discovery returned an incomplete page.'
    }
    foreach ($user in @($page.Users)) { [void]$users.Add($user) }
    if ($users.Count -gt 1) { throw 'The owner email matches multiple Cognito users; resolve the ambiguity first.' }
    $token = Get-PremiumField $page 'PaginationToken'
    if ($null -ne $token -and ($token -isnot [string] -or !$token -or $token -match '\s' -or $token.Length -gt 8192)) {
      throw 'Cognito returned an invalid user pagination token.'
    }
    if ($token -and (!$seenTokens.Add($token) -or $seenTokens.Count -gt 100)) {
      throw 'Cognito user discovery did not complete; no identity was accepted.'
    }
  } while ($token)
  if ($users.Count -ne 1) { throw 'The owner has not been found uniquely. Sign in to StrokeSense with Google first.' }
  $candidate = Assert-PremiumVerifiedUser $users[0] 'Attributes'
  # Google users require their federated Username here, not their UUID sub.
  $fresh = Invoke-PremiumCognito 'admin-get-user' @{ UserPoolId = $ExpectedUserPoolId; Username = $candidate.Username }
  $verified = Assert-PremiumVerifiedUser $fresh 'UserAttributes' $candidate.Sub
  if ($verified.Username -cne $candidate.Username) { throw 'Cognito returned a different federated username.' }
  return $verified
}

function Read-PremiumAdminMembership([string]$Username) {
  $seenTokens = New-Object 'System.Collections.Generic.HashSet[string]'
  $token = $null
  $member = $false
  do {
    $inputData = @{ UserPoolId = $ExpectedUserPoolId; Username = $Username; Limit = 60 }
    if ($token) { $inputData.NextToken = $token }
    $page = Invoke-PremiumCognito 'admin-list-groups-for-user' $inputData
    if (!$page.PSObject.Properties['Groups'] -or $page.Groups -isnot [array]) {
      throw 'Cognito group membership could not be verified.'
    }
    foreach ($group in @($page.Groups)) {
      if ((Get-PremiumField $group 'GroupName') -ceq $adminGroup) {
        if ((Get-PremiumField $group 'UserPoolId') -cne $ExpectedUserPoolId) {
          throw 'The administrator group belongs to an unexpected user pool.'
        }
        $member = $true
      }
    }
    $token = Get-PremiumField $page 'NextToken'
    if ($null -ne $token -and ($token -isnot [string] -or !$token -or $token -match '\s' -or $token.Length -gt 8192)) {
      throw 'Cognito returned an invalid group pagination token.'
    }
    if ($token -and (!$seenTokens.Add($token) -or $seenTokens.Count -gt 100)) {
      throw 'Cognito group membership pagination did not complete.'
    }
  } while ($token)
  return $member
}

function Add-PremiumAdminSub([string]$Value, $List) {
  if (!$Value -or $Value -cnotmatch '^[A-Za-z0-9_-]{1,128}$') {
    throw 'An existing administrator sub is invalid; fix the configuration before preparing owner access.'
  }
  if ($Value -cmatch $uuidPattern) { $Value = $Value.ToLowerInvariant() }
  if (!(@($List) -ccontains $Value)) { [void]$List.Add($Value) }
}

function Assert-PremiumOwnerBinding($Value, [string]$Source, [string]$ResolvedSub) {
  if ($null -eq $Value -or $Value -ceq '') { return }
  if ($Value -isnot [string] -or $Value -cnotmatch $uuidPattern -or $Value -ine $ResolvedSub) {
    throw "The $Source Premium owner does not match the verified identity. Refusing to replace an existing owner."
  }
}

try {
  if (!(Get-Command aws -ErrorAction SilentlyContinue)) { throw 'AWS CLI v2 is required.' }
  if (!$ExpectedUserPoolId.StartsWith($Region + '_', [StringComparison]::Ordinal)) {
    throw 'The expected Cognito user pool does not belong to the selected region.'
  }
  if (!$OwnerEmail -or $OwnerEmail.Length -gt 254 -or $OwnerEmail -match '[\s\p{C}]') {
    throw 'Provide the complete owner email without spaces or invisible characters.'
  }
  try { $address = New-Object System.Net.Mail.MailAddress($OwnerEmail) }
  catch { throw 'Provide a valid complete owner email address.' }
  if ($address.Address -cne $OwnerEmail) { throw 'Provide only the complete owner email address.' }
  $OwnerEmail = $OwnerEmail.ToLowerInvariant()
  $env:PYTHONIOENCODING = 'utf-8'
  [Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
  $temporaryDirectory = Join-Path ([IO.Path]::GetTempPath()) ('strokesense-premium-owner-' + [guid]::NewGuid().ToString('N'))
  [void][IO.Directory]::CreateDirectory($temporaryDirectory)

  $identity = Invoke-PremiumAwsJson -Arguments @('sts', 'get-caller-identity')
  if ((Get-PremiumField $identity 'Account') -cne $ExpectedAccountId) { throw 'Wrong AWS account; no owner inputs were prepared.' }
  $poolResponse = Invoke-PremiumCognito 'describe-user-pool' @{ UserPoolId = $ExpectedUserPoolId }
  $pool = Get-PremiumField $poolResponse 'UserPool'
  $poolArn = "arn:aws:cognito-idp:${Region}:${ExpectedAccountId}:userpool/${ExpectedUserPoolId}"
  if ((Get-PremiumField $pool 'Id') -cne $ExpectedUserPoolId -or (Get-PremiumField $pool 'Arn') -cne $poolArn) {
    throw 'Cognito returned an unexpected user pool, region, or account.'
  }
  $owner = Read-PremiumOwner

  # Never print or fetch an unfiltered Lambda environment. These are the only
  # nonsecret configuration fields needed to preserve current access.
  $query = '{FunctionArn:FunctionArn,AdminCognitoSubs:Environment.Variables.ADMIN_COGNITO_SUBS,PremiumOwnerSub:Environment.Variables.PREMIUM_OWNER_SUB,CognitoUserPoolId:Environment.Variables.COGNITO_USER_POOL_ID}'
  $configuration = Invoke-PremiumAwsJson -Arguments @('lambda', 'get-function-configuration', '--function-name', $ApiFunctionName, '--query', $query)
  if ((Get-PremiumField $configuration 'FunctionArn') -cne "arn:aws:lambda:${Region}:${ExpectedAccountId}:function:${ApiFunctionName}") {
    throw 'The API Lambda belongs to an unexpected function, region, or account.'
  }
  $configuredPool = Get-PremiumField $configuration 'CognitoUserPoolId'
  if ($null -ne $configuredPool -and $configuredPool -cne '' -and $configuredPool -cne $ExpectedUserPoolId) {
    throw 'The API Lambda is configured for a different Cognito user pool.'
  }
  Assert-PremiumOwnerBinding (Get-PremiumField $configuration 'PremiumOwnerSub') 'deployed API' $owner.Sub
  Assert-PremiumOwnerBinding $savedOwnerSub 'Terraform environment' $owner.Sub
  Assert-PremiumOwnerBinding ([Environment]::GetEnvironmentVariable('PREMIUM_OWNER_SUB', 'Process')) 'process environment' $owner.Sub

  $adminSubs = New-Object System.Collections.ArrayList
  $liveSubs = Get-PremiumField $configuration 'AdminCognitoSubs'
  if ($null -ne $liveSubs -and $liveSubs -isnot [string]) { throw 'The deployed administrator allowlist is invalid.' }
  if ($liveSubs) {
    foreach ($sub in $liveSubs.Split(',')) { Add-PremiumAdminSub $sub.Trim() $adminSubs }
  }
  if ($null -ne $savedAdminSubs -and $savedAdminSubs -cne '') {
    if ($savedAdminSubs -notmatch '^\s*\[') { throw 'TF_VAR_admin_cognito_subs must be a JSON array of stable sub strings.' }
    try { $ambientSubs = @($savedAdminSubs | ConvertFrom-Json -ErrorAction Stop) }
    catch { throw 'TF_VAR_admin_cognito_subs must be a valid JSON array.' }
    foreach ($sub in $ambientSubs) {
      if ($sub -isnot [string]) { throw 'TF_VAR_admin_cognito_subs must contain only stable sub strings.' }
      Add-PremiumAdminSub $sub $adminSubs
    }
  }
  Add-PremiumAdminSub $owner.Sub $adminSubs
  if ($adminSubs.Count -gt 5) { throw 'The merged administrator allowlist exceeds five users; no access changes were made.' }

  $groupMember = Read-PremiumAdminMembership $owner.Username
  $groupAdded = $false
  if (!$groupMember -and $EnsureAdminGroup) {
    $groupResponse = Invoke-PremiumCognito 'get-group' @{ UserPoolId = $ExpectedUserPoolId; GroupName = $adminGroup }
    $group = Get-PremiumField $groupResponse 'Group'
    if ((Get-PremiumField $group 'GroupName') -cne $adminGroup -or (Get-PremiumField $group 'UserPoolId') -cne $ExpectedUserPoolId) {
      throw 'The existing administrator group could not be verified; no user was added.'
    }
    # Re-check current account attributes immediately before the sole optional
    # AWS write. A stale discovery result must not grant the wrong identity.
    $fresh = Invoke-PremiumCognito 'admin-get-user' @{ UserPoolId = $ExpectedUserPoolId; Username = $owner.Username }
    $confirmed = Assert-PremiumVerifiedUser $fresh 'UserAttributes' $owner.Sub
    if ($confirmed.Username -cne $owner.Username) { throw 'The owner username changed before group assignment.' }
    $null = Invoke-PremiumCognito 'admin-add-user-to-group' @{ UserPoolId = $ExpectedUserPoolId; Username = $owner.Username; GroupName = $adminGroup } -AllowEmpty
    $groupAdded = $true
    $groupMember = Read-PremiumAdminMembership $owner.Username
    if (!$groupMember) { throw 'The group addition could not be verified. Recheck membership before preparing a plan; previous Terraform inputs are unchanged.' }
  }

  $status = 'ADMIN_GROUP_REQUIRED'
  if ($groupMember) {
    $jsonAdminSubs = ConvertTo-Json -InputObject @($adminSubs) -Compress
    $inputsAssigned = $true
    [Environment]::SetEnvironmentVariable('TF_VAR_premium_owner_sub', $owner.Sub, 'Process')
    [Environment]::SetEnvironmentVariable('TF_VAR_admin_cognito_subs', $jsonAdminSubs, 'Process')
    $status = 'READY_TO_PLAN'
  }
  $result = [pscustomobject][ordered]@{
    Status = $status
    ReadyForPlan = $groupMember
    TerraformInputsSet = $groupMember
    AccountId = $ExpectedAccountId
    Region = $Region
    UserPoolId = $ExpectedUserPoolId
    OwnerSub = $owner.Sub
    AdminAllowlistCount = $adminSubs.Count
    AdminGroupMember = $groupMember
    AdminGroupAdded = $groupAdded
  }
  if ($groupMember) {
    Write-Host 'Verified Premium owner and administrator membership. The two Terraform identity inputs are set in this terminal.'
    Write-Host 'Review the complete infrastructure plan after the active GPU smoke test has cleaned up.'
    if ($groupAdded) { Write-Host 'Sign out of StrokeSense and sign in again after deployment to obtain the new administrator group claim.' }
  } else {
    Write-Warning 'The verified owner is not in strokesense-admin. Rerun with -EnsureAdminGroup to add this existing user; Terraform inputs are unchanged.'
  }
  $completed = $true
} finally {
  try {
    Restore-PremiumEnvironment 'PYTHONIOENCODING' $savedPythonEncoding
    [Console]::OutputEncoding = $savedConsoleEncoding
    if ($temporaryDirectory -and (Test-Path -LiteralPath $temporaryDirectory)) {
      Remove-Item -LiteralPath $temporaryDirectory -Recurse -Force
    }
  } catch {
    $completed = $false
    throw
  } finally {
    if ($inputsAssigned -and !$completed) {
      Restore-PremiumEnvironment 'TF_VAR_premium_owner_sub' $savedOwnerSub
      Restore-PremiumEnvironment 'TF_VAR_admin_cognito_subs' $savedAdminSubs
    }
  }
}
$result
