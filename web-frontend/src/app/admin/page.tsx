"use client";

import { useState } from "react";
import { ShieldCheck, BarChart3 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { ApiError, fetchAdminStats } from "@/lib/api";
import type { UsageRow } from "@/lib/types";

type Phase = "idle" | "loading" | "loaded" | "error";

/** 관리자 사용량 통계 페이지. 토큰은 메모리에만 보관한다(영구 저장 지양). */
export default function AdminPage() {
  const [adminToken, setAdminToken] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [errorText, setErrorText] = useState<string | null>(null);
  const [rows, setRows] = useState<UsageRow[]>([]);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = adminToken.trim();
    if (!trimmed) {
      setErrorText("관리자 토큰을 입력해 주세요.");
      setPhase("error");
      return;
    }

    setPhase("loading");
    setErrorText(null);
    try {
      const usage = await fetchAdminStats(trimmed);
      setRows(usage);
      setPhase("loaded");
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setErrorText("관리자 토큰이 올바르지 않아요.");
      } else if (error instanceof ApiError) {
        setErrorText(error.message);
      } else {
        setErrorText("통계를 불러오지 못했어요.");
      }
      setPhase("error");
    }
  }

  return (
    <div className="mx-auto w-full max-w-3xl space-y-6 px-4 py-8">
      <header className="space-y-1">
        <h1 className="flex items-center gap-2 text-lg font-semibold">
          <ShieldCheck className="h-5 w-5 text-accent" aria-hidden="true" />
          관리자 통계
        </h1>
        <p className="text-sm text-muted">
          관리자 토큰을 입력하면 사용자별 사용량을 확인할 수 있어요.
        </p>
      </header>

      <Card>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4" noValidate>
            <div className="space-y-1.5">
              <Label htmlFor="admin-token">관리자 토큰</Label>
              <Input
                id="admin-token"
                type="password"
                autoComplete="off"
                placeholder="관리자 토큰"
                value={adminToken}
                onChange={(event) => setAdminToken(event.target.value)}
              />
            </div>
            <Button type="submit" disabled={phase === "loading"}>
              {phase === "loading" ? (
                <>
                  <Spinner className="h-4 w-4" />
                  불러오는 중...
                </>
              ) : (
                <>
                  <BarChart3 className="h-4 w-4" aria-hidden="true" />
                  통계 조회
                </>
              )}
            </Button>
          </form>
        </CardContent>
      </Card>

      {phase === "error" && errorText ? (
        <p
          role="alert"
          className="rounded-lg bg-rose-500/10 px-3 py-2 text-sm text-rose-600 dark:text-rose-400"
        >
          {errorText}
        </p>
      ) : null}

      {phase === "loaded" ? (
        rows.length === 0 ? (
          <Card>
            <CardContent className="text-sm text-muted">
              아직 사용 기록이 없어요.
            </CardContent>
          </Card>
        ) : (
          <Card>
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border text-left text-muted">
                      <th className="px-4 py-3 font-medium">사용자</th>
                      <th className="px-4 py-3 text-right font-medium">
                        총 요청
                      </th>
                      <th className="px-4 py-3 text-right font-medium">
                        LLM 호출
                      </th>
                      <th className="px-4 py-3 font-medium">최근 사용</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row, index) => (
                      <tr
                        key={`${row.identity}-${index}`}
                        className="border-b border-border last:border-b-0"
                      >
                        <td className="px-4 py-3 font-medium break-all">
                          {row.identity}
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums">
                          {row.totalCount}
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums">
                          {row.llmCallCount}
                        </td>
                        <td className="px-4 py-3 text-muted">
                          {row.lastUsedAt}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        )
      ) : null}
    </div>
  );
}
