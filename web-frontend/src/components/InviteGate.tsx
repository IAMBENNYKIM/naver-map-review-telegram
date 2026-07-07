"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  Hash,
  Info,
  KeyRound,
  ListOrdered,
  Search,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { ApiError, requestInvite } from "@/lib/api";
import { saveSessionToken } from "@/lib/session";

const inviteSchema = z.object({
  code: z.string().trim().min(1, "초대코드를 입력해 주세요."),
});

type InviteFormValues = z.infer<typeof inviteSchema>;

interface InviteGateProps {
  /** 인증 성공 시 발급된 토큰을 상위로 전달한다. */
  onAuthenticated: (token: string) => void;
}

/** 초대코드 입력 게이트. 성공 시 토큰을 저장하고 상위에 알린다. */
export function InviteGate({ onAuthenticated }: InviteGateProps) {
  const [submitError, setSubmitError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<InviteFormValues>({
    resolver: zodResolver(inviteSchema),
    defaultValues: { code: "" },
  });

  async function onSubmit(values: InviteFormValues) {
    setSubmitError(null);
    try {
      const token = await requestInvite(values.code.trim());
      saveSessionToken(token);
      onAuthenticated(token);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setSubmitError("초대코드가 올바르지 않아요.");
      } else if (error instanceof ApiError) {
        setSubmitError(error.message);
      } else {
        setSubmitError("알 수 없는 오류가 발생했어요.");
      }
    }
  }

  return (
    <div className="flex min-h-full flex-1 flex-col items-center justify-center gap-6 px-4 py-12">
      <Card className="w-full max-w-sm">
        <CardContent className="space-y-6">
          <div className="space-y-2 text-center">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-accent/15">
              <KeyRound className="h-6 w-6 text-accent" aria-hidden="true" />
            </div>
            <h1 className="text-lg font-semibold">초대코드로 시작하기</h1>
            <p className="text-sm text-muted">
              전달받은 초대코드를 입력하면 리뷰 요약을 사용할 수 있어요.
            </p>
          </div>

          <form
            onSubmit={handleSubmit(onSubmit)}
            className="space-y-4"
            noValidate
          >
            <div className="space-y-1.5">
              <Label htmlFor="invite-code">초대코드</Label>
              <Input
                id="invite-code"
                autoComplete="one-time-code"
                placeholder="예: FRIEND-2026"
                aria-invalid={Boolean(errors.code)}
                {...register("code")}
              />
              {errors.code ? (
                <p className="text-xs text-rose-500">{errors.code.message}</p>
              ) : null}
            </div>

            {submitError ? (
              <p
                role="alert"
                className="rounded-lg bg-rose-500/10 px-3 py-2 text-sm text-rose-600 dark:text-rose-400"
              >
                {submitError}
              </p>
            ) : null}

            <Button type="submit" className="w-full" disabled={isSubmitting}>
              {isSubmitting ? (
                <>
                  <Spinner className="h-4 w-4" />
                  확인 중...
                </>
              ) : (
                "입장하기"
              )}
            </Button>
          </form>
        </CardContent>
      </Card>

      <HowItWorks />
    </div>
  );
}

/** 초대 게이트 하단의 작동 방식·신뢰 설명 (실측 확인된 사실만 사용). */
function HowItWorks() {
  const items = [
    {
      icon: Search,
      title: "무엇을 해주나요",
      body: "네이버 지도 장소의 공유 링크(또는 장소 정보 통째)를 붙여넣으면, 그 장소의 리뷰를 대신 읽고 요약해 드려요.",
    },
    {
      icon: ListOrdered,
      title: "어떤 리뷰를 읽나요",
      body: "네이버 '리뷰' 탭의 방문자 리뷰를 최신순(최근 방문 우선)으로 최대 50개까지 읽어요. 리뷰가 적으면 있는 만큼만, 내용이 빈 리뷰는 빼요. '사진/영상 리뷰만' 필터는 걸지 않아 전체 리뷰가 대상이에요.",
    },
    {
      icon: ShieldCheck,
      title: "개인정보는요",
      body: "리뷰어 닉네임 같은 식별 정보는 읽지도 저장하지도 않아요. 리뷰 본문·키워드 태그·방문일만 사용해요.",
    },
    {
      icon: Hash,
      title: "메뉴 'N회 언급' 숫자",
      body: "우리가 센 게 아니라, 네이버가 리뷰 탭 상단 '메뉴' 칩에 표시하는 숫자(예: 치킨 187 · 파닭 146)를 그대로 가져온 거예요.",
    },
    {
      icon: Sparkles,
      title: "요약은 어떻게 만드나요",
      body: "총평·장점·단점·주의사항은 위 최신순 리뷰 본문에서 반복 언급 위주로 AI(Claude)가 정리하고, 메뉴별 추천도(추천·호불호·비추천)는 리뷰 본문과 네이버 메뉴 언급 통계를 함께 근거로 판단해요.",
    },
  ];

  return (
    <Card className="w-full max-w-md">
      <CardContent className="space-y-5">
        <div className="flex items-center gap-2">
          <Info className="h-5 w-5 text-accent" aria-hidden="true" />
          <h2 className="text-base font-semibold">이 서비스는 이렇게 동작해요</h2>
        </div>

        <ul className="space-y-4">
          {items.map((item) => {
            const Icon = item.icon;
            return (
              <li key={item.title} className="flex gap-3">
                <Icon
                  className="mt-0.5 h-4 w-4 shrink-0 text-muted"
                  aria-hidden="true"
                />
                <div className="space-y-0.5">
                  <p className="text-sm font-medium text-foreground">
                    {item.title}
                  </p>
                  <p className="text-sm leading-relaxed text-muted">
                    {item.body}
                  </p>
                </div>
              </li>
            );
          })}
        </ul>

        {/* 신뢰 핵심 — 직접 대조법. 눈에 띄게 강조한다. */}
        <div className="rounded-xl border border-accent/30 bg-accent/10 p-4">
          <p className="text-sm font-semibold text-foreground">
            직접 대조해볼 수 있어요
          </p>
          <p className="mt-1 text-sm leading-relaxed text-muted">
            같은 장소를 네이버 지도에서 열고 <strong className="font-semibold text-foreground">&lsquo;리뷰&rsquo; 탭에서 정렬을 &lsquo;최신순&rsquo;으로</strong>{" "}
            바꾸면(네이버 기본값은 &lsquo;추천순&rsquo;이라 꼭 바꿔야 우리와 같아져요) 우리가 읽은 것과{" "}
            <strong className="font-semibold text-foreground">같은 리뷰들을 위에서부터</strong>{" "}
            직접 확인할 수 있어요. 메뉴 언급 숫자는 같은 탭 상단 &lsquo;메뉴&rsquo; 칩에서 바로 대조돼요.
          </p>
        </div>

        <p className="text-xs leading-relaxed text-muted">
          한 번 분석한 장소는 저장돼 다시 조회하면 빠르게 응답하고, 결과에 갱신 시점이 표시돼요. &lsquo;갱신하기&rsquo;로 최신 리뷰로 다시 분석할 수도 있어요.
        </p>
      </CardContent>
    </Card>
  );
}
