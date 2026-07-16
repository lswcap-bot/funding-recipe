# 글로벌 스타트업 투자 정보

글로벌 스타트업 투자(펀딩) 뉴스를 매일 자동 수집·정제하여 테이블 형태로 보여주는 웹 서비스.

## 구조

```
├── collector/          # 소스별 수집 모듈 (RSS)
├── extractor/          # Claude API 판별·추출 + 환율 환산 (frankfurter.app)
├── storage.py          # SQLite(data/funding.db) + 월별 JSON 내보내기
├── pipeline.py         # 메인 진입점
├── config.yaml         # 소스 목록, 모델명, 수집 설정
├── public/             # 정적 사이트 (GitHub Pages 루트)
│   ├── index.html
│   └── data/           # 월별 JSON (2026-07.json 등) + index.json
└── requirements.txt
```

## 설치

```powershell
pip install -r requirements.txt
```

## API 키 설정

Anthropic API 키가 필요합니다 (https://platform.claude.com 에서 발급).

```powershell
# 현재 세션만
$env:ANTHROPIC_API_KEY = "sk-ant-..."

# 영구 설정 (새 터미널부터 적용)
[Environment]::SetEnvironmentVariable("ANTHROPIC_API_KEY", "sk-ant-...", "User")
```

## 실행

```powershell
python pipeline.py                  # 전체 파이프라인 (수집→추출→저장→JSON)
python pipeline.py --collect-only   # 수집만 (API 키 불필요)
python pipeline.py --limit 10       # 추출 기사 수 제한 (비용 테스트용)
```

## 프론트엔드 로컬 확인

```powershell
python -m http.server 8000 --directory public
# http://localhost:8000 접속
```

## 자동화 (GitHub Actions)

`.github/workflows/daily.yml`이 매일 UTC 22:00(KST 아침 7시)에 파이프라인을 실행하고,
변경된 `data/funding.db`와 `public/data/*.json`을 커밋한 뒤 `public/`을 GitHub Pages로 배포합니다.

설정 방법:
1. GitHub 저장소 생성 후 푸시
2. 저장소 **Settings → Secrets and variables → Actions**에 `ANTHROPIC_API_KEY` 시크릿 등록
3. **Settings → Pages**에서 Source를 **GitHub Actions**로 설정
4. Actions 탭에서 "Daily funding pipeline" 워크플로를 수동 실행(workflow_dispatch)해 첫 배포 확인

## 진행 상황

- [x] Phase 1: TechCrunch + Tech.eu 수집→추출→JSON 저장 파이프라인 + 프론트 테이블
- [x] Phase 2: 10개 소스 전체 활성화, 중복 제거(회사명 정규화 + 단계 + 금액 ±10% 병합)
- [ ] Phase 3: GitHub Actions 자동화 + GitHub Pages 배포
- [ ] Phase 4: 프론트 고도화 (정렬, 검색, 필터 칩, 모바일)
