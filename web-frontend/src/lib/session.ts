/**
 * 초대 세션 토큰을 localStorage 에 보관/조회/삭제하는 헬퍼.
 *
 * 관리자 토큰은 영구 저장하지 않으므로 여기서 다루지 않는다
 * (관리자 페이지는 메모리/sessionStorage 만 사용).
 */

const SESSION_TOKEN_KEY = "naverReviewSessionToken";

/** 서버 렌더링 단계에서 window 접근을 막기 위한 가드. */
function isBrowser(): boolean {
  return typeof window !== "undefined";
}

/** 저장된 세션 토큰을 반환한다. 없으면 null. */
export function getSessionToken(): string | null {
  if (!isBrowser()) {
    return null;
  }
  try {
    return window.localStorage.getItem(SESSION_TOKEN_KEY);
  } catch {
    // 사파리 프라이빗 모드 등에서 localStorage 접근이 막힐 수 있다.
    return null;
  }
}

/** 세션 토큰을 저장한다. */
export function saveSessionToken(token: string): void {
  if (!isBrowser()) {
    return;
  }
  try {
    window.localStorage.setItem(SESSION_TOKEN_KEY, token);
  } catch {
    // 저장 실패는 조용히 무시한다 (다음 요청에서 401 로 유도됨).
  }
}

/** 세션 토큰을 삭제한다 (로그아웃 / 세션 만료). */
export function clearSessionToken(): void {
  if (!isBrowser()) {
    return;
  }
  try {
    window.localStorage.removeItem(SESSION_TOKEN_KEY);
  } catch {
    // 무시.
  }
}
