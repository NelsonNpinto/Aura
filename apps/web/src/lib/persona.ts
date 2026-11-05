"use client";

import { useEffect, useState } from "react";

export type PersonaKey = "rahul" | "priya" | "meera";
export const PERSONAS: { key: PersonaKey; name: string; role: string; blurb: string }[] = [
  { key: "rahul", name: "Rahul", role: "AP clerk", blurb: "Uploads and runs invoices" },
  { key: "priya", name: "Priya", role: "Approver", blurb: "Approves up to $10,000, no HIGH flags" },
  { key: "meera", name: "Meera", role: "Controller", blurb: "Approves HIGH-risk and bank changes" },
];
const KEY = "aura.persona";
const EVT = "aura-persona";

export function getPersona(): PersonaKey {
  try {
    const v = localStorage.getItem(KEY);
    if (v === "rahul" || v === "priya" || v === "meera") return v;
  } catch {}
  return "rahul";
}

export function setPersona(p: PersonaKey) {
  try {
    localStorage.setItem(KEY, p);
  } catch {}
  window.dispatchEvent(new CustomEvent(EVT, { detail: p }));
}

export function usePersona(): [PersonaKey, (p: PersonaKey) => void] {
  const [p, setP] = useState<PersonaKey>("rahul");
  useEffect(() => {
    setP(getPersona());
    const on = (e: Event) => setP((e as CustomEvent<PersonaKey>).detail);
    window.addEventListener(EVT, on);
    return () => window.removeEventListener(EVT, on);
  }, []);
  return [p, setPersona];
}
