"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import { InviteGate } from "@/components/InviteGate";
import { AnalyzeView } from "@/components/AnalyzeView";
import { Spinner } from "@/components/ui/spinner";
import { clearSessionToken, getSessionToken } from "@/lib/session";

/** 초기 로딩(토큰 확인) 화면. */
function LoadingScreen() {
  return (
    <div className="flex min-h-full flex-1 items-center justify-center">
      <Spinner className="h-6 w-6 text-accent" />
    </div>
  );
}

/** useSearchParams 를 사용하므로 Suspense 경계 안에서 렌더한다. */
function HomeContent() {
  const searchParams = useSearchParams();
  const prefillUrl = searchParams.get("prefill") ?? undefined;

  const [token, setToken] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    // 클라이언트에서만 localStorage 를 읽는다.
    setToken(getSessionToken());
    setReady(true);
  }, []);

  const handleLogout = useCallback(() => {
    clearSessionToken();
    setToken(null);
  }, []);

  if (!ready) {
    return <LoadingScreen />;
  }

  if (!token) {
    return <InviteGate onAuthenticated={setToken} />;
  }

  return (
    <AnalyzeView
      token={token}
      initialUrl={prefillUrl}
      onLogout={handleLogout}
      onSessionExpired={handleLogout}
    />
  );
}

export default function Home() {
  return (
    <Suspense fallback={<LoadingScreen />}>
      <HomeContent />
    </Suspense>
  );
}
