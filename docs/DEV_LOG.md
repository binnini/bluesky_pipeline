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

## 다음 작업
- [ ] Phase 2: Terraform 인프라 (EC2 t3.medium, S3, SG, IAM, EIP)
