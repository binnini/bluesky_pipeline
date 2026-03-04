# DEV LOG

---

## 2026-03-03

### 아키텍처 설계 및 스펙 확정
- `bluesky-pipeline-spec.md` 초안 작성 (EVALUATION_KITS.md 기준 데이터 소스 리스크 분석 포함)
- 주요 기술 결정 사항:
  - **Faust → confluent-kafka 대체**: Faust 유지보수 중단 이슈
  - **t3.small → t3.medium**: 로컬 검증 후 클라우드 배포 시 t3.medium으로 시작
  - **키워드 전처리 기준 확정**: NLTK stopwords, 2~50자, 1분 윈도우 내 3회 이상
  - **CI/CD MVP 제외**: Phase 3으로 이동, MVP 속도 우선

### 프로젝트 구조 생성
- 디렉토리 및 플레이스홀더 파일 생성
  ```
  services/{ingestor,processor,s3_sink,grafana}
  infra/terraform
  tests/{unit,integration,smoke}
  ```

### Phase 0 — 로컬 인프라 구성
- `docker-compose.yml` 작성 완료
  - Redpanda (v24.1.13), TimescaleDB (2.14.2-pg16), Grafana (10.4.3)
  - Loki (2.9.8), Promtail (2.9.8), Redpanda Console (v2.6.0)
- `services/timescaledb/init.sql`: keyword_trends, post_volume hypertable 자동 초기화
- `services/grafana/provisioning`: TimescaleDB + Loki datasource, dashboard provider
- `services/loki/config.yml`, `services/promtail/config.yml` 작성
- wikiStreams 프로젝트와 포트 충돌 해결
  - `name: bluesky` 로 네임스페이스 분리 (컨테이너·볼륨·네트워크 prefix)
  - Grafana 3000 → 3001, Loki 3100 → 3101
  - 서비스별 `deploy.resources.limits` 적용 (CPU/메모리 상한)
- **버그 수정**: `redpanda-init` 무한 재시작
  - 원인: `rpk topic create`가 토픽 기존 존재 시 exit 1 → `restart: on-failure` 루프
  - 해결: 토픽 존재 여부 먼저 확인 후 없을 때만 생성

### Phase 1 — Ingestor 구현
- `services/ingestor/schema.py`
  - AT Protocol `app.bsky.feed.post` 이벤트 파싱
  - facets에서 해시태그 추출 (소문자 정규화)
  - 텍스트 길이 필터 (1~3000자), `too_big` 커밋 스킵
- `services/ingestor/reconnect.py`
  - Full Jitter Exponential Backoff (base 1s, max 60s)
  - `threading.Event` 기반 클린 셧다운
- `services/ingestor/main.py`
  - `FirehoseSubscribeReposClient` → CAR 디코딩 → `confluent_kafka.Producer`
  - SIGTERM/SIGINT 핸들러 (Producer flush 후 종료)
  - 500건마다 처리량 로깅
- **동작 확인**: Redpanda `bluesky-raw` 토픽에 실시간 포스트 적재 확인
  ```json
  {
    "cid": "bafyre...",
    "did": "did:plc:...",
    "seq": 27841325368,
    "text": "...",
    "hashtags": ["vtuber", "morningvibes", ...],
    "langs": ["en"],
    "created_at": "2026-03-02T17:45:45.320Z",
    "ingested_at": "2026-03-02T17:45:46.635447+00:00"
  }
  ```

---

## 2026-03-04

### Phase 1 — Processor 구현 (Redpanda → TimescaleDB)

- `services/processor/aggregator.py`
  - `preprocess_keywords()`: 소문자 → 특수문자 제거 → NLTK English stopwords → 길이 필터(2~50자)
  - `MinuteBucketAggregator`: 해시태그 카운터 누적 후 `flush(bucket_ts)` 호출 시 TimescaleDB INSERT
    - `keyword_trends`: 1분 윈도우 내 3회 이상 등장한 키워드만 저장
    - `post_volume`: 분당 총 포스트 수 저장
    - INSERT 성공/실패 무관하게 버퍼 초기화 (중복 방지)
- `services/processor/main.py`
  - TimescaleDB 연결 재시도 (최대 10회, 3초 간격)
  - confluent-kafka Consumer (`bluesky-raw` 구독, group=processor)
  - wall-clock 기준 60초마다 `aggregator.flush()` 트리거
  - SIGTERM/SIGINT 수신 시 최종 flush 후 정상 종료
- **동작 확인**: 첫 flush에서 누적 offset 3,446,182건 소화
  ```
  keyword_trends INSERT: ts=2026-03-04T16:28:00+00:00, keywords=53933
  post_volume INSERT: ts=2026-03-04T16:28:00+00:00, total_posts=3446182
  ```
  Top 키워드: epsteinweb(24k), nsfw(16k), nowplaying(7k), art(6k), iran(5k)

