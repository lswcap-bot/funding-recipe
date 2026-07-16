"""Claude API로 투자 뉴스 판별 + 구조화 추출 (배치 처리로 호출 횟수 절감)."""
import logging
from typing import Optional

import anthropic
from pydantic import BaseModel, Field

from extractor import fx

log = logging.getLogger("extractor")

# 모델별 단가 (USD / 1M tokens, input/output)
_PRICES = {
    "claude-opus": (5.00, 25.00),
    "claude-sonnet": (3.00, 15.00),
    "claude-haiku": (1.00, 5.00),
    "claude-fable": (10.00, 50.00),
}


def _price_for(model: str) -> tuple[float, float]:
    for prefix, price in _PRICES.items():
        if model.startswith(prefix):
            return price
    return (5.00, 25.00)

SECTORS = ["핀테크", "AI", "헬스케어", "커머스", "SaaS", "모빌리티",
           "에듀테크", "바이오", "게임", "푸드테크", "부동산", "에너지",
           "보안", "로보틱스", "농업", "기타"]
REGIONS = ["북미", "유럽", "동아시아", "동남아", "남아시아",
           "중남미", "오세아니아", "중동/아프리카"]


class AmountOriginal(BaseModel):
    value: float = Field(description="숫자 금액 (예: 50)")
    currency: str = Field(description="ISO 통화 코드 (예: USD, EUR, GBP, INR)")
    unit: str = Field(description="단위: billion / million / thousand / crore / lakh / unit. "
                                  "기사에 쓰인 단위 그대로 사용 (예: Rs 100 crore → value=100, currency=INR, unit=crore)")


class Deal(BaseModel):
    company: str
    sector: Optional[str] = Field(default=None, description="표준 분야 분류 중 하나")
    amount_original: Optional[AmountOriginal] = Field(
        default=None, description="기사에 명시된 원 통화 금액. 비공개면 null")
    stage: Optional[str] = Field(
        default=None, description="시드/프리시리즈A/시리즈 A/시리즈 B/시리즈 C/시리즈 D+/그로스/브릿지/비공개 등")
    investors: list[str] = Field(default_factory=list)
    lead_investor: Optional[str] = None
    country: Optional[str] = Field(default=None, description="회사 본사 국가 (한국어)")
    region: Optional[str] = Field(default=None, description="표준 지역 분류 중 하나")
    ai_summary_ko: Optional[str] = Field(
        default=None,
        description="3~4문장 한국어 요약: 무슨 회사이고, 얼마를 어떤 조건으로 유치했으며, 자금을 어디에 쓸 계획인지")


class ArticleResult(BaseModel):
    index: int = Field(description="입력 기사 번호 (0부터)")
    is_funding_news: bool = Field(description="스타트업의 투자(펀딩) 유치 발표 뉴스인지 여부")
    deals: list[Deal] = Field(
        default_factory=list,
        description="기사에 포함된 투자 딜 목록. 딜 모음 기사면 여러 개, 투자 뉴스가 아니면 빈 배열")


class BatchResult(BaseModel):
    results: list[ArticleResult]


_SYSTEM = f"""당신은 스타트업 투자 뉴스 분석가입니다. 기사 제목과 요약(발췌문)을 보고,
각 기사가 "특정 스타트업이 투자(펀딩)를 유치했다"는 발표 뉴스인지 판별하고, 맞으면 구조화 데이터를 추출합니다.

규칙:
- 투자 유치 뉴스가 아니면 is_funding_news=false, deals=[] 로 반환하세요.
  (제품 출시, 인수합병, IPO, 펀드 결성, 일반 시황 기사는 투자 유치 뉴스가 아님. 단, VC가 스타트업에 투자한 건은 해당함)
- 한 기사에 여러 건의 투자 소식이 있으면(예: "Deals in brief" 딜 모음 기사) deals에 각각 별도 항목으로 추출하세요.
- sector는 반드시 다음 중 하나로 정규화: {", ".join(SECTORS)}
- region은 반드시 다음 중 하나로 정규화: {", ".join(REGIONS)}
- amount_original은 기사에 명시된 원 통화·단위 그대로 추출하세요. 환율 환산이나 단위 변환은 하지 마세요.
  금액이 명시되지 않았거나 불확실하면 반드시 null로 두세요 (추측 금지).
- stage는 반드시 한국어 표준 표기를 사용하세요: 시드, 프리시드, 프리시리즈A, 시리즈 A, 시리즈 B,
  시리즈 C, 시리즈 D+, 그로스, 브릿지, 비공개. (Series A → "시리즈 A") 불명확하면 "비공개".
- ai_summary_ko는 기사에 있는 정보만으로 작성하고, 추측하지 마세요.
- 모든 입력 기사에 대해 index를 포함한 결과를 빠짐없이 반환하세요."""


