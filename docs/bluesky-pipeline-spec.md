# BlueSky Firehose 실시간 트렌드 분석 파이프라인
## 기술 스펙 문서 (MVP v0.1.0)

---

## 1. 프로젝트 개요

### 목표
BlueSky SNS의 Firehose 스트림을 실시간으로 수집하여 **해시태그/키워드 빈도** 및 **포스트 볼륨 변화**를 1분 이내 지연으로 시각화하는 데이터 파이프라인 MVP를 구축한다.
개발은 M4, 24GB 로컬 맥미니를 사용하여 빠르게 MVP를 구축한 후, 클라우드로 마이그레이션 한다.

### 범위

| 항목 | MVP | Phase 2 |
|------|-----|---------|
| 해시태그/키워드 빈도 | ✅ | - |
| 포스트 볼륨 변화 | ✅ | - |
| 감성 분석 (Sentiment) | ❌ | ✅ |
| 언어/지역별 분포 | ❌ | ✅ |
| Latency 목표 | 1분 이내 | - |
| IaC (Terraform) | ✅ | - |
| 테스트 (Unit/Integration/Smoke) | ✅ | - |
| CI/CD (GitHub Actions) | ❌ | ✅ |
| Grafana + Loki | ✅ | - |

---

## 2. Data Source 리포팅 (EVALUATION_KITS.md 기준)

### 2-1. 원천 특성 평가

| 평가 항목 | 내용 | 판단 |
|-----------|------|------|
| **원천의 본질** | WebSocket 기반 무한 스트리밍 (AT Protocol) | 스트리밍 아키텍처 필수 |
| **생성 속도** | 초당 500~1,500 이벤트, 일 약 2~5GB | t3.medium 처리 가능, 스파이크 버퍼 필요 |
| **데이터 보존** | Firehose 재전송 없음 (Fire & Forget) | 연결 끊김 시 해당 구간 영구 유실 → Reconnect 로직 필수 |
| **데이터 일관성** | AT Protocol 스키마 비교적 안정적 | null 처리 로직 필요 |
| **중복 가능성** | 낮음. 재연결 시 순간적 중복 가능 | 이벤트 CID 기준 멱등성 처리 |
| **Late-arriving** | 실시간 스트림, out-of-order 거의 없음 | Watermark 단순하게 설계 가능 |
| **스키마 변경** | AT Protocol 버전업 시 변경 가능 | 스키마 버전 검사 로직 필요 |
| **외부 의존성** | Bluesky 서버 가용성에 완전 종속, SLA 없음 | 장애 시 수집 중단 → Gap 감지 알림 필요 |
| **데이터 품질** | 공개 소셜 데이터 → 스팸, 봇 다수 포함 | 볼륨 지표 오염 위험, 필터링 기준 필요 |

### 2-2. 핵심 리스크 및 대응

| 리스크 | 심각도 | 대응 방안 |
|--------|--------|-----------|
| 연결 끊김 → 데이터 유실 | 높음 | Exponential Backoff Reconnect + Gap 감지 알림 |
| 스팸/봇 데이터 오염 | 중간 | 최소 필터링 MVP 적용 (빈 텍스트, 비정상 길이) |
| AT Protocol 스키마 변경 | 중간 | 스키마 버전 로깅, Graceful degradation |
| Bluesky 서비스 장애 | 중간 | Loki 알림 + 수동 복구 절차 문서화 |
| 인프라 처리 한계 | 낮음 | 로컬(맥미니 24GB)에서 먼저 검증 → 클라우드 배포 시 t3.medium 시작 고려 |

---

## 3. 기술 스택

| 레이어 | 기술 | 선택 이유 |
|--------|------|-----------|
| **Ingestion** | Python + atproto SDK | BlueSky 공식 SDK, 경량 |
| **Message Queue** | Redpanda (단일 노드) | Kafka 호환, JVM 없음, t3.small 동작 가능 |
| **Stream Processing** | confluent-kafka (Python) | Faust 유지보수 중단 이슈로 대체. 직접 Consumer 루프 + 인메모리 1분 버킷 집계 |
| **Storage (Raw)** | S3 (Parquet) | 장기 보관, 재처리용 |
| **Storage (Serving)** | TimescaleDB | PostgreSQL 기반 시계열 DB, Grafana 네이티브 연동 |
| **시각화** | Grafana | TimescaleDB 직접 쿼리, 알림 기능 내장 |
| **로그 수집** | Loki + Promtail | Grafana 생태계 통합 |
| **컨테이너** | Docker Compose | EC2 단일 인스턴스, 단순 운영 |
| **IaC** | Terraform (AWS provider) | 재현성, 버전 관리, DR |
| **CI/CD** | GitHub Actions (Phase 2) | MVP 이후 도입 |
| **클라우드** | AWS EC2 t3.medium + S3 | t3.small → 메모리 부족 위험, t3.medium으로 시작 |

