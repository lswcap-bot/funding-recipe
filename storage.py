"""저장 계층: SQLite(data/funding.db) + 프론트엔드용 월별 JSON(public/data)."""
import json
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

log = logging.getLogger("storage")

ROOT = Path(__file__).parent
DB_PATH = ROOT / "data" / "funding.db"
PUBLIC_DATA = ROOT / "public" / "data"

KST = timezone(timedelta(hours=9))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS deals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    company TEXT NOT NULL,
    sector TEXT,
    amount_original TEXT,      -- JSON {"value","currency","unit"} 또는 NULL
    amount_usd INTEGER,        -- NULL = 비공개
    stage TEXT,
    investors TEXT,            -- JSON 배열
    lead_investor TEXT,
    country TEXT,
    region TEXT,
    ai_summary_ko TEXT,
    sources TEXT,              -- JSON 배열 [{"name","url"}] (중복 병합 대비)
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_deals_date ON deals(date);

CREATE TABLE IF NOT EXISTS processed_urls (
    url TEXT PRIMARY KEY,
    is_funding INTEGER NOT NULL,
    processed_at TEXT NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(_SCHEMA)
    return conn


def filter_new_articles(conn: sqlite3.Connection, articles: list[dict]) -> list[dict]:
    """이미 처리한 URL은 제외."""
    seen = set()
    fresh = []
    for a in articles:
        if a["url"] in seen:
            continue
        seen.add(a["url"])
        row = conn.execute("SELECT 1 FROM processed_urls WHERE url = ?", (a["url"],)).fetchone()
        if row is None:
            fresh.append(a)
    return fresh


def save_results(conn: sqlite3.Connection, articles: list[dict], deals: list[dict],
                 funding_urls: set[str] | None = None):
    """딜 저장 + 처리 이력 기록. deals는 dedupe를 거쳐 sources 배열을 가진 신규 딜."""
    now = datetime.now(timezone.utc).isoformat()
    if funding_urls is None:
        funding_urls = {s["url"] for d in deals for s in d["sources"]}

    for d in deals:
        conn.execute(
            """INSERT INTO deals (date, company, sector, amount_original, amount_usd, stage,
                                  investors, lead_investor, country, region, ai_summary_ko,
                                  sources, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                d["date"], d["company"], d["sector"],
                json.dumps(d["amount_original"], ensure_ascii=False) if d["amount_original"] else None,
                d["amount_usd"], d["stage"],
                json.dumps(d["investors"], ensure_ascii=False),
                d["lead_investor"], d["country"], d["region"], d["ai_summary_ko"],
                json.dumps(d["sources"], ensure_ascii=False),
                now,
            ),
        )

    for a in articles:
        conn.execute(
            "INSERT OR IGNORE INTO processed_urls (url, is_funding, processed_at) VALUES (?, ?, ?)",
            (a["url"], 1 if a["url"] in funding_urls else 0, now),
        )
    conn.commit()
    log.info("저장 완료: 딜 %d건, 처리 이력 %d건", len(deals), len(articles))


def export_json(conn: sqlite3.Connection):
    """DB 전체를 월별 JSON + index.json으로 내보낸다."""
    PUBLIC_DATA.mkdir(parents=True, exist_ok=True)
    rows = conn.execute(
        """SELECT date, company, sector, amount_original, amount_usd, stage, investors,
                  lead_investor, country, region, ai_summary_ko, sources
           FROM deals ORDER BY date DESC, id DESC"""
    ).fetchall()

    by_month: dict[str, list[dict]] = {}
    for r in rows:
        deal = {
            "date": r[0], "company": r[1], "sector": r[2],
            "amount_original": json.loads(r[3]) if r[3] else None,
            "amount_usd": r[4], "stage": r[5],
            "investors": json.loads(r[6]) if r[6] else [],
            "lead_investor": r[7], "country": r[8], "region": r[9],
            "ai_summary_ko": r[10],
            "sources": json.loads(r[11]) if r[11] else [],
        }
        by_month.setdefault(r[0][:7], []).append(deal)

    last_updated = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    for month, deals in by_month.items():
        path = PUBLIC_DATA / f"{month}.json"
        path.write_text(
            json.dumps({"month": month, "deals": deals}, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )

    index = {"months": sorted(by_month.keys(), reverse=True), "last_updated": last_updated}
    (PUBLIC_DATA / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    log.info("JSON 내보내기 완료: %d개 월, 총 %d건", len(by_month), len(rows))
