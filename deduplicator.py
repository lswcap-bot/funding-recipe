"""중복 제거: 같은 투자 건이 여러 소스에 실린 경우 병합.

기준: 회사명(정규화) + 투자 단계 + 금액(±10% 허용).
병합 시 소스는 배열로 모두 보존, 요약은 정보량이 많은 쪽(긴 쪽) 유지.
"""
import json
import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone

log = logging.getLogger("dedup")

_LEGAL_SUFFIXES = {"inc", "ltd", "llc", "gmbh", "corp", "limited", "co", "sa", "ag", "bv", "ab"}
_NON_ALNUM = re.compile(r"[^a-z0-9가-힣\s]")

MATCH_WINDOW_DAYS = 30  # 이 기간 내 기존 딜과만 비교


def normalize_company(name: str) -> str:
    s = _NON_ALNUM.sub(" ", (name or "").lower())
    tokens = [t for t in s.split() if t not in _LEGAL_SUFFIXES]
    return "".join(tokens)


def _amounts_match(a: int | None, b: int | None) -> bool:
    """둘 다 있으면 ±10% 이내, 한쪽이라도 비공개면 매치로 간주."""
    if a is None or b is None:
        return True
    hi, lo = max(a, b), min(a, b)
    return lo >= hi * 0.9


_STAGE_ALIASES = {
    "seed": "시드", "preseed": "프리시드", "pre seed": "프리시드",
    "series a": "시리즈 A", "series b": "시리즈 B", "series c": "시리즈 C",
    "series d": "시리즈 D+", "series e": "시리즈 E", "series f": "시리즈 F",
    "growth": "그로스", "bridge": "브릿지",
    "pre series a": "프리시리즈A", "프리 시리즈 a": "프리시리즈A",
}


def normalize_stage(stage: str | None) -> str | None:
    """영문/국문 혼용 단계 표기를 표준 한국어 라벨로 정규화."""
    if not stage:
        return None
    key = re.sub(r"[^a-z가-힣\sA-Z+]", "", stage).strip().lower().replace("-", " ")
    return _STAGE_ALIASES.get(key, stage)


def _stages_match(a: str | None, b: str | None) -> bool:
    """단계가 같거나(표기 정규화 후), 한쪽이 불명(비공개/None)이면 매치."""
    if not a or not b or a == "비공개" or b == "비공개":
        return True
    return normalize_stage(a) == normalize_stage(b)


def _is_same_deal(existing: dict, new: dict) -> bool:
    return (
        normalize_company(existing["company"]) == normalize_company(new["company"])
        and _stages_match(existing.get("stage"), new.get("stage"))
        and _amounts_match(existing.get("amount_usd"), new.get("amount_usd"))
    )


def _merge(base: dict, new: dict) -> dict:
    """new의 정보를 base에 병합해 갱신된 base를 반환."""
    # 요약: 정보량이 많은(긴) 쪽 유지
    if len(new.get("ai_summary_ko") or "") > len(base.get("ai_summary_ko") or ""):
        base["ai_summary_ko"] = new["ai_summary_ko"]
    # 비어 있는 필드 채우기
    for field in ("sector", "stage", "lead_investor", "country", "region"):
        if not base.get(field) or base.get(field) in ("기타", "비공개"):
            if new.get(field) and new.get(field) not in ("기타", "비공개"):
                base[field] = new[field]
    if base.get("amount_usd") is None and new.get("amount_usd") is not None:
        base["amount_usd"] = new["amount_usd"]
        base["amount_original"] = new.get("amount_original")
    # 투자사 합집합 (순서 유지)
    seen = {i.lower() for i in base.get("investors") or []}
    for inv in new.get("investors") or []:
        if inv.lower() not in seen:
            base.setdefault("investors", []).append(inv)
            seen.add(inv.lower())
    # 발표일: 더 이른 날짜 유지
    if new.get("date") and new["date"] < base.get("date", "9999"):
        base["date"] = new["date"]
    # 소스 배열 보존
    new_src = {"name": new["source_name"], "url": new["source_url"]}
    if new_src["url"] not in {s["url"] for s in base["sources"]}:
        base["sources"].append(new_src)
    return base


def _row_to_dict(row) -> dict:
    return {
        "id": row[0], "date": row[1], "company": row[2], "sector": row[3],
        "amount_original": json.loads(row[4]) if row[4] else None,
        "amount_usd": row[5], "stage": row[6],
        "investors": json.loads(row[7]) if row[7] else [],
        "lead_investor": row[8], "country": row[9], "region": row[10],
        "ai_summary_ko": row[11],
        "sources": json.loads(row[12]) if row[12] else [],
    }


def _update_row(conn: sqlite3.Connection, d: dict):
    conn.execute(
        """UPDATE deals SET date=?, sector=?, amount_original=?, amount_usd=?, stage=?,
                            investors=?, lead_investor=?, country=?, region=?,
                            ai_summary_ko=?, sources=?
           WHERE id=?""",
        (
            d["date"], d["sector"],
            json.dumps(d["amount_original"], ensure_ascii=False) if d["amount_original"] else None,
            d["amount_usd"], d["stage"],
            json.dumps(d["investors"], ensure_ascii=False),
            d["lead_investor"], d["country"], d["region"], d["ai_summary_ko"],
            json.dumps(d["sources"], ensure_ascii=False),
            d["id"],
        ),
    )


def dedupe(conn: sqlite3.Connection, deals: list[dict]) -> tuple[list[dict], int]:
    """신규 딜 목록에서 (DB 기존 딜 + 배치 내) 중복을 병합.

    반환: (신규 삽입할 딜 목록, 병합된 건수). DB 병합은 즉시 UPDATE.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=MATCH_WINDOW_DAYS)).date().isoformat()
    rows = conn.execute(
        """SELECT id, date, company, sector, amount_original, amount_usd, stage,
                  investors, lead_investor, country, region, ai_summary_ko, sources
           FROM deals WHERE date >= ?""",
        (since,),
    ).fetchall()
    existing = [_row_to_dict(r) for r in rows]

    pending: list[dict] = []
    merged_count = 0

    for deal in deals:
        # 신규 딜을 저장 형태(sources 배열)로 변환
        deal = dict(deal)
        deal["sources"] = [{"name": deal["source_name"], "url": deal["source_url"]}]

        # 1) DB의 기존 딜과 비교
        db_match = next((e for e in existing if _is_same_deal(e, deal)), None)
        if db_match:
            _merge(db_match, deal)
            _update_row(conn, db_match)
            merged_count += 1
            log.info("병합(DB): %s ← %s", db_match["company"], deal["source_name"])
            continue

        # 2) 이번 배치 내 다른 딜과 비교
        batch_match = next((p for p in pending if _is_same_deal(p, deal)), None)
        if batch_match:
            _merge(batch_match, deal)
            merged_count += 1
            log.info("병합(배치): %s ← %s", batch_match["company"], deal["source_name"])
            continue

        pending.append(deal)

    conn.commit()
    return pending, merged_count
