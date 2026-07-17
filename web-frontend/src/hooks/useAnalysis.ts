"use client";

import { useEffect, useRef, useState } from "react";

import { ApiError, fetchResult, requestAnalyze } from "@/lib/api";
import type { AnalysisResult, AnalysisTarget } from "@/lib/types";

// 초기 폴링 백오프(ms) — 1회차 전 250ms, 2회차 전 750ms로 앞당겨
// 캐시 히트 시 첫 조회를 빠르게 한다. 3회차부터는 POLL_INTERVAL_MS로 정속.
const POLL_DELAYS_MS = [250, 750];
/** 정속 폴링 간격(ms). 백오프 소진 후 매회 적용. */
const POLL_INTERVAL_MS = 1500;
// 최대 시도 횟수 — 총 폴링 예산 250 + 750 + 39×1500 = 59,500ms(약 59.5초, 현행 60초 유지).
const MAX_POLL_ATTEMPTS = 41;

/** 분석 실행 단계. */
export type AnalysisPhase =
  | "idle"
  | "submitting"
  | "polling"
  | "done"
  | "error"
  | "timeout";

interface UseAnalysisArgs {
  token: string;
  /** 세션 만료(401) 시 호출 — 상위가 토큰을 지우고 게이트로 돌린다. */
  onSessionExpired: () => void;
}

interface UseAnalysisApi {
  phase: AnalysisPhase;
  result: AnalysisResult | null;
  errorText: string | null;
  /** 갱신(강제 재분석) 진행 여부. */
  isRefreshing: boolean;
  /** 대상(네이버 URL 또는 place_id)으로 분석을 실행한다. */
  runAnalysis: (
    target: AnalysisTarget,
    options?: { forceRefresh?: boolean },
  ) => void;
  /** 마지막 대상으로 강제 재분석(갱신)한다. 대상이 없으면 무시. */
  refresh: () => void;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * 분석 요청 → 결과 폴링 → 상태 반영 로직을 담은 훅.
 * URL 폼과 검색 후보 선택이 공통으로 사용한다 (동작은 종전과 동일).
 */
export function useAnalysis({
  token,
  onSessionExpired,
}: UseAnalysisArgs): UseAnalysisApi {
  const [phase, setPhase] = useState<AnalysisPhase>("idle");
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [errorText, setErrorText] = useState<string | null>(null);
  // 갱신(강제 재분석) 진행 여부 — 결과 카드의 갱신 버튼을 잠근다.
  const [isRefreshing, setIsRefreshing] = useState(false);

  // 실행 세대 번호 — 새 요청/언마운트 시 이전 폴링 루프를 무효화한다.
  const runIdRef = useRef(0);
  // 현재 결과의 원본 대상 — 갱신 시 재사용한다.
  const lastTargetRef = useRef<AnalysisTarget | null>(null);

  useEffect(() => {
    return () => {
      // 언마운트 시 진행 중 폴링을 중단시킨다.
      runIdRef.current += 1;
    };
  }, []);

  function handleSessionExpired() {
    runIdRef.current += 1;
    onSessionExpired();
  }

  /**
   * 분석 요청 → 폴링 → 결과 반영을 수행하는 공용 실행기.
   * 폼 제출과 결과 카드의 "갱신하기"가 함께 사용한다.
   */
  async function execute(
    target: AnalysisTarget,
    options?: { forceRefresh?: boolean },
  ) {
    const isRefresh = options?.forceRefresh ?? false;
    const runId = runIdRef.current + 1;
    runIdRef.current = runId;
    lastTargetRef.current = target;

    setErrorText(null);
    if (isRefresh) {
      // 갱신은 기존 결과 카드를 유지한 채 버튼만 잠근다.
      setIsRefreshing(true);
    } else {
      setResult(null);
      setIsRefreshing(false);
      setPhase("submitting");
    }

    let jobId: string;
    try {
      jobId = await requestAnalyze(token, target, isRefresh);
    } catch (error) {
      if (runIdRef.current !== runId) {
        return; // 더 최신 요청이 시작됨.
      }
      if (error instanceof ApiError && error.isUnauthorized) {
        setIsRefreshing(false);
        handleSessionExpired();
        return;
      }
      setErrorText(
        error instanceof ApiError
          ? error.message
          : "분석 요청에 실패했어요. 잠시 후 다시 시도해 주세요.",
      );
      setPhase("error");
      setIsRefreshing(false);
      return;
    }

    if (runIdRef.current !== runId) {
      return; // 더 최신 요청이 시작됨.
    }
    if (!isRefresh) {
      setPhase("polling");
    }

    for (let attempt = 0; attempt < MAX_POLL_ATTEMPTS; attempt += 1) {
      // 앞 2회는 백오프(250ms·750ms), 이후는 정속(1500ms)으로 대기한다.
      const currentDelayMs = POLL_DELAYS_MS[attempt] ?? POLL_INTERVAL_MS;
      await delay(currentDelayMs);
      if (runIdRef.current !== runId) {
        return; // 취소됨.
      }

      let latest: AnalysisResult;
      try {
        latest = await fetchResult(token, jobId);
      } catch (error) {
        if (runIdRef.current !== runId) {
          return;
        }
        if (error instanceof ApiError && error.isUnauthorized) {
          setIsRefreshing(false);
          handleSessionExpired();
          return;
        }
        // 404 를 포함한 일시 오류는 폴링을 이어간다 (job 준비 지연 대비).
        if (error instanceof ApiError && error.status === 404) {
          continue;
        }
        setErrorText(
          error instanceof ApiError
            ? error.message
            : "결과 조회 중 오류가 발생했어요.",
        );
        setPhase("error");
        setIsRefreshing(false);
        return;
      }

      if (runIdRef.current !== runId) {
        return;
      }

      if (latest.status === "done") {
        setResult(latest);
        setPhase("done");
        setIsRefreshing(false);
        return;
      }
      if (latest.status === "error") {
        setErrorText(latest.errorMessage ?? "분석에 실패했어요.");
        setPhase("error");
        setIsRefreshing(false);
        return;
      }
      // status === "processing" → 계속 폴링.
    }

    if (runIdRef.current === runId) {
      setPhase("timeout");
      setIsRefreshing(false);
    }
  }

  function runAnalysis(
    target: AnalysisTarget,
    options?: { forceRefresh?: boolean },
  ) {
    void execute(target, options);
  }

  function refresh() {
    if (!lastTargetRef.current) {
      return;
    }
    void execute(lastTargetRef.current, { forceRefresh: true });
  }

  return { phase, result, errorText, isRefreshing, runAnalysis, refresh };
}
