"use client";

import { AlertCircle, Check, Clock } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { ResultCard } from "@/components/ResultCard";
import type { AnalysisPhase } from "@/hooks/useAnalysis";
import type { AnalysisResult, AnalysisStage } from "@/lib/types";
import { cn } from "@/lib/utils";

/** 진행 단계 순서와 한국어 라벨. 체크리스트는 이 순서대로 표시한다. */
const STAGE_STEPS: { stage: AnalysisStage; label: string }[] = [
  { stage: "cache_check", label: "캐시 확인" },
  { stage: "collecting", label: "리뷰 수집" },
  { stage: "summarizing", label: "요약 생성" },
];

interface AnalysisStatusPanelProps {
  phase: AnalysisPhase;
  /** 폴링 중 단계 체크리스트에 쓰는 현재 단계. null이면 범용 문구로 폴백. */
  stage: AnalysisStage | null;
  result: AnalysisResult | null;
  errorText: string | null;
  isRefreshing: boolean;
  /** 결과 카드의 갱신(강제 재분석) 버튼 콜백. */
  onRefresh: () => void;
}

/** 폴링 중 표시하는 단계별 진행 체크리스트. */
function StageChecklist({ stage }: { stage: AnalysisStage }) {
  const currentIndex = STAGE_STEPS.findIndex((step) => step.stage === stage);

  return (
    <ul className="space-y-3" aria-label="분석 진행 단계">
      {STAGE_STEPS.map((step, index) => {
        const isCompleted = index < currentIndex;
        const isCurrent = index === currentIndex;

        return (
          <li
            key={step.stage}
            className={cn(
              "flex items-center gap-3 text-sm",
              isCurrent
                ? "font-medium text-foreground"
                : isCompleted
                  ? "text-foreground"
                  : "text-muted opacity-60",
            )}
          >
            <span
              className="flex h-5 w-5 shrink-0 items-center justify-center"
              aria-hidden="true"
            >
              {isCompleted ? (
                <Check className="h-4 w-4 text-emerald-500" />
              ) : isCurrent ? (
                <Spinner className="h-4 w-4 text-accent" />
              ) : (
                <span className="h-2 w-2 rounded-full bg-border" />
              )}
            </span>
            <span>{step.label}</span>
          </li>
        );
      })}
    </ul>
  );
}

/**
 * 분석 상태(폴링·타임아웃·오류·완료)를 하나로 통합해 렌더하는 공용 패널.
 * URL 붙여넣기 화면과 검색 화면이 공통으로 사용한다.
 */
export function AnalysisStatusPanel({
  phase,
  stage,
  result,
  errorText,
  isRefreshing,
  onRefresh,
}: AnalysisStatusPanelProps) {
  if (phase === "polling") {
    return (
      <Card>
        <CardContent>
          {stage ? (
            <StageChecklist stage={stage} />
          ) : (
            <div className="flex items-center gap-3 text-sm text-muted">
              <Spinner className="h-5 w-5 text-accent" />
              <span>
                리뷰를 수집하고 요약하는 중이에요. 최대 1분 정도 걸릴 수 있어요.
              </span>
            </div>
          )}
        </CardContent>
      </Card>
    );
  }

  if (phase === "timeout") {
    return (
      <Card>
        <CardContent className="flex items-start gap-3 text-sm">
          <Clock
            className="mt-0.5 h-5 w-5 shrink-0 text-amber-500"
            aria-hidden="true"
          />
          <span>
            시간이 조금 오래 걸리고 있어요. 잠시 후 다시 시도해 주세요.
          </span>
        </CardContent>
      </Card>
    );
  }

  if (phase === "error" && errorText) {
    return (
      <Card>
        <CardContent className="flex items-start gap-3 text-sm text-rose-600 dark:text-rose-400">
          <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
          <span role="alert">{errorText}</span>
        </CardContent>
      </Card>
    );
  }

  if (phase === "done" && result) {
    return (
      <ResultCard
        result={result}
        onRefresh={onRefresh}
        isRefreshing={isRefreshing}
      />
    );
  }

  return null;
}
