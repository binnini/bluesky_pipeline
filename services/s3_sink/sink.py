# Parquet 변환 + S3 업로드
# - Redpanda(bluesky-raw topic) 구독
# - 수신 메시지를 Parquet으로 변환
# - S3 시간별 파티션 경로에 업로드
#   (s3://bluesky-raw/year=YYYY/month=MM/day=DD/hour=HH/part-NNN.parquet)
