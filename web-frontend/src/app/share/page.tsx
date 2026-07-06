"use client";

import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { Spinner } from "@/components/ui/spinner";
import { extractNaverUrl } from "@/lib/naver-url";

/*
 * PWA 웹 공유 타겟(share_target)의 착지 라우트.
 *
 * manifest 의 share_target(method: GET)이 이 경로로 title/text/url 쿼리를 넘긴다.
 * 네이버 앱 공유는 URL 을 text 나 url 에 담아 보내므로, 그 안에서 네이버 링크를
 * 뽑아 메인(/)의 prefill 로 넘겨 입력창을 채운다.
 *
 * 참고: method POST 공유 타겟은 서비스워커로 요청을 가로채야 하므로 여기서는
 * 지원 범위가 넓은 GET 방식만 처리한다. iOS 사파리 등 일부 브라우저는
 * share_target 자체를 지원하지 않을 수 있다(best-effort).
 */
function ShareRedirect() {
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    const candidate =
      searchParams.get("url") ??
      searchParams.get("text") ??
      searchParams.get("title") ??
      "";
    const naverUrl = extractNaverUrl(candidate);

    if (naverUrl) {
      router.replace(`/?prefill=${encodeURIComponent(naverUrl)}`);
    } else {
      // 네이버 URL 을 못 찾으면 그냥 메인으로 보낸다.
      router.replace("/");
    }
  }, [router, searchParams]);

  return (
    <div className="flex min-h-full flex-1 items-center justify-center gap-3 px-4 text-sm text-muted">
      <Spinner className="h-5 w-5 text-accent" />
      공유한 주소를 여는 중...
    </div>
  );
}

export default function SharePage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-full flex-1 items-center justify-center">
          <Spinner className="h-5 w-5 text-accent" />
        </div>
      }
    >
      <ShareRedirect />
    </Suspense>
  );
}
