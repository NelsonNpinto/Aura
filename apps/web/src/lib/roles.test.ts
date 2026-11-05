import { describe, expect, it } from "vitest";
import { parseRoles } from "./roles";

describe("parseRoles", () => {
  it("keeps only known roles", () => {
    expect(parseRoles("approver, owner,clerk")).toEqual(["approver", "clerk"]);
    expect(parseRoles(null)).toEqual([]);
  });
});
