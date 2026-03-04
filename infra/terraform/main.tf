terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# ── AMI (Amazon Linux 2023 ARM64) ────────────────────────────────────────────
data "aws_ami" "al2023_arm64" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-arm64"]
  }
  filter {
    name   = "architecture"
    values = ["arm64"]
  }
}

# ── S3 Bucket ─────────────────────────────────────────────────────────────────
resource "aws_s3_bucket" "bluesky_raw" {
  bucket = var.s3_bucket_name
}

resource "aws_s3_bucket_lifecycle_configuration" "bluesky_raw" {
  bucket = aws_s3_bucket.bluesky_raw.id

  rule {
    id     = "glacier-after-90-days"
    status = "Enabled"

    filter {}  # 버킷 내 모든 객체에 적용

    transition {
      days          = 90
      storage_class = "GLACIER"
    }
  }
}

# ── IAM Role (EC2 → S3) ───────────────────────────────────────────────────────
resource "aws_iam_role" "ec2_s3_role" {
  name = "bluesky-ec2-s3-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "ec2_s3_policy" {
  name = "bluesky-s3-access"
  role = aws_iam_role.ec2_s3_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ]
      Resource = [
        aws_s3_bucket.bluesky_raw.arn,
        "${aws_s3_bucket.bluesky_raw.arn}/*"
      ]
    }]
  })
}

resource "aws_iam_instance_profile" "ec2_profile" {
  name = "bluesky-ec2-profile"
  role = aws_iam_role.ec2_s3_role.name
}

# ── Security Group ─────────────────────────────────────────────────────────────
resource "aws_security_group" "bluesky_sg" {
  name        = "bluesky-sg"
  description = "BlueSky pipeline: SSH + Grafana"

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.allowed_cidr]
  }

  ingress {
    description = "Grafana"
    from_port   = 3001
    to_port     = 3001
    protocol    = "tcp"
    cidr_blocks = [var.allowed_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# ── EC2 (t4g.small, ARM64) ────────────────────────────────────────────────────
resource "aws_instance" "bluesky" {
  ami                    = data.aws_ami.al2023_arm64.id
  instance_type          = var.instance_type
  key_name               = var.key_name
  vpc_security_group_ids = [aws_security_group.bluesky_sg.id]
  iam_instance_profile   = aws_iam_instance_profile.ec2_profile.name

  root_block_device {
    volume_type = "gp3"
    volume_size = 30
  }

  user_data = <<-EOF
    #!/bin/bash
    set -e
    dnf update -y
    dnf install -y docker git
    systemctl enable docker
    systemctl start docker
    usermod -aG docker ec2-user

    # Docker Compose plugin (ARM64)
    mkdir -p /usr/local/lib/docker/cli-plugins
    curl -SL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-aarch64" \
      -o /usr/local/lib/docker/cli-plugins/docker-compose
    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

    mkdir -p /home/ec2-user/bluesky
    chown ec2-user:ec2-user /home/ec2-user/bluesky
  EOF

  tags = {
    Name    = "bluesky-pipeline"
    Project = "bluesky"
  }
}

# ── Elastic IP ────────────────────────────────────────────────────────────────
resource "aws_eip" "bluesky" {
  instance = aws_instance.bluesky.id
  domain   = "vpc"

  tags = {
    Name = "bluesky-eip"
  }
}
