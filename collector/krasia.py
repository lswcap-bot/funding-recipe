"""KrASIA 수집기 (RSS 미제공 → 홈페이지 __NEXT_DATA__ JSON 파싱으로 보완)."""
import json
import re
from datetime import datetime, timedelta, timezone

import requests

from collector.base import _strip_html, resolve_ua

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)


def _post_datetime(post: dict) -> datetime | None:
    """date 필드는 epoch ms 문자열 또는 ISO 문자열."""
    raw = post.get("date_gmt") or post.get("date")
    if raw is None:
        return None
    raw = str(raw)
    try:
        if raw.isdigit():
            return datetime.fromtimestamp(int(raw) / 1000, tz=timezone.utc)
        return datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
    except (ValueError, OSError):
        return None


def collect(source: dict, config: dict) -> list[dict]:
    ua = resolve_ua(source, config)
    lookback = timedelta(hours=config.get("lookback_hours", 48))
    cutoff = datetime.now(timezone.utc) - lookback

    resp = requests.get("https://kr-asia.com/", headers={"User-Agent": ua}, timeout=30)
    resp.raise_for_status()
    m = _NEXT_DATA_RE.search(resp.text)
    if not m:
        raise RuntimeError("KrASIA: __NEXT_DATA__ 스크립트를 찾을 수 없음 (페이지 구조 변경?)")

    data = json.loads(m.group(1))
    posts: list[dict] = []

    def walk(obj):
        if isinstance(obj, dict):
            if obj.get("type") == "post" and "title" in obj and "slug" in obj:
                posts.append(obj)
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(data.get("props", {}).get("pageProps", {}))

    articles = []
    seen = set()
    for p in posts:
        slug = p.get("slug")
        if not slug or slug in seen:
            continue
        seen.add(slug)
        published = _post_datetime(p)
        if published is None or published < cutoff:
            continue
        title = p.get("title")
        if isinstance(title, dict):
            title = title.get("rendered", "")
        excerpt = p.get("excerpt")
        if isinstance(excerpt, dict):
            excerpt = excerpt.get("rendered", "")
        articles.append({
            "title": _strip_html(str(title)),
            "url": f"https://kr-asia.com/{slug}",
            "published": published.date().isoformat(),
            "summary": _strip_html(str(excerpt or ""))[:1500],
            "source_name": source["name"],
            "region_hint": source.get("region_hint", ""),
        })
    return articles
