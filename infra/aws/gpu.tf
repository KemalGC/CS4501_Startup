# Paid Deep Analysis remains OFF and not deployed.
# The isolated GPU EC2 preflight may be provisioned only in explicitly
# acknowledged smoke mode; see GPU_SMOKE_M3.md. This DOES NOT enable paid
# uploads, queue triggers, Lambda dispatch, credit charging or user access.
# The ASG has desired_capacity=0 and max_size=1, with ECS managed scaling
# DISABLED for smoke. Only the approved operator script starts one EC2 host.
