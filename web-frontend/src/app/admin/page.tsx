"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  BarChart3,
  LogOut,
  RotateCcw,
  ShieldCheck,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { UsageChart, type MetricMode } from "@/components/UsageChart";
import { ApiError, fetchAdminStats } from "@/lib/api";
import type { UsageRow } from "@/lib/types";
import {
  buildChartSeries,
  filterDailyByRange,
  sumRange,
} from "@/lib/usage-stats";

type Phase = "idle" | "loading" | "loaded" | "error";

/** 표에 표시할 행 (구간 반영 후의 값). */
interface DisplayRow {
  identity: string;
  total: number;
  llm: number;
  lastUsedAt: string;
}

const METRIC_OPTIONS: Array<{ value: MetricMode; label: string }> = [
  { value: "both", label: "둘 다" },
  { value: "total", label: "총요청" },
  { value: "llm", label: "LLM 호출" },
];

/** 관리자 사용량 통계 페이지. 토큰은 메모리에만 보관한다(영구 저장 지양). */
export default function AdminPage() {
  const [adminToken, setAdminToken] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [errorText, setErrorText] = useState<string | null>(null);
  const [rows, setRows] = useState<UsageRow[]>([]);

  // 구간 선택 상태 (빈 문자열 = 미선택 = 무제한).
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [metricMode, setMetricMode] = useState<MetricMode>("both");

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

  /** 구간만 해제한다 (조회 결과는 유지). */
  function handleResetRange() {
    setStartDate("");
    setEndDate("");
  }

  /** 로드 상태에서 완전히 나간다. 메모리의 관리자 토큰까지 제거한다. */
  function handleExit() {
    setAdminToken("");
    setRows([]);
    setErrorText(null);
    setStartDate("");
    setEndDate("");
    setMetricMode("both");
    setPhase("idle");
  }

  const rangeStart = startDate || null;
  const rangeEnd = endDate || null;
  const isRangeActive = Boolean(rangeStart || rangeEnd);

  const rangeLabel = isRangeActive
    ? `${startDate || "처음"} ~ ${endDate || "지금"}`
    : "전체 기간";

  // 표에 쓸 행: 구간이 선택되면 daily 를 구간 합산, 아니면 lifetime 값.
  const displayRows = useMemo<DisplayRow[]>(() => {
    return rows.map((row) => {
      if (!isRangeActive) {
        return {
          identity: row.identity,
          total: row.totalCount,
          llm: row.llmCallCount,
          lastUsedAt: row.lastUsedAt,
        };
      }
      const ranged = sumRange(
        filterDailyByRange(row.daily, rangeStart, rangeEnd),
      );
      return {
        identity: row.identity,
        total: ranged.total,
        llm: ranged.llm,
        lastUsedAt: row.lastUsedAt,
      };
    });
  }, [rows, isRangeActive, rangeStart, rangeEnd]);

  const chartSeries = useMemo(
    () => buildChartSeries(rows, rangeStart, rangeEnd),
    [rows, rangeStart, rangeEnd],
  );

  const showTotalColumn = metricMode !== "llm";
  const showLlmColumn = metricMode !== "total";

  return (
    <div className="mx-auto w-full max-w-3xl space-y-6 px-4 py-8">
      <header className="space-y-2">
        <Link
          href="/"
          className="inline-flex items-center gap-1 text-sm text-muted transition-colors hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          홈으로
        </Link>
        <div className="space-y-1">
          <h1 className="flex items-center gap-2 text-lg font-semibold">
            <ShieldCheck className="h-5 w-5 text-accent" aria-hidden="true" />
            관리자 통계
          </h1>
          <p className="text-sm text-muted">
            관리자 토큰을 입력하면 사용자별 사용량을 확인할 수 있어요.
          </p>
        </div>
      </header>

      {phase !== "loaded" ? (
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
      ) : null}

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
          <>
            <Card>
              <CardContent className="text-sm text-muted">
                아직 사용 기록이 없어요.
              </CardContent>
            </Card>
            <Button variant="outline" onClick={handleExit}>
              <LogOut className="h-4 w-4" aria-hidden="true" />
              나가기
            </Button>
          </>
        ) : (
          <>
            {/* 구간·지표 선택 + 나가기 */}
            <Card>
              <CardContent className="space-y-4">
                <div className="flex flex-wrap items-end gap-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="range-start">시작일</Label>
                    <Input
                      id="range-start"
                      type="date"
                      value={startDate}
                      max={endDate || undefined}
                      onChange={(event) => setStartDate(event.target.value)}
                      className="w-auto"
                    />
                  </div>
                  <span className="pb-3 text-muted">~</span>
                  <div className="space-y-1.5">
                    <Label htmlFor="range-end">종료일</Label>
                    <Input
                      id="range-end"
                      type="date"
                      value={endDate}
                      min={startDate || undefined}
                      onChange={(event) => setEndDate(event.target.value)}
                      className="w-auto"
                    />
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleResetRange}
                    disabled={!isRangeActive}
                    className="mb-0.5"
                  >
                    <RotateCcw className="h-4 w-4" aria-hidden="true" />
                    초기화
                  </Button>
                </div>

                <div className="space-y-1.5">
                  <Label>표시 지표</Label>
                  <div className="flex flex-wrap gap-2">
                    {METRIC_OPTIONS.map((option) => (
                      <Button
                        key={option.value}
                        size="sm"
                        variant={
                          metricMode === option.value ? "primary" : "outline"
                        }
                        onClick={() => setMetricMode(option.value)}
                      >
                        {option.label}
                      </Button>
                    ))}
                  </div>
                </div>

                <div className="flex items-center justify-between border-t border-border pt-3">
                  <span className="text-sm text-muted">
                    범위: <span className="font-medium text-foreground">{rangeLabel}</span>
                  </span>
                  <Button variant="outline" size="sm" onClick={handleExit}>
                    <LogOut className="h-4 w-4" aria-hidden="true" />
                    나가기
                  </Button>
                </div>
              </CardContent>
            </Card>

            {/* 사용량 표 */}
            <Card>
              <CardContent className="p-0">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border text-left text-muted">
                        <th className="px-4 py-3 font-medium">사용자</th>
                        {showTotalColumn ? (
                          <th className="px-4 py-3 text-right font-medium">
                            총 요청
                          </th>
                        ) : null}
                        {showLlmColumn ? (
                          <th className="px-4 py-3 text-right font-medium">
                            LLM 호출
                          </th>
                        ) : null}
                        <th className="px-4 py-3 font-medium">최근 사용</th>
                      </tr>
                    </thead>
                    <tbody>
                      {displayRows.map((row, index) => (
                        <tr
                          key={`${row.identity}-${index}`}
                          className="border-b border-border last:border-b-0"
                        >
                          <td className="px-4 py-3 font-medium break-all">
                            {row.identity}
                          </td>
                          {showTotalColumn ? (
                            <td className="px-4 py-3 text-right tabular-nums">
                              {row.total}
                            </td>
                          ) : null}
                          {showLlmColumn ? (
                            <td className="px-4 py-3 text-right tabular-nums">
                              {row.llm}
                            </td>
                          ) : null}
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

            {/* 일자별 사용량 그래프 */}
            <Card>
              <CardContent className="space-y-3">
                <h2 className="text-sm font-medium text-foreground">
                  일자별 사용량
                </h2>
                <UsageChart
                  data={chartSeries.data}
                  identities={chartSeries.identities}
                  metricMode={metricMode}
                />
              </CardContent>
            </Card>
          </>
        )
      ) : null}
    </div>
  );
}
