/**
 * 백엔드 API 호출을 한곳에 모은 래퍼 모듈.
 *
 * - 베이스 URL 은 환경변수 `NEXT_PUBLIC_API_BASE_URL` 에서만 읽는다 (하드코딩 금지).
 * - 모든 요청에 Bearer 인증 헤더와 JSON 파싱, 에러 정규화를 적용한다.
 */

import type {
  AnalysisResult,
  AnalysisStage,
  AnalysisTarget,
  DailyUsage,
  HistoryEntry,
  PlaceCandidate,
  PlaceSearchResult,
  ReviewSummary,
  SummaryMenu,
  UsageRow,
} from "./types";

/** API 계층에서 던지는 표준 에러. status 0 은 네트워크/설정 오류를 의미한다. */
export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }

  /** 세션 만료(401) 여부. */
  get isUnauthorized(): boolean {
    return this.status === 401;
  }
}

/** 설정된 API 베이스 URL 을 반환한다. 미설정이면 명확한 에러를 던진다. */
function resolveBaseUrl(): string {
  const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!baseUrl || baseUrl.trim().length === 0) {
    throw new ApiError(
      "API 서버 주소가 설정되지 않았어요. 관리자에게 문의해 주세요.",
      0,
    );
  }
  // 뒤쪽 슬래시를 제거해 경로 조합 시 중복 슬래시를 막는다.
  return baseUrl.trim().replace(/\/+$/, "");
}

interface RequestOptions {
  method: "GET" | "POST" | "DELETE";
  path: string;
  token?: string;
  body?: unknown;
}

/**
 * 공통 fetch 래퍼. JSON 을 파싱해 반환하며, 2xx 가 아니면 ApiError 를 던진다.
 * 404 는 호출부에서 개별 처리할 수 있도록 status 를 그대로 담는다.
 */
