"""1분 버킷 집계, 키워드 전처리, TimescaleDB INSERT"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime
from typing import TYPE_CHECKING

import nltk
import psycopg2  # noqa: F401

if TYPE_CHECKING:
    import psycopg2.extensions

# NLTK stopwords 최초 실행 시 다운로드
nltk.download("stopwords", quiet=True)
from nltk.corpus import stopwords  # noqa: E402

logger = logging.getLogger(__name__)

_STOPWORDS: set[str] = set(stopwords.words("english"))
_NON_ALNUM = re.compile(r"[^a-z0-9가-힣]")  # 영문 소문자·숫자·한글만 허용

MIN_KEYWORD_LEN = 2
MAX_KEYWORD_LEN = 50
MIN_KEYWORD_FREQ = 3   # 1분 윈도우 내 최소 빈도


def preprocess_keywords(words: list[str]) -> list[str]:
    """키워드 전처리.

    순서:
        1. 소문자 변환
        2. 특수문자 제거 (영문 소문자·숫자·한글만 유지)
        3. English stopwords 제거
        4. 길이 필터 (2자 이상, 50자 이하)
    """
    result: list[str] = []
    for word in words:
        word = word.lower()
        word = _NON_ALNUM.sub("", word)
        if not word:
            continue
        if word in _STOPWORDS:
            continue
        if not (MIN_KEYWORD_LEN <= len(word) <= MAX_KEYWORD_LEN):
            continue
        result.append(word)
    return result


class MinuteBucketAggregator:
    """1분 단위 집계 버퍼.

    main.py 가 wall-clock 기준으로 60초마다 flush()를 호출해
    TimescaleDB에 INSERT한다.
    """

    def __init__(self, conn: "psycopg2.extensions.connection") -> None:
        self._conn = conn
        self._keyword_counts: defaultdict[str, int] = defaultdict(int)
        self._post_count = 0

    def add(self, message: dict) -> None:
        """메시지에서 해시태그를 추출·전처리 후 카운터 증가."""
        hashtags: list[str] = message.get("hashtags") or []
        for kw in preprocess_keywords(hashtags):
            self._keyword_counts[kw] += 1
        self._post_count += 1

    def flush(self, bucket_ts: datetime) -> None:
        """현재 버퍼를 TimescaleDB에 INSERT하고 카운터를 초기화.

        Args:
            bucket_ts: 버킷 기준 타임스탬프 (초·마이크로초 0으로 내림)
        """
        post_count = self._post_count
        keyword_rows = [
            (bucket_ts, kw, count, 60)
            for kw, count in self._keyword_counts.items()
            if count >= MIN_KEYWORD_FREQ
        ]

        if post_count == 0:
            return

        try:
            cur = self._conn.cursor()

            if keyword_rows:
                cur.executemany(
                    "INSERT INTO keyword_trends (ts, keyword, count, window_sec)"
                    " VALUES (%s, %s, %s, %s)",
                    keyword_rows,
                )
                logger.info(
                    "keyword_trends INSERT: ts=%s, keywords=%d",
                    bucket_ts.isoformat(),
                    len(keyword_rows),
                )

            cur.execute(
                "INSERT INTO post_volume (ts, total_posts, window_sec) VALUES (%s, %s, %s)",
                (bucket_ts, post_count, 60),
            )
            logger.info(
                "post_volume INSERT: ts=%s, total_posts=%d",
                bucket_ts.isoformat(),
                post_count,
            )

            self._conn.commit()

        except Exception as exc:
            logger.error("TimescaleDB INSERT 실패: %s", exc)
            try:
                self._conn.rollback()
            except Exception:
                pass

        finally:
            # INSERT 성공/실패 무관하게 버퍼 초기화
            self._keyword_counts.clear()
            self._post_count = 0
