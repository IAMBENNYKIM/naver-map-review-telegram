"use client";

import { useEffect, useRef, useState } from "react";

import { runAnalysisToCompletion } from "@/lib/analysis-runner";
import type { AnalysisResult, AnalysisStage, AnalysisTarget } from "@/lib/types";

/** 배치 분석 대상 한 건. key는 목록 내 안정 식별자(place_id 등)로 항목 상태를 잇는다. */
export interface BatchEntry {
  key: string;
  label: string;
  target: AnalysisTarget;
}

/** 배치 항목 하나의 진행 상태. */
export interface BatchItemState {
  entry: BatchEntry;
  status: "waiting" | "running" | "done" | "error" | "timeout";
  stage: AnalysisStage | null;
  result: AnalysisResult | null;
  errorText: string | null;
  isRefreshing: boolean;
}

interface UseBatchAnalysisArgs {
  token: string;
  /** 세션 만료(401) 시 호출 — 상위가 토큰을 지우고 게이트로 돌린다. */
  onSessionExpired: () => void;
}

interface UseBatchAnalysisApi {
  items: BatchItemState[];
  /** 배치가 순차 실행 중인지 여부. */
  isRunning: boolean;
  /** 완료(done·error·timeout)된 항목 수. 진행 표시("n/5곳")에 쓴다. */
  completedCount: number;
  /**
   * 새 항목들을 대기로 추가하고 순차 분석을 시작한다(병합 시맨틱).
   * 겹치지 않는 완료 항목은 유지하고, 겹치는 항목만 이번 실행으로 대체한다.
   */
  startBatch: (entries: BatchEntry[]) => void;
  /** 특정 항목만 강제 재분석한다. 배치 실행 중에는 무시한다. */
  refreshItem: (key: string) => void;
  /** 진행 중 폴링을 중단한다. 완료 항목의 결과는 유지한다. */
  cancel: () => void;
  /** 전체 초기화 — 진행 중 폴링 중단 + 항목 전체 비움(새 검색 시 사용). */
  reset: () => void;
}

/** 일일 상한(HTTP 429) 도달 시 사용자에게 보여줄 문구. */
const DAILY_LIMIT_MESSAGE =
  "오늘 분석 가능 횟수를 모두 사용했어요. 내일 다시 시도해 주세요.";

/** 완료로 간주하는 상태(진행 카운트·취소 시 보존 판정에 쓴다). */
function isFinishedStatus(status: BatchItemState["status"]): boolean {
  return status === "done" || status === "error" || status === "timeout";
}

/**
 * 여러 대상을 순차로 분석하는 훅.
 * 요청·폴링 본체는 순수 실행기(runAnalysisToCompletion)에 위임하고,
 * 이 훅은 항목별 React 상태 반영과 세대 무효화만 담당한다.
 * useAnalysis의 관례(runIdRef 세대 무효화·언마운트 정리)를 그대로 따른다.
 */
