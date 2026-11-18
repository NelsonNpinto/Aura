"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Badge, Button, Card, ErrorNote } from "@/components/ui";
import { clearApiToken } from "@/lib/api";
import { authClient } from "@/lib/auth-client";

export default function DemoPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [signedIn, setSignedIn] = useState<boolean | null>(null);

  // A browser that already has a session (guest or account) goes straight back in:
  // Better Auth refuses a second anonymous sign-in for an existing anonymous session.
  useEffect(() => {
    authClient.getSession()
      .then((r) => setSignedIn(Boolean(r.data?.session)))
      .catch(() => setSignedIn(false));
  }, []);

  function go() {
    router.push("/app");
    router.refresh();
  }

  async function enter() {
    setBusy(true);
    setError(null);
    try {
      const res = await authClient.signIn.anonymous();
      if (res.error && res.error.code !== "ANONYMOUS_USERS_CANNOT_SIGN_IN_AGAIN_ANONYMOUSLY") {
        throw new Error(res.error.message ?? "Could not start the demo");
      }
      clearApiToken();
      go();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start the demo");
    } finally {
      setBusy(false);
    }
  }

  async function startFresh() {
    setBusy(true);
    setError(null);
    try {
      const res = await authClient.signOut();
      if (res.error) throw new Error(res.error.message ?? "Could not sign out");
      clearApiToken();
      setSignedIn(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not sign out");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-4">
      <Link href="/" className="mb-6 text-lg font-semibold">AURA</Link>
      <Card>
        <Badge tone="warn">Synthetic data only</Badge>
        <h1 className="mt-3 text-xl font-semibold">Try the AURA demo</h1>
        <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-muted">
          <li>You join a shared demo workspace as a guest, with a daily run quota.</li>
          <li>Do not upload real documents. Guest uploads are deleted after 72 hours.</li>
          <li>Prompts may be processed by free-tier model providers.</li>
        </ul>
        <ErrorNote error={error} />
        {signedIn ? (
          <div className="mt-4 space-y-3">
            <Button className="w-full" onClick={go}>Continue to the demo</Button>
            <button className="w-full text-sm text-muted underline" disabled={busy} onClick={startFresh}>
              Sign out and start a new guest session
            </button>
          </div>
        ) : (
          <div className="mt-4 space-y-3">
            <Button className="w-full" onClick={enter} disabled={busy || signedIn === null}>
              {busy ? "Starting…" : "Enter the demo"}
            </Button>
          </div>
        )}
      </Card>
    </main>
  );
}
