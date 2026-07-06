/**
 * 분석 결과를 복사/공유용 순수 평문으로 조립하는 헬퍼.
 *
 * Telegram `review_formatter.format_analysis` 레이아웃을 웹 도메인 모델
 * (`AnalysisResult`) 기준으로 재현한다. MarkdownV2 이스케이프는 하지 않는다
 * (클립보드/Web Share 는 평문을 그대로 다루기 때문).
 */

import type { AnalysisResult, MenuSentiment, SummaryMenu } from "./types";

/** 감성 값 → 아이콘 (Telegram `_SENTIMENT_ICONS` 와 동일). */
const SENTIMENT_ICONS: Record<MenuSentiment, string> = {
  추천: "✅",
  호불호: "⚠️",
  비추천: "❌",
};

/** updatedAt 파싱 결과: KST 기준 날짜 문자열과 오늘과의 경과일. */
interface ParsedUpdatedAt {
  /** `YYYY-MM-DD` 형태의 KST 날짜. */
  dateString: string;
  /** 오늘(KST)과의 경과일. 음수면 0 으로 취급한다. */
  daysAgo: number;
}

/** 한 자리 수를 두 자리 문자열로 보정한다. */
function padTwo(value: number): string {
  return value.toString().padStart(2, "0");
}

/** UTC 타임스탬프를 KST 벽시계 기준 연/월/일로 변환한다 (한국은 DST 없음). */
function toKstYearMonthDay(date: Date): { year: number; month: number; day: number } {
  const kstShifted = new Date(date.getTime() + 9 * 60 * 60 * 1000);
  return {
    year: kstShifted.getUTCFullYear(),
    month: kstShifted.getUTCMonth() + 1,
    day: kstShifted.getUTCDate(),
  };
}

/**
 * updatedAt ISO 문자열 → KST 날짜 문자열 + 경과일.
 * 파싱에 실패하면 null 을 반환한다 (Telegram `_parse_updated_at` 로직 참고).
 */
function parseUpdatedAt(updatedAt: string | null): ParsedUpdatedAt | null {
  if (!updatedAt) {
    return null;
  }
  const parsed = new Date(updatedAt);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }

  const target = toKstYearMonthDay(parsed);
  const today = toKstYearMonthDay(new Date());
  const dateString = `${target.year}-${padTwo(target.month)}-${padTwo(target.day)}`;

  const targetDayUtc = Date.UTC(target.year, target.month - 1, target.day);
  const todayDayUtc = Date.UTC(today.year, today.month - 1, today.day);
  const daysAgo = Math.round((todayDayUtc - targetDayUtc) / (24 * 60 * 60 * 1000));

  return { dateString, daysAgo };
}

/**
 * updatedAt 을 `"2026-07-05 갱신 · 2일 전"` 형태의 표시 문자열로 변환한다.
 * 경과일이 0 이하이면 "오늘" 로 표기한다. 파싱 실패 시 null.
 */
export function formatUpdatedAt(updatedAt: string | null): string | null {
  const parsed = parseUpdatedAt(updatedAt);
  if (!parsed) {
    return null;
  }
  const daysAgoLabel = parsed.daysAgo <= 0 ? "오늘" : `${parsed.daysAgo}일 전`;
  return `${parsed.dateString} 갱신 · ${daysAgoLabel}`;
}

/** 메뉴 한 줄: `✅ 이름 — 추천 (N회 언급) : note`. */
function buildMenuLine(menu: SummaryMenu): string {
  let line = `${SENTIMENT_ICONS[menu.sentiment]} ${menu.name} — ${menu.sentiment}`;
  if (menu.mentions > 0) {
    line += ` (${menu.mentions}회 언급)`;
  }
  if (menu.note) {
    line += ` : ${menu.note}`;
  }
  return line;
}

/**
 * 분석 결과를 복사/공유용 순수 평문으로 조립한다.
 * 값이 없는 줄은 생략하며, summary 가 null 이면 원문(rawSummaryJson) 또는
 * 장소명만이라도 담아 반환한다.
 */
export function buildShareText(result: AnalysisResult): string {
  const { summary, rawSummaryJson, placeName, address, reviewCount, updatedAt } =
    result;
  const lines: string[] = [];

  // 장소 헤더 (웹에는 avg_rating 이 없어 ⭐ 줄은 생략한다)
  lines.push(`🍽 ${placeName ?? "이름 미상 장소"}`);
  if (address) {
    lines.push(`📍 ${address}`);
  }
  if (typeof reviewCount === "number") {
    lines.push(`리뷰 ${reviewCount}개 기반`);
  }

  if (summary) {
    if (summary.overall) {
      lines.push("");
      lines.push("■ 총평");
      lines.push(summary.overall);
    }
    if (summary.pros.length > 0) {
      lines.push("");
      lines.push("👍 장점");
      for (const item of summary.pros) {
        lines.push(`• ${item}`);
      }
    }
    if (summary.cons.length > 0) {
      lines.push("");
      lines.push("👎 단점");
      for (const item of summary.cons) {
        lines.push(`• ${item}`);
      }
    }
    if (summary.menus.length > 0) {
      lines.push("");
      lines.push("🍜 메뉴별 추천도");
      for (const menu of summary.menus) {
        lines.push(buildMenuLine(menu));
      }
    }
    if (summary.caution) {
      lines.push("");
      lines.push(`⚠️ 주의: ${summary.caution}`);
    }
  } else if (rawSummaryJson) {
    // 파싱 실패 폴백 — 원문이라도 담는다.
    lines.push("");
    lines.push(rawSummaryJson);
  }

  // 꼬리 — 리뷰 수 기준 + 갱신 날짜(있을 때만)
  const parsed = parseUpdatedAt(updatedAt);
  const tailParts: string[] = [];
  if (typeof reviewCount === "number") {
    tailParts.push(`리뷰 ${reviewCount}개 기준`);
  }
  if (parsed) {
    tailParts.push(`${parsed.dateString} 갱신`);
  }
  if (tailParts.length > 0) {
    lines.push("");
    lines.push(`(${tailParts.join(" · ")})`);
  }

  return lines.join("\n").trim();
}
