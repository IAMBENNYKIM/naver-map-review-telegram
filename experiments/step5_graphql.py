"""Step 5: pcmap-api.place.naver.com/graphql visitorReviews 직접 호출 검증.

실험 항목:
  A) 전체 헤더 + page=1, size=10  → 기본 동작 확인
  B) size=50, page=1              → 한 번에 50개 가능 여부
  C) Referer 제거                 → Referer 필수 여부 확정
  D) page=2                       → 페이지네이션 동작(다른 리뷰 반환) 확인

요청 간 0.6초 대기. 403/captcha 시 즉시 중단.
"""

import json
import sys
import time

import httpx

PLACE_ID = "33099281"
GRAPHQL_URL = "https://pcmap-api.place.naver.com/graphql"

HEADERS_FULL = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 13; SM-S911N) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
    ),
    "Referer": f"https://pcmap.place.naver.com/restaurant/{PLACE_ID}/review/visitor",
    "Content-Type": "application/json",
    "Accept": "*/*",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

QUERY = """
query getVisitorReviews($input: VisitorReviewsInput) {
  visitorReviews(input: $input) {
    items {
      id
      reviewId
      rating
      author { id nickname }
      body
      visited
      created
      visitCount
      originType
      votedKeywords { name }
      representativeVisitDateTime
    }
    total
  }
}
"""


def build_payload(page: int, size: int) -> list[dict]:
    return [
        {
            "operationName": "getVisitorReviews",
            "variables": {
                "input": {
                    "businessId": PLACE_ID,
                    "businessType": "restaurant",
                    "item": "0",
                    "page": page,
                    "size": size,
                    "isPhotoUsed": False,
                    "includeContent": True,
                    "getUserStats": True,
                    "includeReceiptPhotos": True,
                }
            },
            "query": QUERY,
        }
    ]


def call(client: httpx.Client, name: str, payload, headers) -> None:
    resp = client.post(GRAPHQL_URL, json=payload, headers=headers)
    print(f"\n=== {name}: status={resp.status_code} encoding={resp.encoding}")
    if resp.status_code == 403 or "captcha" in resp.text.lower():
        print("!!! 차단 신호 감지 — 즉시 중단")
        sys.exit(1)
    fn = f"experiments/dumps/step5_{name}.json"
    with open(fn, "w", encoding="utf-8") as f:
        f.write(resp.text)
    try:
        data = resp.json()
        vr = data[0]["data"]["visitorReviews"]
        if vr is None:
            print("visitorReviews=None, errors:", json.dumps(data[0].get("errors", []))[:400])
            return
        items = vr["items"]
        print(f"total={vr['total']} items={len(items)}")
        for it in items[:3]:
            body = (it.get("body") or "")[:40].replace("\n", " ")
            print(f"  id={it['id']} rating={it.get('rating')} visited={it.get('visited')} body={body!r}")
        print("first_id=", items[0]["id"] if items else None, "last_id=", items[-1]["id"] if items else None)
    except Exception as e:
        print("parse fail:", e, resp.text[:300])
    print("saved", fn)


def main() -> None:
    with httpx.Client(timeout=15.0) as client:
        call(client, "A_full_p1s10", build_payload(1, 10), HEADERS_FULL)
        time.sleep(0.6)
        call(client, "B_full_p1s50", build_payload(1, 50), HEADERS_FULL)
        time.sleep(0.6)
        no_ref = {k: v for k, v in HEADERS_FULL.items() if k != "Referer"}
        call(client, "C_noreferer_p1s10", build_payload(1, 10), no_ref)
        time.sleep(0.6)
        call(client, "D_full_p2s10", build_payload(2, 10), HEADERS_FULL)


if __name__ == "__main__":
    main()
