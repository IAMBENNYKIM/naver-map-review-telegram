"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Search, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { AnalysisStatusPanel } from "@/components/AnalysisStatusPanel";
import type { AnalysisPhase } from "@/hooks/useAnalysis";
import { useBatchAnalysis, type BatchItemState } from "@/hooks/useBatchAnalysis";
import { extractNaverUrls } from "@/lib/naver-url";

/** 붙여넣기 예시 placeholder (네이버 앱 공유 텍스트 형태). */
const PASTE_PLACEHOLDER = [
  "[네이버지도]",
  "가게 이름",
  "서울특별시 ...",
  "https://naver.me/XXXXXXXX",
].join("\n");

/** 한 번에 순서대로 분석하는 링크의 최대 개수. */
const MAX_BATCH_URLS = 5;

const analyzeSchema = z.object({
  // 필드 값은 URL 뿐 아니라 공유 텍스트 전체를 담을 수 있고, 여러 링크가 섞여도 된다.
  naverUrl: z
    .string()
    .trim()
    .min(1, "네이버 지도 주소를 입력해 주세요.")
    .refine(
      (value) => extractNaverUrls(value).length > 0,
      "네이버 지도 링크를 찾지 못했어요. 공유한 장소 정보를 그대로 붙여넣어 주세요.",
    ),
});

type AnalyzeFormValues = z.infer<typeof analyzeSchema>;

interface AnalyzeViewProps {
  token: string;
  /** 공유(share_target) 등으로 프리필할 초기 URL. */
  initialUrl?: string;
  /** 세션 만료(401) 시 호출 — 상위가 토큰을 지우고 게이트로 돌린다. */
  onSessionExpired: () => void;
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

/** 긴 URL 을 항목 보조 라벨용으로 축약한다(호스트+경로 앞부분, 최대 30자). */
function toShortLabel(url: string): string {
  let display = url;
  try {
    const parsed = new URL(url);
    const pathAndQuery = parsed.pathname + parsed.search;
    display = parsed.host + (pathAndQuery === "/" ? "" : pathAndQuery);
  } catch {
    // URL 파싱 실패 시 원문을 그대로 축약한다.
  }
  return display.length > 30 ? `${display.slice(0, 30)}…` : display;
}

/**
 * URL 붙여넣기 화면: 공유 텍스트에서 네이버 링크를 전부 뽑아
 * 순서대로 이어서 분석하고(최대 5개), 각 링크의 결과를 항목별로 표시한다.
 */
export function AnalyzeView({
  token,
  initialUrl,
  onSessionExpired,
}: AnalyzeViewProps) {
  // 5개 초과 입력 시 앞 5개만 처리한다는 안내(에러가 아니라 진행 안내).
  const [batchNotice, setBatchNotice] = useState<string | null>(null);

  const { items, isRunning, completedCount, startBatch, refreshItem, cancel, reset } =
    useBatchAnalysis({ token, onSessionExpired });

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<AnalyzeFormValues>({
    resolver: zodResolver(analyzeSchema),
    defaultValues: { naverUrl: initialUrl ?? "" },
  });

  // 2건 이상 배치일 때만 진행 헤더·항목 라벨·안내 문구를 노출한다(단건 UX 보존).
  const isMultiBatch = items.length >= 2;

  function onSubmit(values: AnalyzeFormValues) {
    const allUrls = extractNaverUrls(values.naverUrl);
    if (allUrls.length === 0) {
      // 스키마 검증이 이미 막지만 타입 좁히기를 위한 방어 코드.
      return;
    }

    let urlsToAnalyze = allUrls;
    if (allUrls.length > MAX_BATCH_URLS) {
      urlsToAnalyze = allUrls.slice(0, MAX_BATCH_URLS);
      setBatchNotice(
        `링크가 ${allUrls.length}개예요. 처음 ${MAX_BATCH_URLS}개만 순서대로 분석해요.`,
      );
    } else {
      setBatchNotice(null);
    }

    // 새 제출은 새 목록으로 본다 — 병합 잔여를 남기지 않도록 먼저 비운다.
    reset();
    startBatch(
      urlsToAnalyze.map((url) => ({
        key: url,
        label: url,
        target: { naverUrl: url },
      })),
    );
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
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
            <div className="space-y-1.5">
              <Label htmlFor="naver-url">
                복사한 장소 정보를 여기에 붙여넣으세요
              </Label>
              <Textarea
                id="naver-url"
                rows={4}
                placeholder={PASTE_PLACEHOLDER}
                aria-invalid={Boolean(errors.naverUrl)}
                disabled={isRunning}
                {...register("naverUrl")}
              />
              {errors.naverUrl ? (
                <p className="text-xs text-rose-500">{errors.naverUrl.message}</p>
              ) : (
                <p className="px-1 text-xs text-muted">
                  링크를 여러 개 붙여넣으면 순서대로 이어서 분석해요(최대{" "}
                  {MAX_BATCH_URLS}개).
                </p>
              )}
            </div>

            <Button type="submit" className="w-full" disabled={isRunning}>
              {isRunning ? (
                <>
                  <Spinner className="h-4 w-4" />
                  분석 중…
                </>
              ) : (
                <>
                  <Search className="h-4 w-4" aria-hidden="true" />
                  리뷰 요약하기
                </>
              )}
            </Button>
          </form>
        </CardContent>
      </Card>

      {/* 5개 초과 절단 안내 */}
      {batchNotice ? (
        <p className="px-1 text-sm text-muted">{batchNotice}</p>
      ) : null}

      {/* 여러 건 진행 제어 — 진행 헤더 + 취소 (단건은 생략) */}
      {isMultiBatch && isRunning ? (
        <div className="space-y-1.5">
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
          <p className="px-1 text-xs text-muted">
            여러 링크를 순서대로 이어서 분석해요. 한 곳당 최대 1분까지 걸릴 수
            있어요.
          </p>
        </div>
      ) : null}

      {/* 링크별 분석 결과 목록 */}
      {items.length > 0 ? (
        <ul className="space-y-4">
          {items.map((item) => (
            <li key={item.entry.key} className="space-y-1">
              {isMultiBatch ? (
                <p className="truncate px-1 text-xs text-muted">
                  {toShortLabel(item.entry.label)}
                </p>
              ) : null}
              {renderItemStatus(item)}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
