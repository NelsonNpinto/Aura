"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useState } from "react";
import { Turnstile } from "@/components/turnstile";
import { Button, Card, ErrorNote, Input, Label } from "@/components/ui";
import { authClient } from "@/lib/auth-client";

export function AuthForm({ mode }: { mode: "login" | "signup" }) {
  const router = useRouter();
  const params = useSearchParams();
  const [captcha, setCaptcha] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const onToken = useCallback((t: string | null) => setCaptcha(t), []);
  const needsCaptcha = Boolean(process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY);

  async function submit(form: FormData) {
    setBusy(true);
    setError(null);
    const fetchOptions = { headers: captcha ? { "x-captcha-response": captcha } : {} };
    const email = String(form.get("email"));
    const password = String(form.get("password"));
    const res =
      mode === "signup"
        ? await authClient.signUp.email({ email, password, name: String(form.get("name") || email.split("@")[0]), fetchOptions })
        : await authClient.signIn.email({ email, password, fetchOptions });
    setBusy(false);
    if (res.error) {
      setError(res.error.message ?? "Authentication failed");
      return;
    }
    const next = params.get("next");
    router.push(next?.startsWith("/app") ? next : "/app");
    router.refresh();
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-sm flex-col justify-center px-4">
      <Link href="/" className="mb-6 text-lg font-semibold">AURA</Link>
      <Card>
        <h1 className="mb-4 text-xl font-semibold">{mode === "signup" ? "Create your workspace" : "Log in"}</h1>
        <form action={submit} className="space-y-3">
          {mode === "signup" && (
            <div>
              <Label htmlFor="name">Name</Label>
              <Input id="name" name="name" autoComplete="name" maxLength={80} />
            </div>
          )}
          <div>
            <Label htmlFor="email">Email</Label>
            <Input id="email" name="email" type="email" required autoComplete="email" maxLength={200} />
          </div>
          <div>
            <Label htmlFor="password">Password</Label>
            <Input id="password" name="password" type="password" required minLength={10} maxLength={128}
              autoComplete={mode === "signup" ? "new-password" : "current-password"} />
          </div>
          <Turnstile onToken={onToken} />
          <ErrorNote error={error} />
          <Button type="submit" className="w-full" disabled={busy || (needsCaptcha && !captcha)}>
            {busy ? "Please wait…" : mode === "signup" ? "Sign up" : "Log in"}
          </Button>
        </form>
        <p className="mt-4 text-sm text-muted">
          {mode === "signup" ? (
            <>Have an account? <Link className="text-accent underline" href="/login">Log in</Link></>
          ) : (
            <>New here? <Link className="text-accent underline" href="/signup">Sign up</Link> or <Link className="text-accent underline" href="/demo">try the demo</Link></>
          )}
        </p>
      </Card>
    </main>
  );
}