async function request<TResponse>(options: RequestOptions): Promise<TResponse> {
  const { method, path, token, body } = options;
  const baseUrl = resolveBaseUrl();

  const headers: Record<string, string> = {};
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetch(`${baseUrl}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    // 네트워크 자체 실패 (CORS, 오프라인, DNS 등).
    throw new ApiError("서버에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.", 0);
  }

  // 응답 본문을 안전하게 파싱한다 (빈 본문/비 JSON 대비).
  let payload: unknown = null;
  const text = await response.text();
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    const serverMessage =
      payload &&
      typeof payload === "object" &&
      "error" in payload &&
      typeof (payload as { error: unknown }).error === "string"
        ? (payload as { error: string }).error
        : null;
    throw new ApiError(
      serverMessage ?? "요청을 처리하지 못했어요.",
      response.status,
    );
  }

  return payload as TResponse;
}

/** `POST /invite` — 초대코드로 세션 토큰을 발급받는다. */
export async function requestInvite(code: string): Promise<string> {
  const data = await request<{ token: string }>({
    method: "POST",
    path: "/invite",
    body: { code },
  });
  return data.token;
}

/**
 * `POST /analyze` — 분석을 요청하고 job_id 를 받는다.
 * 대상은 네이버 URL 또는 place_id 중 하나이며, 백엔드에는 둘 중 하나만 보낸다.
 */
export async function requestAnalyze(
  token: string,
  target: AnalysisTarget,
  forceRefresh = false,
): Promise<string> {
  const body =
    "naverUrl" in target
      ? { naver_url: target.naverUrl, force_refresh: forceRefresh }
      : { place_id: target.placeId, force_refresh: forceRefresh };
  const data = await request<{ job_id: string }>({
    method: "POST",
    path: "/analyze",
    token,
    body,
  });
  return data.job_id;
}

/** `POST /search` 원본 응답(snake_case). */
interface RawPlaceSearchResponse {
  keyword?: string;
  places?: unknown;
}

/**
 * 후보 장소 한 건을 방어적으로 매핑한다.
 * place_id·name 이 온전치 않으면 null 을 반환해 호출부가 걸러내게 한다.
 */
function toPlaceCandidate(value: unknown): PlaceCandidate | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const record = value as Record<string, unknown>;
  const placeId = typeof record.place_id === "string" ? record.place_id : "";
  const name = typeof record.name === "string" ? record.name : "";
  if (!placeId || !name) {
    return null;
  }
  const category = typeof record.category === "string" ? record.category : "";
  const roadAddress =
    typeof record.road_address === "string" ? record.road_address : "";
  const reviewCount =
    typeof record.review_count === "number" &&
    Number.isFinite(record.review_count)
      ? record.review_count
      : null;
  return { placeId, name, category, roadAddress, reviewCount };
}

/** `POST /search` — 자연어 프롬프트로 후보 장소를 검색한다. */
export async function searchPlaces(
  token: string,
  prompt: string,
): Promise<PlaceSearchResult> {
  const raw = await request<RawPlaceSearchResponse>({
    method: "POST",
    path: "/search",
    token,
    body: { prompt },
  });

  const keyword = typeof raw.keyword === "string" ? raw.keyword : "";
  const places = Array.isArray(raw.places)
    ? raw.places
        .map(toPlaceCandidate)
        .filter((candidate): candidate is PlaceCandidate => candidate !== null)
    : [];
  return { keyword, places };
}

/** `GET /history` 원본 응답(snake_case). */
interface RawHistoryResponse {
  history?: unknown;
}

/**
 * 보관함 항목 한 건을 방어적으로 매핑한다.
 * place_id 가 온전치 않으면 null 을 반환해 호출부가 걸러내게 한다.
 */
function toHistoryEntry(value: unknown): HistoryEntry | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const record = value as Record<string, unknown>;
  const placeId = typeof record.place_id === "string" ? record.place_id : "";
  if (!placeId) {
    return null;
  }
  const placeName =
    typeof record.place_name === "string" ? record.place_name : "";
  const address = typeof record.address === "string" ? record.address : "";
  const lastViewedAt =
    typeof record.last_viewed_at === "string" ? record.last_viewed_at : "";
  const viewCount =
    typeof record.view_count === "number" && Number.isFinite(record.view_count)
      ? record.view_count
      : 0;
  return { placeId, placeName, address, lastViewedAt, viewCount };
}

/** `GET /history` — 개인별 조회 식당 보관함을 최신순으로 조회한다. */
export async function fetchHistory(token: string): Promise<HistoryEntry[]> {
  const raw = await request<RawHistoryResponse>({
    method: "GET",
    path: "/history",
    token,
  });

  return Array.isArray(raw.history)
    ? raw.history
        .map(toHistoryEntry)
        .filter((entry): entry is HistoryEntry => entry !== null)
    : [];
}

/** `DELETE /history/{place_id}` — 보관함에서 항목 하나를 삭제한다. */
export async function deleteHistoryEntry(
  token: string,
  placeId: string,
): Promise<void> {
  await request<{ deleted?: boolean }>({
    method: "DELETE",
    path: `/history/${encodeURIComponent(placeId)}`,
    token,
  });
}

/** 백엔드가 내려주는 `GET /result` 원본 응답(snake_case). */
interface RawResultResponse {
  status: "processing" | "done" | "error";
  /** processing 중 세부 단계. 3값 외(빈 문자열·미지 값·부재)는 null로 매핑한다. */
  stage?: string;
  summary_json?: string;
  place_name?: string;
  address?: string;
  review_count?: number;
  cache_hit?: boolean;
  updated_at?: string;
  error_message?: string;
}

/**
 * summary_json 문자열을 방어적으로 파싱한다.
 * 구조가 어긋나면 null 을 반환해 호출부가 원문 폴백을 하도록 한다.
 */
export function parseSummaryJson(raw: string | undefined): ReviewSummary | null {
  if (!raw) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object") {
      return null;
    }
    const candidate = parsed as Record<string, unknown>;

    const overall = typeof candidate.overall === "string" ? candidate.overall : "";
    const pros = toStringArray(candidate.pros);
    const cons = toStringArray(candidate.cons);
    const menus = toMenuArray(candidate.menus);
    const caution =
      typeof candidate.caution === "string" ? candidate.caution : null;

    // 최소한 총평이나 메뉴 중 하나라도 있어야 유효한 요약으로 본다.
    if (!overall && menus.length === 0 && pros.length === 0 && cons.length === 0) {
      return null;
    }

    return { overall, pros, cons, menus, caution };
  } catch {
    return null;
  }
}

/**
 * 응답의 stage 값을 유효한 3단계로만 좁힌다.
 * 빈 문자열·미지 값·부재는 null로 방어 매핑한다.
 */
function toAnalysisStage(value: unknown): AnalysisStage | null {
  if (
    value === "cache_check" ||
    value === "collecting" ||
    value === "summarizing"
  ) {
    return value;
  }
  return null;
}

function toStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is string => typeof item === "string");
}

function toMenuArray(value: unknown): SummaryMenu[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const menus: SummaryMenu[] = [];
  for (const item of value) {
    if (!item || typeof item !== "object") {
      continue;
    }
    const record = item as Record<string, unknown>;
    const name = typeof record.name === "string" ? record.name : "";
    if (!name) {
      continue;
    }
    const sentiment =
      record.sentiment === "추천" ||
      record.sentiment === "비추천" ||
      record.sentiment === "호불호"
        ? record.sentiment
        : "호불호";
    const mentions =
      typeof record.mentions === "number" && Number.isFinite(record.mentions)
        ? record.mentions
        : 0;
    const note = typeof record.note === "string" ? record.note : "";
    menus.push({ name, sentiment, mentions, note });
  }
  return menus;
}

/** `GET /result/{job_id}` — 분석 상태/결과를 조회한다. */
export async function fetchResult(
  token: string,
  jobId: string,
): Promise<AnalysisResult> {
  const raw = await request<RawResultResponse>({
    method: "GET",
    path: `/result/${encodeURIComponent(jobId)}`,
    token,
  });

  return {
    status: raw.status,
    stage: toAnalysisStage(raw.stage),
    summary: parseSummaryJson(raw.summary_json),
    rawSummaryJson: raw.summary_json ?? null,
    placeName: raw.place_name ?? null,
    address: raw.address ?? null,
    reviewCount:
      typeof raw.review_count === "number" ? raw.review_count : null,
    cacheHit: Boolean(raw.cache_hit),
    updatedAt: raw.updated_at ?? null,
    errorMessage: raw.error_message ?? null,
  };
}

/** 숫자로 강제 변환한다. 유한수가 아니면 0. */
function toFiniteNumber(value: unknown): number {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

/**
 * 응답의 daily 필드를 방어적으로 매핑한다.
 * 배열이 아니거나 각 원소가 온전치 않으면 안전한 기본값으로 채운다.
 */
function toDailyUsage(value: unknown): DailyUsage[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const result: DailyUsage[] = [];
  for (const item of value) {
    if (!item || typeof item !== "object") {
      continue;
    }
    const record = item as Record<string, unknown>;
    const date = typeof record.date === "string" ? record.date : "";
    if (!date) {
      continue;
    }
    result.push({
      date,
      total: toFiniteNumber(record.total),
      llm: toFiniteNumber(record.llm),
      search: toFiniteNumber(record.search),
    });
  }
  return result;
}

/** `GET /admin/stats` — 관리자 사용량 통계를 조회한다. */
export async function fetchAdminStats(adminToken: string): Promise<UsageRow[]> {
  const data = await request<{
    usage: Array<{
      identity: string;
      total_count: number;
      llm_call_count: number;
      search_count?: number;
      last_used_at: string;
      daily?: unknown;
    }>;
  }>({
    method: "GET",
    path: "/admin/stats",
    token: adminToken,
  });

  return (data.usage ?? []).map((row) => ({
    identity: row.identity,
    totalCount: toFiniteNumber(row.total_count),
    llmCallCount: toFiniteNumber(row.llm_call_count),
    searchCount: toFiniteNumber(row.search_count),
    lastUsedAt: row.last_used_at,
    daily: toDailyUsage(row.daily),
  }));
}
