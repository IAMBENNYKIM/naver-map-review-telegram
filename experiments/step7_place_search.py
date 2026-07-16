"""step7 확정 산출물 — 텍스트 키워드 -> 장소 후보 리스트(place_id 포함).

확정 엔드포인트: GET https://map.naver.com/p/api/search/instant-search
  필수 파라미터: query (검색어)
  선택 파라미터: coords="lat,lng" (근접도 정렬용 — 없어도 200이나 dist/정렬이 좌표 기준으로 바뀜)
  필수 헤더    : Referer (없으면 403 Forbidden) + Accept-Language
                 User-Agent는 데스크톱/모바일 둘 다 허용(instant-search는 UA 차단 안 함).

CLAUDE.md 하드 제약 준수: 모바일 Chrome UA 기본, 요청 간 0.5초, 429 무재시도 즉시 중단.

실행:
    PYTHONUTF8=1 python experiments/step7_place_search.py
"""

import time
import httpx

# config.NAVER_REQUEST_HEADERS 재사용 (모바일 Chrome UA + Referer 필수)
NAVER_SEARCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 13; SM-S911N) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
    ),
    "Referer": "https://map.naver.com/",  # 없으면 403 (실측 확정)
    "Accept-Language": "ko-KR,ko;q=0.9",
}
INSTANT_SEARCH_URL = "https://map.naver.com/p/api/search/instant-search"
RATE_LIMIT_DELAY = 0.5

# 강남역 근방 좌표 (근접도 정렬 기준 — 지역 키워드가 명시돼 있으면 큰 영향 없음)
DEFAULT_COORDS = "37.4979,127.0276"

TEST_KEYWORDS = ["강남 양식", "돈멜", "강남 데이트 양식집"]


def search_places(query: str, coords: str = DEFAULT_COORDS) -> list[dict]:
    """키워드 -> 장소 후보 리스트. 각 후보의 정규화된 필드만 반환."""
    params = {"query": query, "coords": coords}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(INSTANT_SEARCH_URL, params=params, headers=NAVER_SEARCH_HEADERS)
    if resp.status_code == 429:
        raise RuntimeError("429 rate limited — 무재시도 즉시 중단")
    resp.raise_for_status()
    data = resp.json()
    candidates = []
    for place in data.get("place", []):
        candidates.append(
            {
                "place_id": place.get("id"),          # 문자열 숫자 (예: "33099281")
                "name": place.get("title"),           # 장소명
                "category": place.get("ctg"),         # 업종
                "road_address": place.get("roadAddress"),
                "jibun_address": place.get("jibunAddress"),
                "review_count": place.get("review", {}).get("count"),
                "x": place.get("x"),                  # 경도
                "y": place.get("y"),                  # 위도
            }
        )
    return candidates


def main() -> None:
    for idx, keyword in enumerate(TEST_KEYWORDS):
        print(f"\n{'='*70}\n키워드: {keyword!r}\n{'='*70}")
        candidates = search_places(keyword)
        print(f"후보 {len(candidates)}건")
        for rank, cand in enumerate(candidates, start=1):
            print(
                f"  {rank}. place_id={cand['place_id']:>12}  "
                f"{cand['name']}  [{cand['category']}]  "
                f"리뷰{cand['review_count']}  {cand['road_address']}"
            )
        # 돈멜 교차 검증
        if keyword == "돈멜":
            ids = [c["place_id"] for c in candidates]
            hit = "33099281" in ids
            print(f"  >>> 교차검증: 돈멜 본점 place_id '33099281' 포함 = {hit}")
        if idx < len(TEST_KEYWORDS) - 1:
            time.sleep(RATE_LIMIT_DELAY)


if __name__ == "__main__":
    main()
