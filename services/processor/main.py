"""Redpanda (bluesky-raw) → 1분 집계 → TimescaleDB Processor"""
from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone

import psycopg2
from confluent_kafka import Consumer, KafkaError

from aggregator import MinuteBucketAggregator

# ── 로깅 ─────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── 설정 ─────────────────────────────────────────────────────────────────────
KAFKA_BROKERS = os.getenv("KAFKA_BROKERS", "redpanda:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "bluesky-raw")
KAFKA_GROUP_ID = os.getenv("KAFKA_GROUP_ID", "processor")
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://bluesky:bluesky@timescaledb:5432/bluesky",
)
FLUSH_INTERVAL_SEC = int(os.getenv("FLUSH_INTERVAL_SEC", "60"))
POLL_TIMEOUT_SEC = 1.0


# ── DB 연결 ───────────────────────────────────────────────────────────────────
def _connect_db(
    dsn: str,
    max_retries: int = 10,
    retry_delay: float = 3.0,
) -> psycopg2.extensions.connection:
    """TimescaleDB 연결 (재시도 포함)."""
    for attempt in range(1, max_retries + 1):
        try:
            conn = psycopg2.connect(dsn)
            logger.info("TimescaleDB 연결 성공")
            return conn
        except Exception as exc:
            logger.warning(
                "TimescaleDB 연결 실패 (시도 %d/%d): %s", attempt, max_retries, exc
            )
            if attempt < max_retries:
                time.sleep(retry_delay)

    logger.error("TimescaleDB 연결 최대 재시도 초과, 종료")
    sys.exit(1)


# ── 진입점 ────────────────────────────────────────────────────────────────────
def main() -> None:
    running = True

    def _shutdown(signum, frame) -> None:
        nonlocal running
        logger.info("종료 신호 수신 (signal=%d)", signum)
        running = False

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    db_conn = _connect_db(DATABASE_URL)
    aggregator = MinuteBucketAggregator(db_conn)

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

    last_flush_at = time.monotonic()
    processed = 0

    try:
        while running:
            msg = consumer.poll(POLL_TIMEOUT_SEC)

            # 플러시 주기 도달 시 TimescaleDB INSERT
            now = time.monotonic()
            if now - last_flush_at >= FLUSH_INTERVAL_SEC:
                bucket_ts = datetime.now(timezone.utc).replace(second=0, microsecond=0)
                aggregator.flush(bucket_ts)
                last_flush_at = now

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

            aggregator.add(data)
            processed += 1

            if processed % 1000 == 0:
                logger.info("누적 처리 메시지: %d", processed)

    finally:
        logger.info("최종 flush 후 종료...")
        bucket_ts = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        aggregator.flush(bucket_ts)
        consumer.close()
        db_conn.close()
        logger.info("Processor 종료 완료.")


if __name__ == "__main__":
    main()
