variable "aws_region" {
  description = "AWS 리전"
  type        = string
  default     = "ap-northeast-2"
}

variable "instance_type" {
  description = "EC2 인스턴스 타입"
  type        = string
  default     = "t4g.small"
}

variable "key_name" {
  description = "EC2 SSH 키페어 이름"
  type        = string
  default     = "bluesky-key"
}

variable "allowed_cidr" {
  description = "SSH / Grafana 접근 허용 IP (CIDR)"
  type        = string
  default     = "1.213.250.69/32"
}

variable "s3_bucket_name" {
  description = "S3 버킷 이름 (전 세계 고유)"
  type        = string
  default     = "bluesky-raw-707042668475"
}
