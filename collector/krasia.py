"""KrASIA 수집기 (RSS 미제공 → 홈페이지 목록 파싱).

예전에는 홈페이지의 __NEXT_DATA__ JSON 에 글 목록과 날짜가 들어 있었다.
사이트가 Next.js 앱 라우터로 옮기면서 그 스크립트가 사라져 수집이 멈췄다.
지금은 목록이 평범한 <article> 마크업으로 나오므로 그쪽에서 제목과 주소를 읽는다.

주의: 바뀐 마크업에는 발행일이 없다. 본문 페이지를 글마다 열어 날짜를 확인하면
요청이 수십 배로 늘어나므로, 수집일을 발행일로 쓴다. 홈페이지 맨 앞이 최신이고
파이프라인이 매일 도는 데다 이미 본 주소는 processed_urls 가 걸러 내므로,
하루 안팎의 오차로 수렴한다. 정확한 날짜가 필요하면 그때 본문을 열어야 한다.

robots.txt 는 /wp-json/ 만 막고 홈페이지는 허용한다(2026-11 확인).
"""
import logging
import re
from datetime import datetime, timezone

import requests

from collector.base import _strip_html, resolve_ua

log = logging.getLogger("collector")

HOME = "https://kr-asia.com/"

# <a ... href="/slug"><h3 ...>제목</h3></a> 형태. 목록 카드가 모두 이 모양이다.
_CARD_RE = re.compile(
    r'<a[^>]+href="(/[^"#?]+)"[^>]*>\s*<h[1-4][^>]*>(.*?)</h[1-4]>\s*</a>', re.S
)

# 글이 아닌 링크(섹션·태그·정적 페이지)는 거른다.
_NOT_POST = re.compile(
    r"^/(?:page|category|tag|author|about|contact|privacy|terms|advertise|events?|"
    r"newsletter|subscribe|search|feed)(?:/|$)"
)


def collect(source: dict, config: dict) -> list[dict]:
    ua = resolve_ua(source, config)
    max_items = int(source.get("max_items") or config.get("krasia_max_items", 40))

    resp = requests.get(HOME, headers={"User-Agent": ua}, timeout=30)
    resp.raise_for_status()

    today = datetime.now(timezone.utc).date().isoformat()
    articles = []
    seen = set()

    for href, raw_title in _CARD_RE.findall(resp.text):
        slug = href.strip()
        if _NOT_POST.match(slug) or slug.count("/") != 1 or len(slug) < 12:
            continue
        title = _strip_html(raw_title)
        if not title or len(title) < 15 or slug in seen:
            continue
        seen.add(slug)
        articles.append({
            "title": title,
            "url": "https://kr-asia.com" + slug,
            "published": today,   # 위 주석 참고: 목록에 발행일이 없어 수집일을 쓴다
            "summary": "",        # 목록에 발췌문이 없다. 판별은 제목으로 한다
            "source_name": source["name"],
            "region_hint": source.get("region_hint", ""),
        })
        if len(articles) >= max_items:
            break

    if not articles:
        raise RuntimeError("KrASIA: 홈페이지에서 글 목록을 찾지 못함 (페이지 구조 변경?)")
    return articles
