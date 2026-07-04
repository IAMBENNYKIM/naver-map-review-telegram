"""Step 2: m.place.naver.com 리뷰 페이지 HTML 내 embedded JSON 탐색.

place_id=33099281 (돈멜 본점). restaurant 타입 추정.
window.__APOLLO_STATE__ 등 embedded state 존재 여부 확인.
"""

import time

import httpx

PLACE_ID = "33099281"

MOBILE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 13; SM-S911N) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
    ),
    "Referer": "https://map.naver.com/",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

CANDIDATES = [
    f"https://m.place.naver.com/restaurant/{PLACE_ID}/review/visitor",
    f"https://m.place.naver.com/place/{PLACE_ID}/review/visitor",
]


def main() -> None:
    with httpx.Client(headers=MOBILE_HEADERS, timeout=15.0, follow_redirects=True) as client:
        for i, url in enumerate(CANDIDATES):
            resp = client.get(url)
            print(f"\n=== CANDIDATE {i}: {url}")
            print("status", resp.status_code, "final_url", resp.url)
            print("encoding", resp.encoding, "content-type", resp.headers.get("content-type"))
            text = resp.text
            print("len", len(text))
            for marker in ["__APOLLO_STATE__", "__NEXT_DATA__", "window.__PLACE_STATE__", "visitorReviews", "PlaceReview", "graphql"]:
                print(f"  marker {marker!r}: {marker in text}")
            fn = f"experiments/dumps/step2_cand{i}.html"
            with open(fn, "w", encoding="utf-8") as f:
                f.write(text)
            print("saved", fn)
            time.sleep(0.6)


if __name__ == "__main__":
    main()
