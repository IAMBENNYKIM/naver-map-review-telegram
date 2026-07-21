"use client";

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { AnalysisStatusPanel } from "@/components/AnalysisStatusPanel";
import { useAnalysis } from "@/hooks/useAnalysis";
import { extractNaverUrl } from "@/lib/naver-url";

/** 붙여넣기 예시 placeholder (네이버 앱 공유 텍스트 형태). */
const PASTE_PLACEHOLDER = [
  "[네이버지도]",
  "가게 이름",
  "서울특별시 ...",
  "https://naver.me/XXXXXXXX",
].join("\n");

const analyzeSchema = z.object({
  // 필드 값은 URL 뿐 아니라 공유 텍스트 전체를 담을 수 있다.
  naverUrl: z
    .string()
    .trim()
    .min(1, "네이버 지도 주소를 입력해 주세요.")
    .refine(
      (value) => extractNaverUrl(value) !== null,
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

/** URL 붙여넣기 화면: 공유 텍스트 입력 → 분석 요청 → 결과 폴링 → 카드 표시. */
export function AnalyzeView({
  token,
  initialUrl,
  onSessionExpired,
}: AnalyzeViewProps) {
  const { phase, result, errorText, stage, isRefreshing, runAnalysis, refresh } =
    useAnalysis({ token, onSessionExpired });

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<AnalyzeFormValues>({
    resolver: zodResolver(analyzeSchema),
    defaultValues: { naverUrl: initialUrl ?? "" },
  });

  const isBusy = phase === "submitting" || phase === "polling";

  function onSubmit(values: AnalyzeFormValues) {
    const naverUrl = extractNaverUrl(values.naverUrl);
    if (!naverUrl) {
      // 스키마 검증이 이미 막지만 타입 좁히기를 위한 방어 코드.
      return;
    }
    runAnalysis({ naverUrl });
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
                disabled={isBusy}
                {...register("naverUrl")}
              />
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

      {/* 상태별 하단 영역 (폴링·타임아웃·오류·결과) */}
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
