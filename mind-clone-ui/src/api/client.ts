export class ApiRequestError extends Error {
  status: number;
  detail?: unknown;

  constructor(message: string, status = 500, detail?: unknown) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.detail = detail;
  }
}

export type ApiRequestOptions = {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  token?: string;
  signal?: AbortSignal;
};

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export async function apiRequest<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const { method = "GET", body, token, signal } = options;
  const headers: Record<string, string> = {
    Accept: "application/json"
  };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const response = await fetch(path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal
  });

  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();

  if (!response.ok) {
    const detail = isRecord(payload) ? payload.detail || payload.error || payload : payload;
    throw new ApiRequestError(`Request failed: ${response.status}`, response.status, detail);
  }
  return payload as T;
}

export function apiGet<T>(path: string, token?: string, signal?: AbortSignal): Promise<T> {
  return apiRequest<T>(path, { method: "GET", token, signal });
}

export function apiPost<T>(path: string, body: unknown, token?: string, signal?: AbortSignal): Promise<T> {
  return apiRequest<T>(path, { method: "POST", body, token, signal });
}

export function apiPatch<T>(path: string, body: unknown, token?: string, signal?: AbortSignal): Promise<T> {
  return apiRequest<T>(path, { method: "PATCH", body, token, signal });
}
