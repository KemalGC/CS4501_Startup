# Offline contract tests for Windows PowerShell 5.1 and PowerShell 7.
# The aws function below is the only command provider; no real AWS call runs.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:Under = Join-Path $PSScriptRoot 'prepare-premium-owner.ps1'
$script:Account = '851226124502'
$script:Pool = 'us-east-1_SACxYjDH5'
$script:OwnerSub = '12345678-1234-1234-1234-123456789abc'
$script:OtherSub = '87654321-4321-4321-4321-cba987654321'
$script:Username = 'Google_112233445566778899'
$script:Failures = 0
$script:ExpectedErrorPatterns = @{
  'native-error' = 'AWS sts get-caller-identity failed.*expired'
  'invalid-json' = 'returned invalid JSON'
  'null-json' = 'returned an invalid object'
  'wrong-account' = 'Wrong AWS account'
  'wrong-pool' = 'unexpected user pool'
  'wrong-pool-account' = 'unexpected user pool'
  'missing-user' = 'owner has not been found uniquely'
  'invalid-user-page' = 'discovery returned an incomplete page'
  'duplicate-user' = 'matches multiple Cognito users'
  'duplicate-second-page' = 'matches multiple Cognito users'
  'pagination-loop' = 'discovery did not complete'
  'stale-sub' = 'identity changed between discovery and verification'
  'stale-email' = 'exact verified email'
  'unverified' = 'exact verified email'
  'disabled' = 'enabled Cognito user'
  'invalid-sub' = 'valid stable sub'
  'wrong-username' = 'different federated username'
  'duplicate-attribute' = 'malformed or duplicate user attributes'
  'wrong-function' = 'unexpected function'
  'wrong-api-pool' = 'different Cognito user pool'
  'live-owner-conflict' = 'deployed API Premium owner does not match'
  'invalid-live-admin' = 'existing administrator sub is invalid'
  'too-many-admins' = 'allowlist exceeds five users'
  'group-read-error' = 'AWS cognito-idp admin-list-groups-for-user failed'
  'wrong-group-pool' = 'group belongs to an unexpected user pool'
  'group-missing' = 'AWS cognito-idp get-group failed'
  'disabled-before-add' = 'enabled Cognito user'
  'group-add-error' = 'AWS cognito-idp admin-add-user-to-group failed'
  'group-not-confirmed' = 'group addition could not be verified'
  'ambient-owner-conflict' = 'Terraform environment Premium owner does not match'
  'process-owner-conflict' = 'process environment Premium owner does not match'
  'invalid-ambient-admins' = 'TF_VAR_admin_cognito_subs|existing administrator sub is invalid'
}
$script:SavedEnvironment = @{}
$script:EnvironmentNames = @(
  'TF_VAR_premium_owner_sub', 'TF_VAR_admin_cognito_subs', 'PREMIUM_OWNER_SUB',
  'TF_VAR_enable_gpu', 'TF_VAR_gpu_smoke_mode', 'TF_VAR_enable_cpu_analysis',
  'TF_VAR_gpu_worker_image_uri', 'AWS_PROFILE', 'PYTHONIOENCODING'
)
foreach ($name in $script:EnvironmentNames) {
  $script:SavedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
$previousAws = Get-Item Function:\aws -ErrorAction SilentlyContinue
$script:PreviousAwsFunction = $null
if ($previousAws) { $script:PreviousAwsFunction = $previousAws.ScriptBlock }

function Assert-PremiumTest([bool]$Condition, [string]$Message) {
  if (!$Condition) { throw $Message }
}
function Read-FakeArgument([string[]]$Arguments, [string]$Name) {
  $index = [array]::IndexOf($Arguments, $Name)
  if ($index -lt 0 -or $index + 1 -ge $Arguments.Count) { throw "Missing expected AWS argument: $Name" }
  return $Arguments[$index + 1]
}
function New-FakeOwner([string]$AttributeName, [string]$Sub = $PremiumWorld.OwnerSub) {
  $result = @{
    Username = $PremiumWorld.Username; Enabled = $true
    $AttributeName = @(
      @{ Name = 'sub'; Value = $Sub },
      @{ Name = 'email'; Value = 'kemalgcortuk@gmail.com' },
      @{ Name = 'email_verified'; Value = 'true' }
    )
  }
  return $result
}
function Write-FakeNativeError([string]$Message) {
  $global:LASTEXITCODE = 255
  # Models PS5.1 native stderr, including the empty leading line that must
  # not be formatted into a fabricated RemoteException type prefix.
  foreach ($line in @('', $Message)) {
    [System.Management.Automation.ErrorRecord]::new(
      [System.Management.Automation.RemoteException]::new($line),
      'NativeCommandError', [System.Management.Automation.ErrorCategory]::NotSpecified, 'aws')
  }
}
function global:aws {
  $a = @($args | ForEach-Object { [string]$_ })
  $op = $a[0] + ' ' + $a[1]
  [void]$PremiumWorld.Calls.Add($op)
  $global:LASTEXITCODE = 0
  Assert-PremiumTest ((Read-FakeArgument $a '--profile') -ceq 'fake') 'Helper used the wrong profile.'
  Assert-PremiumTest ((Read-FakeArgument $a '--region') -ceq 'us-east-1') 'Helper used the wrong region.'
  $scenario = $PremiumWorld.Scenario
  $inputData = $null
  if ($a[0] -ceq 'cognito-idp') {
    Assert-PremiumTest ($a -contains '--no-paginate') 'Cognito pagination must be explicit.'
    $uri = Read-FakeArgument $a '--cli-input-json'
    Assert-PremiumTest ($uri.StartsWith('file://')) 'Native JSON quoting must use a temporary request file.'
    $path = $uri.Substring(7)
    [void]$PremiumWorld.InputPaths.Add($path)
    $bytes = [IO.File]::ReadAllBytes($path)
    Assert-PremiumTest (!($bytes.Length -ge 3 -and $bytes[0] -eq 239 -and $bytes[1] -eq 187 -and $bytes[2] -eq 191)) 'Input JSON has a UTF-8 BOM.'
    $inputData = [IO.File]::ReadAllText($path) | ConvertFrom-Json
    Assert-PremiumTest ($inputData.UserPoolId -ceq $PremiumWorld.Pool) 'Wrong pool in Cognito request.'
    [void]$PremiumWorld.Requests.Add(@{ Operation = $op; Input = $inputData })
  }
  switch ($op) {
    'sts get-caller-identity' {
      if ($scenario -eq 'native-error') { Write-FakeNativeError 'Your session has expired. Reauthenticate.'; return }
      if ($scenario -eq 'invalid-json') { return 'not JSON' }
      if ($scenario -eq 'null-json') { return 'null' }
      if ($scenario -eq 'wrong-account') { return '{"Account":"111111111111"}' }
      return (@{ Account = $PremiumWorld.Account } | ConvertTo-Json)
    }
    'cognito-idp describe-user-pool' {
      $id = $PremiumWorld.Pool
      $arn = "arn:aws:cognito-idp:us-east-1:$($PremiumWorld.Account):userpool/$id"
      if ($scenario -eq 'wrong-pool') { $id = 'us-east-1_Different' }
      if ($scenario -eq 'wrong-pool-account') { $arn = "arn:aws:cognito-idp:us-east-1:111111111111:userpool/$id" }
      return (@{ UserPool = @{ Id = $id; Arn = $arn } } | ConvertTo-Json)
    }
    'cognito-idp list-users' {
      $PremiumWorld.UserReads++
      Assert-PremiumTest ($inputData.Filter -ceq 'email = "kemalgcortuk@gmail.com"') 'Email filter lost quoting or became a prefix lookup.'
      $owner = New-FakeOwner 'Attributes'
      $response = @{ Users = @($owner) }
      if ($scenario -eq 'missing-user') { $response.Users = @() }
      if ($scenario -eq 'invalid-user-page') { $response.Users = $null }
      if ($scenario -eq 'duplicate-user') { $response.Users = @($owner, (New-FakeOwner 'Attributes' $PremiumWorld.OtherSub)) }
      if ($scenario -in @('second-page', 'duplicate-second-page', 'pagination-loop')) {
        if ($PremiumWorld.UserReads -eq 1) {
          $response.PaginationToken = 'users-next'
          if ($scenario -eq 'second-page') { $response.Users = @() }
        } else {
          Assert-PremiumTest ($inputData.PaginationToken -ceq 'users-next') 'User pagination token was not replayed.'
          if ($scenario -eq 'pagination-loop') { $response = @{ Users = @(); PaginationToken = 'users-next' } }
          if ($scenario -eq 'duplicate-second-page') { $response.Users = @((New-FakeOwner 'Attributes' $PremiumWorld.OtherSub)) }
        }
      }
      return ($response | ConvertTo-Json -Depth 8)
    }
    'cognito-idp admin-get-user' {
      $PremiumWorld.IdentityReads++
      Assert-PremiumTest ($inputData.Username -ceq $PremiumWorld.Username) 'A federated identity was looked up by sub instead of Google username.'
      $owner = New-FakeOwner 'UserAttributes'
      if ($scenario -eq 'stale-sub') { $owner = New-FakeOwner 'UserAttributes' $PremiumWorld.OtherSub }
      if ($scenario -eq 'stale-email') { $owner.UserAttributes[1].Value = 'different@example.com' }
      if ($scenario -eq 'unverified') { $owner.UserAttributes[2].Value = 'false' }
      if ($scenario -eq 'disabled' -or ($scenario -eq 'disabled-before-add' -and $PremiumWorld.IdentityReads -gt 1)) { $owner.Enabled = $false }
      if ($scenario -eq 'invalid-sub') { $owner.UserAttributes[0].Value = 'not-a-uuid' }
      if ($scenario -eq 'wrong-username') { $owner.Username = 'Google_other' }
      if ($scenario -eq 'duplicate-attribute') { $owner.UserAttributes += @{ Name = 'sub'; Value = $PremiumWorld.OtherSub } }
      return ($owner | ConvertTo-Json -Depth 8)
    }
    'lambda get-function-configuration' {
      Assert-PremiumTest ((Read-FakeArgument $a '--function-name') -ceq 'strokesense-aws-dev-api') 'Wrong API Lambda name.'
      $query = Read-FakeArgument $a '--query'
      $expected = '{FunctionArn:FunctionArn,AdminCognitoSubs:Environment.Variables.ADMIN_COGNITO_SUBS,PremiumOwnerSub:Environment.Variables.PREMIUM_OWNER_SUB,CognitoUserPoolId:Environment.Variables.COGNITO_USER_POOL_ID}'
      Assert-PremiumTest ($query -ceq $expected) 'Lambda read must select only safe fields, never the complete environment.'
      $response = @{
        FunctionArn = "arn:aws:lambda:us-east-1:$($PremiumWorld.Account):function:strokesense-aws-dev-api"
        AdminCognitoSubs = 'live-admin'; PremiumOwnerSub = $null; CognitoUserPoolId = $null
      }
      if ($scenario -eq 'ready-only-owner') { $response.AdminCognitoSubs = '' }
      if ($scenario -eq 'wrong-function') { $response.FunctionArn += ':alias' }
      if ($scenario -eq 'wrong-api-pool') { $response.CognitoUserPoolId = 'us-east-1_Different' }
      if ($scenario -eq 'live-owner-conflict') { $response.PremiumOwnerSub = $PremiumWorld.OtherSub }
      if ($scenario -eq 'live-owner-matches') { $response.PremiumOwnerSub = $PremiumWorld.OwnerSub.ToUpperInvariant() }
      if ($scenario -eq 'invalid-live-admin') { $response.AdminCognitoSubs = 'someone@example.com' }
      if ($scenario -eq 'too-many-admins') { $response.AdminCognitoSubs = 'admin-one,admin-two,admin-three,admin-four,admin-five' }
      return ($response | ConvertTo-Json)
    }
    'cognito-idp admin-list-groups-for-user' {
      $PremiumWorld.GroupReads++
      Assert-PremiumTest ($inputData.Username -ceq $PremiumWorld.Username) 'Group read targeted an unverified identity.'
      if ($scenario -eq 'group-read-error') { Write-FakeNativeError 'AccessDenied'; return }
      $group = @{ GroupName = 'strokesense-admin'; UserPoolId = $PremiumWorld.Pool }
      if ($scenario -eq 'wrong-group-pool') { $group.UserPoolId = 'us-east-1_Different' }
      $groups = @($group)
      if ($scenario -in @('group-absent', 'add-group', 'group-add-error', 'group-not-confirmed', 'group-missing', 'disabled-before-add')) {
        if ($PremiumWorld.AddCalls -eq 0 -or $scenario -eq 'group-not-confirmed') { $groups = @() }
      }
      $response = @{ Groups = $groups }
      if ($scenario -eq 'group-second-page' -and $PremiumWorld.GroupReads -eq 1) {
        $response = @{ Groups = @(@{ GroupName = 'another-group'; UserPoolId = $PremiumWorld.Pool }); NextToken = 'groups-next' }
      }
      if ($scenario -eq 'group-second-page' -and $PremiumWorld.GroupReads -eq 2) {
        Assert-PremiumTest ($inputData.NextToken -ceq 'groups-next') 'Group pagination token was not replayed.'
      }
      return ($response | ConvertTo-Json -Depth 6)
    }
    'cognito-idp get-group' {
      Assert-PremiumTest ($inputData.GroupName -ceq 'strokesense-admin') 'Unexpected admin group target.'
      if ($scenario -eq 'group-missing') { Write-FakeNativeError 'ResourceNotFoundException'; return }
      return (@{ Group = @{ GroupName = 'strokesense-admin'; UserPoolId = $PremiumWorld.Pool } } | ConvertTo-Json)
    }
    'cognito-idp admin-add-user-to-group' {
      $PremiumWorld.AddCalls++
      Assert-PremiumTest ($PremiumWorld.Ensure) 'Group mutation happened without -EnsureAdminGroup.'
      Assert-PremiumTest ($inputData.Username -ceq $PremiumWorld.Username -and $inputData.GroupName -ceq 'strokesense-admin') 'Group mutation targeted the wrong user/group.'
      Assert-PremiumTest ($PremiumWorld.IdentityReads -eq 2) 'Identity was not freshly verified before mutation.'
      if ($scenario -eq 'group-add-error') { Write-FakeNativeError 'AccessDenied'; return }
      # Successful AdminAddUserToGroup has no response body.
      return
    }
    default { throw "Unexpected AWS operation: $op" }
  }
}

function Invoke-PremiumCase {
  param([string]$Scenario, [bool]$Ensure = $false, [bool]$ExpectThrow = $false,
    [scriptblock]$Setup = {}, [scriptblock]$Check = {})
  $global:PremiumWorld = @{
    Scenario = $Scenario; Ensure = $Ensure
    Account = $script:Account; Pool = $script:Pool; OwnerSub = $script:OwnerSub; OtherSub = $script:OtherSub; Username = $script:Username
    Calls = New-Object System.Collections.ArrayList
    Requests = New-Object System.Collections.ArrayList
    InputPaths = New-Object System.Collections.ArrayList
    AddCalls = 0; UserReads = 0; IdentityReads = 0; GroupReads = 0
  }
  $env:TF_VAR_premium_owner_sub = $script:OwnerSub
  $env:TF_VAR_admin_cognito_subs = '["ambient-admin","live-admin"]'
  $env:PREMIUM_OWNER_SUB = $script:OwnerSub
  $env:TF_VAR_enable_gpu = 'true'
  $env:TF_VAR_gpu_smoke_mode = 'true'
  $env:TF_VAR_enable_cpu_analysis = 'true'
  $env:TF_VAR_gpu_worker_image_uri = 'existing-reviewed-image@sha256:unchanged'
  $env:AWS_PROFILE = 'ambient-profile-must-stay'
  & $Setup
  $before = @{}
  foreach ($name in $script:EnvironmentNames) { $before[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
  $beforeConsole = [Console]::OutputEncoding.CodePage
  $result = $null; $errorMessage = $null
  try {
    $result = & $script:Under -ExpectedAccountId $script:Account -AwsProfile fake -EnsureAdminGroup:$Ensure 3>$null 6>$null
  } catch { $errorMessage = $_.Exception.Message }
  try {
    Assert-PremiumTest (($null -ne $errorMessage) -eq $ExpectThrow) "Unexpected success/failure: $errorMessage"
    if ($ExpectThrow) {
      Assert-PremiumTest ($script:ExpectedErrorPatterns.ContainsKey($Scenario)) 'Negative scenario has no expected failure reason.'
      Assert-PremiumTest ($errorMessage -match $script:ExpectedErrorPatterns[$Scenario]) "Wrong failure reason: $errorMessage"
    }
    if (!$errorMessage -and $Scenario -ne 'group-absent') {
      Assert-PremiumTest ($result.ReadyForPlan -and $result.TerraformInputsSet -and $result.Status -ceq 'READY_TO_PLAN') 'Missing truthful ready result.'
      Assert-PremiumTest ($env:TF_VAR_premium_owner_sub -ceq $script:OwnerSub) 'Owner sub input was not set correctly.'
      # Root-array pipeline enumeration differs between PS5.1 and PS7. The
      # property keeps the actual array type, including a one-item result.
      $null = ConvertFrom-Json -InputObject $env:TF_VAR_admin_cognito_subs -ErrorAction Stop
      $mergedDocument = ConvertFrom-Json -InputObject ('{"subs":' + $env:TF_VAR_admin_cognito_subs + '}') -ErrorAction Stop
      $merged = $mergedDocument.subs
      Assert-PremiumTest ($merged -is [array]) 'Prepared allowlist must remain a JSON array, including a single owner.'
      foreach ($sub in $merged) { Assert-PremiumTest ($sub -is [string]) 'Prepared allowlist contains a nested array or nonstring.' }
      Assert-PremiumTest ($merged -ccontains $script:OwnerSub) 'Owner was not included in the prepared allowlist.'
      if ($Scenario -ne 'ready-only-owner') {
        Assert-PremiumTest ($merged -ccontains 'live-admin') 'Live administrators were not preserved.'
      }
      Assert-PremiumTest ($merged.Count -eq $result.AdminAllowlistCount) 'Result count does not match the actual JSON array length.'
      if ($before.TF_VAR_admin_cognito_subs -eq '["ambient-admin","live-admin"]') {
        Assert-PremiumTest ($merged.Count -eq 3 -and $merged -ccontains 'ambient-admin') 'Ambient admin merge lost a user or duplicated one.'
      }
    } else {
      Assert-PremiumTest ([Environment]::GetEnvironmentVariable('TF_VAR_premium_owner_sub', 'Process') -ceq $before.TF_VAR_premium_owner_sub) 'Failed/not-ready run changed owner input.'
      Assert-PremiumTest ([Environment]::GetEnvironmentVariable('TF_VAR_admin_cognito_subs', 'Process') -ceq $before.TF_VAR_admin_cognito_subs) 'Failed/not-ready run changed admin inputs.'
      if ($errorMessage) { Assert-PremiumTest ($null -eq $result) 'Failed run emitted a stale ready object.' }
    }
    foreach ($name in $script:EnvironmentNames | Where-Object { $_ -notin @('TF_VAR_premium_owner_sub', 'TF_VAR_admin_cognito_subs') }) {
      Assert-PremiumTest ([Environment]::GetEnvironmentVariable($name, 'Process') -ceq $before[$name]) "Unrelated environment changed: $name"
    }
    Assert-PremiumTest ([Console]::OutputEncoding.CodePage -eq $beforeConsole) 'Console encoding was not restored.'
    foreach ($path in $PremiumWorld.InputPaths) {
      Assert-PremiumTest (!(Test-Path -LiteralPath $path)) 'A temporary JSON request was left behind.'
      Assert-PremiumTest (!(Test-Path -LiteralPath (Split-Path -Parent $path))) 'A temporary owner directory was left behind.'
    }
    if (!$Ensure) { Assert-PremiumTest ($PremiumWorld.AddCalls -eq 0) 'Read-only run changed a group.' }
    & $Check $result $errorMessage
    Write-Host "PASS $Scenario"
  } catch {
    $script:Failures++
    Write-Host "FAIL $Scenario : $($_.Exception.Message)"
  }
}

try {
  Invoke-PremiumCase 'ready' -Check { param($r, $e)
    Assert-PremiumTest ($PremiumWorld.AddCalls -eq 0 -and !$r.AdminGroupAdded) 'Existing group membership should be idempotent.' }
  Invoke-PremiumCase 'ready-empty-inputs' -Setup {
    Remove-Item Env:TF_VAR_premium_owner_sub, Env:TF_VAR_admin_cognito_subs, Env:PREMIUM_OWNER_SUB -ErrorAction SilentlyContinue
  }
  Invoke-PremiumCase 'ready-empty-admin-array' -Setup {
    $env:TF_VAR_admin_cognito_subs = '[]'
  } -Check { param($r, $e) Assert-PremiumTest ($r.AdminAllowlistCount -eq 2) 'An empty JSON array was not merged correctly.' }
  Invoke-PremiumCase 'ready-single-admin-array' -Setup {
    $env:TF_VAR_admin_cognito_subs = '["ambient-admin"]'
  } -Check { param($r, $e) Assert-PremiumTest ($r.AdminAllowlistCount -eq 3) 'A one-element JSON array was not merged correctly.' }
  Invoke-PremiumCase 'ready-multiple-admin-array' -Setup {
    $env:TF_VAR_admin_cognito_subs = '["ambient-admin","another-admin"]'
  } -Check { param($r, $e) Assert-PremiumTest ($r.AdminAllowlistCount -eq 4) 'A multiple-element JSON array was not merged correctly.' }
  Invoke-PremiumCase 'ready-duplicate-admin-array' -Setup {
    $env:TF_VAR_admin_cognito_subs = '["live-admin","live-admin","' + $script:OwnerSub.ToUpperInvariant() + '"]'
  } -Check { param($r, $e) Assert-PremiumTest ($r.AdminAllowlistCount -eq 2) 'Duplicate/canonical owner entries were not deduplicated.' }
  Invoke-PremiumCase 'ready-only-owner' -Setup {
    $env:TF_VAR_admin_cognito_subs = '[]'
  } -Check { param($r, $e) Assert-PremiumTest ($r.AdminAllowlistCount -eq 1) 'A sole owner was not kept as a one-element JSON array.' }
  Invoke-PremiumCase 'second-page' -Check { param($r, $e)
    Assert-PremiumTest ($PremiumWorld.UserReads -eq 2) 'Did not follow the user page after an empty first page.' }
  Invoke-PremiumCase 'group-second-page' -Check { param($r, $e)
    Assert-PremiumTest ($PremiumWorld.GroupReads -eq 2) 'Did not follow group pagination.' }
  Invoke-PremiumCase 'live-owner-matches'
  Invoke-PremiumCase 'ready-existing-member-with-switch' -Ensure $true -Check { param($r, $e)
    Assert-PremiumTest ($PremiumWorld.AddCalls -eq 0) 'Idempotent ensure repeated an existing group write.' }
  Invoke-PremiumCase 'group-absent' -Check { param($r, $e)
    Assert-PremiumTest (!$r.ReadyForPlan -and !$r.TerraformInputsSet -and $r.Status -ceq 'ADMIN_GROUP_REQUIRED') 'Missing group was reported ready.' }
  Invoke-PremiumCase 'add-group' -Ensure $true -Check { param($r, $e)
    Assert-PremiumTest ($r.AdminGroupAdded -and $PremiumWorld.AddCalls -eq 1 -and $PremiumWorld.GroupReads -eq 2) 'Group addition was not read/add/rechecked.' }
  foreach ($scenario in @('native-error', 'invalid-json', 'null-json', 'wrong-account', 'wrong-pool', 'wrong-pool-account',
      'missing-user', 'invalid-user-page', 'duplicate-user', 'duplicate-second-page', 'pagination-loop',
      'stale-sub', 'stale-email', 'unverified', 'disabled', 'invalid-sub', 'wrong-username', 'duplicate-attribute',
      'wrong-function', 'wrong-api-pool', 'live-owner-conflict', 'invalid-live-admin', 'too-many-admins',
      'group-read-error', 'wrong-group-pool', 'group-missing', 'disabled-before-add')) {
    Invoke-PremiumCase $scenario -Ensure $true -ExpectThrow $true -Check { param($r, $e)
      Assert-PremiumTest ($PremiumWorld.AddCalls -eq 0) 'An invalid identity/configuration triggered a group write.' }
  }
  foreach ($scenario in @('group-add-error', 'group-not-confirmed')) {
    Invoke-PremiumCase $scenario -Ensure $true -ExpectThrow $true -Check { param($r, $e)
      Assert-PremiumTest ($PremiumWorld.AddCalls -eq 1) 'Expected a single failed/unconfirmed group attempt.' }
  }
  Invoke-PremiumCase 'ambient-owner-conflict' -Ensure $true -ExpectThrow $true -Setup {
    $env:TF_VAR_premium_owner_sub = $script:OtherSub
  } -Check { param($r, $e) Assert-PremiumTest ($PremiumWorld.AddCalls -eq 0) 'Ambient identity conflict changed access.' }
  Invoke-PremiumCase 'process-owner-conflict' -Ensure $true -ExpectThrow $true -Setup {
    $env:PREMIUM_OWNER_SUB = $script:OtherSub
  }
  foreach ($invalid in @('not-json', '{"sub":"someone"}', '["someone@example.com"]', '[123]', '[null]',
      '[["nested-admin"]]', '["valid-admin",["nested-admin"]]', '[[]]', '[true]', '[{}]',
      '[],"subs":["injected-admin"]')) {
    Invoke-PremiumCase 'invalid-ambient-admins' -Ensure $true -ExpectThrow $true -Setup {
      $env:TF_VAR_admin_cognito_subs = $invalid
    } -Check { param($r, $e) Assert-PremiumTest ($PremiumWorld.AddCalls -eq 0) 'Invalid ambient allowlist changed access.' }
  }
} finally {
  if ($script:PreviousAwsFunction) { Set-Item Function:\global:aws -Value $script:PreviousAwsFunction }
  else { Remove-Item Function:\aws -ErrorAction SilentlyContinue }
  Remove-Variable PremiumWorld -Scope Global -ErrorAction SilentlyContinue
  foreach ($name in $script:EnvironmentNames) {
    if ($null -eq $script:SavedEnvironment[$name]) { Remove-Item "Env:$name" -ErrorAction SilentlyContinue }
    else { [Environment]::SetEnvironmentVariable($name, $script:SavedEnvironment[$name], 'Process') }
  }
}
if ($script:Failures) { throw "$script:Failures Premium owner preparation scenario(s) failed." }
Write-Host 'All Premium owner preparation scenarios passed without AWS calls.'
$global:LASTEXITCODE = 0
