output "eip_public_ip" {
  description = "EC2 고정 공인 IP"
  value       = aws_eip.bluesky.public_ip
}

output "s3_bucket_name" {
  description = "S3 버킷 이름"
  value       = aws_s3_bucket.bluesky_raw.bucket
}

output "ssh_command" {
  description = "EC2 접속 명령어"
  value       = "ssh -i ~/.ssh/bluesky-key.pem ec2-user@${aws_eip.bluesky.public_ip}"
}

output "rsync_command" {
  description = "프로젝트 파일 전송 명령어"
  value       = "rsync -avz --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' -e 'ssh -i ~/.ssh/bluesky-key.pem' ~/workSpace/blueSky/ ec2-user@${aws_eip.bluesky.public_ip}:~/bluesky/"
}

output "grafana_url" {
  description = "Grafana 접속 URL"
  value       = "http://${aws_eip.bluesky.public_ip}:3001"
}
