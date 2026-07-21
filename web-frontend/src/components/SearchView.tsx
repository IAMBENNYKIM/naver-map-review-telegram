"use client";

import { useState } from "react";
import { Search, AlertCircle, MapPin, ChevronRight, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { AnalysisStatusPanel } from "@/components/AnalysisStatusPanel";
import type { AnalysisPhase } from "@/hooks/useAnalysis";
import {
  useBatchAnalysis,
  type BatchEntry,
  type BatchItemState,
} from "@/hooks/useBatchAnalysis";
import { ApiError, searchPlaces } from "@/lib/api";
import type { PlaceCandidate } from "@/lib/types";

/** 검색 입력 예시 placeholder. */
const SEARCH_PLACEHOLDER = "강남에서 데이트하기 좋은 양식집";

/** 한 번에 일괄 분석하는 장소 수. */
const BATCH_SIZE = 5;

/** 장소 검색 단계. */
type SearchPhase = "idle" | "searching" | "done" | "error";

interface SearchViewProps {
  token: string;
  /** 세션 만료(401) 시 호출 — 상위가 토큰을 지우고 게이트로 돌린다. */
  onSessionExpired: () => void;
}

/** 후보 장소를 배치 분석 항목으로 변환한다. key는 place_id로 항목 상태를 잇는다. */
function toBatchEntry(place: PlaceCandidate): BatchEntry {
  return {
    key: place.placeId,
    label: place.name,
    target: { placeId: place.placeId },
  };
}

/** 배치 항목 상태를 상태 패널의 phase로 매핑한다(waiting은 패널을 쓰지 않는다). */
function toPanelPhase(status: BatchItemState["status"]): AnalysisPhase {
  switch (status) {
    case "running":
      return "polling";
    case "done":
      return "done";
    case "error":
      return "error";
    case "timeout":
      return "timeout";
    default:
      return "idle";
  }
}

/**
 * 검색 화면: 자연어 프롬프트로 후보 장소를 찾고,
 * 후보를 고르거나 상위 N곳을 일괄로 골라 분석 결과를 각 항목 아래에 인라인으로 표시한다.
 */
export function SearchView({ token, onSessionExpired }: SearchViewProps) {
  const [prompt, setPrompt] = useState("");
  const [searchPhase, setSearchPhase] = useState<SearchPhase>("idle");
  const [searchErrorText, setSearchErrorText] = useState<string | null>(null);
  const [keyword, setKeyword] = useState<string | null>(null);
  const [places, setPlaces] = useState<PlaceCandidate[]>([]);
  // 일괄 분석 진척 오프셋 — "다음 5곳"에서 다음 구간을 가리킨다.
  const [batchOffset, setBatchOffset] = useState(0);
  // 일괄 분석을 한 번이라도 시작했는지 — 버튼 문구("상위" vs "다음") 판정에 쓴다.
  const [batchStarted, setBatchStarted] = useState(false);

  const {
    items,
    isRunning,
    completedCount,
    startBatch,
    refreshItem,
    cancel,
    reset,
  } = useBatchAnalysis({ token, onSessionExpired });

  const isSearching = searchPhase === "searching";
  // place_id로 항목 상태를 빠르게 조회하기 위한 맵.
  const itemByKey = new Map(items.map((item) => [item.entry.key, item]));

  // 다음 일괄 분석이 가리킬 오프셋과 노출 여부.
  const nextBatchOffset = batchStarted ? batchOffset + BATCH_SIZE : 0;
  const canStartBatch = places.length > 0 && nextBatchOffset < places.length;
  const remainingCount = Math.min(BATCH_SIZE, places.length - nextBatchOffset);
  const batchButtonLabel = batchStarted
    ? `다음 ${remainingCount}곳 분석하기`
    : `상위 ${Math.min(BATCH_SIZE, places.length)}곳 분석하기`;

  async function handleSearch(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedPrompt = prompt.trim();
    if (!trimmedPrompt || isSearching || isRunning) {
      return; // 빈 입력·이중 제출·배치 진행 중 방지.
    }

    // 새 검색 — 진행 중 배치를 중단하고 항목 전체와 일괄 분석 진척을 초기화한다.
    reset();
    setBatchStarted(false);
    setBatchOffset(0);
    setSearchPhase("searching");
    setSearchErrorText(null);
    try {
      const searchResult = await searchPlaces(token, trimmedPrompt);
      setKeyword(searchResult.keyword);
      setPlaces(searchResult.places);
      setSearchPhase("done");
    } catch (error) {
      if (error instanceof ApiError && error.isUnauthorized) {
        onSessionExpired();
        return;
      }
      setSearchErrorText(
        error instanceof ApiError
          ? error.message
          : "검색에 실패했어요. 잠시 후 다시 시도해 주세요.",
      );
      setSearchPhase("error");
    }
  }

  function handleSelectPlace(place: PlaceCandidate) {
    if (isRunning) {
      return; // 배치 진행 중에는 개별 선택을 잠근다.
    }
    const existing = itemByKey.get(place.placeId);
    if (existing && existing.status === "done") {
      return; // 이미 결과가 있으면 무시 — 재분석은 결과 카드의 갱신 버튼으로만.
    }
    // 단건 클릭 = 병합 배치 1건. 일괄 분석 진척(오프셋)은 되돌리지 않는다.
    startBatch([toBatchEntry(place)]);
  }

  function handleStartBatch() {
    const offset = nextBatchOffset;
    const slice = places.slice(offset, offset + BATCH_SIZE);
    if (slice.length === 0) {
      return;
    }
    setBatchOffset(offset);
    setBatchStarted(true);
    startBatch(slice.map(toBatchEntry));
  }

  /** 배치 항목 하나의 상태(대기 배지 또는 상태 패널)를 렌더한다. */
  function renderItemStatus(item: BatchItemState) {
    if (item.status === "waiting") {
      return (
        <div className="pt-2 pl-1">
          <Badge tone="neutral">대기 중</Badge>
        </div>
      );
    }
    return (
      <div className="pt-2">
        <AnalysisStatusPanel
          phase={toPanelPhase(item.status)}
          stage={item.stage}
          result={item.result}
          errorText={item.errorText}
          isRefreshing={item.isRefreshing}
          onRefresh={() => refreshItem(item.entry.key)}
        />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardContent>
          <form onSubmit={handleSearch} className="space-y-4" noValidate>
            <div className="space-y-1.5">
              <Label htmlFor="search-prompt">어떤 곳을 찾으세요?</Label>
              <Input
                id="search-prompt"
                placeholder={SEARCH_PLACEHOLDER}
                value={prompt}
                disabled={isSearching || isRunning}
                onChange={(event) => setPrompt(event.target.value)}
              />
            </div>

            <Button
              type="submit"
              className="w-full"
              disabled={isSearching || isRunning || prompt.trim().length === 0}
            >
              {isSearching ? (
                <>
                  <Spinner className="h-4 w-4" />
                  검색 중...
                </>
              ) : (
                <>
                  <Search className="h-4 w-4" aria-hidden="true" />
                  장소 검색하기
                </>
              )}
            </Button>
          </form>
        </CardContent>
      </Card>

      {/* 검색 오류 */}
      {searchPhase === "error" && searchErrorText ? (
        <Card>
          <CardContent className="flex items-start gap-3 text-sm text-rose-600 dark:text-rose-400">
            <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
            <span role="alert">{searchErrorText}</span>
          </CardContent>
        </Card>
      ) : null}

      {/* 검색 결과 */}
      {searchPhase === "done" ? (
        places.length === 0 ? (
          <Card>
            <CardContent className="text-sm text-muted">
              검색 결과가 없어요. 지역+음식 종류로 다시 써보세요.
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-3">
            {keyword ? (
              <p className="px-1 text-sm text-muted">
                &lsquo;{keyword}&rsquo;(으)로 검색했어요.
              </p>
            ) : null}

            {/* 일괄 분석 제어 — 진행 중이면 진척+취소, 아니면 시작 버튼 */}
            {isRunning ? (
              <div className="flex items-center justify-between gap-3 rounded-xl border border-border bg-card px-4 py-3">
                <span className="flex items-center gap-2 text-sm font-medium">
                  <Spinner className="h-4 w-4 text-accent" />
                  {Math.min(completedCount + 1, items.length)}/{items.length}곳
                  분석 중…
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={cancel}
                  aria-label="일괄 분석 취소하기"
                >
                  <X className="h-4 w-4" aria-hidden="true" />
                  취소
                </Button>
              </div>
            ) : canStartBatch ? (
              <div className="space-y-1.5">
                <Button
                  type="button"
                  variant="outline"
                  className="w-full"
                  onClick={handleStartBatch}
                >
                  {batchButtonLabel}
                </Button>
                <p className="px-1 text-xs text-muted">
                  여러 곳을 순서대로 이어서 분석해요. 한 곳당 최대 1분까지 걸릴
                  수 있어요.
                </p>
              </div>
            ) : null}

            <ul className="space-y-2">
              {places.map((place) => {
                const item = itemByKey.get(place.placeId);
                const isItemRunning = item?.status === "running";
                return (
                  <li key={place.placeId}>
                    <button
                      type="button"
                      onClick={() => handleSelectPlace(place)}
                      disabled={isRunning}
                      aria-label={`${place.name} 리뷰 분석하기`}
                      className="flex w-full items-center gap-3 rounded-xl border border-border bg-card px-4 py-3 text-left transition-colors hover:bg-black/5 disabled:cursor-not-allowed disabled:opacity-60 dark:hover:bg-white/5"
                    >
                      <div className="min-w-0 flex-1 space-y-0.5">
                        <div className="flex items-center gap-2">
                          <span className="truncate font-medium">
                            {place.name}
                          </span>
                          {place.category ? (
                            <span className="shrink-0 text-xs text-muted">
                              {place.category}
                            </span>
                          ) : null}
                        </div>
                        {place.roadAddress ? (
                          <p className="flex items-center gap-1 truncate text-xs text-muted">
                            <MapPin className="h-3 w-3 shrink-0" aria-hidden="true" />
                            {place.roadAddress}
                          </p>
                        ) : null}
                        {typeof place.reviewCount === "number" ? (
                          <p className="text-xs text-muted">
                            리뷰 {place.reviewCount.toLocaleString("ko-KR")}개
                          </p>
                        ) : null}
                      </div>
                      {isItemRunning ? (
                        <Spinner className="h-4 w-4 shrink-0 text-accent" />
                      ) : (
                        <ChevronRight
                          className="h-4 w-4 shrink-0 text-muted"
                          aria-hidden="true"
                        />
                      )}
                    </button>

                    {/* 선택한 항목의 분석 상태를 후보 바로 아래에 인라인 표시 */}
                    {item ? renderItemStatus(item) : null}
                  </li>
                );
              })}
            </ul>
          </div>
        )
      ) : null}
    </div>
  );
}
