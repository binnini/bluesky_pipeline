# BlueSky Pipeline — MVP 평가 결과

평가 기준: `EVALUATION_KITS.md` | 평가 시점: 2026-03-04 (Phase 2 완료)

범례: ✅ 충족 · ⚠️ 부분 충족 · ❌ 미충족 · N/A 해당 없음

---

## 1. Data Source System

| # | 핵심 질문 | 결과 | 비고 |
|---|-----------|------|------|
| 1 | 원천의 본질 | ✅ | BlueSky Firehose = 무한 WebSocket 스트림 → 스트리밍 아키텍처 선택 적합 |
| 2 | 데이터 보존 기간 | ⚠️ | Firehose는 실시간 push 방식, 미수집 이벤트 재요청 불가 → Redpanda 토픽 보존 기간 미설정(현재 기본값) |
| 3 | 생성 속도 | ✅ | 초당 수만 건 수준 실측 확인 (첫 flush 3,446,182건 / ~60분) · Redpanda 1파티션으로 현재 트래픽 소화 |
| 4 | 데이터 일관성 | ✅ | AT Protocol 구조화 JSON · 텍스트 길이 필터(1~3,000자) · `too_big` 커밋 스킵 |
| 5 | 에러 발생 빈도 | ✅ | Full Jitter Exponential Backoff 구현 (base 1s, cap 60s) · SIGTERM 클린 셧다운 |
| 6 | 중복 데이터 가능성 | ⚠️ | Consumer group offset 기반 at-least-once · 재시작 시 중복 레코드 가능 (Exactly-once 미보장) |
| 7 | Late-arriving / Out-of-order | ⚠️ | `created_at` + `ingested_at` 이중 타임스탬프 보존 · Watermark / 이벤트 타임 집계 미적용 |
| 8 | 스키마 복잡도 | ✅ | 단일 JSON 구조 · facets 기반 해시태그 추출 로직 캡슐화 (schema.py) |
| 9 | 스키마 변경 대응 | ⚠️ | Schema Registry 미사용 · `atproto` 라이브러리 버전에 파싱 로직 의존 |
| 10 | 수집 주기 | ✅ | 실시간 연속 스트리밍 (WebSocket keep-alive) |
| 11 | Stateful 원천 | N/A | 이벤트 스트림 방식, 스냅숏/CDC 불해당 |
| 12 | 데이터 제공자 | ✅ | 외부 공개 API (Bluesky AT Protocol) · Rate Limit 없음 · 공식 SDK 사용 |
| 13 | 원천 조회 성능 영향 | ✅ | Push 방식 수신 → 원천 서버에 조회 부하 없음 |
| 14 | 업스트림 의존 관계 | ✅ | Firehose 단절 시 Grafana Slack 알림 발송 (Ingestor 연결 끊김 규칙) |
| 15 | 데이터 품질 검사 | ⚠️ | 텍스트 길이 필터 적용 · 언어 필터 없음 (전체 언어 수집) · Anomaly 감지 미구현 |

**소결**: 실시간 스트리밍 수집의 핵심 요건(속도·에러 대응·타임스탬프 보존)은 충족. 중복 제거(Exactly-once)와 Schema Registry는 트래픽이 임계치를 넘을 시점에 도입 권장.

---

## 2. Storage System

| # | 핵심 질문 | 결과 | 비고 |
|---|-----------|------|------|
| 1 | 읽기·쓰기 속도 적합성 | ✅ | TimescaleDB = 시계열 OLAP 최적화 · S3 Parquet = 콜드 아카이브 적합 |
| 2 | 파이프라인 병목 가능성 | ✅ | Redpanda가 Producer/Consumer 속도 차를 버퍼링 · 현재 트래픽 수준에서 병목 없음 |
| 3 | 스토리지 작동 방식 이해 | ✅ | TimescaleDB 청크 기반 자동 파티셔닝 · S3 Hive 파티션 (`year/month/day/hour`) |
| 4 | 확장성 | ⚠️ | TimescaleDB 단일 노드 · S3는 무제한 수평 확장 · 트래픽 급증 시 DB 수직 확장 필요 |
| 5 | SLA 충족 여부 | ⚠️ | EC2 단일 인스턴스, Multi-AZ 없음 · 인스턴스 장애 시 수동 복구 필요 |
| 6 | 메타데이터 수집 | ❌ | Data Lineage, 스키마 변경 이력 미관리 |
| 7 | 순수 스토리지 vs 웨어하우스 | ✅ | S3 = Data Lake(raw), TimescaleDB = Serving Layer(집계) 명확히 분리 |
| 8 | 스키마 정책 | ✅ | 양쪽 모두 Schema-on-write (Parquet 명시 스키마 · TimescaleDB DDL 정의) |
| 9 | 데이터 거버넌스 | ❌ | Golden Record, 마스터 데이터 관리 미구현 (MVP 범위 외) |
| 10 | 법령·데이터 주권 | ⚠️ | 서울 리전(ap-northeast-2) 저장 · 공개 게시물이나 `did`(분산 식별자) 포함 → PII 경계 재검토 필요 |

