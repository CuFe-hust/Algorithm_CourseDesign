export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
    public requestId?: string,
  ) {
    super(message);
  }
}
export function token() {
  return sessionStorage.getItem("algoclass.token");
}
export function clearSession() {
  sessionStorage.removeItem("algoclass.token");
  sessionStorage.removeItem("algoclass.user");
}
export async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (token()) headers.set("Authorization", `Bearer ${token()}`);
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, { ...options, headers });
  } catch {
    throw new ApiError(
      0,
      "NETWORK_ERROR",
      "无法连接服务，请检查网络和后端是否启动。",
    );
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    if (response.status === 401 && !path.startsWith("/auth/login")) {
      clearSession();
      window.dispatchEvent(new Event("session-expired"));
    }
    throw new ApiError(
      response.status,
      body.code || "REQUEST_FAILED",
      body.message || "请求失败，请稍后重试。",
      body.details,
      body.request_id,
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
export const post = <T>(path: string, body?: unknown) =>
  request<T>(path, {
    method: "POST",
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
export function errorText(error: unknown) {
  if (error instanceof ApiError)
    return `${error.message}${error.requestId ? `（请求编号：${error.requestId}）` : ""}`;
  return error instanceof Error ? error.message : "操作失败，请稍后重试。";
}
export function query(values: Record<string, string | number | undefined>) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values))
    if (value !== undefined && value !== "") params.set(key, String(value));
  return params.toString();
}
