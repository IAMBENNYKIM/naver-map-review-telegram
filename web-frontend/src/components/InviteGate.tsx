"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { KeyRound } from "lucide-react";

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
    <div className="flex min-h-full flex-1 items-center justify-center px-4 py-16">
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
    </div>
  );
}
