"""Browser agent for the legacy vendor portal (Phase 5.2).

The portal has no API, so invoices can only be fetched by driving the UI. The agent works from
the **accessibility tree first** — roles and names, which are stable — and only falls back to a
screenshot when a step cannot be resolved that way. Every step is recorded as a trajectory so it
can be scored like any other agent run.

It runs in GitHub Actions (triggered from the app with `workflow_dispatch`), never in the
serving path: Playwright and a browser do not fit in the Vercel bundle budget (§B4).

    python -m agent.browser_agent --base-url http://localhost:8020 --out ./downloads
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

MAX_INVOICES = 10
STEP_TIMEOUT_MS = 15_000


@dataclass
class Step:
    name: str
    strategy: str  # accessibility | vision | navigation
    ok: bool
    detail: str = ""
    ms: int = 0

    def public(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Trajectory:
    steps: list[Step] = field(default_factory=list)
    downloads: list[str] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)

    def add(self, step: Step) -> None:
        self.steps.append(step)

    def public(self) -> dict[str, Any]:
        return {
            "steps": [s.public() for s in self.steps],
            "downloads": self.downloads,
            "screenshots": self.screenshots,
            "succeeded": all(s.ok for s in self.steps) and bool(self.downloads),
            "vision_fallbacks": sum(1 for s in self.steps if s.strategy == "vision"),
        }


async def _timed(trajectory: Trajectory, name: str, strategy: str, coro: Any) -> Any:
    started = time.monotonic()
    try:
        result = await coro
    except Exception as exc:
        trajectory.add(
            Step(name, strategy, False, f"{type(exc).__name__}: {exc}"[:200],
                 int((time.monotonic() - started) * 1000))
        )
        raise
    trajectory.add(Step(name, strategy, True, "", int((time.monotonic() - started) * 1000)))
    return result


async def run(base_url: str, out_dir: Path, username: str, password: str, limit: int) -> dict[str, Any]:
    from playwright.async_api import async_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    trajectory = Trajectory()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()
        page.set_default_timeout(STEP_TIMEOUT_MS)
        try:
            await _timed(trajectory, "open_portal", "navigation", page.goto(f"{base_url}/portal/"))

            # Accessibility-tree first: fields are found by their label, not by CSS.
            await _timed(
                trajectory, "fill_username", "accessibility",
                page.get_by_label("Username").fill(username),
            )
            await _timed(
                trajectory, "fill_password", "accessibility",
                page.get_by_label("Password").fill(password),
            )
            await _timed(
                trajectory, "submit_login", "accessibility",
                page.get_by_role("button", name="Sign in").click(),
            )
            await _timed(
                trajectory, "invoice_list_visible", "accessibility",
                page.get_by_role("heading", name="Your invoices").wait_for(),
            )

            links = page.get_by_role("link").filter(has_text="INV-")
            count = min(await links.count(), limit)
            if count == 0:
                # Nothing resolved from the accessibility tree: take a screenshot so a human can
                # see what the page actually looked like, and report the failure honestly.
                shot = out_dir / "no-invoices.png"
                await page.screenshot(path=str(shot))
                trajectory.screenshots.append(str(shot))
                trajectory.add(Step("find_invoices", "vision", False, "no invoice links found"))
                return trajectory.public()

            numbers = [await links.nth(i).inner_text() for i in range(count)]
            for number in numbers:
                await _timed(
                    trajectory, f"open_{number}", "accessibility",
                    page.get_by_role("link", name=number).click(),
                )
                async with page.expect_download() as download_info:
                    await _timed(
                        trajectory, f"download_{number}", "accessibility",
                        page.get_by_role("link", name="Download PDF").click(),
                    )
                download = await download_info.value
                target = out_dir / f"{number}.pdf"
                await download.save_as(str(target))
                trajectory.downloads.append(str(target))
                await _timed(
                    trajectory, f"back_from_{number}", "accessibility",
                    page.get_by_role("link", name="Back to invoices").click(),
                )
        finally:
            await context.close()
            await browser.close()
    return trajectory.public()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("PORTAL_URL", "http://localhost:8020"))
    parser.add_argument("--out", default="./downloads")
    parser.add_argument("--username", default=os.environ.get("PORTAL_USER", "acme"))
    parser.add_argument("--password", default=os.environ.get("PORTAL_PASSWORD", "portal-demo-only"))
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--report", help="write the trajectory JSON here")
    args = parser.parse_args()
    if not 1 <= args.limit <= MAX_INVOICES:
        parser.error(f"limit must be between 1 and {MAX_INVOICES}")

    result = asyncio.run(
        run(args.base_url.rstrip("/"), Path(args.out), args.username, args.password, args.limit)
    )
    rendered = json.dumps(result, indent=2)
    if args.report:
        Path(args.report).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    sys.exit(0 if result["succeeded"] else 1)


if __name__ == "__main__":
    main()
