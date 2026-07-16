# Claude Code 요청문: 글로벌 스타트업 투자 정보 서비스

아래 내용을 Claude Code에 그대로 붙여넣거나, 프로젝트 루트에 `CLAUDE.md` 또는 `SPEC.md`로 저장한 뒤 "이 스펙대로 만들어줘"라고 요청하세요. 한 번에 전부 요청하기보다 **Phase 단위로 나눠 요청**하는 것을 권장합니다.

---

## 프로젝트 개요

글로벌 스타트업 투자(펀딩) 뉴스를 매일 자동 수집·정제하여, 테이블 형태로 보여주는 웹 서비스 "글로벌 스타트업 투자 정보"를 만들어줘.

## 데이터 소스 (10개)

| 소스 | URL | 커버 지역 |
|---|---|---|
| TechCrunch | https://techcrunch.com/ | 글로벌/미국 |
| Tech in Asia | https://www.techinasia.com/ | 동남아/아시아 (페이월 주의) |
| KrASIA | https://kr-asia.com/ | 아시아 |
| Tech.eu | https://tech.eu/ | 유럽 |
| EU-Startups | https://www.eu-startups.com/ | 유럽 |
| YourStory | https://yourstory.com/ | 인도 |
| Startup Daily | https://www.startupdaily.net/ | 호주/뉴질랜드 |
| LatamList | https://latamlist.com/ | 중남미 |
| Contxto | https://www.contxto.com/ | 중남미 |
| TechNode | https://technode.com/ | 중국 |

**수집 원칙:**
- 각 소스의 RSS 피드를 먼저 탐색해서 사용하고(예: `/feed`, `/rss` 경로 확인), RSS가 없거나 항목이 부족한 소스만 목록 페이지 HTML 파싱으로 보완해줘.
- robots.txt를 존중하고, 요청 간격(예: 2~3초)과 User-Agent를 설정해줘.
- 페이월이 있는 소스(Tech in Asia 등)는 RSS의 제목/요약 수준만 사용하고 본문 크롤링은 시도하지 마.
- 기사 본문 전문은 저장하지 말 것. 추출된 구조화 데이터 + 자체 생성 요약 + 원문 링크만 저장 (저작권 이슈 방지).

## 파이프라인 구성

### 1단계: 수집 (collector)
- 매일 1회 실행되는 스크립트 (Python 권장)
- 최근 24~48시간 내 발행 기사 목록 수집 (제목, 링크, 발행일, RSS 요약/발췌문)
- 이미 처리한 기사는 URL 기준으로 스킵 (처리 이력 저장)

### 2단계: 판별 + 추출 (extractor, Claude API 사용)
- Anthropic API를 사용해서 각 기사가 **스타트업 투자 유치 뉴스인지** 판별하고, 맞으면 아래 스키마로 구조화 추출해줘. 판별과 추출을 한 번의 API 호출로 처리해서 비용을 아껴줘 (배치 처리: 기사 여러 건을 한 호출에 묶기).
- API 키는 환경변수 `ANTHROPIC_API_KEY`로 관리.

추출 스키마 (JSON):
```json
{
  "is_funding_news": true,
  "date": "2026-07-14",            // 투자 발표일 (기사 발행일 기준)
  "company": "회사명",
  "sector": "핀테크",               // 분야: 핀테크, AI, 헬스케어, 커머스, SaaS, 모빌리티, 에듀테크, 바이오, 기타 등 표준 분류로 정규화
  "amount_original": {"value": 50, "currency": "EUR", "unit": "million"},
  "amount_usd": 54200000,          // 달러 환산액 (환율 API로 계산, LLM이 직접 환산하지 말 것)
  "stage": "시리즈 B",              // 시드, 프리시리즈A, 시리즈 A/B/C/D+, 그로스, 브릿지, 비공개 등
  "investors": ["리드 투자사", "참여 투자사1", "참여 투자사2"],
  "lead_investor": "리드 투자사",
  "country": "독일",
  "region": "유럽",                 // 북미, 유럽, 동아시아, 동남아, 남아시아, 중남미, 오세아니아, 중동/아프리카
  "ai_summary_ko": "3~4문장의 한국어 요약: 무슨 회사이고, 얼마를 어떤 조건으로 유치했으며, 자금을 어디에 쓸 계획인지",
  "source_name": "Tech.eu",
  "source_url": "https://..."
}
```

