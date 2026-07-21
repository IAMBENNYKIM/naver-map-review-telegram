"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { LogOut, Link2, Sparkles, Bookmark } from "lucide-react";

import { InviteGate } from "@/components/InviteGate";
import { SearchView } from "@/components/SearchView";
import { AnalyzeView } from "@/components/AnalyzeView";
import { HistoryView } from "@/components/HistoryView";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";
import { clearSessionToken, getSessionToken } from "@/lib/session";

/** 인증 후 상단 탭 종류. */
type HomeTab = "search" | "paste" | "history";

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
  // 공유(share_target)로 프리필 URL 이 오면 "링크 붙여넣기" 탭을 초기 활성화한다.
  const [activeTab, setActiveTab] = useState<HomeTab>(
    prefillUrl ? "paste" : "search",
  );

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
    <div className="mx-auto w-full max-w-2xl space-y-6 px-4 py-8">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold">리뷰 요약</h1>
          <p className="text-sm text-muted">
            가고 싶은 곳을 검색하거나 링크로 리뷰를 요약해 드려요.
          </p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="shrink-0"
          onClick={handleLogout}
          aria-label="로그아웃"
        >
          <LogOut className="h-4 w-4" aria-hidden="true" />
          로그아웃
        </Button>
      </header>

      {/* 탭 전환 */}
      <div
        role="tablist"
        aria-label="입력 방식"
        className="flex gap-1 rounded-xl border border-border bg-card p-1"
      >
        <TabButton
          isActive={activeTab === "search"}
          onClick={() => setActiveTab("search")}
        >
          <Sparkles className="h-4 w-4 max-[430px]:hidden" aria-hidden="true" />
          검색
        </TabButton>
        <TabButton
          isActive={activeTab === "paste"}
          onClick={() => setActiveTab("paste")}
        >
          <Link2 className="h-4 w-4 max-[430px]:hidden" aria-hidden="true" />
          링크 붙여넣기
        </TabButton>
        <TabButton
          isActive={activeTab === "history"}
          onClick={() => setActiveTab("history")}
        >
          <Bookmark className="h-4 w-4 max-[430px]:hidden" aria-hidden="true" />
          보관함
        </TabButton>
      </div>

      {activeTab === "search" ? (
        <SearchView token={token} onSessionExpired={handleLogout} />
      ) : activeTab === "paste" ? (
        <AnalyzeView
          token={token}
          initialUrl={prefillUrl}
          onSessionExpired={handleLogout}
        />
      ) : (
        <HistoryView token={token} onSessionExpired={handleLogout} />
      )}

      {/* 관리자 진입 링크 (눈에 띄지 않게) */}
      <div className="pt-2 text-center">
        <Link href="/admin" className="text-xs text-muted hover:underline">
          관리자
        </Link>
      </div>
    </div>
  );
}

interface TabButtonProps {
  isActive: boolean;
  onClick: () => void;
  children: React.ReactNode;
}

/** 간단한 탭 토글 버튼 (외부 패키지 없이 UI 프리미티브 스타일에 맞춘다). */
function TabButton({ isActive, onClick, children }: TabButtonProps) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={isActive}
      onClick={onClick}
      className={cn(
        "flex flex-1 items-center justify-center gap-1.5 whitespace-nowrap rounded-lg px-2 py-2 text-sm font-medium transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40",
        isActive
          ? "bg-accent text-white"
          : "text-muted hover:bg-black/5 dark:hover:bg-white/5",
      )}
    >
      {children}
    </button>
  );
}

export default function Home() {
  return (
    <Suspense fallback={<LoadingScreen />}>
      <HomeContent />
    </Suspense>
  );
}
