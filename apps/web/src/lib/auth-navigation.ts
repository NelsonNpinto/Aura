"use client";

import { clearApiToken } from "./api";

export const authChangeKey = "aura.auth-change";

export function navigateAfterAuthChange(path: string) {
  clearApiToken();
  try {
    localStorage.setItem(authChangeKey, crypto.randomUUID());
  } catch {
    // Navigation still clears this tab's state if browser storage is disabled.
  }
  window.location.assign(new URL(path, window.location.origin));
}
