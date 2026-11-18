"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { useEffect, useState } from "react";
import { ApiError, clearApiToken } from "@/lib/api";
import { authChangeKey } from "@/lib/auth-navigation";

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 15_000,
            retry: (attempt, error) =>
              attempt === 0 &&
              (!(error instanceof ApiError) || error.status >= 500),
          },
        },
      }),
  );
  useEffect(() => {
    function restore() {
      clearApiToken();
      client.clear();
      if (/^\/app(?:\/|$)/.test(window.location.pathname))
        window.location.reload();
    }
    function onStorage(event: StorageEvent) {
      if (event.key === authChangeKey) restore();
    }
    function onPageShow(event: PageTransitionEvent) {
      if (event.persisted) restore();
    }
    window.addEventListener("storage", onStorage);
    window.addEventListener("pageshow", onPageShow);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener("pageshow", onPageShow);
    };
  }, [client]);
  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </ThemeProvider>
  );
}
