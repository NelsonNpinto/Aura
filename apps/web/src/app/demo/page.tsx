"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";
import { Turnstile } from "@/components/turnstile";
import { Badge, Button, Card, ErrorNote } from "@/components/ui";
import { authClient } from "@/lib/auth-client";

export default function DemoPage() {
  const router = useRouter();
  const [captcha, setCaptcha] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const onToken = useCallback((t: string | null) => setCaptcha(t), []);
  const needsCaptcha = Boolean(process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY);

  async function enter() {
    setBusy(true);
    setError(null);
    const res = await authClient.signIn.anonymous({
      fetchOptions: { headers: captcha ? { "x-captcha-response": captcha } : {} },
    });
    setBusy(false);
    if (res.error) return setError(res.error.message ?? "Could not start the demo");
    router.push("/app");
    router.refresh();
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
        <div className="mt-4 space-y-3">
          <Turnstile onToken={onToken} />
          <ErrorNote error={error} />
          <Button className="w-full" onClick={enter} disabled={busy || (needsCaptcha && !captcha)}>
            {busy ? "Starting…" : "Enter the demo"}
          </Button>
        </div>
      </Card>
    </main>
  );
}
