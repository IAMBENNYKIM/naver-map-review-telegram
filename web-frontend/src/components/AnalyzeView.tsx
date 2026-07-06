"use client";

import { useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Link2, LogOut, Search, AlertCircle, Clock } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { ResultCard } from "@/components/ResultCard";
import { ApiError, fetchResult, requestAnalyze } from "@/lib/api";
import { looksLikeNaverUrl } from "@/lib/naver-url";
import type { AnalysisResult } from "@/lib/types";

/** 폴링 간격(ms)과 최대 시도 횟수. 약 60초 후 타임아웃. */
const POLL_INTERVAL_MS = 1500;
const MAX_POLL_ATTEMPTS = 40;

const analyzeSchema = z.object({
  naverUrl: z
    .string()
    .trim()
    .min(1, "네이버 지도 주소를 입력해 주세요.")
    .refine(looksLikeNaverUrl, "네이버 지도 주소(naver.me 등)로 보이지 않아요."),
});

type AnalyzeFormValues = z.infer<typeof analyzeSchema>;

type Phase = "idle" | "submitting" | "polling" | "done" | "error" | "timeout";

interface AnalyzeViewProps {
  token: string;
  /** 공유(share_target) 등으로 프리필할 초기 URL. */
  initialUrl?: string;
  /** 로그아웃(토큰 삭제) 요청. */
  onLogout: () => void;
  /** 세션 만료(401) 시 호출 — 상위가 토큰을 지우고 게이트로 돌린다. */
  onSessionExpired: () => void;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** 메인 분석 화면: URL 입력 → 분석 요청 → 결과 폴링 → 카드 표시. */
export function AnalyzeView({
  token,
  initialUrl,
  onLogout,
  onSessionExpired,
}: AnalyzeViewProps) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [errorText, setErrorText] = useState<string | null>(null);

  // 실행 세대 번호 — 새 요청/언마운트 시 이전 폴링 루프를 무효화한다.
  const runIdRef = useRef(0);

  useEffect(() => {
    return () => {
      // 언마운트 시 진행 중 폴링을 중단시킨다.
      runIdRef.current += 1;
    };
  }, []);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<AnalyzeFormValues>({
    resolver: zodResolver(analyzeSchema),
    defaultValues: { naverUrl: initialUrl ?? "" },
  });

  const isBusy = phase === "submitting" || phase === "polling";

  function handleSessionExpired() {
    runIdRef.current += 1;
    onSessionExpired();
  }

  async function onSubmit(values: AnalyzeFormValues) {
    const runId = runIdRef.current + 1;
    runIdRef.current = runId;

    setResult(null);
    setErrorText(null);
    setPhase("submitting");

    let jobId: string;
    try {
      jobId = await requestAnalyze(token, values.naverUrl.trim());
    } catch (error) {
      if (error instanceof ApiError && error.isUnauthorized) {
        handleSessionExpired();
        return;
      }
      setErrorText(
        error instanceof ApiError
          ? error.message
          : "분석 요청에 실패했어요. 잠시 후 다시 시도해 주세요.",
      );
      setPhase("error");
      return;
    }

    if (runIdRef.current !== runId) {
      return; // 더 최신 요청이 시작됨.
    }
    setPhase("polling");

    for (let attempt = 0; attempt < MAX_POLL_ATTEMPTS; attempt += 1) {
      await delay(POLL_INTERVAL_MS);
      if (runIdRef.current !== runId) {
        return; // 취소됨.
      }

      let latest: AnalysisResult;
      try {
        latest = await fetchResult(token, jobId);
      } catch (error) {
        if (error instanceof ApiError && error.isUnauthorized) {
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
        return;
      }

      if (runIdRef.current !== runId) {
        return;
      }

      if (latest.status === "done") {
        setResult(latest);
        setPhase("done");
        return;
      }
      if (latest.status === "error") {
        setErrorText(latest.errorMessage ?? "분석에 실패했어요.");
        setPhase("error");
        return;
      }
      // status === "processing" → 계속 폴링.
    }

    if (runIdRef.current === runId) {
      setPhase("timeout");
    }
  }

  return (
    <div className="mx-auto w-full max-w-2xl space-y-6 px-4 py-8">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold">리뷰 요약</h1>
          <p className="text-sm text-muted">
            네이버 지도 공유 주소를 넣으면 리뷰를 요약해 드려요.
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={onLogout} aria-label="로그아웃">
          <LogOut className="h-4 w-4" aria-hidden="true" />
          로그아웃
        </Button>
      </header>

      <Card>
        <CardContent>
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
            <div className="space-y-1.5">
              <Label htmlFor="naver-url">네이버 지도 주소</Label>
              <div className="relative">
                <Link2
                  className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted"
                  aria-hidden="true"
                />
                <Input
                  id="naver-url"
                  inputMode="url"
                  autoComplete="url"
                  placeholder="https://naver.me/..."
                  className="pl-9"
                  aria-invalid={Boolean(errors.naverUrl)}
                  disabled={isBusy}
                  {...register("naverUrl")}
                />
              </div>
              {errors.naverUrl ? (
                <p className="text-xs text-rose-500">{errors.naverUrl.message}</p>
              ) : null}
            </div>

            <Button type="submit" className="w-full" disabled={isBusy}>
              {isBusy ? (
                <>
                  <Spinner className="h-4 w-4" />
                  {phase === "submitting" ? "요청 중..." : "요약 생성 중..."}
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

      {/* 상태별 하단 영역 */}
      {phase === "polling" ? (
        <Card>
          <CardContent className="flex items-center gap-3 text-sm text-muted">
            <Spinner className="h-5 w-5 text-accent" />
            <span>
              리뷰를 수집하고 요약하는 중이에요. 최대 1분 정도 걸릴 수 있어요.
            </span>
          </CardContent>
        </Card>
      ) : null}

      {phase === "timeout" ? (
        <Card>
          <CardContent className="flex items-start gap-3 text-sm">
            <Clock className="mt-0.5 h-5 w-5 shrink-0 text-amber-500" aria-hidden="true" />
            <span>
              시간이 조금 오래 걸리고 있어요. 잠시 후 같은 주소로 다시 시도해 주세요.
            </span>
          </CardContent>
        </Card>
      ) : null}

      {phase === "error" && errorText ? (
        <Card>
          <CardContent className="flex items-start gap-3 text-sm text-rose-600 dark:text-rose-400">
            <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
            <span role="alert">{errorText}</span>
          </CardContent>
        </Card>
      ) : null}

      {phase === "done" && result ? <ResultCard result={result} /> : null}
    </div>
  );
}
