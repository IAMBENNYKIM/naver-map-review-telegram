"""Step 6: 페이지네이션 파라미터 확정.

E) __type 인트로스펙션으로 VisitorReviewsInput 필드 목록 확인 (가능하면 확실한 답)
F) size=3 + page=2 vs G) size=3 + page=3 비교 — page 동작 재확인
"""

import json
import sys
import time

import httpx

PLACE_ID = "33099281"
GRAPHQL_URL = "https://pcmap-api.place.naver.com/graphql"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 13; SM-S911N) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
    ),
    "Referer": f"https://pcmap.place.naver.com/restaurant/{PLACE_ID}/review/visitor",
    "Content-Type": "application/json",
}

INTROSPECT = {
    "operationName": None,
    "variables": {},
    "query": '{ __type(name: "VisitorReviewsInput") { name inputFields { name type { name kind ofType { name } } } } }',
}

QUERY = """
query getVisitorReviews($input: VisitorReviewsInput) {
  visitorReviews(input: $input) { items { id visited } total }
}
"""


def review_payload(extra: dict) -> list[dict]:
    base = {
        "businessId": PLACE_ID,
        "businessType": "restaurant",
        "item": "0",
        "includeContent": True,
    }
    base.update(extra)
    return [{"operationName": "getVisitorReviews", "variables": {"input": base}, "query": QUERY}]


def main() -> None:
    with httpx.Client(timeout=15.0, headers=HEADERS) as client:
        r = client.post(GRAPHQL_URL, json=[INTROSPECT])
        print("=== E introspection status", r.status_code)
        if r.status_code == 403:
            sys.exit("차단 신호 — 중단")
        with open("experiments/dumps/step6_E_introspect.json", "w", encoding="utf-8") as f:
            f.write(r.text)
        try:
            t = r.json()[0]["data"]["__type"]
            if t:
                for fld in t["inputFields"]:
                    ty = fld["type"]
                    tn = ty.get("name") or (ty.get("ofType") or {}).get("name") or ty.get("kind")
                    print(f"  {fld['name']}: {tn}")
            else:
                print("  __type=None (인트로스펙션 차단)")
        except Exception as e:
            print("  introspection parse fail:", e, r.text[:200])

        time.sleep(0.6)
        r = client.post(GRAPHQL_URL, json=review_payload({"size": 3, "page": 2}))
        d = r.json()[0]["data"]["visitorReviews"]
        print("=== F page=2 size=3:", [i["id"] for i in d["items"]])
        with open("experiments/dumps/step6_F_p2s3.json", "w", encoding="utf-8") as f:
            f.write(r.text)

        time.sleep(0.6)
        r = client.post(GRAPHQL_URL, json=review_payload({"size": 3, "page": 3}))
        d = r.json()[0]["data"]["visitorReviews"]
        print("=== G page=3 size=3:", [i["id"] for i in d["items"]])
        with open("experiments/dumps/step6_G_p3s3.json", "w", encoding="utf-8") as f:
            f.write(r.text)


if __name__ == "__main__":
    main()