- 금액이 기사에 명시되지 않은 경우 `amount_usd: null`, "비공개"로 표기.
- **환율 환산은 LLM에게 맡기지 말고**, LLM은 원 통화·금액만 추출하게 하고 코드에서 무료 환율 API(예: frankfurter.app, exchangerate.host)로 기사 발행일 기준 환산해줘.

### 3단계: 중복 제거 (deduplicator)
- 같은 투자 건이 여러 소스에 실릴 수 있음. **회사명(정규화) + 투자 단계 + 금액(±10% 허용)** 기준으로 같은 건이면 병합.
- 병합 시 소스는 배열로 모두 보존, 요약은 정보량이 많은 쪽 유지.

### 4단계: 저장 (storage)
- SQLite 단일 파일 DB (`data/funding.db`) 사용. 테이블: `deals`, `processed_urls`.
- 프론트엔드용으로 월별 JSON 파일도 함께 생성: `public/data/2026-07.json`, 그리고 사용 가능한 연/월 목록 `public/data/index.json`.

### 5단계: 자동화 (GitHub Actions)
- 매일 UTC 22:00 (한국시간 아침 7시)에 실행되는 workflow 작성.
- 실행 → 수집/추출/저장 → 변경된 JSON/DB를 커밋 → GitHub Pages 자동 재배포.
- 실패 시 로그 확인이 쉽게 각 단계별 로그 출력.

## 프론트엔드 (웹 페이지)

- 기술: 빌드 없이 배포 가능한 정적 사이트. 단순하게 vanilla JS + HTML 하나로 하거나, 필요하면 Vite + React. GitHub Pages로 배포.
- 페이지 제목: **"글로벌 스타트업 투자 정보"**

레이아웃 요구사항:
1. **화면 대부분을 차지하는 큰 테이블**이 메인. 컬럼: 일자 | 기업명 | 분야 | 투자금(USD) | 투자 단계 | 투자사 | 국가(지역) | 요약보기 버튼
2. **연도/월 선택 필터**: 상단에 연도 드롭다운 + 월 선택 (탭 또는 드롭다운). 선택하면 해당 월 JSON을 불러와 테이블 갱신.
3. **AI 요약 팝업**: 각 행의 "요약" 버튼(또는 행 클릭) 시 모달 팝업으로 한국어 AI 요약 + 투자사 전체 목록 + 원문 링크(출처 표기) 표시.
4. 테이블 부가 기능: 컬럼 헤더 클릭 정렬(일자/금액), 상단에 기업명·투자사 검색창, 지역/분야/단계 필터 칩.
5. 투자금은 `$54.2M`, `$1.2B` 형태로 축약 표기, 비공개는 "비공개"로.
6. 모바일에서도 볼 수 있게 가로 스크롤 처리.
7. 상단에 "마지막 업데이트: YYYY-MM-DD HH:mm KST" 표시.

## 프로젝트 구조 (제안)

```
funding-tracker/
├── collector/          # 소스별 수집 모듈 (소스마다 파일 분리)
├── extractor/          # Claude API 판별·추출, 환율 환산
├── data/funding.db
├── public/             # 정적 사이트 (GitHub Pages 루트)
│   ├── index.html
│   └── data/           # 월별 JSON
├── .github/workflows/daily.yml
├── requirements.txt
└── README.md           # 설치/실행/키 설정 방법
```

## 진행 순서 (Phase별로 나눠서 요청)

- **Phase 1**: 소스 2개(TechCrunch, Tech.eu)만으로 수집→추출→JSON 저장까지 엔드투엔드 파이프라인 완성 + 샘플 데이터로 프론트 테이블 확인
- **Phase 2**: 나머지 8개 소스 추가, 중복 제거 로직
- **Phase 3**: GitHub Actions 자동화 + GitHub Pages 배포
- **Phase 4**: 프론트 고도화 (필터, 정렬, 검색, 모바일)

각 Phase 완료 시 실제로 실행해서 결과를 보여주고, 문제가 있으면 수정한 뒤 다음 단계로 넘어가줘.

## 기타 요구사항

- 소스 하나가 실패해도 전체 파이프라인이 죽지 않게 소스별 try/except 처리.
- Claude API 호출 비용을 로그로 출력 (기사 몇 건 처리, 토큰 대략치).
- 설정값(소스 목록, 수집 주기, 모델명)은 `config.yaml`로 분리해서 나중에 소스를 쉽게 추가할 수 있게.
