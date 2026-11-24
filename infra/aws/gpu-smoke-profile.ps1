# Pure hardware contract shared by preparation, plan review and the runner.
# Keep the allowlist and GPU units aligned with variables.tf/gpu_capacity.tf.
function Get-GpuSmokeProfile {
  [CmdletBinding()]
  param([Parameter(Mandatory=$true)][string]$InstanceType)

  switch -CaseSensitive ($InstanceType) {
    'g6f.xlarge' {
      return [pscustomobject]@{
        InstanceType = 'g6f.xlarge'; Vcpus = 4; GpuResource = '0.125'
        MinGpuMemoryMiB = 2800; Approval = 'I_APPROVE_ONE_G6F_SMOKE_INSTANCE'
      }
    }
    'g4dn.xlarge' {
      # A T4 advertises 16 GiB; allow memory reserved by the NVIDIA driver.
      return [pscustomobject]@{
        InstanceType = 'g4dn.xlarge'; Vcpus = 4; GpuResource = '1'
        MinGpuMemoryMiB = 14000; Approval = 'I_APPROVE_ONE_G4DN_SMOKE_INSTANCE'
      }
    }
    default { throw 'Supported GPU smoke instance types are exactly g6f.xlarge and g4dn.xlarge.' }
  }
}
