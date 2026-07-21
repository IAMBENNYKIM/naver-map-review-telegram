"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  Bookmark,
  ChevronDown,
  ChevronRight,
  Eye,
  MapPin,
  RefreshCw,
  Search,
  Trash2,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { AnalysisStatusPanel } from "@/components/AnalysisStatusPanel";
import { useAnalysis } from "@/hooks/useAnalysis";
import { ApiError, deleteHistoryEntry, fetchHistory } from "@/lib/api";
import type { HistoryEntry } from "@/lib/types";

/** 보관함 목록 로딩 단계. */
type LoadPhase = "loading" | "done" | "error";

/** 완료로 간주하는 분석 단계(재클릭 시 접기 토글 대상). */
function isFinishedPhase(phase: string): boolean {
  return phase === "done" || phase === "error" || phase === "timeout";
}

interface HistoryViewProps {
  token: string;
  /** 세션 만료(401) 시 호출 — 상위가 토큰을 지우고 게이트로 돌린다. */
  onSessionExpired: () => void;
}

/**
 * ISO 문자열을 KST 기준 간단한 한국어 표기로 변환한다.
 * 오늘/어제는 상대 표기, 그 외에는 "M월 D일". 파싱 실패 시 빈 문자열.
 * (summary-text.ts 의 KST 변환과 동일한 방식을 쓰되 "갱신" 문구가 없는
 *  보관함 전용 표기라 로컬로 구현한다.)
 */
function formatLastViewed(isoString: string): string {
  if (!isoString) {
    return "";
  }
  const parsed = new Date(isoString);
  if (Number.isNaN(parsed.getTime())) {
    return "";
  }
  // 한국은 DST 가 없어 +9시간 고정 시프트로 KST 벽시계를 얻는다.
  const kstShifted = new Date(parsed.getTime() + 9 * 60 * 60 * 1000);
  const month = kstShifted.getUTCMonth() + 1;
  const day = kstShifted.getUTCDate();

  const nowKst = new Date(Date.now() + 9 * 60 * 60 * 1000);
  const targetDayUtc = Date.UTC(
    kstShifted.getUTCFullYear(),
    kstShifted.getUTCMonth(),
    kstShifted.getUTCDate(),
  );
  const todayDayUtc = Date.UTC(
    nowKst.getUTCFullYear(),
    nowKst.getUTCMonth(),
    nowKst.getUTCDate(),
  );
  const daysAgo = Math.round((todayDayUtc - targetDayUtc) / (24 * 60 * 60 * 1000));

  if (daysAgo <= 0) {
    return "오늘";
  }
  if (daysAgo === 1) {
    return "어제";
  }
  return `${month}월 ${day}일`;
}

/**
 * 보관함 화면: 개인이 조회했던 식당 목록을 최신순으로 보여주고,
 * 항목을 고르면 place_id 로 재분석(대부분 캐시 히트)해 결과를 항목 바로 아래에
 * 인라인으로 표시한다. 항목별 삭제도 지원한다.
 */
