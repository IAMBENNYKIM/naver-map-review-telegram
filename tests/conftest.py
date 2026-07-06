"""pytest 공통 설정 — config 모듈 import 전에 테스트용 환경변수를 주입한다.

config는 import 시점에 시크릿을 로드하므로(LOCAL_DEV=true → .env/환경변수),
어떤 테스트 모듈보다 먼저 이 conftest에서 환경변수를 확정해야 한다.
load_dotenv(override=False)는 기존 환경변수를 덮어쓰지 않으므로 여기 값이 우선한다.
"""

import os
import sys

# 배포 대상 모듈이 위치한 src/ 를 import 경로에 추가 (src 평면 구조 모듈 import용)
_SRC_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"
)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

# config import 전에 확정해야 하는 테스트용 환경변수
os.environ["LOCAL_DEV"] = "true"
os.environ["TELEGRAM_BOT_TOKEN"] = "test-bot-token"
os.environ["TELEGRAM_CHAT_IDS"] = '["123456789"]'
os.environ["TELEGRAM_DEVELOPER_CHAT_ID"] = "999999999"
os.environ["TELEGRAM_WEBHOOK_SECRET"] = "test-webhook-secret"
os.environ["ANTHROPIC_API_KEY"] = "test-anthropic-key"
os.environ["DYNAMO_TABLE_PREFIX"] = "dev_"
os.environ["AWS_DEFAULT_REGION"] = "ap-northeast-2"
os.environ["WORKER_FUNCTION_NAME"] = "test-worker-function"
os.environ["WEB_WORKER_FUNCTION_NAME"] = "test-web-worker-function"

# 웹 진입점(naver-review-web) 전용 시크릿 — config import 전에 확정한다.
os.environ["WEB_SESSION_SECRET"] = "test-web-session-secret"
os.environ["WEB_ADMIN_TOKEN"] = "test-web-admin-token"
os.environ["WEB_INVITE_CODES"] = '{"invite-code-1": "친구A", "invite-code-2": "친구B"}'
os.environ["PROD_REVIEW_CACHE_TABLE"] = "prod_review_cache"

# moto용 가짜 AWS 자격증명 (실제 AWS 호출 차단)
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["AWS_SECURITY_TOKEN"] = "testing"
os.environ["AWS_SESSION_TOKEN"] = "testing"