---

## 4. 아키텍처

```
BlueSky Firehose (WebSocket, AT Protocol)
            │
            ▼
┌──────────────────────────────────────────────┐
│             EC2 t3.medium (AWS)              │
│                                              │
│  [1] Ingestor (Python + atproto SDK)         │
│      WebSocket 연결 유지                      │
│      Exponential Backoff Reconnect           │
│      스키마 버전 검사                         │
│              │ Produce                       │
│  [2] Redpanda (단일 노드)                    │
│      Topic: bluesky-raw                      │
│              │ Consume                       │
│       ┌──────┴──────┐                        │
│       ▼             ▼                        │
│  [3a] Processor [3b] S3 Sink                 │
│  (confluent-    Parquet 변환                  │
│   kafka)        시간별 파티션                  │
│  1분 버킷 집계  (장기 보관)                   │
│       │                                      │
│       ▼                                      │
│  [4] TimescaleDB                             │
│      keyword_trends (hypertable)             │
│      post_volume (hypertable)                │
│       │                                      │
│       ▼                                      │
│  [5] Grafana + Loki + Promtail               │
│      실시간 트렌드 대시보드                    │
│      파이프라인 로그 수집/쿼리                 │
│      알림 (Gap 감지, 처리 지연 등)            │
└──────────────────────────────────────────────┘
                   │
                   ▼
            S3 (Raw Parquet)
```

---

## 5. 데이터 모델

### TimescaleDB 스키마

```sql
-- 키워드/해시태그 빈도 (1분 집계)
CREATE TABLE keyword_trends (
    ts          TIMESTAMPTZ NOT NULL,
    keyword     TEXT        NOT NULL,
    count       INTEGER     NOT NULL,
    window_sec  INTEGER     NOT NULL DEFAULT 60
);
SELECT create_hypertable('keyword_trends', 'ts');
CREATE INDEX ON keyword_trends (keyword, ts DESC);

-- 포스트 볼륨 (1분 집계)
CREATE TABLE post_volume (
    ts          TIMESTAMPTZ NOT NULL,
    total_posts INTEGER     NOT NULL,
    window_sec  INTEGER     NOT NULL DEFAULT 60
);
SELECT create_hypertable('post_volume', 'ts');
```

### 키워드 전처리 기준 (확정)

| 항목 | 기준 | 비고 |
|------|------|------|
| **트렌드 임계값** | 1분 윈도우 내 **3회 이상** 등장 | 미만 키워드는 저장하지 않음 |
| **글자 수 필터** | **2자 이상, 50자 이하** | 단일 문자·비정상 길이 제거 |
| **불용어 제거** | NLTK English stopwords 적용 | 다국어는 Phase 2에서 확장 |
| **전처리 순서** | 소문자 변환 → 특수문자 제거 → 불용어 제거 → 길이 필터 → 빈도 집계 | - |

### S3 파티션 구조

```
s3://bluesky-raw/
  year=2026/month=03/day=03/hour=14/
    part-000.parquet
```

---

## 6. 프로젝트 디렉토리 구조

```
bluesky-pipeline/
├── infra/
│   └── terraform/
│       ├── main.tf         # EC2, S3, VPC, SG
│       ├── variables.tf
│       └── outputs.tf
├── services/
│   ├── ingestor/
│   │   ├── Dockerfile
│   │   ├── main.py         # Firehose WebSocket consumer
│   │   ├── reconnect.py    # Exponential Backoff
│   │   └── schema.py       # AT Protocol 스키마 검사
│   ├── processor/
│   │   ├── Dockerfile
│   │   ├── main.py         # confluent-kafka Consumer 루프
│   │   └── aggregator.py   # 1분 버킷 집계, 키워드 전처리, TimescaleDB INSERT
│   ├── s3_sink/
│   │   ├── Dockerfile
│   │   └── sink.py         # Parquet 변환 + S3 업로드
│   └── grafana/
│       ├── dashboards/
│       │   └── trends.json
│       └── provisioning/
├── docker-compose.yml
├── tests/
│   ├── unit/
│   │   ├── test_schema.py
│   │   └── test_aggregator.py
│   ├── integration/
│   │   └── test_pipeline.py
│   └── smoke/
│       └── test_health.py
└── README.md
```

---

