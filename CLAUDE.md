# CLAUDE.md — 네이버 지도 리뷰 요약 봇 (Telegram + 웹)

이 문서는 이 저장소에서 작업하는 모든 세션(Advisor·Worker)의 시스템 프롬프트다. 여기 있는 규칙은 예외 없이 지킨다.

## 프로젝트 요약·운영 현황

네이버 지도 공유 URL(naver.me)을 보내면 리뷰 요약 + 메뉴별 추천도를 응답하는 개인용 서버리스 서비스.

- **Telegram 봇**: 스택 `naver-map-review-telegram` — 2026-07-05 라이브 (chat_id 허용목록)
- **웹 진입점**: 스택 `naver-review-web` + Vercel `benny-naver-review.vercel.app` — 2026-07-07 라이브 (초대코드제)

## 문서 지도 (단일 원천 원칙)

문서 위계: REQUIREMENTS → PRD → ROADMAP → CLAUDE.md(구현 제약). 충돌 시 상위 문서가 우선하며, 구현 세부는 이 문서가 우선한다.

각 사실의 상세는 **아래 원천 문서 한 곳에만** 서술한다. 다른 문서에는 요약 1줄 + 포인터만 둔다. 사실이 바뀌면 원천을 고치고, 그 사실을 가리키는 포인터의 정합을 확인한다.

| 사실 | 원천 |
|---|---|
| 스크래핑 실측 (엔드포인트·정렬·429·UA) | `experiments/findings.md` |
| 배포 절차·함정 상세 | `docs/setup-guide.md` (실행은 `/deploy-*` 스킬) |
| 진행 상태 | `ROADMAP.md` |
| 코드 구조·인프라·테이블 스키마 | `ARCHITECTURE.md` |
| 요구사항 / 기능 명세·JSON 계약 | `REQUIREMENTS.md` / `PRD.md` |
| 웹 설계 결정 (격리·비용 방어·잡+폴링 근거) | `docs/web-design.md` |
| 하드 제약·워크플로우·시크릿 스키마 | 이 문서 |

## 역할 분담: Advisor / Worker

- **Advisor(메인 세션)**: 요구사항 분석, 작업 분해, 설계 결정, 브리프 작성, diff·테스트 직접 검증, 커밋, 사용자 보고.
- **Worker(서브에이전트)**: 구현 노동 전부. `.claude/agents/worker-dev.md`(구현), `.claude/agents/worker-scraper.md`(스크래핑 탐사).
- Worker의 완료 보고를 그대로 믿지 않는다 — Advisor가 diff와 테스트로 확인 후 승인한다. 검증 실패는 수정 브리프로 재위임. Advisor 직접 수정은 한두 줄 마무리에만 허용.
- Worker는 커밋하지 않는다. 커밋은 Advisor가 작은 단위로, 메시지는 한국어로.

## 표준 워크플로우 (작업 유형별)

| 작업 유형 | 절차 |
|---|---|
| 기능 구현·수정 | `/delegate` 스킬로 브리프 작성 → worker-dev 위임 → diff 직접 검증 → `/verify` → 커밋 |
| Telegram 스택 배포 | `/deploy-telegram` 스킬 사용. 배포 명령 수기 조합 금지 |
| 웹 스택 배포 | `/deploy-web` 스킬 사용. 배포 명령 수기 조합 금지 (파라미터 원복 함정) |
| 스크래핑 변경·탐사 | `experiments/findings.md` 필독 → worker-scraper 위임 → findings.md 증분 갱신 |
| 문서 갱신 | 위 단일 원천 지도에 따라 원천 1곳 수정 + 포인터 정합 확인 |
| 사용자 대면 문구 작성 | 동작·정렬·개수 등 사실 주장은 코드·실측으로 검증 후 작성. 추측 금지 |

## 하드 제약

