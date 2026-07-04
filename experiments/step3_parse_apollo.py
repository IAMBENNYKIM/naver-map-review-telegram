"""Step 3: step2 덤프에서 __APOLLO_STATE__ 추출·구조 분석.

리뷰 카드 필드 경로, 장소명/주소, GraphQL 힌트 확인.
"""

import json
import re

DUMP = "experiments/dumps/step2_cand0.html"


def extract_apollo(html: str):
    # window.__APOLLO_STATE__ = {...};  — 중괄호 균형 매칭으로 정확히 잘라낸다.
    m = re.search(r"__APOLLO_STATE__\s*=\s*", html)
    if not m:
        return None
    start = html.find("{", m.end())
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(html)):
        ch = html[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return html[start:i + 1]
    return None


def main() -> None:
    with open(DUMP, encoding="utf-8") as f:
        html = f.read()
    raw = extract_apollo(html)
    if not raw:
        print("APOLLO_STATE 추출 실패 — 컨텍스트 확인")
        idx = html.find("__APOLLO_STATE__")
        print(html[idx:idx + 300])
        return
    print("raw apollo len", len(raw))
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print("json parse fail", e)
        with open("experiments/dumps/step3_apollo_raw.txt", "w", encoding="utf-8") as f:
            f.write(raw)
        return
    with open("experiments/dumps/step3_apollo.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("total keys", len(data))
    # 키 타입 분류
    prefixes = {}
    for k in data:
        pref = k.split(":")[0].split("(")[0].split(".")[0]
        prefixes[pref] = prefixes.get(pref, 0) + 1
    print("=== key prefixes ===")
    for p, c in sorted(prefixes.items(), key=lambda x: -x[1]):
        print(f"  {p}: {c}")
    # 리뷰/장소 관련 키 샘플
    print("\n=== keys containing Review ===")
    for k in list(data)[:2000]:
        if "eview" in k:
            print(" ", k)
    print("\n=== keys containing Place/Restaurant/Business ===")
    for k in list(data):
        if any(t in k for t in ("Place", "Restaurant", "Business", "Base")):
            print(" ", k)


if __name__ == "__main__":
    main()
