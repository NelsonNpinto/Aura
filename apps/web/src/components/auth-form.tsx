"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useRef, useState } from "react";
import { Button, Card, ErrorNote, Input, Label } from "@/components/ui";
import { navigateAfterAuthChange } from "@/lib/auth-navigation";
import { authClient } from "@/lib/auth-client";
import { PURCHASING_DEMO_ORG } from "@/lib/purchasing-demo";

export type DemoLogin = { label: string; email: string; password: string; workspaceId: string };

export function AuthForm({ mode, demoLogins = [], publicDemo = false }: { mode: "login" | "signup"; demoLogins?: DemoLogin[]; publicDemo?: boolean }) {
  const params = useSearchParams();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);

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
    const email = String(form.get("email")).trim();
    const password = String(form.get("password"));
    try {
      const res =
        mode === "signup"
          ? await authClient.signUp.email({ email, password, name: String(form.get("name") || email.split("@")[0]) })
          : await authClient.signIn.email({ email, password });
      if (res.error) throw new Error(res.error.message ?? "Authentication failed");
      const demoLogin = demoLogins.find((login) => login.email.toLowerCase() === email.toLowerCase());
      const next = params.get("next");
      if (demoLogin && demoLogin.workspaceId !== PURCHASING_DEMO_ORG) {
        const active = await authClient.organization.setActive({ organizationId: demoLogin.workspaceId });
        if (active.error) throw new Error(active.error.message ?? "Could not open the Purchasing workspace");
      }
      const requested = next && /^\/app(?:\/|\?|$)/.test(next) ? next : null;
      const keepsDemoScope = requested && /^\/app\/(?:procurement|copilot)(?:\?|$)/.test(requested);
      navigateAfterAuthChange(demoLogin && !keepsDemoScope ? "/app/procurement" : requested ?? "/app");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not sign in. Try again.");
      setBusy(false);
    }
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
          <ErrorNote error={error} />
          <Button type="submit" className="w-full" disabled={busy}>
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
