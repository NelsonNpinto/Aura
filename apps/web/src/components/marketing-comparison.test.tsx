import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import { MarketingComparison } from "./marketing-comparison";

vi.mock("@/lib/api", () => ({ api: vi.fn() }));

it("shows the simulated false approval first and lets a guest inspect another case", async () => {
  const clean = { id: "clean", passed: true, expected_pass: true };
  const inflated = { id: "inflated", passed: false, expected_pass: false };
  const baseline = {
    gate_passed: true,
    errors: 0,
    false_passes: [],
    false_fails: [],
    human_calibration: null,
    results: [clean, inflated],
  };
  vi.mocked(api).mockResolvedValue({
    dataset_sha256: "test-only",
    cases: [
      { id: "clean", facts: "Eight hours.", draft: "Get eight hours." },
      { id: "inflated", facts: "Eight hours.", draft: "Get 48 hours." },
    ],
    simulation: {
      baseline,
      candidate: {
        ...baseline,
        gate_passed: false,
        false_passes: ["inflated"],
        results: [clean, { ...inflated, passed: true }],
      },
    },
    live: null,
  });

  render(
    <QueryClientProvider client={new QueryClient()}>
      <MarketingComparison />
    </QueryClientProvider>,
  );
  expect(await screen.findByText("Simulated example")).toBeTruthy();
  expect(screen.getByText("Would block release")).toBeTruthy();
  expect(screen.getByText("Get 48 hours.")).toBeTruthy();
  expect(screen.getByText("Rejected")).toBeTruthy();
  expect(screen.getByText("Approved")).toBeTruthy();
  fireEvent.change(screen.getByRole("combobox", { name: "Inspect a case" }), {
    target: { value: "clean" },
  });
  expect(screen.getByText("Get eight hours.")).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: "Run live comparison" }),
  ).toBeNull();
});