**소결**: 시계열 집계(Hot)와 원시 아카이브(Cold) 이중 저장 구조는 적절. 단일 노드 고가용성과 메타데이터 관리는 Phase 3 이후 과제.

---

## 3. Data Ingestion System

| # | 핵심 질문 | 결과 | 비고 |
|---|-----------|------|------|
| 1 | 재사용 가능성 | ✅ | `bluesky-raw` 토픽을 Processor + S3 Sink가 독립 consumer group으로 병렬 소비 → Single Source of Truth |
| 2 | 내결함성 | ⚠️ | Exponential Backoff ✅ · at-least-once 보장 · 재시작 시 Redpanda offset 복구 ✅ · 중복 레코드 가능성 잔존 |
| 3 | 목적지 | ✅ | Redpanda → TimescaleDB(집계) + S3(원시) 이중 경로 |
| 4 | 접근 빈도 | ✅ | Hot: TimescaleDB(Grafana 실시간 조회) · Cold: S3 Parquet → 90일 후 Glacier |
| 5 | 도착 데이터 용량 | ⚠️ | Redpanda 1파티션 버퍼링 · 트래픽 급증 시 파티션 확장 또는 Producer backpressure 설계 필요 |
| 6 | 데이터 포맷 | ✅ | JSON(수집) → Parquet/snappy(아카이브) · 변환 비용 최소 |
| 7 | 즉시 사용 가능 여부 | ✅ | ELT 방식: raw 수집 후 Processor에서 집계 변환 → 원천 데이터 보존 |
| 8 | 스트리밍 인플라이트 변환 | ✅ | 단순 1분 윈도우 카운팅 → Flink/Spark Streaming 불필요, confluent-kafka Consumer로 충분 |

**스트리밍 vs 배치 판단:**

| 질문 | 평가 |
|------|------|
| 실시간 수집의 구체적 이점 | 트렌드 키워드 실시간 감지 (1분 지연) · 배치 대비 피크 이벤트 즉시 포착 |
| 비용·복잡도 감수 가치 | Redpanda 단일 노드 운영 비용 최소 · 배치 대비 인프라 복잡도 소폭 증가, 수용 가능 |
| Exactly-once 보장 | 미보장 (at-least-once) · 집계 레이어에서 중복 영향 미미 (카운팅 집계) |
| 관리형 vs 자체 운영 | Redpanda 자체 운영 선택 · 관리형(Kinesis) 대비 비용 절감, 팀 운영 역량 내 수용 |

**소결**: 인제스천 설계는 MVP 요건 충족. Exactly-once와 파티션 확장 계획은 트래픽 2배 이상 증가 시점에 검토.

---

## 4. Data Transformation System

| # | 핵심 질문 | 결과 | 비고 |
|---|-----------|------|------|
| 1 | 비용 vs ROI | ✅ | NLTK stopwords 필터 + Python 카운팅 · 연산 비용 최소 · 분당 5만 건 이상 처리 확인 |
| 2 | 단순성·독립성 | ✅ | `schema.py`(파싱) · `aggregator.py`(집계) · `main.py`(루프) 단일 책임 분리 |
| 3 | 비즈니스 규칙 반영 | ✅ | 1분 윈도우 내 3회 이상 등장 키워드만 저장 (노이즈 제거) · 2~50자 길이 필터 · 영어 stopwords 제거 |

**소결**: 변환 로직은 단순·명확. 언어별 stopwords 확장(한국어 등)은 Phase 4 감성 분석 단계에서 검토.

---

## 5. Undercurrents (횡단 관심사)

### 5-1. Security

| 항목 | 결과 | 비고 |
|------|------|------|
| 최소 권한 원칙 | ✅ | IAM Role: S3 PutObject/GetObject/DeleteObject/ListBucket만 허용 |
| 네트워크 접근 제어 | ✅ | SG: SSH(22) + Grafana(3001) → 운영자 IP(`1.213.250.69/32`)만 허용 · Outbound 전체 허용 |
| 임시 자격증명 | ✅ | EC2 IAM Instance Profile → S3 접근 시 장기 자격증명 불필요 |
| 전송 암호화 | ⚠️ | Firehose WebSocket = wss:// ✅ · EC2 내부 서비스 간 통신 = 평문 (Docker 내부 네트워크) |
| 저장 암호화 | ⚠️ | S3 SSE 미설정 · TimescaleDB 볼륨 암호화 미설정 |
| 패스워드 정책 | ❌ | Grafana `admin/admin` · TimescaleDB `bluesky/bluesky` → 운영 전 변경 필요 |

### 5-2. Data Management

