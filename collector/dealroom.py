"""Dealroom News 수집기 (Google News 사이트맵 + 기사별 요약).

robots.txt 가 모든 수집기에 Allow: / 를 주고, 뉴스 사이트맵을 스스로 알려 준다.

    User-agent: *
    Allow: /
    Sitemap: https://dealroom.co/news/news-sitemap.xml

사이트맵에는 제목과 발행 시각만 있고 요약이 없다. 제목만으로는 금액·투자사·단계를
뽑아내기 어려워, 추린 기사에 한해 본문 페이지의 og:description 을 한 번씩 더 받아 온다.
사이트맵이 사흘치(하루 150건 안팎)를 담으므로 lookback_hours 로 먼저 줄이고 받는다.
"""
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree

import requests

from collector.base import _strip_html, resolve_ua

log = logging.getLogger("collector")

SITEMAP = "https://dealroom.co/news/news-sitemap.xml"
_SM = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
_NEWS = "{http://www.google.com/schemas/sitemap-news/0.9}"

_META_RE = [
    re.compile(r'<meta[^>]+property="og:description"[^>]+content="([^"]*)"', re.I),
    re.compile(r'<meta[^>]+content="([^"]*)"[^>]+property="og:description"', re.I),
    re.compile(r'<meta[^>]+name="description"[^>]+content="([^"]*)"', re.I),
]


def _parse_dt(raw: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(raw.strip())
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _summary(url: str, ua: str, timeout: int) -> str:
    """기사 페이지의 og:description. 실패하면 빈 문자열(제목만으로 판별한다)."""
    try:
        resp = requests.get(url, headers={"User-Agent": ua}, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException:
        return ""
    for pat in _META_RE:
        m = pat.search(resp.text)
        if m and m.group(1).strip():
            return _strip_html(m.group(1))[:1500]
    return ""


def collect(source: dict, config: dict) -> list[dict]:
    ua = resolve_ua(source, config)
    timeout = int(source.get("timeout") or 20)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=config.get("lookback_hours", 48))
    max_items = int(source.get("max_items") or 200)

    resp = requests.get(SITEMAP, headers={"User-Agent": ua}, timeout=30)
    resp.raise_for_status()
    try:
        root = ElementTree.fromstring(resp.content)
    except ElementTree.ParseError as e:
        raise RuntimeError(f"Dealroom: 사이트맵 파싱 실패 ({e})") from e

    picked = []
    for url_el in root.findall(f"{_SM}url"):
        loc = (url_el.findtext(f"{_SM}loc") or "").strip()
        news = url_el.find(f"{_NEWS}news")
        if not loc or news is None:
            continue
        title = _strip_html(news.findtext(f"{_NEWS}title") or "")
        published = _parse_dt(news.findtext(f"{_NEWS}publication_date") or "")
        if not title or published is None or published < cutoff:
            continue
        picked.append((loc, title, published))

    picked.sort(key=lambda r: r[2], reverse=True)
    if len(picked) > max_items:
        log.info("Dealroom: 최근 기사 %d건 중 최신 %d건만 가져온다", len(picked), max_items)
        picked = picked[:max_items]

    if not picked:
        log.warning("Dealroom: 사이트맵에 최근 %d시간 기사가 없음", config.get("lookback_hours", 48))
        return []

    # 요약은 기사마다 한 번씩 받아야 한다. 같은 호스트라 동시 요청 수를 낮게 둔다.
    with ThreadPoolExecutor(max_workers=int(source.get("workers") or 5)) as ex:
        summaries = list(ex.map(lambda r: _summary(r[0], ua, timeout), picked))

    got = sum(1 for s in summaries if s)
    if got < len(picked):
        log.info("Dealroom: 요약 %d/%d건 확보 (나머지는 제목만으로 판별)", got, len(picked))

    return [
        {
            "title": title,
            "url": loc,
            "published": published.date().isoformat(),
            "summary": summary,
            "source_name": source["name"],
            "region_hint": source.get("region_hint", ""),
        }
        for (loc, title, published), summary in zip(picked, summaries)
    ]
