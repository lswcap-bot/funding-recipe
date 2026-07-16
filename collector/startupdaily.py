"""Startup Daily 수집기 (RSS)."""
from collector.base import collect_rss


def collect(source: dict, config: dict) -> list[dict]:
    return collect_rss(source, config)
