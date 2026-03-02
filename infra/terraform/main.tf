# EC2, S3, VPC, SG, IAM, EIP
# - aws_instance            (EC2 t3.medium)
# - aws_s3_bucket           (raw data)
# - aws_s3_bucket_lifecycle (90일 → Glacier 전환)
# - aws_security_group      (SSH, Grafana 포트)
# - aws_iam_role + policy   (EC2 → S3 접근권한)
# - aws_eip                 (고정 IP, 재시작 대응)