## 7. CI/CD (Phase 2 예정)

MVP 기간에는 수동 배포로 운영한다. 파이프라인이 안정화된 이후 Phase 2에서 아래 구조로 도입한다.

```
[CI] Push / PR → main
    ├── Lint (ruff, black)
    ├── Type Check (mypy)
    ├── Unit Tests (pytest)
    ├── Integration Tests (Docker Compose 기반)
    └── Docker Image Build 검증

[CD] Merge → main
    ├── Docker 이미지 빌드
    ├── ECR Push
    └── EC2 SSH → docker compose pull && up -d
```

---

## 8. 테스트 전략

| 레벨 | 대상 | 도구 |
|------|------|------|
| **Unit** | 스키마 파서, 집계 로직(aggregator), 키워드 전처리 함수 | pytest |
| **Integration** | Redpanda → Processor → TimescaleDB 흐름 | pytest + Docker Compose |
| **Smoke** | 배포 후 헬스체크, Grafana 접근 | pytest |
| **E2E** | 실제 Firehose → 대시보드 확인 | 수동 (Phase 2 자동화) |

---

## 9. Observability

### Grafana 대시보드 패널
- Top 20 키워드 빈도 (1분 롤링, Bar chart)
- 포스트 볼륨 시계열 (Time series)
- 파이프라인 처리 지연 (Gauge)
- Ingestor 연결 상태 (Stat panel)

### Loki 알림 규칙
- Firehose 연결 끊김 감지 → 즉시 알림
- 처리량 급감 (이전 5분 대비 50% 이하) → 알림
- TimescaleDB INSERT 에러율 > 1% → 알림

### DataOps 목표 지표
- **MTTD** (장애 인지 시간): 목표 < 2분
- **MTTR** (장애 해결 시간): 목표 < 30분

---

## 10. IaC (Terraform) 관리 범위

```hcl
# 관리 리소스
- aws_instance            (EC2 t3.medium)
- aws_s3_bucket           (raw data)
- aws_s3_bucket_lifecycle (90일 → Glacier 전환)
- aws_security_group      (SSH, Grafana 포트)
- aws_iam_role + policy   (EC2 → S3 접근권한)
- aws_eip                 (고정 IP, 재시작 대응)
```

---

## 11. 비용 추정 (월)

| 항목 | 스펙 | 예상 비용 |
|------|------|-----------|
| EC2 t3.medium | On-Demand, 24/7 | ~$33 (약 48,000원) |
| S3 스토리지 | ~90GB/월 Parquet 압축 | ~$2 (약 2,900원) |
| S3 요청 | PUT/GET | ~$1 (약 1,500원) |
| 데이터 전송 | Egress 최소 | ~$1 (약 1,500원) |
| **합계** | | **~$37 (약 54,000원)** |

> 월 5만원 예산을 소폭 초과하나 서비스 안정성 우선. 안정화 후 Reserved Instance 전환 시 약 $21 수준으로 절감 가능.
> 파이프라인 검증 완료 후 t3.small 다운그레이드 가능 여부 재검토.

---

## 12. 남은 결정 사항 (착수 전)

| 항목 | 내용 | 우선순위 |
|------|------|---------|
| ~~**키워드 트렌드 기준**~~ | ✅ 확정: 1분 윈도우 내 3회 이상 | - |
| ~~**키워드 전처리**~~ | ✅ 확정: NLTK stopwords, 2~50자, 소문자 정규화 | - |
| **데이터 보존 정책** | TimescaleDB: 최근 30일 / S3: 90일 후 Glacier | 중간 |
| **Grafana 접근 제어** | 공개 vs AWS SG IP 화이트리스트 | 중간 |
| **알림 채널** | Slack? 이메일? | 낮음 |

---

## 13. 구현 로드맵

| Phase | 내용 | 기간 |
|-------|------|------|
| **Phase 0** | 로컬 Docker Compose 환경 구성 (Redpanda + TimescaleDB + Grafana) | 3~5일 |
| **Phase 1** | Ingestor + confluent-kafka Processor + S3 Sink → 로컬에서 실제 Firehose 연결 검증 | 1~2주 |
| **Phase 2** | Terraform 인프라 → 클라우드 배포 (EC2 t3.medium), Grafana 대시보드 완성, 알림 규칙 | 1주 |
| **Phase 3** | 통합 테스트, Loki 알림, 부하 테스트, 비용 검증, 문서화, GitHub Actions CI/CD | 1~2주 |
| **Phase 4** | Sentiment 분석, 언어/지역 분포, 트렌드 비교 기능 | 이후 |