### Phase 1 — S3 Sink 구현 (Redpanda → MinIO Parquet)

- `services/s3_sink/sink.py`
  - `ParquetBuffer`: pyarrow + snappy 압축으로 Parquet 변환 후 boto3로 S3 업로드
  - Flush 조건 (먼저 도달하는 것): 시간 경계(hour) 변경 OR 건수 50,000 초과
  - S3 경로: `s3://bluesky-raw/year=YYYY/month=MM/day=DD/hour=HH/part-NNNNN.parquet`
  - `_wait_for_bucket()`: MinIO 기동 완료까지 재시도 (최대 20회)
  - **AWS S3 전환**: `S3_ENDPOINT_URL` 환경변수 제거 + AWS 자격증명 교체만으로 마이그레이션 가능
- **인프라**: docker-compose에 MinIO(RELEASE.2024-01-16) + minio-init 서비스 추가
  - 포트: `9010:9000`(S3 API), `9011:9001`(Console) — ClickHouse가 9000 점유 중
  - minio-init: `mc alias set` 재시도 루프로 MinIO 준비 완료 후 버킷 생성
  - distroless 이미지 특성상 healthcheck 제거, `service_started` 조건으로 처리
- **동작 확인**: Parquet 파일 정상 적재
  ```
  S3 업로드 완료: s3://bluesky-raw/year=2026/month=03/day=03/hour=15/part-00075.parquet (50000 rows, 9809.4 KB)
  ```

### Phase 1 — Grafana 대시보드 초안

- `services/grafana/dashboards/trends.json` (Grafana 10.4 JSON, schemaVersion 38)
  - **Stat ×4** (상단 행): 포스트 수, 유니크 키워드 수, 파이프라인 지연(green<120s/yellow<300s/red), Ingestor 활동(Loki count_over_time 5m)
  - **Time series**: 분당 포스트 볼륨 (bar style, fillOpacity 60)
  - **Bar chart**: Top 20 키워드 빈도 (horizontal, 선택 기간 집계)
- `services/grafana/provisioning/datasources/datasources.yml`에 UID 추가 (`timescaledb`, `loki`) → 대시보드 JSON에서 고정 참조

### 트러블슈팅 — Grafana 포트 바인딩 오류 (macOS)

- **증상**: `docker ps`는 3000/3001로 정상 표시되나 실제 접속 시 포트가 밀려있음
  - 다른 프로젝트 Grafana: 3000 → 실제 3001로 바인딩
  - BlueSky Grafana: 3001 → 실제 3002로 바인딩
- **원인**: Docker Desktop for Mac의 userland-proxy(vpnkit) 경쟁 조건
  - Linux는 iptables로 포트를 직접 제어하지만, macOS는 `com.docker.backend` 단일 프로세스가 모든 포트 포워딩을 중계
  - 컨테이너 재시작 시 vpnkit이 포트를 해제·재바인딩하는 사이 공백 구간에 다른 컨테이너가 선점
  - `docker ps`는 설정값을 그대로 표시하므로 에러 없이 조용히 발생
- **해결**: 맥미니 OS 재기동으로 포트 바인딩 상태 완전 초기화
- **재발 방지**: 컨테이너 시작 순서 고정 (다른 프로젝트 → BlueSky 순)
  ```bash
  docker compose -f ~/workSpace/wikiStreams/docker-compose.yml up -d
  cd ~/workSpace/blueSky && docker compose up -d
  ```

### 디스크 현황 (2026-03-04 기준)
| 볼륨 | 사용량 |
|---|---|
| redpanda-data | 1.56 GB |
| timescaledb-data | 75.96 MB |
| loki-data | 2.88 MB |
| grafana-data | 997 KB |

---

### 메모리 최적화 — t4g.small(2GB) 대응

로컬 파이프라인 리소스 사용량 측정 후 클라우드 배포 스펙 결정:
- 실제 CPU 사용량: ~0.13 코어 (10코어 호스트 기준) → CPU 병목 없음
- 실제 메모리 사용량: ~1,454 MiB (MinIO 포함)
- 클라우드(MinIO 제거): ~650 MiB → t4g.small(2GB) 여유 ~1,000 MiB

**변경 파일**
- `services/ingestor/main.py`: Kafka 프로듀서 버퍼 128MB → 32MB, 메시지 큐 100k → 10k
- `services/loki/config.yml`: `chunk_idle_period` 5m→3m, `chunk_retain_period` 30s→15s, `max_chunk_age: 5m` 추가
- `docker-compose.yml`:
  - Redpanda `--memory 512M → 256M`, limit 1024M → 512M
  - TimescaleDB `command`로 PG 파라미터 주입: `shared_buffers=64MB`, `max_connections=20` 등, limit 1536M → 384M
  - s3_sink `MAX_RECORDS` 50000 → 10000 (pyarrow 배치 메모리 절감)
  - 전체 메모리 limit 합계: 6,528MB → **2,624MB**

