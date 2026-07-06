/**
 * 공유(share_target)로 넘어온 임의의 텍스트에서 네이버 지도 URL 을 추출한다.
 *
 * 네이버 앱의 "공유"는 URL 을 text 필드에 문장과 함께 담아 보내는 경우가 많아,
 * 정규식으로 첫 번째 네이버 링크만 골라낸다.
 */

const NAVER_URL_PATTERN = /https?:\/\/[^\s]*naver\.[^\s]+/i;

/** 텍스트에서 첫 번째 네이버 URL 을 뽑아낸다. 없으면 null. */
export function extractNaverUrl(text: string | null | undefined): string | null {
  if (!text) {
    return null;
  }
  const match = text.match(NAVER_URL_PATTERN);
  if (!match) {
    return null;
  }
  // 문장 끝에 붙는 마침표/괄호 등 후행 문장부호를 정리한다.
  return match[0].replace(/[).,]+$/, "");
}

/** 입력값에 naver.me 또는 naver 도메인이 포함되는지 가볍게 검증한다. */
export function looksLikeNaverUrl(value: string): boolean {
  return /naver\.me|naver\.com|map\.naver/i.test(value);
}
