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

/**
 * 분석 대상. 네이버 지도 URL 또는 검색으로 고른 place_id 중 하나로 지정한다.
 * (백엔드 `POST /analyze` 는 둘 중 하나만 받는다.)
 */
export type AnalysisTarget = { naverUrl: string } | { placeId: string };

/** `POST /search` 응답의 후보 장소 한 곳 (snake_case → camelCase 매핑 후). */
export interface PlaceCandidate {
  placeId: string;
  name: string;
  category: string;
  roadAddress: string;
  /** 리뷰 수. 백엔드가 모르면 null. */
  reviewCount: number | null;
}

/** `POST /search` 응답을 camelCase로 매핑한 검색 결과. */
export interface PlaceSearchResult {
  /** LLM이 정규화한 검색어. 없으면 빈 문자열. */
  keyword: string;
  /** 후보 장소 목록. 결과가 없으면 빈 배열. */
  places: PlaceCandidate[];
}

/**
 * `GET /history` 응답의 개인별 조회 식당 보관함 한 항목
 * (snake_case → camelCase 매핑 후). 서버가 최신순으로 정렬해 내려준다.
 */
export interface HistoryEntry {
  placeId: string;
  placeName: string;
  address: string;
  /** 마지막 조회 시각 ISO 문자열 (KST 오프셋 포함, 예: `2026-...+09:00`). */
  lastViewedAt: string;
  /** 누적 조회 횟수. */
  viewCount: number;
}

/** 분석 진행 상태. */
export type AnalysisStatus = "processing" | "done" | "error";

/**
 * 분석 진행 단계 (processing 상태의 세부 단계).
 * `GET /result` 응답의 stage 필드에서 이 3값만 유효하며,
 * 빈 문자열·미지 값·부재는 프론트에서 null로 방어 매핑한다.
 */
export type AnalysisStage = "cache_check" | "collecting" | "summarizing";

/**
 * `GET /result/{job_id}` 응답을 camelCase로 매핑한 도메인 모델.
 * done 상태일 때만 장소 정보와 요약이 채워진다.
 */
export interface AnalysisResult {
  status: AnalysisStatus;
  /** processing 중 세부 진행 단계. 미지 값·부재 시 null. */
  stage: AnalysisStage | null;
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

/** `GET /admin/stats` 응답의 일자별 사용량 한 칸. */
export interface DailyUsage {
  /** `YYYY-MM-DD` 형태의 날짜 (KST 기준). */
  date: string;
  /** 그 날의 총 요청 수. */
  total: number;
  /** 그 날의 LLM 호출 수. */
  llm: number;
  /** 그 날의 장소 검색 수. */
  search: number;
}

/** `GET /admin/stats` 응답의 사용량 한 행. */
export interface UsageRow {
  identity: string;
  totalCount: number;
  llmCallCount: number;
  /** 누적 장소 검색 수. */
  searchCount: number;
  lastUsedAt: string;
  /** 일자별 사용량 (날짜 오름차순). 과거 데이터는 비어 있을 수 있다. */
  daily: DailyUsage[];
}