### 아키텍처
1. HTTP 클라이언트는 **httpx로 통일**. 다른 HTTP 라이브러리 추가 금지.
2. `async def lambda_handler` 금지 — `def lambda_handler` 안에서 `asyncio.run()` 래퍼를 사용한다.
3. Webhook은 어떤 경우에도 **200 반환** (예외 흡수 — Telegram 재시도 폭주 방지). 무거운 처리는 WorkerFunction에 `InvocationType="Event"` 비동기 invoke로 넘긴다 (3초 응답 제한).
4. 배포 대상 Python은 **`src/`에만** 둔다 (루트 금지 — Lambda 패키지 250MB 초과). 두 템플릿 모두 `CodeUri: src/`.

### 보안·PII
5. chat_id 허용목록 검사 + `X-Telegram-Bot-Api-Secret-Token` 헤더를 `hmac.compare_digest` 상수시간 비교.
6. 시크릿은 이중 로드(로컬 `.env` ↔ Lambda Secrets Manager)만 사용. 하드코딩 금지. `config._SECRET_KEYS`와 `.env.example` 키 목록을 항상 일치시킨다.
7. PII 최소화 로깅: 리뷰 본문·chat_id 전문을 INFO 로그에 남기지 않는다. 리뷰어 닉네임 등 식별 정보는 수집 자체를 하지 않는다.

### 탄력성 (non-critical 실패)
8. 캐시(DynamoDB) 쓰기 실패해도 사용자 응답은 발송한다. float는 `Decimal`로 변환해 저장.
9. Claude 요약 실패 시 수집 성공 사실과 함께 폴백 응답을 발송한다.
10. Telegram 발송은 MarkdownV2 — 모든 동적 텍스트는 `review_formatter`의 이스케이프 헬퍼를 반드시 경유한다.

### 네이버 스크래핑 (실측 확정 — 상세·근거는 `experiments/findings.md`)
11. **모바일 Chrome User-Agent 필수** — 데스크톱 UA는 429 차단(실측). `config.NAVER_REQUEST_HEADERS`를 사용한다.
12. **GraphQL 인트로스펙션 절대 금지** — 즉시 429 + 지속 차단(실사고).
13. 429 응답은 **무재시도 즉시 실패**(`ReviewCollectError`). 요청 간 `RATE_LIMIT_DELAY`(0.5초) 준수.
14. 엔드포인트·파라미터는 findings.md의 실측 확정값만 사용. 리뷰 기본 정렬은 **최신순** (네이버 UI 기본값 '추천순'과 다름 — 사용자 안내 문구 주의).

### 웹 스택 (naver-review-web)
15. 웹은 **별도 SAM 스택**(`template-web.yaml`) — 기존 Telegram 봇 영향 0이 절대 제약. 배포는 반드시 `/deploy-web` 스킬을 경유한다.
16. WebWorker는 Telegram `prod_review_cache`를 **읽기전용 read-through**만 한다. Telegram WorkerFunction invoke 권한 없음.
17. 응답 구조는 비동기 잡+폴링. 관리자 통계는 `web_usage`에 누적 합계 + 일별 카운터(`req#`/`llm#`, 스키마리스 `ADD`) — 상세는 `ARCHITECTURE.md`.
18. 웹 `/analyze`의 `naver_url`은 서버측 허용호스트 검증(`_is_allowed_naver_url` — `https` + `WEB_ALLOWED_NAVER_HOSTS`)을 통과한 것만 처리한다(SSRF 방어 — 프론트 검사는 신뢰 경계 아님). 캐시 미스로 LLM을 호출하는 경로(캐시 히트 제외)는 `WEB_DAILY_LLM_LIMIT` 일일 상한 검사를 거친다(비용 폭탄 방어). 상세·근거는 `docs/web-design.md` 결정 8.

### 네이밍·언어
19. Python은 변수·함수 `snake_case`, 클래스 `PascalCase`, 상수 `UPPER_SNAKE_CASE`. `web-frontend/` TypeScript는 `camelCase`/`PascalCase`. 줄임말 대신 목적이 드러나는 이름(`data` 대신 `review_list`). 한글 식별자 금지.
20. 주석·docstring·로그·커밋 메시지는 한국어. 단 `requirements.txt` 주석만 ASCII 유지 (`sam build` 시 cp949 로케일 pip 실패 방지).

