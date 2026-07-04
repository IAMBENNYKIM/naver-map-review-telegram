"""Step 4: 리뷰 카드/장소 필드 경로 확정. UTF-8 파일로 덤프해 콘솔 인코딩 회피."""

import json

with open("experiments/dumps/step3_apollo.json", encoding="utf-8") as f:
    data = json.load(f)

out = []


def show(title, obj):
    out.append(f"\n===== {title} =====")
    out.append(json.dumps(obj, ensure_ascii=False, indent=2))


# PlaceDetailBase (장소명/주소)
base_key = next(k for k in data if k.startswith("PlaceDetailBase:"))
show(f"PlaceDetailBase key={base_key}", data[base_key])

# VisitorReviewStatsResult (별점/통계)
stats_key = next((k for k in data if k.startswith("VisitorReviewStatsResult:")), None)
if stats_key:
    show(f"VisitorReviewStatsResult key={stats_key}", data[stats_key])

# 첫 VisitorReview 카드 전체
vr_key = next(k for k in data if k.startswith("VisitorReview:"))
show(f"VisitorReview sample key={vr_key}", data[vr_key])

# VisitorReviewAuthor 샘플
va_key = next(k for k in data if k.startswith("VisitorReviewAuthor:"))
show(f"VisitorReviewAuthor sample key={va_key}", data[va_key])

# ROOT_QUERY: visitorReviews 쿼리 형태 확인
show("ROOT_QUERY", data.get("ROOT_QUERY", {}))

with open("experiments/dumps/step4_fields.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("saved experiments/dumps/step4_fields.txt")
