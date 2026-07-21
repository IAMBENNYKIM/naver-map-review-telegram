"use client";

import { useEffect, useRef, useState } from "react";

import { runAnalysisToCompletion } from "@/lib/analysis-runner";
import type { AnalysisResult, AnalysisStage, AnalysisTarget } from "@/lib/types";

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
  /** 폴링 중 진행 단계. processing 세부 단계이며 그 외에는 null. */
  stage: AnalysisStage | null;
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

/**
 * 분석 요청 → 결과 폴링 → 상태 반영을 담은 훅.
 * 요청·폴링 본체는 순수 실행기(runAnalysisToCompletion)에 위임하고,
 * 이 훅은 React 상태 반영과 세대 무효화만 담당한다 (동작은 종전과 동일).
 */
export function useAnalysis({
  token,
  onSessionExpired,
}: UseAnalysisArgs): UseAnalysisApi {
  const [phase, setPhase] = useState<AnalysisPhase>("idle");
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [errorText, setErrorText] = useState<string | null>(null);
  // 폴링 중 진행 단계 — 상태 패널의 단계 체크리스트에 쓰인다.
  const [stage, setStage] = useState<AnalysisStage | null>(null);
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
    setStage(null);
    if (isRefresh) {
      // 갱신은 기존 결과 카드를 유지한 채 버튼만 잠근다.
      setIsRefreshing(true);
    } else {
      setResult(null);
      setIsRefreshing(false);
      setPhase("submitting");
    }

    const outcome = await runAnalysisToCompletion(token, target, {
      forceRefresh: isRefresh,
      isCancelled: () => runIdRef.current !== runId,
      onStage: (nextStage) => {
        if (runIdRef.current !== runId) {
          return; // 더 최신 요청이 시작됨.
        }
        // 갱신은 기존 done 카드를 유지하므로 phase를 바꾸지 않는다.
        if (!isRefresh) {
          setPhase("polling");
        }
        setStage(nextStage);
      },
    });

    if (runIdRef.current !== runId) {
      return; // 더 최신 요청이 시작됨.
    }

    switch (outcome.kind) {
      case "cancelled":
        return;
      case "unauthorized":
        setIsRefreshing(false);
        handleSessionExpired();
        return;
      case "done":
        setResult(outcome.result);
        setStage(null);
        setPhase("done");
        setIsRefreshing(false);
        return;
      case "error":
        setErrorText(outcome.errorText);
        setStage(null);
        setPhase("error");
        setIsRefreshing(false);
        return;
      case "timeout":
        setStage(null);
        setPhase("timeout");
        setIsRefreshing(false);
        return;
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

  return {
    phase,
    result,
    errorText,
    stage,
    isRefreshing,
    runAnalysis,
    refresh,
  };
}
