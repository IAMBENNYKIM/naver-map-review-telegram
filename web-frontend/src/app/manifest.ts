import type { MetadataRoute } from "next";

/**
 * PWA 웹 앱 매니페스트.
 *
 * share_target(method: GET) 을 정의해, 네이버 앱 등에서 "공유 → 이 앱"을 하면
 * 공유 데이터가 `/share` 로 전달되어 분석 입력창을 프리필한다.
 * (POST 방식 공유 타겟은 서비스워커가 필요하므로 지원 범위가 넓은 GET 만 사용.)
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "네이버 리뷰 요약",
    short_name: "리뷰요약",
    description: "네이버 지도 리뷰를 요약해 카드로 보여주는 앱",
    start_url: "/",
    display: "standalone",
    background_color: "#f6f7f8",
    theme_color: "#03c75a",
    lang: "ko",
    icons: [
      {
        src: "/icon-192.png",
        sizes: "192x192",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/icon-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/icon-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ],
    // 웹 공유 타겟: 공유된 title/text/url 을 /share 로 GET 전달한다.
    share_target: {
      action: "/share",
      method: "GET",
      params: {
        title: "title",
        text: "text",
        url: "url",
      },
    },
  };
}