def _build_prompt(batch: list[dict]) -> str:
    parts = []
    for i, a in enumerate(batch):
        parts.append(
            f"[기사 {i}]\n제목: {a['title']}\n출처: {a['source_name']} ({a['region_hint']})\n"
            f"발행일: {a['published']}\n요약: {a['summary'] or '(없음)'}"
        )
    return "다음 기사들을 분석하세요.\n\n" + "\n\n".join(parts)


def extract_batch(client: anthropic.Anthropic, batch: list[dict], config: dict) -> tuple[list[dict], dict]:
    """기사 배치 → (완성된 딜 레코드 목록, usage 정보). 판별+추출을 한 번의 호출로 처리."""
    response = client.messages.parse(
        model=config["model"],
        max_tokens=config.get("max_tokens", 16000),
        system=_SYSTEM,
        messages=[{"role": "user", "content": _build_prompt(batch)}],
        output_format=BatchResult,
    )

    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }

    deals = []
    parsed = response.parsed_output
    if parsed is None:
        log.error("구조화 출력 파싱 실패 (stop_reason=%s)", response.stop_reason)
        return deals, usage

    for r in parsed.results:
        if not r.is_funding_news or not r.deals:
            continue
        if r.index < 0 or r.index >= len(batch):
            log.warning("잘못된 index %s - 건너뜀", r.index)
            continue
        article = batch[r.index]
        for d in r.deals:
            amount = d.amount_original.model_dump() if d.amount_original else None
            usd = fx.to_usd(amount, article["published"])
            if usd is not None and usd < 10_000:
                # 단위 소실 가능성 (예: $160M → $160). 신뢰 불가 → 비공개 처리
                log.warning("금액 비정상 의심 (%s: $%s) - 비공개 처리", d.company, usd)
                amount, usd = None, None
            deals.append({
                "date": article["published"],
                "company": d.company,
                "sector": d.sector or "기타",
                "amount_original": amount,
                "amount_usd": usd,
                "stage": d.stage or "비공개",
                "investors": d.investors,
                "lead_investor": d.lead_investor,
                "country": d.country,
                "region": d.region,
                "ai_summary_ko": d.ai_summary_ko,
                "source_name": article["source_name"],
                "source_url": article["url"],
            })
    return deals, usage


def extract_all(articles: list[dict], config: dict) -> list[dict]:
    """전체 기사를 배치로 나눠 추출. 비용 로그 출력."""
    client = anthropic.Anthropic()
    batch_size = config.get("batch_size", 5)
    all_deals = []
    total_in = total_out = 0

    for i in range(0, len(articles), batch_size):
        batch = articles[i:i + batch_size]
        try:
            deals, usage = extract_batch(client, batch, config)
        except anthropic.APIStatusError as e:
            log.error("API 오류 (배치 %d-%d): %s %s - 건너뜀", i, i + len(batch) - 1, e.status_code, e.message)
            continue
        except anthropic.APIConnectionError as e:
            log.error("네트워크 오류 (배치 %d-%d): %s - 건너뜀", i, i + len(batch) - 1, e)
            continue
        total_in += usage["input_tokens"]
        total_out += usage["output_tokens"]
        log.info("배치 %d-%d: 기사 %d건 중 투자뉴스 %d건 (in=%d, out=%d tokens)",
                 i, i + len(batch) - 1, len(batch), len(deals),
                 usage["input_tokens"], usage["output_tokens"])
        all_deals.extend(deals)

    price_in, price_out = _price_for(config["model"])
    cost = total_in / 1e6 * price_in + total_out / 1e6 * price_out
    log.info("API 비용 요약: 기사 %d건 처리, input=%d / output=%d tokens, 약 $%.4f",
             len(articles), total_in, total_out, cost)
    return all_deals
