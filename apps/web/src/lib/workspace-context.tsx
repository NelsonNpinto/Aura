"use client";

import { createContext, useContext } from "react";

type Workspace = {
  id: string | null;
  name: string | null;
  workspaces: { id: string; name: string }[];
};

const Context = createContext<Workspace>({
  id: null,
  name: null,
  workspaces: [],
});

export function WorkspaceProvider({
  value,
  children,
}: {
  value: Workspace;
  children: React.ReactNode;
}) {
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useWorkspace() {
  return useContext(Context);
}
