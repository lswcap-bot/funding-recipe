"""Tech in Asia 수집기 (RSS, 페이월 소스 - 제목/요약만 사용, 본문 크롤링 금지)."""
from collector.base import collect_rss


def collect(source: dict, config: dict) -> list[dict]:
    return collect_rss(source, config)
