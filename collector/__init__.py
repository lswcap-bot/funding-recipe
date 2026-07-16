import importlib
import logging
import time

log = logging.getLogger("collector")


def collect_all(config: dict) -> list[dict]:
    """활성화된 모든 소스에서 기사를 수집한다. 소스 하나가 실패해도 계속 진행."""
    articles = []
    delay = config.get("request_delay_seconds", 2.5)
    enabled = [s for s in config["sources"] if s.get("enabled")]

    for i, source in enumerate(enabled):
        try:
            mod = importlib.import_module(f"collector.{source['module']}")
            items = mod.collect(source, config)
            log.info("[%s] %d건 수집", source["name"], len(items))
            articles.extend(items)
        except Exception:
            log.exception("[%s] 수집 실패 - 건너뜀", source["name"])
        if i < len(enabled) - 1:
            time.sleep(delay)

    return articles
