"""Tech.eu 수집기 (Google News 사이트맵).

RSS(/feed/)를 쓰지 않는다. tech.eu/robots.txt 가 모든 수집기에 대해 막아 둔 곳이라
요청하면 403 이 돌아온다. 같은 robots.txt 가 사이트맵은 스스로 알려 주므로 그쪽을 쓴다.

    User-agent: *
    Disallow: /feed/
    Sitemap: https://tech.eu/sitemap/news.xml

news 사이트맵에는 제목과 발행 시각이 함께 들어 있어 RSS 와 같은 정보를 얻는다.
다만 최근 이틀 정도만 담기므로, 하루 한 번 도는 파이프라인에 맞춰 쓴다.
"""
import logging
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree

import requests

from collector.base import _strip_html, resolve_ua

log = logging.getLogger("collector")

SITEMAP = "https://tech.eu/sitemap/news.xml"
_SM = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
_NEWS = "{http://www.google.com/schemas/sitemap-news/0.9}"


def _parse_dt(raw: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(raw.strip())
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def collect(source: dict, config: dict) -> list[dict]:
    ua = resolve_ua(source, config)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=config.get("lookback_hours", 48))

    resp = requests.get(SITEMAP, headers={"User-Agent": ua}, timeout=30)
    resp.raise_for_status()

    try:
        root = ElementTree.fromstring(resp.content)
    except ElementTree.ParseError as e:
        raise RuntimeError(f"Tech.eu: 사이트맵 파싱 실패 ({e})") from e

    articles = []
    for url_el in root.findall(f"{_SM}url"):
        loc = (url_el.findtext(f"{_SM}loc") or "").strip()
        news = url_el.find(f"{_NEWS}news")
        if not loc or news is None:
            continue
        title = _strip_html(news.findtext(f"{_NEWS}title") or "")
        published = _parse_dt(news.findtext(f"{_NEWS}publication_date") or "")
        if not title or published is None or published < cutoff:
            continue
        articles.append({
            "title": title,
            # 사이트맵이 끝에 슬래시를 하나 더 붙여 주는 때가 있다. 중복 판정이 어긋나므로 정리한다.
            "url": loc.rstrip("/") + "/",
            "published": published.date().isoformat(),
            # 사이트맵에는 요약이 없다. 키워드가 있으면 그거라도 넘긴다.
            "summary": _strip_html(news.findtext(f"{_NEWS}keywords") or "")[:1500],
            "source_name": source["name"],
            "region_hint": source.get("region_hint", ""),
        })

    if not articles:
        log.warning("Tech.eu: 사이트맵에 최근 %d시간 기사가 없음", config.get("lookback_hours", 48))
    return articles
