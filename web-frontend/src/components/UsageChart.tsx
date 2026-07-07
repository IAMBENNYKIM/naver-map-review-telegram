"use client";

import { Fragment } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { seriesKey, type UsageMetric } from "@/lib/usage-stats";

/** 지표 표시 모드: 총요청만 / LLM만 / 둘 다. */
export type MetricMode = "both" | "total" | "llm";

interface UsageChartProps {
  /** buildChartSeries 로 만든 일자별 레코드 배열. */
  data: Array<Record<string, number | string>>;
  /** 등장하는 사용자 식별자 목록. */
  identities: string[];
  metricMode: MetricMode;
}

/** 사용자 인덱스 → CSS 변수 팔레트(6색 순환). */
function colorForIndex(index: number): string {
  return `var(--chart-${(index % 6) + 1})`;
}

/** 지표별 한국어 라벨. */
const METRIC_LABEL: Record<UsageMetric, string> = {
  total: "총요청",
  llm: "LLM",
};

/**
 * 사용량 꺾은선 그래프.
 * 사용자별 1선(총요청=실선, LLM=점선). 지표 모드에 따라 선 구성이 달라진다.
 * 축·격자·툴팁 색은 테마 토큰(CSS 변수)을 사용해 다크/라이트 모두 읽히게 한다.
 */
export function UsageChart({ data, identities, metricMode }: UsageChartProps) {
  if (data.length === 0 || identities.length === 0) {
    return (
      <p className="px-1 py-8 text-center text-sm text-muted">
        표시할 사용량 데이터가 없어요.
      </p>
    );
  }

  const showTotal = metricMode !== "llm";
  const showLlm = metricMode !== "total";

  // 날짜 수가 많으면 가로로 넓혀 스크롤되게 한다.
  const minWidth = Math.max(480, data.length * 44);

  return (
    <div className="overflow-x-auto">
      <div style={{ minWidth }}>
        <ResponsiveContainer width="100%" height={320}>
          <LineChart
            data={data}
            margin={{ top: 8, right: 16, bottom: 8, left: 0 }}
          >
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
            <XAxis
              dataKey="date"
              tick={{ fill: "var(--muted)", fontSize: 12 }}
              stroke="var(--border)"
            />
            <YAxis
              allowDecimals={false}
              tick={{ fill: "var(--muted)", fontSize: 12 }}
              stroke="var(--border)"
              width={36}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "var(--card)",
                border: "1px solid var(--border)",
                borderRadius: 12,
                fontSize: 12,
              }}
              labelStyle={{ color: "var(--foreground)" }}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            {identities.map((identity, index) => {
              const color = colorForIndex(index);
              return (
                <Fragment key={identity}>
                  {showTotal ? (
                    <Line
                      type="monotone"
                      dataKey={seriesKey(identity, "total")}
                      name={`${identity} · ${METRIC_LABEL.total}`}
                      stroke={color}
                      strokeWidth={2}
                      dot={false}
                      connectNulls
                    />
                  ) : null}
                  {showLlm ? (
                    <Line
                      type="monotone"
                      dataKey={seriesKey(identity, "llm")}
                      name={`${identity} · ${METRIC_LABEL.llm}`}
                      stroke={color}
                      strokeWidth={2}
                      strokeDasharray="5 4"
                      dot={false}
                      connectNulls
                    />
                  ) : null}
                </Fragment>
              );
            })}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
