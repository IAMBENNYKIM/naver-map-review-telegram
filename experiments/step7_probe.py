"""step7 탐사용 유연한 probe 스크립트.

텍스트 키워드 -> 장소 후보 리스트(place_id 포함) 엔드포인트를 실측 확정하기 위한 도구.
CLAUDE.md 하드 제약 준수: 모바일 Chrome UA 기본, 429 무재시도 즉시 중단, GraphQL 인트로스펙션 금지.

사용:
    PYTHONUTF8=1 python experiments/step7_probe.py <endpoint_key> <query> [--desktop] [--no-referer] [--dump NAME]

endpoint_key:
    instant   : https://map.naver.com/p/api/search/instant-search
    allsearch : https://map.naver.com/p/api/search/allSearch
    searchmore: https://m.map.naver.com/search2/searchMore.naver
"""

import sys
import json
import httpx

# config.NAVER_REQUEST_HEADERS 재사용 (모바일 Chrome UA)
MOBILE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 13; SM-S911N) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
    ),
    "Referer": "https://map.naver.com/",
    "Accept-Language": "ko-KR,ko;q=0.9",
}
DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

DUMP_DIR = "experiments/dumps"


def build_request(endpoint_key: str, query: str):
    """엔드포인트별 URL/params 반환."""
    if endpoint_key == "instant":
        url = "https://map.naver.com/p/api/search/instant-search"
        params = {"query": query, "coords": "37.4979,127.0276"}  # 강남역 근방 좌표
    elif endpoint_key == "instant-nocoords":
        url = "https://map.naver.com/p/api/search/instant-search"
        params = {"query": query}
    elif endpoint_key == "allsearch":
        url = "https://map.naver.com/p/api/search/allSearch"
        params = {"query": query, "type": "all", "searchCoord": "127.0276;37.4979", "boundary": ""}
    elif endpoint_key == "searchmore":
        url = "https://m.map.naver.com/search2/searchMore.naver"
        params = {"query": query, "page": "1", "displayCount": "10", "type": "SITE_1"}
    else:
        raise ValueError(f"unknown endpoint_key: {endpoint_key}")
    return url, params


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        sys.exit(1)
    endpoint_key = args[0]
    query = args[1]
    desktop = "--desktop" in args
    no_referer = "--no-referer" in args
    dump_name = None
    if "--dump" in args:
        dump_name = args[args.index("--dump") + 1]

    headers = dict(MOBILE_HEADERS)
    if desktop:
        headers["User-Agent"] = DESKTOP_UA
    if no_referer:
        headers.pop("Referer", None)

    url, params = build_request(endpoint_key, query)

    print(f"=== {endpoint_key} | query={query!r} | desktop={desktop} | no_referer={no_referer} ===")
    print(f"GET {url}  params={params}")

    with httpx.Client(timeout=15.0, follow_redirects=True) as client:
        resp = client.get(url, params=params, headers=headers)

    print(f"HTTP {resp.status_code}  final_url={resp.url}")
    print(f"content-type={resp.headers.get('content-type')}  len={len(resp.text)}")

    if resp.status_code == 429:
        print("!!! 429 감지 — 무재시도 즉시 중단 (CLAUDE.md 제약 13)")
        sys.exit(2)

    body = resp.text
    is_json = "application/json" in (resp.headers.get("content-type") or "")
    if dump_name:
        ext = "json" if is_json else "html"
        path = f"{DUMP_DIR}/{dump_name}.{ext}"
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        print(f"dumped -> {path}")

    if is_json:
        try:
            data = resp.json()
            print("top-level type:", type(data).__name__)
            if isinstance(data, dict):
                print("top-level keys:", list(data.keys()))
            print("--- preview (2000 chars) ---")
            print(json.dumps(data, ensure_ascii=False)[:2000])
        except Exception as e:  # noqa: BLE001
            print("JSON parse fail:", e)
            print(body[:1000])
    else:
        print("--- body preview (1200 chars) ---")
        print(body[:1200])


if __name__ == "__main__":
    main()
