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

## 다음 작업
- [ ] Processor 구현 (Redpanda → 1분 집계 → TimescaleDB)
