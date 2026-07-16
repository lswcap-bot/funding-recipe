"""환율 환산: LLM이 아닌 코드에서 처리한다 (frankfurter.app 무료 API)."""
import logging

import requests

log = logging.getLogger("fx")

_UNIT_MULTIPLIER = {
    "billion": 1_000_000_000,
    "million": 1_000_000,
    "thousand": 1_000,
    "crore": 10_000_000,   # 인도 단위 (1천만)
    "lakh": 100_000,       # 인도 단위 (10만)
    "unit": 1,
}

_rate_cache: dict[tuple[str, str], float | None] = {}


def _get_rate(currency: str, date: str) -> float | None:
    """기사 발행일 기준 currency→USD 환율. 실패 시 None."""
    key = (currency, date)
    if key in _rate_cache:
        return _rate_cache[key]

    rate = None
    try:
        resp = requests.get(
            f"https://api.frankfurter.app/{date}",
            params={"from": currency, "to": "USD"},
            timeout=15,
        )
        if resp.status_code == 200:
            rate = resp.json().get("rates", {}).get("USD")
        else:
            log.warning("환율 조회 실패 (%s, %s): HTTP %s", currency, date, resp.status_code)
    except Exception as e:
        log.warning("환율 조회 오류 (%s, %s): %s", currency, date, e)

    _rate_cache[key] = rate
    return rate


def to_usd(amount: dict | None, date: str) -> int | None:
    """{"value": 50, "currency": "EUR", "unit": "million"} → USD 정수 금액. 비공개/실패 시 None."""
    if not amount or amount.get("value") in (None, 0):
        return None
    value = amount["value"]
    currency = (amount.get("currency") or "USD").upper()
    multiplier = _UNIT_MULTIPLIER.get((amount.get("unit") or "unit").lower(), 1)
    base = value * multiplier

    if currency == "USD":
        return round(base)

    rate = _get_rate(currency, date)
    if rate is None:
        return None
    return round(base * rate)
