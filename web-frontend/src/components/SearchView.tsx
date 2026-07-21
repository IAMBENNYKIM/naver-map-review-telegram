"use client";

import { useState } from "react";
import { Search, AlertCircle, MapPin, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { AnalysisStatusPanel } from "@/components/AnalysisStatusPanel";
import { useAnalysis } from "@/hooks/useAnalysis";
import { ApiError, searchPlaces } from "@/lib/api";
import type { PlaceCandidate } from "@/lib/types";

/** 검색 입력 예시 placeholder. */
const SEARCH_PLACEHOLDER = "강남에서 데이트하기 좋은 양식집";

/** 장소 검색 단계. */
type SearchPhase = "idle" | "searching" | "done" | "error";

interface SearchViewProps {
  token: string;
  /** 세션 만료(401) 시 호출 — 상위가 토큰을 지우고 게이트로 돌린다. */
  onSessionExpired: () => void;
}

/**
 * 검색 화면: 자연어 프롬프트로 후보 장소를 찾고,
 * 후보를 고르면 place_id 로 기존 분석 흐름(폴링·결과 카드)을 재사용한다.
 */
export function SearchView({ token, onSessionExpired }: SearchViewProps) {
  const [prompt, setPrompt] = useState("");
  const [searchPhase, setSearchPhase] = useState<SearchPhase>("idle");
  const [searchErrorText, setSearchErrorText] = useState<string | null>(null);
  const [keyword, setKeyword] = useState<string | null>(null);
  const [places, setPlaces] = useState<PlaceCandidate[]>([]);
  // 현재 분석 중인 후보 — 선택된 카드를 강조하기 위해 보관한다.
  const [selectedPlaceId, setSelectedPlaceId] = useState<string | null>(null);

  const { phase, result, errorText, stage, isRefreshing, runAnalysis, refresh } =
    useAnalysis({ token, onSessionExpired });

  const isSearching = searchPhase === "searching";
  const isAnalyzing = phase === "submitting" || phase === "polling";

  async function handleSearch(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedPrompt = prompt.trim();
    if (!trimmedPrompt || isSearching) {
      return; // 빈 입력·이중 제출 방지.
    }

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
    if (isAnalyzing) {
      return; // 분석 진행 중에는 후보 선택을 잠근다.
    }
    setSelectedPlaceId(place.placeId);
    runAnalysis({ placeId: place.placeId });
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
                disabled={isSearching}
                onChange={(event) => setPrompt(event.target.value)}
              />
            </div>

            <Button
              type="submit"
              className="w-full"
              disabled={isSearching || prompt.trim().length === 0}
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
          <div className="space-y-2">
            {keyword ? (
              <p className="px-1 text-sm text-muted">
                &lsquo;{keyword}&rsquo;(으)로 검색했어요.
              </p>
            ) : null}
            <ul className="space-y-2">
              {places.map((place) => {
                const isSelected =
                  selectedPlaceId === place.placeId && isAnalyzing;
                return (
                  <li key={place.placeId}>
                    <button
                      type="button"
                      onClick={() => handleSelectPlace(place)}
                      disabled={isAnalyzing}
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
                      {isSelected ? (
                        <Spinner className="h-4 w-4 shrink-0 text-accent" />
                      ) : (
                        <ChevronRight
                          className="h-4 w-4 shrink-0 text-muted"
                          aria-hidden="true"
                        />
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        )
      ) : null}

      {/* 분석 상태 (후보 선택 후 — 폴링·타임아웃·오류·결과) */}
      <AnalysisStatusPanel
        phase={phase}
        stage={stage}
        result={result}
        errorText={errorText}
        isRefreshing={isRefreshing}
        onRefresh={refresh}
      />
    </div>
  );
}