### Phase 2 — Terraform 인프라 구축

**기술 결정**
- 인스턴스: `t4g.small` (ARM64 Graviton2, 2vCPU 2GB) — t3.small 대비 ~20% 저렴
- 모든 Docker 이미지 및 Python 패키지 ARM64 지원 확인 (코드 변경 불필요)
- AWS 리전: `ap-northeast-2` (서울)

**인프라 코드** (`infra/terraform/`)
- `main.tf`: AMI(AL2023 ARM64 자동 조회), EC2, S3, IAM Role/Policy/InstanceProfile, SG, EIP
- `variables.tf`: 리전, 인스턴스 타입, 키페어, 허용 CIDR, S3 버킷명
- `outputs.tf`: EIP, ssh_command, rsync_command, grafana_url

**`docker-compose.prod.yml`** (클라우드 전용)
- MinIO / minio-init / redpanda-console 제거
- s3_sink: `S3_ENDPOINT_URL` 및 AWS 자격증명 제거 → EC2 IAM 인스턴스 프로파일 자동 사용
- S3 버킷명: `bluesky-raw-707042668475`, 리전: `ap-northeast-2`

**`terraform apply` 완료** (2026-03-04)
| 리소스 | 값 |
|---|---|
| EC2 | `i-03721588712a356d7` (t4g.small, AMI: ami-06589f7037b0a7e32) |
| EIP | `3.39.93.197` |
| S3 버킷 | `bluesky-raw-707042668475` (90일 후 Glacier lifecycle) |
| Security Group | `sg-0cc88e55a94dbcb50` (SSH/Grafana: 1.213.250.69/32) |
| SSH 키페어 | `bluesky-key` → `~/.ssh/bluesky-key.pem` |

**트러블슈팅**
- EC2 볼륨 20GB → 오류: AL2023 AMI 최소 요구 30GB (`InvalidBlockDeviceMapping`)
- 해결: `volume_size = 30`으로 수정 후 재apply

---

### Phase 2 — EC2 배포 및 동작 확인

- `tar | ssh` 파이프로 프로젝트 파일 전송 (rsync는 AL2023 기본 미포함)
- Docker Buildx v0.19.3 수동 설치 (`compose build requires buildx 0.17.0` 오류 해결)
- `docker compose -f docker-compose.prod.yml up -d --build` 성공
  - 전체 8개 컨테이너 정상 기동 (ingestor, processor, s3_sink, redpanda, timescaledb, grafana, loki, promtail)
- Grafana 대시보드 데이터 수신 확인 (http://3.39.93.197:3001) ✅
- **Phase 2 완료**

---

### Phase 2 — 알림 및 데이터 보존 정책

**TimescaleDB 30일 chunk dropping**
- `services/timescaledb/init.sql`에 `add_retention_policy` 추가 (신규 배포 자동 적용)
- 실행 중인 EC2 DB에 직접 적용 (`psql`로 즉시 실행)
  - `keyword_trends` → job_id 1000, drop_after 30 days
  - `post_volume` → job_id 1001, drop_after 30 days

**Loki 알림 규칙 (Grafana Alerting → Slack)**
- Promtail Docker SD 방식으로 업그레이드 → `service`, `container` 레이블 자동 부여
  - 기존 `static_configs` 방식에서 변경, `job: docker` 레이블 유지(대시보드 호환)
- `services/grafana/provisioning/alerting/` 3개 파일 추가:
  - `contact-points.yml`: Slack Incoming Webhook 등록
  - `notification-policies.yml`: 모든 알림 → slack-bluesky, 4시간 repeat
  - `rules.yml`: 알림 규칙 3개

| 규칙 | LogQL | 조건 | 심각도 |
|---|---|---|---|
| Ingestor 연결 끊김 | `count_over_time({service="ingestor"}[10m])` | < 1 (10분간 로그 없음) | critical |
| 처리량 급감 | `count_over_time({service="processor"} \|= "keyword_trends INSERT" [5m])` | < 1 (5분간 flush 없음) | warning |
| DB/S3 에러율 급증 | `count_over_time({service=~"processor\|s3_sink"} \|~ "error\|실패" [5m])` | > 5 | warning |

- Grafana 로그에서 3개 규칙 모두 스케줄러 평가 중 확인 ✅
- **Phase 2 완료**

---

## 다음 작업
- [ ] Phase 3: Unit 테스트 (schema, aggregator)
- [ ] Phase 3: Integration 테스트 (Redpanda → Processor → TimescaleDB)
- [ ] Phase 3: GitHub Actions CI/CD 파이프라인
