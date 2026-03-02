"""AT Protocol 이벤트 파싱 및 검증"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_POST_TYPE = "app.bsky.feed.post"
_TAG_FEATURE_TYPE = "app.bsky.richtext.facet#tag"

_MIN_TEXT_LEN = 1
_MAX_TEXT_LEN = 3000  # Bluesky 포스트는 최대 300 grapheme이나 바이트 여유 확보


def is_post_create(op: Any) -> bool:
    """Firehose op이 포스트 생성 이벤트인지 확인"""
    return (
        getattr(op, "action", None) == "create"
        and getattr(op, "path", "").startswith("app.bsky.feed.post/")
    )


def extract_hashtags(record: dict) -> list[str]:
    """facets에서 해시태그 추출 (소문자 정규화)"""
    hashtags = []
    for facet in record.get("facets") or []:
        for feature in facet.get("features") or []:
            if feature.get("$type") == _TAG_FEATURE_TYPE:
                tag = feature.get("tag", "").strip()
                if tag:
                    hashtags.append(tag.lower())
    return hashtags


def parse_record(record: dict | None) -> dict | None:
    """
    CAR 블록에서 파싱한 record dict를 검증하고 정규화.
    유효하지 않으면 None 반환.
    """
    if not record:
        return None

    if record.get("$type") != _POST_TYPE:
        return None

    text: str = record.get("text") or ""
    if not (_MIN_TEXT_LEN <= len(text) <= _MAX_TEXT_LEN):
        logger.debug("텍스트 길이 필터 탈락: len=%d", len(text))
        return None

    return {
        "text": text,
        "hashtags": extract_hashtags(record),
        "langs": record.get("langs") or [],
        "created_at": record.get("createdAt") or "",
    }
