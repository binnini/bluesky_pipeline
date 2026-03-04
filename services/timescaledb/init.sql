-- BlueSky Pipeline — TimescaleDB 초기화 스크립트
-- docker-entrypoint-initdb.d 에 의해 컨테이너 최초 기동 시 1회 실행

-- 키워드/해시태그 빈도 (1분 집계)
CREATE TABLE IF NOT EXISTS keyword_trends (
    ts          TIMESTAMPTZ NOT NULL,
    keyword     TEXT        NOT NULL,
    count       INTEGER     NOT NULL,
    window_sec  INTEGER     NOT NULL DEFAULT 60
);
SELECT create_hypertable('keyword_trends', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_keyword_trends_keyword_ts ON keyword_trends (keyword, ts DESC);

-- 포스트 볼륨 (1분 집계)
CREATE TABLE IF NOT EXISTS post_volume (
    ts          TIMESTAMPTZ NOT NULL,
    total_posts INTEGER     NOT NULL,
    window_sec  INTEGER     NOT NULL DEFAULT 60
);
SELECT create_hypertable('post_volume', 'ts', if_not_exists => TRUE);

-- 데이터 보존 정책: 30일 초과 청크 자동 삭제
SELECT add_retention_policy('keyword_trends', INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_retention_policy('post_volume',    INTERVAL '30 days', if_not_exists => TRUE);