| 항목 | 결과 | 비고 |
|------|------|------|
| Data Governance | ❌ | Discoverability · Accountability 체계 미구현 |
| Metadata 수집 | ⚠️ | Parquet 파일 경로(Hive 파티션)가 Operational Metadata 역할 수행 · Business/Technical 메타데이터 없음 |
| Data Accountability | ❌ | 테이블·필드 단위 Owner 미지정 |
| Data Quality | ⚠️ | 텍스트 길이·타입 검증 ✅ · Completeness/Timeliness 자동 검사 없음 |
| Data Modeling | ✅ | `keyword_trends`(keyword × ts) + `post_volume`(ts) · Grafana 소비 패턴에 최적화 |
| Data Lineage | ❌ | Audit Trail 없음 |
| Data Lifecycle Management | ✅ | TimescaleDB 30일 chunk dropping · S3 90일 → Glacier lifecycle |
| Ethics & Privacy | ⚠️ | 공개 게시물 수집 · `did`(분산 식별자) 저장 → 준PII 취급 기준 수립 필요 |

### 5-3. DataOps

| 항목 | 결과 | 비고 |
|------|------|------|
| Automation | ⚠️ | Docker `restart: unless-stopped` 자동 재시작 ✅ · CI/CD 파이프라인 없음 (Phase 3 예정) |
| Observability | ✅ | Grafana 대시보드 (포스트 볼륨, Top 20 키워드, 파이프라인 지연, Ingestor 상태) · Loki 로그 수집 |
| Incident Response | ✅ | Slack 알림 3종: Ingestor 연결 끊김(critical) · 처리량 급감(warning) · DB 에러율(warning) |
| Data Drift 감지 | ❌ | 볼륨 급변 감지 없음 (처리량 급감 알림이 일부 대체) |

### 5-4. Data Architecture

| 항목 | 결과 | 비고 |
|------|------|------|
| 모듈형 설계 | ✅ | ingestor / processor / s3_sink 독립 컨테이너 · 개별 교체 가능 |
| 컴포넌트 교체 가능성 | ✅ | MinIO → AWS S3 환경변수 변경만으로 전환 · Redpanda → Kafka 호환 API |
| 전 구간 일관성 | ✅ | Source → Ingestor → Redpanda → Processor+S3Sink → TimescaleDB+S3 → Grafana |
| 고가용성 | ⚠️ | 단일 EC2, 단일 AZ · 장애 시 수동 복구 필요 |
| 비용 최적화 | ✅ | t4g.small ARM64 (t3.small 대비 ~20% 절감) · 메모리 최적화로 2GB RAM 내 운영 |

### 5-5. Orchestration

| 항목 | 결과 | 비고 |
|------|------|------|
| 오케스트레이터 | ❌ | Airflow/Dagster 없음 · Docker restart 정책으로 단순 대체 |
| 데이터 의존성 관리 | ⚠️ | `depends_on` + `healthcheck`으로 서비스 기동 순서 보장 ✅ · DAG 수준 의존성 없음 |
| Retry / SLA 모니터링 | ⚠️ | Exponential Backoff 재연결 ✅ · SLA 대시보드 없음 |
| Failover 구조 | ❌ | 단일 인스턴스 · Failover 없음 |

### 5-6. Software Engineering

| 항목 | 결과 | 비고 |
|------|------|------|
| 테스트 커버리지 | ❌ | Unit/Integration/Smoke 테스트 없음 (Phase 3 예정) |
| 오픈소스 활용 | ✅ | Redpanda · TimescaleDB · Grafana · Loki · atproto · confluent-kafka · pyarrow · boto3 |
| IaC | ✅ | Terraform: EC2 · S3 · IAM · SG · EIP 코드화 · `.gitignore`로 tfstate 제외 |
| 버전 관리 | ✅ | Git 커밋 이력 · docker-compose.prod.yml(클라우드)와 docker-compose.yml(로컬) 분리 |

---

## 종합 평가

| 영역 | 점수 | 핵심 강점 | 핵심 과제 |
|------|------|-----------|-----------|
| Data Source | 3.5/5 | Firehose 실시간 수집 · Backoff 재연결 | 중복 제거 · Schema Registry |
| Storage | 3/5 | Hot/Cold 이중 저장 · 보존 정책 | HA · 메타데이터 관리 |
| Ingestion | 3.5/5 | Single Source of Truth · ELT | Exactly-once · 파티션 확장 계획 |
| Transformation | 4/5 | 단일 책임 · 노이즈 제거 로직 | 다국어 stopwords |
| Security | 2.5/5 | IAM Role · SG 화이트리스트 | 패스워드 정책 · S3 SSE |
| Data Management | 2/5 | Lifecycle 정책 완비 | Lineage · Governance |
| DataOps | 3.5/5 | Grafana + Slack 알림 | CI/CD · Data Drift |
| Architecture | 3.5/5 | 모듈형 · 비용 최적화 | HA · Orchestration |
| SW Engineering | 3/5 | IaC · OSS 활용 | 테스트 커버리지 |

### Phase 3에서 우선 해결해야 할 항목

1. **패스워드 강화** — Grafana · TimescaleDB 기본 자격증명 교체 (보안 임박 위험)
2. **테스트 구축** — Unit(schema, aggregator) → Integration → Smoke 순서
3. **CI/CD** — GitHub Actions: 테스트 → 빌드 → EC2 배포 자동화
4. **Redpanda 토픽 보존 기간 설정** — 재수집 불가 특성 보완 (예: 7일 보존)
