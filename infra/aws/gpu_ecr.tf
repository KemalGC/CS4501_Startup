
# Private opt-in GPU worker image bootstrap. This does NOT provision EC2, ECS,
# queues, Lambda triggers or any paid user access. Push/build separately.
resource "aws_ecr_repository" "gpu_worker" {
  count                = var.enable_gpu_image_repository ? 1 : 0
  name                 = "${local.prefix}-gpu-worker"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "gpu_worker" {
  count      = var.enable_gpu_image_repository ? 1 : 0
  repository = aws_ecr_repository.gpu_worker[0].name
  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Remove untagged images after 7 days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 7
        }
        action = { type = "expire" }
      }
    ]
  })
}
