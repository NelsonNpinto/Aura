import { createContext, useContext, type ReactNode } from "react";
import { useApi } from "../hooks/useApi";
import type { ModelStatus } from "../types";
type ModelsState = ReturnType<typeof useApi<ModelStatus>>;
const ModelsContext = createContext<ModelsState | null>(null);
export function ModelsProvider({ children }: { children: ReactNode }) {
  const models = useApi<ModelStatus>("/models");
  return (
    <ModelsContext.Provider value={models}>{children}</ModelsContext.Provider>
  );
}
export function useModels() {
  const models = useContext(ModelsContext);
  if (!models) throw new Error("useModels requires ModelsProvider");
  return models;
}
