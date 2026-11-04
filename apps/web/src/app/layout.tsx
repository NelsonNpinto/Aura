import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: { default: "AURA — Auditable, Unified, Reliable Agents", template: "%s · AURA" },
  description:
    "Live demo of an auditable multi-agent accounts-payable platform on synthetic data: invoice-to-pay agents, finance copilot and a built-in trust layer.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen font-sans antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
