# naver-map-review-telegram

네이버 지도 장소 리뷰를 Telegram으로 요약해주는 개인용 서버리스 봇. (신규 프로젝트 — 골격 구축 단계)

## 기능

- **온디맨드(요청-응답)** — Telegram으로 장소명이나 네이버 지도 링크를 보내면 리뷰를 수집·요약해 응답
  - `장소명` 또는 `/review 장소명` → 리뷰 수집 + **Claude LLM 요약**(장점·단점·방문 팁)
  - `/help` → 사용법
- 같은 장소 반복 조회는 **DynamoDB 캐시**(TTL)로 재수집·재요약을 절약

## 기술 스택

Python 3.12 / Telegram Bot API / **Anthropic Claude API**(리뷰 요약) /
AWS Lambda·API Gateway·DynamoDB·Secrets Manager / SAM CLI · pytest.
주요 라이브러리: `boto3` · `httpx` · `anthropic` · `beautifulsoup4` · `python-dotenv`.
웹/모바일 프론트엔드 없음 — Telegram이 UI.

### 진입점
- `webhook_handler.lambda_handler` — Telegram Webhook(온디맨드 명령 라우팅)

## 구조

```
config.py                  # 설정·시크릿 이중 로드(.env ↔ Secrets Manager)
webhook_handler.py         # 진입점(검증·라우팅)
command_router.py          # 명령 분기(/review·/help·기본=장소명)
naver_review_collector.py  # 네이버 리뷰 수집(httpx+BeautifulSoup)
review_analyst.py          # Claude 요약
review_formatter.py        # MarkdownV2 포맷·이스케이프
dynamo_writer.py           # 리뷰 캐시 read/write(비크리티컬)
telegram_sender.py         # 발송·재시도·에러 알림
template.yaml              # SAM(Lambda + HttpApi + DynamoDB + Secrets)
```

자세한 코드 구조는 `ARCHITECTURE.md`, 개발 지침은 `CLAUDE.md` 참조.

## 빠른 시작

```powershell
python -m venv .venv; .venv\Scripts\activate
pip install -r requirements.txt
Copy-Item .env.example .env    # 값 채우기
```

배포·Telegram 연동 등 **전체 초기 설정 절차는 [`docs/setup-guide.md`](docs/setup-guide.md)** 참조.

## 다음 할 일 (골격 → 동작)

1. `naver_review_collector.py`의 `# TODO`(place id 해석·엔드포인트·셀렉터)를 실제 네이버 응답으로 확정
2. `ROADMAP.md`에 따라 Task 순서대로 구현 + 테스트 추가
3. `docs/setup-guide.md`로 배포 및 Webhook 등록
