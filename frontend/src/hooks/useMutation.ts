import { useState } from "react";
import { toast } from "sonner";
import { errorMessage } from "../services/api";
export function useMutation<T>() {
  const [result, setResult] = useState<T | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null);
  async function execute(
    action: () => Promise<T>,
    message = "Saved",
    after?: () => void,
  ) {
    setBusy(true);
    setError(null);
    try {
      const value = await action();
      setResult(value);
      toast.success(message);
      after?.();
      return value;
    } catch (e) {
      setError(errorMessage(e));
      return null;
    } finally {
      setBusy(false);
    }
  }
  return { result, busy, error, execute };
}
