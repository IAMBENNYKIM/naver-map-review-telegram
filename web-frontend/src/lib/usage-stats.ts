/**
 * 관리자 사용량 통계의 순수 계산 로직.
 *
 * 페이지 컴포넌트를 가볍게 유지하기 위해 구간 필터·합산·차트 시리즈 조립을
 * 부수효과 없는 순수 함수로 분리한다 (재사용·테스트 용이).
 *
 * 날짜는 모두 `YYYY-MM-DD` 형태이므로 사전식(문자열) 비교로 크기 비교가 성립한다.
 */

import type { DailyUsage, UsageRow } from "./types";

/** 구간 합산 결과. */
export interface RangeSum {
  total: number;
  llm: number;
  search: number;
}

/** 차트 지표 종류. */
export type UsageMetric = "total" | "llm" | "search";

/**
 * recharts 데이터 레코드의 시리즈 키를 만든다.
 * 사용자명에 특수문자가 있어도 안전하도록 `__` 구분자 뒤에 지표를 고정 접미한다.
 */
export function seriesKey(identity: string, metric: UsageMetric): string {
  return `${identity}__${metric}`;
}

/**
 * daily 배열을 start~end 구간으로 필터한다.
 * start/end 가 null 이면 그 방향은 무제한. 사전식 비교로 경계를 판정한다.
 */
export function filterDailyByRange(
  daily: DailyUsage[],
  start: string | null,
  end: string | null,
): DailyUsage[] {
  if (!Array.isArray(daily) || daily.length === 0) {
    return [];
  }
  return daily.filter((entry) => {
    if (!entry || typeof entry.date !== "string") {
      return false;
    }
    if (start && entry.date < start) {
      return false;
    }
    if (end && entry.date > end) {
      return false;
    }
    return true;
  });
}

/** daily 배열의 total·llm 을 각각 합산한다. */
export function sumRange(daily: DailyUsage[]): RangeSum {
  if (!Array.isArray(daily)) {
    return { total: 0, llm: 0, search: 0 };
  }
  return daily.reduce<RangeSum>(
    (accumulator, entry) => {
      if (!entry) {
        return accumulator;
      }
      const total = Number.isFinite(entry.total) ? entry.total : 0;
      const llm = Number.isFinite(entry.llm) ? entry.llm : 0;
      const search = Number.isFinite(entry.search) ? entry.search : 0;
      return {
        total: accumulator.total + total,
        llm: accumulator.llm + llm,
        search: accumulator.search + search,
      };
    },
    { total: 0, llm: 0, search: 0 },
  );
}

/** buildChartSeries 반환 형태. */
export interface ChartSeries {
  /** 일자별 레코드 배열. 각 레코드는 `{ date, "<identity>__total": n, ... }`. */
  data: Array<Record<string, number | string>>;
  /** 등장하는 사용자 식별자 목록 (rows 순서 유지). */
  identities: string[];
}

/**
 * 선택 구간(미선택 시 존재하는 모든 날짜)의 정렬된 일자 축을 만들고,
 * 각 일자 레코드에 사용자별 total·llm·search 값을 채운다.
 * 값이 없는 (사용자, 날짜) 조합은 0 으로 둔다.
 */
export function buildChartSeries(
  rows: UsageRow[],
  start: string | null,
  end: string | null,
): ChartSeries {
  if (!Array.isArray(rows) || rows.length === 0) {
    return { data: [], identities: [] };
  }

  const identities = rows.map((row) => row.identity);

  // 구간 필터를 적용한 사용자별 daily 를 미리 만들어 둔다.
  const filteredByIdentity = new Map<string, DailyUsage[]>();
  const dateSet = new Set<string>();
  for (const row of rows) {
    const filtered = filterDailyByRange(row.daily ?? [], start, end);
    filteredByIdentity.set(row.identity, filtered);
    for (const entry of filtered) {
      dateSet.add(entry.date);
    }
  }

  // 정렬된 일자 축 (사전식 = 시간순).
  const sortedDates = Array.from(dateSet).sort();
  if (sortedDates.length === 0) {
    return { data: [], identities };
  }

  // 빠른 조회를 위해 (사용자, 날짜) → DailyUsage 인덱스를 만든다.
  const lookupByIdentity = new Map<string, Map<string, DailyUsage>>();
  for (const [identity, filtered] of filteredByIdentity) {
    const byDate = new Map<string, DailyUsage>();
    for (const entry of filtered) {
      byDate.set(entry.date, entry);
    }
    lookupByIdentity.set(identity, byDate);
  }

  const data = sortedDates.map((date) => {
    const record: Record<string, number | string> = { date };
    for (const identity of identities) {
      const entry = lookupByIdentity.get(identity)?.get(date);
      record[seriesKey(identity, "total")] = entry ? entry.total : 0;
      record[seriesKey(identity, "llm")] = entry ? entry.llm : 0;
      record[seriesKey(identity, "search")] = entry ? entry.search : 0;
    }
    return record;
  });

  return { data, identities };
}
