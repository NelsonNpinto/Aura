import { readFile } from "node:fs/promises";
import path from "node:path";
import { headers } from "next/headers";
import { Suspense } from "react";
import { AuthForm, type DemoLogin } from "@/components/auth-form";

export const metadata = { title: "Log in" };

export default function LoginPage() {
  return (
    <Suspense>
      <LocalLoginForm />
    </Suspense>
  );
}

async function LocalLoginForm() {
  let demoLogins: DemoLogin[] | undefined;
  if (process.env.NODE_ENV === "development") {
    const host = (await headers()).get("host") ?? "";
    if (/^(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$/i.test(host)) {
      try {
        demoLogins = JSON.parse(
          await readFile(path.join(process.cwd(), ".local", "purchasing-demo-logins.json"), "utf8"),
        ) as DemoLogin[];
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
      }
    }
  }
  return <AuthForm mode="login" demoLogins={demoLogins} />;
}