export function useBatchAnalysis({
  token,
  onSessionExpired,
}: UseBatchAnalysisArgs): UseBatchAnalysisApi {
  const [items, setItems] = useState<BatchItemState[]>([]);
  const [isRunning, setIsRunning] = useState(false);

  // 실행 세대 번호 — 새 배치/취소/언마운트 시 이전 폴링 루프를 무효화한다.
  const runIdRef = useRef(0);
  // isRunning의 동기 미러 — refreshItem에서 최신 값을 즉시 참조한다.
  const isRunningRef = useRef(false);

  useEffect(() => {
    return () => {
      // 언마운트 시 진행 중 폴링을 중단시킨다.
      runIdRef.current += 1;
    };
  }, []);

  /** isRunning 상태와 동기 미러 ref를 함께 갱신한다. */
  function setRunning(value: boolean) {
    isRunningRef.current = value;
    setIsRunning(value);
  }

  /** 세대가 유효할 때만 특정 키의 항목을 부분 갱신한다. */
  function patchItem(runId: number, key: string, patch: Partial<BatchItemState>) {
    setItems((previousItems) => {
      if (runIdRef.current !== runId) {
        return previousItems; // 더 최신 실행이 시작됨.
      }
      return previousItems.map((item) =>
        item.entry.key === key ? { ...item, ...patch } : item,
      );
    });
  }

  function handleSessionExpired() {
    runIdRef.current += 1;
    setRunning(false);
    onSessionExpired();
  }

  async function executeBatch(entries: BatchEntry[]) {
    const runId = runIdRef.current + 1;
    runIdRef.current = runId;

    // 병합 초기화: 이번 entries와 key가 겹치지 않는 완료 항목은 유지하고,
    // 이전 실행의 waiting/running 잔여(세대 무효화로 어차피 중단됨)는 제거한다.
    // 이번 entries는 모두 waiting으로 추가한다(겹치는 항목은 이 재실행으로 대체됨).
    const newEntryKeys = new Set(entries.map((entry) => entry.key));
    const newItems: BatchItemState[] = entries.map((entry) => ({
      entry,
      status: "waiting",
      stage: null,
      result: null,
      errorText: null,
      isRefreshing: false,
    }));
    setItems((previousItems) => {
      const preservedItems = previousItems.filter(
        (item) => isFinishedStatus(item.status) && !newEntryKeys.has(item.entry.key),
      );
      return [...preservedItems, ...newItems];
    });
    setRunning(true);

    // 순차 for-await 실행 — 동시 실행 금지(네이버 429 방어). 한 번에 폴링 1개만 유지한다.
    for (const entry of entries) {
      if (runIdRef.current !== runId) {
        return; // 취소·재시작으로 무효화됨.
      }
      patchItem(runId, entry.key, {
        status: "running",
        stage: null,
        errorText: null,
      });

      const outcome = await runAnalysisToCompletion(token, entry.target, {
        isCancelled: () => runIdRef.current !== runId,
        onStage: (nextStage) => {
          patchItem(runId, entry.key, { status: "running", stage: nextStage });
        },
      });

      if (runIdRef.current !== runId) {
        return; // 취소됨.
      }

      if (outcome.kind === "cancelled") {
        return;
      }
      if (outcome.kind === "unauthorized") {
        handleSessionExpired();
        return;
      }
      if (outcome.kind === "done") {
        patchItem(runId, entry.key, {
          status: "done",
          result: outcome.result,
          stage: null,
        });
        continue;
      }
      if (outcome.kind === "timeout") {
        patchItem(runId, entry.key, { status: "timeout", stage: null });
        continue;
      }

      // outcome.kind === "error"
      if (outcome.status === 429) {
        // 일일 상한 도달 — 현재 항목과 남은 대기 항목을 모두 같은 사유로 종료한다
        // (이어지는 항목도 어차피 전부 429이므로 조기 중단한다).
        setItems((previousItems) => {
          if (runIdRef.current !== runId) {
            return previousItems;
          }
          return previousItems.map((item) =>
            item.entry.key === entry.key || item.status === "waiting"
              ? {
                  ...item,
                  status: "error",
                  errorText: DAILY_LIMIT_MESSAGE,
                  stage: null,
                }
              : item,
          );
        });
        setRunning(false);
        return;
      }

      // 그 밖의 오류·타임아웃은 표시만 하고 다음 항목으로 계속 진행한다.
      patchItem(runId, entry.key, {
        status: "error",
        errorText: outcome.errorText,
        stage: null,
      });
    }

    if (runIdRef.current !== runId) {
      return;
    }
    setRunning(false);
  }

  async function executeRefresh(key: string) {
    const targetItem = items.find((item) => item.entry.key === key);
    if (!targetItem) {
      return;
    }
    const runId = runIdRef.current + 1;
    runIdRef.current = runId;

    // 갱신은 기존 결과 카드를 유지한 채 버튼만 잠근다(useAnalysis 갱신 관례).
    patchItem(runId, key, { isRefreshing: true, errorText: null });

    const outcome = await runAnalysisToCompletion(token, targetItem.entry.target, {
      forceRefresh: true,
      isCancelled: () => runIdRef.current !== runId,
    });

    if (runIdRef.current !== runId) {
      return; // 더 최신 실행이 시작됨.
    }

    if (outcome.kind === "cancelled") {
      return;
    }
    if (outcome.kind === "unauthorized") {
      patchItem(runId, key, { isRefreshing: false });
      handleSessionExpired();
      return;
    }
    if (outcome.kind === "done") {
      patchItem(runId, key, {
        status: "done",
        result: outcome.result,
        stage: null,
        isRefreshing: false,
      });
      return;
    }
    if (outcome.kind === "timeout") {
      patchItem(runId, key, {
        status: "timeout",
        stage: null,
        isRefreshing: false,
      });
      return;
    }

    // outcome.kind === "error"
    const errorText =
      outcome.status === 429 ? DAILY_LIMIT_MESSAGE : outcome.errorText;
    patchItem(runId, key, {
      status: "error",
      errorText,
      stage: null,
      isRefreshing: false,
    });
  }

  function startBatch(entries: BatchEntry[]) {
    if (entries.length === 0) {
      return;
    }
    void executeBatch(entries);
  }

  function refreshItem(key: string) {
    if (isRunningRef.current) {
      return; // 배치 실행 중에는 개별 갱신을 무시한다.
    }
    void executeRefresh(key);
  }

  function cancel() {
    runIdRef.current += 1; // 진행 중 폴링을 무효화한다.
    setRunning(false);
    // 완료된 항목의 결과는 유지하고, 대기·실행 중 항목은 목록에서 제거한다.
    setItems((previousItems) =>
      previousItems.filter((item) => isFinishedStatus(item.status)),
    );
  }

  function reset() {
    runIdRef.current += 1; // 진행 중 폴링을 무효화한다.
    setRunning(false);
    setItems([]); // 항목 전체를 비운다(새 검색 시 사용).
  }

  const completedCount = items.filter((item) =>
    isFinishedStatus(item.status),
  ).length;

  return {
    items,
    isRunning,
    completedCount,
    startBatch,
    refreshItem,
    cancel,
    reset,
  };
}
