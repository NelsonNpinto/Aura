"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useRef, useState } from "react";
import { Turnstile } from "@/components/turnstile";
import { Button, Card, ErrorNote, Input, Label } from "@/components/ui";
import { clearApiToken } from "@/lib/api";
import { authClient } from "@/lib/auth-client";

export type DemoLogin = { label: string; email: string; password: string; workspaceId: string };

export function AuthForm({ mode, demoLogins = [], publicDemo = false }: { mode: "login" | "signup"; demoLogins?: DemoLogin[]; publicDemo?: boolean }) {
  const router = useRouter();
  const params = useSearchParams();
  const [captcha, setCaptcha] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);
  const onToken = useCallback((t: string | null) => setCaptcha(t), []);
  // Turnstile tokens are single-use: after any attempt, render a fresh widget for the next one.
  const [widget, setWidget] = useState(0);
  const needsCaptcha = Boolean(process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY);

  function fillDemo(login: DemoLogin) {
    const email = formRef.current?.elements.namedItem("email");
    const password = formRef.current?.elements.namedItem("password");
    if (email instanceof HTMLInputElement && password instanceof HTMLInputElement) {
      email.value = login.email;
      password.value = login.password;
      setError(null);
    }
  }

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
    if (res.error) {
      setBusy(false);
      setCaptcha(null);
      setWidget((w) => w + 1);
      setError(res.error.message ?? "Authentication failed");
      return;
    }
    const demoLogin = demoLogins.find((login) => login.email === email && login.password === password);
    if (demoLogin) {
      try {
        // The session's active workspace controls the role used on the Purchasing page.
        await authClient.organization.setActive({ organizationId: demoLogin.workspaceId });
      } catch {
        // Purchasing also has a workspace selector if the switch could not be completed.
      }
      clearApiToken();
      router.push("/app/procurement");
      router.refresh();
      setBusy(false);
      return;
    }
    setBusy(false);
    const next = params.get("next");
    router.push(next?.startsWith("/app") ? next : "/app");
    router.refresh();
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-sm flex-col justify-center px-4">
      <Link href="/" className="mb-6 text-lg font-semibold">AURA</Link>
      <Card>
        <h1 className="mb-4 text-xl font-semibold">{mode === "signup" ? "Create your workspace" : "Log in"}</h1>
        {mode === "login" && demoLogins.length > 0 && (
          <div className="mb-5 space-y-2 rounded-lg border border-border bg-surface-2 p-3">
            <p className="text-sm font-semibold">Purchasing demo logins</p>
            <p className="text-xs text-muted">Choose a role to fill the form, then click Log in.</p>
            {publicDemo && <p className="text-xs text-muted">Shared demo workspace. Use sample documents. Payment emails are previewed.</p>}
            <div className="grid grid-cols-2 gap-2">
              {demoLogins.map((login) => (
                <Button key={login.email} type="button" variant="secondary" disabled={busy} onClick={() => fillDemo(login)}>
                  {login.label}
                </Button>
              ))}
            </div>
          </div>
        )}
        <form ref={formRef} action={submit} className="space-y-3">
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
          <Turnstile key={widget} onToken={onToken} />
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
