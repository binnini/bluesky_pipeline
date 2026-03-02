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
- [ ] Processor (Redpanda → TimescaleDB)
  - [ ] aggregator.py (1분 버킷 집계, 키워드 전처리)
  - [ ] main.py (confluent-kafka Consumer 루프)
  - [ ] docker-compose processor 서비스 추가
- [ ] S3 Sink (Redpanda → S3 Parquet)
  - [ ] sink.py (Parquet 변환 + S3 업로드)
  - [ ] docker-compose s3_sink 서비스 추가
- [ ] Grafana 대시보드 초안
  - [ ] Top 20 키워드 빈도 (Bar chart)
  - [ ] 포스트 볼륨 시계열 (Time series)
  - [ ] 파이프라인 처리 지연 (Gauge)
  - [ ] Ingestor 연결 상태 (Stat panel)

## Phase 2 — 클라우드 배포
- [ ] Terraform 인프라 작성 (EC2 t3.medium, S3, SG, IAM, EIP)
- [ ] EC2 배포 및 동작 확인
- [ ] Loki 알림 규칙 (연결 끊김, 처리량 급감, DB 에러율)
- [ ] 데이터 보존 정책 결정 (TimescaleDB 30일, S3 90일 → Glacier)
- [ ] Grafana 접근 제어 (AWS SG IP 화이트리스트)

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
- [ ] 데이터 보존 정책 확정 (TimescaleDB: 30일 / S3: 90일 후 Glacier)
- [ ] Grafana 접근 제어 방식 (공개 vs IP 화이트리스트)
- [ ] 알림 채널 선택 (Slack / 이메일)
