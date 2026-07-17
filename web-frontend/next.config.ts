import type { NextConfig } from "next";

// 모든 경로에 적용할 HTTP 보안 응답 헤더.
// connect-src 는 프론트가 호출하는 API 오리진(AWS HttpApi = *.execute-api.<region>.amazonaws.com)을
// 허용한다. NEXT_PUBLIC_API_BASE_URL 이 이 execute-api 도메인이므로 와일드카드로 커버된다.
// script-src/style-src 의 'unsafe-inline' 은 Next 15 의 인라인 런타임/스타일 요구 때문에 필요하다
// (nonce 기반 강화는 이번 범위 밖).
const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  "connect-src 'self' https://*.execute-api.ap-northeast-2.amazonaws.com",
  "img-src 'self' data:",
  "style-src 'self' 'unsafe-inline'",
  "script-src 'self' 'unsafe-inline'",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

const SECURITY_HEADERS = [
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=()",
  },
  {
    key: "Strict-Transport-Security",
    value: "max-age=63072000; includeSubDomains; preload",
  },
  { key: "Content-Security-Policy", value: CONTENT_SECURITY_POLICY },
];

const nextConfig: NextConfig = {
  async headers() {
    return [
      {
        source: "/:path*",
        headers: SECURITY_HEADERS,
      },
    ];
  },
};

export default nextConfig;