export function HistoryView({ token, onSessionExpired }: HistoryViewProps) {
  const [entries, setEntries] = useState<HistoryEntry[]>([]);
  const [loadPhase, setLoadPhase] = useState<LoadPhase>("loading");
  const [loadErrorText, setLoadErrorText] = useState<string | null>(null);
  // 결과를 인라인 표시할 선택 항목의 place_id.
  const [selectedPlaceId, setSelectedPlaceId] = useState<string | null>(null);
  // 선택 항목의 결과 패널을 접었는지 여부(완료 항목 재클릭 시 토글 — 목록 훑기 편의).
  const [isResultCollapsed, setIsResultCollapsed] = useState(false);
  // 보관함 내 검색어(클라이언트 필터 — 서버 호출 없음).
  const [filterText, setFilterText] = useState("");
  // 삭제 진행 중인 항목의 place_id — 해당 삭제 버튼만 잠근다.
  const [deletingPlaceId, setDeletingPlaceId] = useState<string | null>(null);
  // 삭제 실패 등 동작 오류 문구 (목록 상단에 표시).
  const [actionErrorText, setActionErrorText] = useState<string | null>(null);

  const { phase, result, errorText, stage, isRefreshing, runAnalysis, refresh } =
    useAnalysis({ token, onSessionExpired });

  // 분석 진행 중에는 다른 항목 클릭을 잠근다.
  const isAnalyzing = phase === "submitting" || phase === "polling";

  const loadHistory = useCallback(async () => {
    setLoadPhase("loading");
    setLoadErrorText(null);
    try {
      const historyEntries = await fetchHistory(token);
      setEntries(historyEntries);
      setLoadPhase("done");
    } catch (error) {
      if (error instanceof ApiError && error.isUnauthorized) {
        onSessionExpired();
        return;
      }
      setLoadErrorText(
        error instanceof ApiError
          ? error.message
          : "보관함을 불러오지 못했어요. 잠시 후 다시 시도해 주세요.",
      );
      setLoadPhase("error");
    }
  }, [token, onSessionExpired]);

  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  function handleSelect(entry: HistoryEntry) {
    if (isAnalyzing) {
      return; // 분석 진행 중에는 다른 항목 선택을 잠근다.
    }
    if (entry.placeId === selectedPlaceId && isFinishedPhase(phase)) {
      // 완료 항목 재클릭 = 결과 접기/펼치기 토글(재분석하지 않는다).
      setIsResultCollapsed((previous) => !previous);
      return;
    }
    setIsResultCollapsed(false); // 새 항목을 분석할 때는 결과를 펼친 상태로 시작한다.
    setSelectedPlaceId(entry.placeId);
    runAnalysis({ placeId: entry.placeId });
  }

  async function handleDelete(
    event: React.MouseEvent<HTMLButtonElement>,
    entry: HistoryEntry,
  ) {
    event.stopPropagation(); // 항목 클릭(분석)과 분리.
    if (deletingPlaceId) {
      return; // 이중 삭제 방지.
    }
    setActionErrorText(null);
    setDeletingPlaceId(entry.placeId);
    try {
      await deleteHistoryEntry(token, entry.placeId);
      // 로컬 상태에서 제거 — 재fetch 하지 않는다.
      setEntries((current) =>
        current.filter((item) => item.placeId !== entry.placeId),
      );
      if (selectedPlaceId === entry.placeId) {
        setSelectedPlaceId(null); // 삭제된 항목의 인라인 결과를 닫는다.
        setIsResultCollapsed(false); // 접힘 상태도 초기화한다.
      }
    } catch (error) {
      if (error instanceof ApiError && error.isUnauthorized) {
        onSessionExpired();
        return;
      }
      setActionErrorText(
        error instanceof ApiError
          ? error.message
          : "삭제에 실패했어요. 잠시 후 다시 시도해 주세요.",
      );
    } finally {
      setDeletingPlaceId(null);
    }
  }

  if (loadPhase === "loading") {
    return (
      <div className="flex items-center justify-center py-16">
        <Spinner className="h-6 w-6 text-accent" />
      </div>
    );
  }

  if (loadPhase === "error") {
    return (
      <Card>
        <CardContent className="space-y-4">
          <div className="flex items-start gap-3 text-sm text-rose-600 dark:text-rose-400">
            <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
            <span role="alert">
              {loadErrorText ?? "보관함을 불러오지 못했어요."}
            </span>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void loadHistory()}
          >
            <RefreshCw className="h-4 w-4" aria-hidden="true" />
            다시 시도
          </Button>
        </CardContent>
      </Card>
    );
  }

  if (entries.length === 0) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-2 py-12 text-center">
          <Bookmark className="h-8 w-8 text-muted" aria-hidden="true" />
          <p className="text-sm font-medium">아직 조회한 식당이 없어요</p>
          <p className="text-xs text-muted">
            검색이나 링크로 리뷰를 요약하면 여기에 쌓여요.
          </p>
        </CardContent>
      </Card>
    );
  }

  // 보관함 내 검색 — 식당명·주소 부분 일치로 표시할 항목만 거른다(표시만 거르고 상태는 유지).
  const normalizedFilter = filterText.trim().toLowerCase();
  const filteredEntries = normalizedFilter
    ? entries.filter(
        (entry) =>
          entry.placeName.toLowerCase().includes(normalizedFilter) ||
          entry.address.toLowerCase().includes(normalizedFilter),
      )
    : entries;

  return (
    <div className="space-y-3">
      <div className="relative">
        <Search
          className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted"
          aria-hidden="true"
        />
        <Input
          type="search"
          value={filterText}
          onChange={(event) => setFilterText(event.target.value)}
          placeholder="식당명이나 주소로 찾기"
          aria-label="보관함 내 검색"
          className="pl-9"
        />
      </div>

      {actionErrorText ? (
        <Card>
          <CardContent className="flex items-start gap-3 text-sm text-rose-600 dark:text-rose-400">
            <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
            <span role="alert">{actionErrorText}</span>
          </CardContent>
        </Card>
      ) : null}

      {filteredEntries.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-2 py-12 text-center">
            <Search className="h-8 w-8 text-muted" aria-hidden="true" />
            <p className="text-sm font-medium">
              &lsquo;{filterText.trim()}&rsquo;에 해당하는 식당이 없어요
            </p>
            <p className="text-xs text-muted">다른 검색어로 찾아보세요.</p>
          </CardContent>
        </Card>
      ) : null}

      <ul className="space-y-2">
        {filteredEntries.map((entry) => {
          const isSelected = entry.placeId === selectedPlaceId;
          const isItemAnalyzing = isSelected && isAnalyzing;
          // 단일 훅이라 phase는 선택 항목에만 적용된다 — 선택+완료 항목만 접기 대상.
          const isItemFinished = isSelected && isFinishedPhase(phase);
          const isDeleting = entry.placeId === deletingPlaceId;
          const lastViewedLabel = formatLastViewed(entry.lastViewedAt);

          return (
            <li key={entry.placeId}>
              <div className="flex items-center gap-2 rounded-xl border border-border bg-card px-3 py-3">
                <button
                  type="button"
                  onClick={() => handleSelect(entry)}
                  disabled={isAnalyzing}
                  aria-label={
                    isItemFinished
                      ? `${entry.placeName || "이름 미상 장소"} 분석 결과 ${
                          isResultCollapsed ? "펼치기" : "접기"
                        }`
                      : `${entry.placeName || "이름 미상 장소"} 리뷰 다시 보기`
                  }
                  aria-expanded={isItemFinished ? !isResultCollapsed : undefined}
                  className="flex min-w-0 flex-1 items-center gap-3 rounded-lg px-1 text-left transition-colors hover:bg-black/5 disabled:cursor-not-allowed disabled:opacity-60 dark:hover:bg-white/5"
                >
                  <div className="min-w-0 flex-1 space-y-0.5">
                    <span className="block truncate font-medium">
                      {entry.placeName || "이름 미상 장소"}
                    </span>
                    {entry.address ? (
                      <p className="flex items-center gap-1 truncate text-xs text-muted">
                        <MapPin className="h-3 w-3 shrink-0" aria-hidden="true" />
                        {entry.address}
                      </p>
                    ) : null}
                    <p className="flex items-center gap-2 text-xs text-muted">
                      {lastViewedLabel ? (
                        <span>마지막 조회 {lastViewedLabel}</span>
                      ) : null}
                      <span className="flex items-center gap-1">
                        <Eye className="h-3 w-3 shrink-0" aria-hidden="true" />
                        {entry.viewCount.toLocaleString("ko-KR")}회
                      </span>
                    </p>
                  </div>
                  {isItemAnalyzing ? (
                    <Spinner className="h-4 w-4 shrink-0 text-accent" />
                  ) : isItemFinished && !isResultCollapsed ? (
                    <ChevronDown
                      className="h-4 w-4 shrink-0 text-muted"
                      aria-hidden="true"
                    />
                  ) : (
                    <ChevronRight
                      className="h-4 w-4 shrink-0 text-muted"
                      aria-hidden="true"
                    />
                  )}
                </button>

                <button
                  type="button"
                  onClick={(event) => handleDelete(event, entry)}
                  disabled={isDeleting}
                  aria-label={`${entry.placeName || "이름 미상 장소"} 보관함에서 삭제`}
                  className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-black/5 hover:text-rose-600 disabled:cursor-not-allowed disabled:opacity-60 dark:hover:bg-white/5 dark:hover:text-rose-400"
                >
                  {isDeleting ? (
                    <Spinner className="h-4 w-4" />
                  ) : (
                    <Trash2 className="h-4 w-4" aria-hidden="true" />
                  )}
                </button>
              </div>

              {/* 선택한 항목의 분석 상태를 바로 아래에 인라인 표시(접힘 시 생략) */}
              {isSelected && !isResultCollapsed ? (
                <div className="pt-2">
                  <AnalysisStatusPanel
                    phase={phase}
                    stage={stage}
                    result={result}
                    errorText={errorText}
                    isRefreshing={isRefreshing}
                    onRefresh={() => {
                      setIsResultCollapsed(false); // 갱신 시 접힘을 방어적으로 해제한다.
                      refresh();
                    }}
                  />
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