## 함정 등록부 (한 번 겪은 사고 — 반복 금지)

| 함정 | 증상 → 처방 | 상세 |
|---|---|---|
| Lambda 250MB 초과 | 루트 `CodeUri`가 `.venv`·`web-frontend`·`.git` 포함(sam build는 .gitignore 무시) → 배포 Python은 `src/` | setup-guide 문제해결 |
| `--parameter-overrides` 원복 | 생략한 파라미터가 template 기본값으로 되돌아감 → CORS `*` 원복·예산 삭제. 재배포 시 현행값 전량 명시 | `/deploy-web`, setup-guide §8-2 |
| `sam deploy -t` | 소스 직배포로 deps 누락 → ImportError. build 후 **`-t` 없이** deploy | setup-guide §8-2 |
| samconfig 누출 | samconfig.toml은 Telegram 전용 — 웹 배포에 `--stack-name` 누락 시 봇 스택을 덮어씀 | setup-guide §8-2 |
| 데스크톱 UA | `m.place.naver.com`이 429 차단 → 모바일 Chrome UA | findings.md §1 |
| GraphQL 인트로스펙션 | 즉시 429 + 지속 차단 → 절대 금지 | findings.md §4 |
| cp949 pip 실패 | `requirements.txt` 비ASCII 주석 → `sam build` 실패 → ASCII 유지 | 제약 20 |
| PowerShell `curl` | `Invoke-WebRequest` 별칭이라 `-H`/`-d` 불가 → `curl.exe` 또는 `Invoke-RestMethod` | setup-guide 문제해결 |
| 콘솔 cp949 크래시 | 한국어·특수문자 print 시 UnicodeEncodeError → `PYTHONUTF8=1` 설정 | — |
| Vercel 브랜치 | Production Branch=main — feature push는 Preview만 생성 → `main` 병합해야 프로덕션 반영 | setup-guide §8-3 |

## 명령어 (로컬 개발)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt   # 런타임(-r src/requirements.txt) + pytest/moto

pytest tests/            # 단위 테스트 (외부 API 전부 mock — 네트워크 불필요)
pytest tests/ -m live    # 실측 통합 테스트 (옵트인 — 실제 네이버 호출)

cd web-frontend; npm run build; npm run lint   # 프론트 변경 시
```

배포 명령은 `/deploy-telegram`·`/deploy-web` 스킬이 정확한 절차를 담고 있다. 수기 조합 금지.

## 시크릿 스키마 (`.env` / Secrets Manager 공통)

- Telegram 스택 (`naver-review/production`): `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_IDS`(JSON 배열 문자열), `TELEGRAM_DEVELOPER_CHAT_ID`, `TELEGRAM_WEBHOOK_SECRET`, `ANTHROPIC_API_KEY`
- 웹 스택 (`naver-review/web`): `ANTHROPIC_API_KEY`(재사용), `WEB_SESSION_SECRET`, `WEB_INVITE_CODES`(`{"코드":"표시이름"}` JSON 문자열), `WEB_ADMIN_TOKEN`

`config._SECRET_KEYS`는 두 스택 키의 **상위집합**이다. 각 시크릿은 자기 키만 담고, 부재 키는 `_secret.get(k, "")`로 빈 문자열이 되어 무해하다 (스택 격리의 핵심).

추가 로컬 환경변수: `LOCAL_DEV=true`, `SECRETS_NAME`, `DYNAMO_TABLE_PREFIX`(로컬 `dev_` / 프로덕션 `prod_`), `AWS_DEFAULT_REGION`. 웹 전용: `PROD_REVIEW_CACHE_TABLE`, `LLM_COMMENTARY_ENABLED`(킬 스위치).

## 참조 구현

`ref/` 폴더는 이전 골격의 읽기 전용 참조본이다. 패턴 참고는 자유이나 **직접 수정 금지**. 배포 대상 프로덕션 코드는 `src/`에 둔다 (제약 4).
