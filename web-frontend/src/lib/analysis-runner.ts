/**
 * 분석 요청 → 결과 폴링 → 완료까지를 담은 순수 비동기 실행기.
 *
 * useAnalysis 훅에서 React 상태와 얽혀 있던 요청·폴링 본체를 분리해,
 * 이후 배치 분석(다중 URL·상위 N곳)에서 재사용할 수 있게 한다.
 * 이 모듈은 React에 의존하지 않으며, 진행 상황은 콜백으로만 통지한다.
 */

import { ApiError, fetchResult, requestAnalyze } from "./api";
import type { AnalysisResult, AnalysisStage, AnalysisTarget } from "./types";

// 초기 폴링 백오프(ms) — 1회차 전 250ms, 2회차 전 750ms로 앞당겨
// 캐시 히트 시 첫 조회를 빠르게 한다. 3회차부터는 POLL_INTERVAL_MS로 정속.
const POLL_DELAYS_MS = [250, 750];
/** 정속 폴링 간격(ms). 백오프 소진 후 매회 적용. */
const POLL_INTERVAL_MS = 1500;
// 최대 시도 횟수 — 총 폴링 예산 250 + 750 + 39×1500 = 59,500ms(약 59.5초, 현행 60초 유지).
const MAX_POLL_ATTEMPTS = 41;

/** 실행 결과의 판별 유니온. 호출부가 kind로 분기해 상태를 반영한다. */
export type RunnerOutcome =
  | { kind: "done"; result: AnalysisResult }
  | { kind: "error"; errorText: string }
  | { kind: "timeout" }
  | { kind: "unauthorized" }
  | { kind: "cancelled" };

/** runAnalysisToCompletion 의 선택 옵션. */
interface RunnerOptions {
  /** 강제 재분석(캐시 무시) 여부. */
  forceRefresh?: boolean;
  /** 폴링 응답마다 현재 진행 단계를 통지한다. */
  onStage?: (stage: AnalysisStage | null) => void;
  /** true를 반환하면 즉시 { kind: "cancelled" }로 중단한다. */
  isCancelled?: () => boolean;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * 대상 하나를 분석 요청하고 결과가 나올 때까지 폴링한다.
 * 매 대기 후와 매 응답 후 isCancelled()를 확인해 취소에 즉시 반응한다.
 */
export async function runAnalysisToCompletion(
  token: string,
  target: AnalysisTarget,
  options?: RunnerOptions,
): Promise<RunnerOutcome> {
  const forceRefresh = options?.forceRefresh ?? false;
  const isCancelled = options?.isCancelled ?? (() => false);
  const onStage = options?.onStage;

  if (isCancelled()) {
    return { kind: "cancelled" };
  }

  let jobId: string;
  try {
    jobId = await requestAnalyze(token, target, forceRefresh);
  } catch (error) {
    if (isCancelled()) {
      return { kind: "cancelled" };
    }
    if (error instanceof ApiError && error.isUnauthorized) {
      return { kind: "unauthorized" };
    }
    return {
      kind: "error",
      errorText:
        error instanceof ApiError
          ? error.message
          : "분석 요청에 실패했어요. 잠시 후 다시 시도해 주세요.",
    };
  }

  if (isCancelled()) {
    return { kind: "cancelled" };
  }

  for (let attempt = 0; attempt < MAX_POLL_ATTEMPTS; attempt += 1) {
    // 앞 2회는 백오프(250ms·750ms), 이후는 정속(1500ms)으로 대기한다.
    const currentDelayMs = POLL_DELAYS_MS[attempt] ?? POLL_INTERVAL_MS;
    await delay(currentDelayMs);
    if (isCancelled()) {
      return { kind: "cancelled" };
    }

    let latest: AnalysisResult;
    try {
      latest = await fetchResult(token, jobId);
    } catch (error) {
      if (isCancelled()) {
        return { kind: "cancelled" };
      }
      if (error instanceof ApiError && error.isUnauthorized) {
        return { kind: "unauthorized" };
      }
      // 404 를 포함한 일시 오류는 폴링을 이어간다 (job 준비 지연 대비).
      if (error instanceof ApiError && error.status === 404) {
        continue;
      }
      return {
        kind: "error",
        errorText:
          error instanceof ApiError
            ? error.message
            : "결과 조회 중 오류가 발생했어요.",
      };
    }

    if (isCancelled()) {
      return { kind: "cancelled" };
    }

    if (latest.status === "done") {
      return { kind: "done", result: latest };
    }
    if (latest.status === "error") {
      return {
        kind: "error",
        errorText: latest.errorMessage ?? "분석에 실패했어요.",
      };
    }
    // status === "processing" → 진행 단계를 통지하고 계속 폴링한다.
    onStage?.(latest.stage);
  }

  return { kind: "timeout" };
}
