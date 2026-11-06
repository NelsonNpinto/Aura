"use client";

import clsx from "clsx";
import { PERSONAS, usePersona } from "@/lib/persona";

export function PersonaSwitcher() {
  const [persona, setPersona] = usePersona();
  return (
    <div className="mx-3 mb-4 rounded-lg border border-border p-3">
      <div className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">Acting as</div>
      <div className="flex flex-wrap gap-1 lg:flex-col" role="radiogroup" aria-label="Demo persona">
        {PERSONAS.map((p) => (
          <button key={p.key} role="radio" aria-checked={persona === p.key} onClick={() => setPersona(p.key)}
            className={clsx("min-h-9 rounded-md px-2 py-1.5 text-left text-sm",
              persona === p.key ? "bg-accent/15 font-medium text-accent" : "hover:bg-surface-2")}>
            {p.name} <span className="text-xs text-muted">· {p.role}</span>
          </button>
        ))}
      </div>
      <p className="mt-2 hidden text-xs text-muted md:block">
        Segregation of duties applies between personas: Rahul can&apos;t approve what he submitted.
      </p>
    </div>
  );
}
