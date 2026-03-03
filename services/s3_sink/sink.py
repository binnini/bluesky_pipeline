"""Redpanda (bluesky-raw) → Parquet → S3/MinIO Sink

S3 전환 방법:
    - 로컬(MinIO): S3_ENDPOINT_URL=http://minio:9000
    - AWS S3:      S3_ENDPOINT_URL 환경변수 제거 + AWS 자격증명 교체
"""
from __future__ import annotations

import io
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone

import boto3
import pyarrow as pa
import pyarrow.parquet as pq
from confluent_kafka import Consumer, KafkaError

# ── 로깅 ─────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── 설정 ─────────────────────────────────────────────────────────────────────
KAFKA_BROKERS      = os.getenv("KAFKA_BROKERS", "redpanda:9092")
KAFKA_TOPIC        = os.getenv("KAFKA_TOPIC", "bluesky-raw")
KAFKA_GROUP_ID     = os.getenv("KAFKA_GROUP_ID", "s3_sink")
S3_BUCKET          = os.getenv("S3_BUCKET", "bluesky-raw")
S3_ENDPOINT_URL    = os.getenv("S3_ENDPOINT_URL")          # MinIO: http://minio:9000, AWS: 비워둠
AWS_ACCESS_KEY_ID  = os.getenv("AWS_ACCESS_KEY_ID", "minioadmin")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "minioadmin")
MAX_RECORDS        = int(os.getenv("MAX_RECORDS", "50000")) # 건수 초과 시 flush
POLL_TIMEOUT_SEC   = 1.0

# ── Parquet 스키마 ────────────────────────────────────────────────────────────
_SCHEMA = pa.schema([
    pa.field("cid",         pa.string()),
    pa.field("did",         pa.string()),
    pa.field("seq",         pa.int64()),
    pa.field("text",        pa.string()),
    pa.field("hashtags",    pa.list_(pa.string())),
    pa.field("langs",       pa.list_(pa.string())),
    pa.field("created_at",  pa.string()),
    pa.field("ingested_at", pa.string()),
])


# ── S3 클라이언트 ─────────────────────────────────────────────────────────────
def _make_s3_client():
    kwargs = dict(
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name="us-east-1",
    )
    if S3_ENDPOINT_URL:
        kwargs["endpoint_url"] = S3_ENDPOINT_URL
    return boto3.client("s3", **kwargs)


def _wait_for_bucket(s3, bucket: str, max_retries: int = 20, retry_delay: float = 3.0) -> None:
    """버킷이 존재할 때까지 대기 (MinIO 기동 완료 확인)."""
    for attempt in range(1, max_retries + 1):
        try:
            s3.head_bucket(Bucket=bucket)
            logger.info("S3 버킷 확인 완료: %s", bucket)
            return
        except Exception as exc:
            logger.warning("S3 버킷 대기 중 (시도 %d/%d): %s", attempt, max_retries, exc)
            time.sleep(retry_delay)
    logger.error("S3 버킷 준비 시간 초과: %s", bucket)
    sys.exit(1)


def _partition_prefix(ts: datetime) -> str:
    """Hive 스타일 시간별 파티션 경로."""
    return (
        f"year={ts.year:04d}/month={ts.month:02d}"
        f"/day={ts.day:02d}/hour={ts.hour:02d}"
    )


# ── Parquet 버퍼 ──────────────────────────────────────────────────────────────
class ParquetBuffer:
    """메시지를 버퍼링해 Parquet으로 변환 후 S3에 업로드.

    Flush 조건 (먼저 도달하는 것):
        1. 시간 경계(hour) 변경
        2. 버퍼 건수 >= MAX_RECORDS
    """

    def __init__(self, s3, bucket: str, max_records: int) -> None:
        self._s3 = s3
        self._bucket = bucket
        self._max_records = max_records
        self._rows: list[dict] = []
        self._current_hour: str | None = None
        self._part_counter = 0

    def add(self, message: dict) -> None:
        ingested_at = message.get("ingested_at") or ""
        try:
            ts = datetime.fromisoformat(ingested_at.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            ts = datetime.now(timezone.utc)

        hour_key = _partition_prefix(ts)

        # 시간 경계가 바뀌면 이전 버퍼를 먼저 flush
        if self._current_hour is not None and hour_key != self._current_hour:
            self.flush()

        self._current_hour = hour_key
        self._rows.append(message)

        if len(self._rows) >= self._max_records:
            self.flush()

    def flush(self) -> None:
        if not self._rows:
            return

        rows = self._rows
        partition = self._current_hour
        self._rows = []

        table = pa.table(
            {
                "cid":         [r.get("cid") or "" for r in rows],
                "did":         [r.get("did") or "" for r in rows],
                "seq":         [r.get("seq") or 0 for r in rows],
                "text":        [r.get("text") or "" for r in rows],
                "hashtags":    [r.get("hashtags") or [] for r in rows],
                "langs":       [r.get("langs") or [] for r in rows],
                "created_at":  [r.get("created_at") or "" for r in rows],
                "ingested_at": [r.get("ingested_at") or "" for r in rows],
            },
            schema=_SCHEMA,
        )

        buf = io.BytesIO()
        pq.write_table(table, buf, compression="snappy")
        buf.seek(0)
        parquet_bytes = buf.getvalue()

        self._part_counter += 1
        key = f"{partition}/part-{self._part_counter:05d}.parquet"

        try:
            self._s3.put_object(Bucket=self._bucket, Key=key, Body=parquet_bytes)
            logger.info(
                "S3 업로드 완료: s3://%s/%s (%d rows, %.1f KB)",
                self._bucket, key, len(rows), len(parquet_bytes) / 1024,
            )
        except Exception as exc:
            logger.error("S3 업로드 실패 [%s]: %s", key, exc)


# ── 진입점 ────────────────────────────────────────────────────────────────────
def main() -> None:
    running = True

    def _shutdown(signum, frame) -> None:
        nonlocal running
        logger.info("종료 신호 수신 (signal=%d)", signum)
        running = False

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    s3 = _make_s3_client()
    _wait_for_bucket(s3, S3_BUCKET)
    buffer = ParquetBuffer(s3, S3_BUCKET, MAX_RECORDS)

    consumer = Consumer(
        {
            "bootstrap.servers": KAFKA_BROKERS,
            "group.id": KAFKA_GROUP_ID,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": True,
        }
    )
    consumer.subscribe([KAFKA_TOPIC])
    logger.info(
        "Consumer 구독 시작: topic=%s, group=%s", KAFKA_TOPIC, KAFKA_GROUP_ID
    )

    processed = 0

    try:
        while running:
            msg = consumer.poll(POLL_TIMEOUT_SEC)
            if msg is None:
                continue

            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                logger.error("Kafka 에러: %s", msg.error())
                continue

            try:
                data = json.loads(msg.value().decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                logger.warning("메시지 디코딩 실패: %s", exc)
                continue

            buffer.add(data)
            processed += 1

            if processed % 10000 == 0:
                logger.info("누적 처리 메시지: %d", processed)

    finally:
        logger.info("최종 flush 후 종료...")
        buffer.flush()
        consumer.close()
        logger.info("S3 Sink 종료 완료.")


if __name__ == "__main__":
    main()
