"""BlueSky Firehose → Redpanda Ingestor"""
from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
from datetime import datetime, timezone

from atproto import CAR, FirehoseSubscribeReposClient, parse_subscribe_repos_message
from confluent_kafka import Producer

from reconnect import run_with_backoff
from schema import is_post_create, parse_record

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

# ── Kafka Producer (프로세스 수명 동안 단일 인스턴스) ─────────────────────────
_producer = Producer(
    {
        "bootstrap.servers": KAFKA_BROKERS,
        "linger.ms": 50,                   # 소량 배치로 처리량 개선
        "queue.buffering.max.messages": 10_000,   # 100k → 10k
        "queue.buffering.max.kbytes": 32_768,     # 128MB → 32MB
    }
)


def _delivery_report(err, msg) -> None:
    if err:
        logger.error("Kafka produce 실패 [topic=%s]: %s", msg.topic(), err)


# ── 메시지 처리 ───────────────────────────────────────────────────────────────
def _build_payload(commit, op, record_data: dict) -> bytes:
    return json.dumps(
        {
            "cid": str(op.cid),
            "did": commit.repo,
            "seq": commit.seq,
            "text": record_data["text"],
            "hashtags": record_data["hashtags"],
            "langs": record_data["langs"],
            "created_at": record_data["created_at"],
            "ingested_at": datetime.now(timezone.utc).isoformat(),
        },
        ensure_ascii=False,
    ).encode()


def _make_message_handler(stop_event: threading.Event):
    processed = 0

    def on_message(message) -> None:
        nonlocal processed

        if stop_event.is_set():
            return

        try:
            commit = parse_subscribe_repos_message(message)
        except Exception as exc:
            logger.debug("메시지 파싱 실패: %s", exc)
            return

        if not hasattr(commit, "ops"):
            return

        # too_big 커밋은 블록 데이터가 없으므로 스킵
        if getattr(commit, "too_big", False):
            return

        try:
            car = CAR.from_bytes(commit.blocks)
        except Exception as exc:
            logger.debug("CAR 디코딩 실패 (seq=%s): %s", getattr(commit, "seq", "?"), exc)
            return

        for op in commit.ops:
            if not is_post_create(op):
                continue

            raw = car.blocks.get(op.cid)
            record_data = parse_record(raw)
            if record_data is None:
                continue

            _producer.produce(
                KAFKA_TOPIC,
                key=commit.repo.encode(),
                value=_build_payload(commit, op, record_data),
                callback=_delivery_report,
            )
            processed += 1

            if processed % 500 == 0:
                _producer.poll(0)
                logger.info("누적 처리 포스트: %d", processed)

    return on_message


# ── Firehose 연결 (재연결 단위 함수) ─────────────────────────────────────────
def _connect(stop_event: threading.Event) -> None:
    client = FirehoseSubscribeReposClient()

    # stop_event 감지 시 클라이언트 종료
    def _watch_stop():
        stop_event.wait()
        client.stop()

    watcher = threading.Thread(target=_watch_stop, daemon=True)
    watcher.start()

    client.start(_make_message_handler(stop_event))


# ── 진입점 ────────────────────────────────────────────────────────────────────
def main() -> None:
    stop_event = threading.Event()

    def _shutdown(signum, frame):
        logger.info("종료 신호 수신 (signal=%d), 플러시 후 종료...", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        run_with_backoff(
            lambda: _connect(stop_event),
            stop_event,
        )
    finally:
        logger.info("Producer 플러시 중...")
        _producer.flush(timeout=15)
        logger.info("종료 완료.")


if __name__ == "__main__":
    main()
