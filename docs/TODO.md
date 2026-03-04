# TODO

## Phase 0 — 로컬 인프라 ✅
- [x] docker-compose.yml 작성 (Redpanda, TimescaleDB, Grafana, Loki, Promtail)
- [x] TimescaleDB init.sql (hypertable 스키마)
- [x] Grafana provisioning (datasources, dashboard provider)
- [x] 프로젝트 네임스페이스 분리 (`name: bluesky`)
- [x] wikiStreams 포트 충돌 해결 (Grafana 3001, Loki 3101)
- [x] 서비스별 CPU/메모리 리소스 리밋 설정

## Phase 1 — 파이프라인 구현
- [x] Ingestor (Firehose → Redpanda)
  - [x] schema.py (AT Protocol 파싱, 해시태그 추출, 텍스트 검증)
  - [x] reconnect.py (Full Jitter Exponential Backoff)
  - [x] main.py (WebSocket Consumer → confluent-kafka Producer)
  - [x] docker-compose ingestor 서비스 추가 및 동작 확인
- [x] Processor (Redpanda → TimescaleDB)
  - [x] aggregator.py (1분 버킷 집계, 키워드 전처리)
  - [x] main.py (confluent-kafka Consumer 루프)
  - [x] docker-compose processor 서비스 추가
- [x] S3 Sink (Redpanda → S3 Parquet)
  - [x] sink.py (Parquet 변환 + S3 업로드)
  - [x] docker-compose s3_sink 서비스 추가 (MinIO 포함)
- [x] Grafana 대시보드 초안
  - [x] Top 20 키워드 빈도 (Bar chart, horizontal)
  - [x] 포스트 볼륨 시계열 (Time series, bar style)
  - [x] 파이프라인 처리 지연 (Stat, 초 단위 / green→yellow→red)
  - [x] Ingestor 연결 상태 (Stat, Loki count_over_time)

## Phase 2 — 클라우드 배포 ✅
- [x] Terraform 인프라 작성 (EC2 t4g.small ARM64, S3, SG, IAM, EIP)
- [x] S3 데이터 보존 정책 (90일 → Glacier, lifecycle rule)
- [x] Grafana 접근 제어 (AWS SG IP 화이트리스트 `1.213.250.69/32`)
- [x] EC2 배포 및 동작 확인 (rsync → docker compose up)
- [x] Loki 알림 규칙 (연결 끊김, 처리량 급감, DB 에러율) → Grafana Alerting + Slack
- [x] TimescaleDB 데이터 보존 정책 (30일 chunk dropping)

## Phase 3 — 안정화 및 CI/CD
- [ ] Unit 테스트 (schema, aggregator)
- [ ] Integration 테스트 (Redpanda → Processor → TimescaleDB)
- [ ] Smoke 테스트 (헬스체크, Grafana 접근)
- [ ] GitHub Actions CI/CD 파이프라인

## Phase 4 — 기능 확장
- [ ] 감성 분석 (Sentiment)
- [ ] 언어/지역별 분포
- [ ] 트렌드 비교 기능

## 미결 사항
- [ ] Phase 3 착수 시점 결정
