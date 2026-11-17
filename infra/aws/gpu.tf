# Deferred paid Deep Analysis GPU infrastructure (explicitly disabled).
# enable_gpu has a validation guard that rejects true. No GPU resources can be
# launched by this Terraform configuration as currently written.
#
# Rationale: AWS ECS supports `GPU=0.125` on g6f.large (~3 GB L4 VRAM), but
# that requires a tested fractional-GPU ECS capacity path and a CUDA-enabled
# image. An ordinary CPU ONNX Runtime + llama-cpp-python image will not use GPU
# merely because a GPU EC2 instance exists. See GPU_PLAN.md before adding
# AWS ECS Managed Instances / GPU-optimized EC2 Auto Scaling Group resources.
