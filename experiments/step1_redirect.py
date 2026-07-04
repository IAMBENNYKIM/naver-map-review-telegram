"""Step 1: naver.me 단축 URL 리다이렉트 체인 추적 → place_id 추출.

요청 규칙: Referer + 모바일 Chrome UA, 요청 간 0.5초 대기.
"""

import time

import httpx

SHORT_URL = "https://naver.me/GB3423bX"

MOBILE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 13; SM-S911N) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
    ),
    "Referer": "https://map.naver.com/",
    "Accept-Language": "ko-KR,ko;q=0.9",
}


def main() -> None:
    with httpx.Client(headers=MOBILE_HEADERS, timeout=15.0) as client:
        # follow_redirects=True 로 전체 체인 추적
        response = client.get(SHORT_URL, follow_redirects=True)
        print("=== FINAL URL ===")
        print(response.url)
        print("=== STATUS ===", response.status_code)
        print("=== REDIRECT CHAIN ===")
        for hist in response.history:
            loc = hist.headers.get("location")
            print(f"  {hist.status_code} {hist.url}  ->  {loc}")
        print("=== FINAL ENCODING ===", response.encoding)
        # HTML 덤프 저장
        with open("experiments/dumps/step1_final.html", "w", encoding="utf-8") as f:
            f.write(response.text)
        print("saved experiments/dumps/step1_final.html len=", len(response.text))


if __name__ == "__main__":
    main()
    time.sleep(0.5)
