import {
  MapPin,
  ThumbsUp,
  ThumbsDown,
  AlertTriangle,
  Database,
} from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { AnalysisResult, MenuSentiment } from "@/lib/types";

/** 감성 값 → 배지 톤 매핑. */
const sentimentTone: Record<MenuSentiment, "positive" | "negative" | "warning"> = {
  추천: "positive",
  비추천: "negative",
  호불호: "warning",
};

interface ResultCardProps {
  result: AnalysisResult;
}

/** 분석 결과(done)를 카드로 렌더한다. */
export function ResultCard({ result }: ResultCardProps) {
  const { summary, rawSummaryJson, placeName, address, reviewCount, cacheHit } =
    result;

  return (
    <Card className="w-full">
      <CardContent className="space-y-6">
        {/* 장소 헤더 */}
        <header className="space-y-1">
          <div className="flex items-start justify-between gap-3">
            <h2 className="text-xl font-semibold leading-tight">
              {placeName ?? "이름 미상 장소"}
            </h2>
            {cacheHit ? (
              <Badge tone="accent" className="shrink-0">
                <Database className="h-3 w-3" aria-hidden="true" />
                캐시
              </Badge>
            ) : null}
          </div>
          {address ? (
            <p className="flex items-center gap-1 text-sm text-muted">
              <MapPin className="h-3.5 w-3.5" aria-hidden="true" />
              {address}
            </p>
          ) : null}
          {typeof reviewCount === "number" ? (
            <p className="text-xs text-muted">리뷰 {reviewCount}개 기반 요약</p>
          ) : null}
        </header>

        {summary ? (
          <>
            {/* 총평 */}
            {summary.overall ? (
              <section className="space-y-1">
                <h3 className="text-sm font-semibold text-muted">총평</h3>
                <p className="text-sm leading-relaxed">{summary.overall}</p>
              </section>
            ) : null}

            {/* 장점 / 단점 */}
            {(summary.pros.length > 0 || summary.cons.length > 0) && (
              <div className="grid gap-4 sm:grid-cols-2">
                {summary.pros.length > 0 ? (
                  <section className="space-y-2">
                    <h3 className="flex items-center gap-1.5 text-sm font-semibold text-emerald-600 dark:text-emerald-400">
                      <ThumbsUp className="h-4 w-4" aria-hidden="true" />
                      장점
                    </h3>
                    <ul className="space-y-1.5">
                      {summary.pros.map((item, index) => (
                        <li
                          key={`pro-${index}`}
                          className="flex gap-2 text-sm leading-relaxed"
                        >
                          <span className="text-emerald-500" aria-hidden="true">
                            •
                          </span>
                          <span>{item}</span>
                        </li>
                      ))}
                    </ul>
                  </section>
                ) : null}

                {summary.cons.length > 0 ? (
                  <section className="space-y-2">
                    <h3 className="flex items-center gap-1.5 text-sm font-semibold text-rose-600 dark:text-rose-400">
                      <ThumbsDown className="h-4 w-4" aria-hidden="true" />
                      단점
                    </h3>
                    <ul className="space-y-1.5">
                      {summary.cons.map((item, index) => (
                        <li
                          key={`con-${index}`}
                          className="flex gap-2 text-sm leading-relaxed"
                        >
                          <span className="text-rose-500" aria-hidden="true">
                            •
                          </span>
                          <span>{item}</span>
                        </li>
                      ))}
                    </ul>
                  </section>
                ) : null}
              </div>
            )}

            {/* 메뉴 추천 칩 */}
            {summary.menus.length > 0 ? (
              <section className="space-y-2">
                <h3 className="text-sm font-semibold text-muted">메뉴 추천</h3>
                <ul className="flex flex-wrap gap-2">
                  {summary.menus.map((menu, index) => (
                    <li key={`menu-${index}`}>
                      <div className="rounded-xl border border-border bg-background/40 px-3 py-2">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium">
                            {menu.name}
                          </span>
                          <Badge tone={sentimentTone[menu.sentiment]}>
                            {menu.sentiment}
                          </Badge>
                          {menu.mentions > 0 ? (
                            <span className="text-xs text-muted">
                              {menu.mentions}회 언급
                            </span>
                          ) : null}
                        </div>
                        {menu.note ? (
                          <p className="mt-1 text-xs text-muted">{menu.note}</p>
                        ) : null}
                      </div>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            {/* 주의 배너 */}
            {summary.caution ? (
              <div className="flex gap-2 rounded-xl bg-amber-500/10 px-4 py-3 text-sm text-amber-700 dark:text-amber-300">
                <AlertTriangle
                  className="mt-0.5 h-4 w-4 shrink-0"
                  aria-hidden="true"
                />
                <span>{summary.caution}</span>
              </div>
            ) : null}
          </>
        ) : (
          /* 파싱 실패 폴백 */
          <section className="space-y-2">
            <p className="text-sm text-muted">
              요약을 표 형태로 표시하지 못했어요. 아래 원문을 확인해 주세요.
            </p>
            {rawSummaryJson ? (
              <pre className="max-h-72 overflow-auto rounded-xl border border-border bg-background/40 p-3 text-xs whitespace-pre-wrap break-words">
                {rawSummaryJson}
              </pre>
            ) : (
              <p className="text-sm text-muted">표시할 요약 내용이 없어요.</p>
            )}
          </section>
        )}
      </CardContent>
    </Card>
  );
}
