import { readFile } from "node:fs/promises";
import path from "node:path";
import { headers } from "next/headers";
import { Suspense } from "react";
import { AuthForm, type DemoLogin } from "@/components/auth-form";
import { pool } from "@/lib/db";
import { purchasingDemoAccounts, PURCHASING_DEMO_ORG } from "@/lib/purchasing-demo";

export const metadata = { title: "Log in" };

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}

async function LoginForm() {
  const host = (await headers()).get("host") ?? "";
  if (process.env.NODE_ENV === "production") {
    const result = await pool.query<{ provisioned: boolean }>(
      `SELECT EXISTS (SELECT 1 FROM auth.organization WHERE id = $1) AS provisioned`,
      [PURCHASING_DEMO_ORG],
    ).catch(() => null);
    if (result?.rows[0]?.provisioned) {
      return <AuthForm mode="login" demoLogins={purchasingDemoAccounts} publicDemo />;
    }
  }
  let demoLogins: DemoLogin[] | undefined;
  if (process.env.NODE_ENV === "development" && /^(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$/i.test(host)) {
    try {
      demoLogins = JSON.parse(
        await readFile(path.join(process.cwd(), ".local", "purchasing-demo-logins.json"), "utf8"),
      ) as DemoLogin[];
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }
  }
  return <AuthForm mode="login" demoLogins={demoLogins} />;
}
