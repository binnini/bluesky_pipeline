"""Exponential Backoff Reconnect 유틸리티"""
from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)


def run_with_backoff(
    fn: Callable[[], None],
    stop_event: threading.Event,
    *,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
) -> None:
    """
    stop_event가 set될 때까지 fn을 무한 재시도.
    실패 시 Jitter 포함 Exponential Backoff 적용.

    base_delay: 첫 재시도 대기 시간(초)
    max_delay:  대기 시간 상한(초)
    """
    attempt = 0

    while not stop_event.is_set():
        try:
            logger.info("Firehose 연결 시도 (attempt=%d)", attempt + 1)
            fn()
            # fn()이 예외 없이 반환 → 외부에서 정상 종료된 경우
            if stop_event.is_set():
                break
            logger.warning("Firehose 클라이언트가 예기치 않게 종료됨, 재연결합니다.")
        except Exception as exc:
            if stop_event.is_set():
                break
            logger.error("Firehose 연결 오류: %s", exc)

        attempt += 1
        # Full Jitter: delay = random(0, min(cap, base * 2^attempt))
        ceiling = min(max_delay, base_delay * (2 ** (attempt - 1)))
        delay = random.uniform(0, ceiling)
        logger.info("%.1f초 후 재연결... (attempt=%d)", delay, attempt + 1)
        stop_event.wait(timeout=delay)
