"""메인 파이프라인: 수집 → 판별·추출 → 저장 → JSON 내보내기.

사용법:
    python pipeline.py                  # 전체 파이프라인 실행 (ANTHROPIC_API_KEY 필요)
    python pipeline.py --collect-only  # 수집만 실행 (API 키 불필요, 결과 미리보기)
    python pipeline.py --limit 10      # 추출할 기사 수 제한 (비용 테스트용)
"""
import argparse
import logging
import os
import sys

import yaml

import storage
from collector import collect_all

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pipeline")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--collect-only", action="store_true", help="수집 단계만 실행")
    parser.add_argument("--limit", type=int, default=None, help="추출할 기사 수 제한")
    args = parser.parse_args()

    with open("config.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # ── 1단계: 수집 ──────────────────────────────────────
    log.info("=== 1단계: 수집 시작 ===")
    articles = collect_all(config)
    log.info("수집 완료: 총 %d건", len(articles))

    conn = storage.connect()
    fresh = storage.filter_new_articles(conn, articles)
    log.info("신규 기사 (미처리): %d건", len(fresh))

    if args.collect_only:
        for a in fresh[:20]:
            log.info("  - [%s] %s (%s)", a["source_name"], a["title"], a["published"])
        if len(fresh) > 20:
            log.info("  ... 외 %d건", len(fresh) - 20)
        return

    if not fresh:
        log.info("처리할 신규 기사가 없습니다. JSON만 갱신합니다.")
        storage.export_json(conn)
        return

    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.error("ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다. "
                  "설정 후 다시 실행하거나 --collect-only로 수집만 확인하세요.")
        sys.exit(1)

    if args.limit:
        fresh = fresh[:args.limit]
        log.info("--limit 적용: %d건만 추출", len(fresh))

    # ── 2단계: 판별 + 추출 (Claude API) ──────────────────
    log.info("=== 2단계: 판별·추출 시작 (모델: %s) ===", config["model"])
    from extractor.extractor import extract_all
    deals = extract_all(fresh, config)
    log.info("추출 완료: 투자 뉴스 %d건", len(deals))

    # ── 3단계: 중복 제거 ─────────────────────────────────
    log.info("=== 3단계: 중복 제거 ===")
    from deduplicator import dedupe
    funding_urls = {d["source_url"] for d in deals}
    new_deals, merged = dedupe(conn, deals)
    log.info("중복 제거 완료: 신규 %d건, 병합 %d건", len(new_deals), merged)

    # ── 4단계: 저장 + JSON 내보내기 ──────────────────────
    log.info("=== 4단계: 저장 ===")
    storage.save_results(conn, fresh, new_deals, funding_urls)
    storage.export_json(conn)
    log.info("파이프라인 완료")


if __name__ == "__main__":
    main()
