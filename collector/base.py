"""RSS 기반 수집 공통 로직."""
import calendar
import html
import logging
import re
from datetime import datetime, timedelta, timezone

import feedparser
import requests

log = logging.getLogger("collector")

_TAG_RE = re.compile(r"<[^>]+>")

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def resolve_ua(source: dict, config: dict) -> str:
    """일부 소스(CDN 봇 차단)는 브라우저 UA가 필요하다. config에 browser_ua: true 지정."""
    if source.get("browser_ua"):
        return BROWSER_UA
    return config.get("user_agent", "FundingRecipeBot/0.1")


def _strip_html(text: str) -> str:
    return html.unescape(_TAG_RE.sub(" ", text or "")).strip()


def _entry_datetime(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
    return None


def collect_rss(source: dict, config: dict) -> list[dict]:
    """RSS 피드에서 최근 lookback_hours 이내 기사 목록을 반환한다."""
    url = source["rss"]
    ua = resolve_ua(source, config)
    lookback = timedelta(hours=config.get("lookback_hours", 48))
    cutoff = datetime.now(timezone.utc) - lookback

    resp = requests.get(url, headers={"User-Agent": ua}, timeout=30)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)

    if feed.bozo and not feed.entries:
        raise RuntimeError(f"RSS 파싱 실패: {url} ({feed.bozo_exception})")

    articles = []
    for entry in feed.entries:
        published = _entry_datetime(entry)
        if published is None or published < cutoff:
            continue
        link = getattr(entry, "link", None)
        title = _strip_html(getattr(entry, "title", ""))
        if not link or not title:
            continue
        summary = _strip_html(getattr(entry, "summary", ""))
        articles.append({
            "title": title,
            "url": link,
            "published": published.date().isoformat(),
            "summary": summary[:1500],
            "source_name": source["name"],
            "region_hint": source.get("region_hint", ""),
        })
    return articles
