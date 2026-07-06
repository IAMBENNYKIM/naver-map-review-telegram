/**
 * 백엔드 API 계약과 프론트엔드 도메인 모델의 타입 정의.
 *
 * 백엔드 응답은 snake_case JSON이지만, 프론트엔드 내부에서는
 * camelCase 도메인 객체로 변환해 사용한다 (경계 매핑은 lib/api.ts 참조).
 */

/** 메뉴별 추천 감성 값 (백엔드가 한국어 문자열로 내려준다). */
export type MenuSentiment = "추천" | "비추천" | "호불호";

/** summary_json 문자열을 파싱한 결과의 메뉴 항목. */
export interface SummaryMenu {
  name: string;
  sentiment: MenuSentiment;
  mentions: number;
  note: string;
}

/** summary_json 문자열을 파싱한 리뷰 요약 구조. */
export interface ReviewSummary {
  overall: string;
  pros: string[];
  cons: string[];
  menus: SummaryMenu[];
  caution: string | null;
}

/** 분석 진행 상태. */
export type AnalysisStatus = "processing" | "done" | "error";

/**
 * `GET /result/{job_id}` 응답을 camelCase로 매핑한 도메인 모델.
 * done 상태일 때만 장소 정보와 요약이 채워진다.
 */
export interface AnalysisResult {
  status: AnalysisStatus;
  /** 파싱에 성공한 요약. 파싱 실패 시 null 이며 rawSummaryJson 로 폴백한다. */
  summary: ReviewSummary | null;
  /** 파싱 실패 대비 원문 문자열. */
  rawSummaryJson: string | null;
  placeName: string | null;
  address: string | null;
  reviewCount: number | null;
  cacheHit: boolean;
  /** 분석/캐시 갱신 시점 ISO 문자열. 없으면 null. */
  updatedAt: string | null;
  errorMessage: string | null;
}

/** `GET /admin/stats` 응답의 사용량 한 행. */
export interface UsageRow {
  identity: string;
  totalCount: number;
  llmCallCount: number;
  lastUsedAt: string;
}
