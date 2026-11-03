import axios from "axios";
export const api = axios.create({ baseURL: "/api/v1", timeout: 1200000 });
api.interceptors.request.use((config) => {
  const key = sessionStorage.getItem("aura-api-key");
  if (key) config.headers.Authorization = `Bearer ${key}`;
  return config;
});
export function errorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (detail?.message) return detail.message;
    if (Array.isArray(detail))
      return detail.map((v: { msg: string }) => v.msg).join("; ");
    if (error.response) return `The server could not complete the request (HTTP ${error.response.status}). Check service health and request traces.`;
    return "Cannot reach the API. Check that the backend is running.";
  }
  return error instanceof Error
    ? error.message
    : "An unexpected error occurred";
}
