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
async function transport(
  path: string,
  options: RequestInit = {},
): Promise<Response> {
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
  return response;
}
export async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await transport(path, options);
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
export async function requestBlob(path: string): Promise<Blob> {
  return (await transport(path)).blob();
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

const fieldNames: Record<string, string> = {
  title: "题目名称",
  code: "题目编号",
  question_type: "题型",
  statement_md: "题干",
  answer_requirements_md: "作答要求",
  input_spec_md: "输入格式",
  output_spec_md: "输出格式",
  data_constraints_md: "数据范围",
  public_examples_md: "公开示例",
  source_reference: "来源与引用",
  difficulty_level: "难度",
  knowledge_point_ids: "知识点",
  reference_solutions: "参考答案",
  content: "内容",
  language: "语言",
  test_suite: "测试配置",
  cpu_limit_ms: "CPU 时限",
  memory_limit_kib: "内存上限",
  allowed_languages: "允许语言",
  cases: "测试点",
  input_text: "输入",
  expected_output: "期望输出",
  weight: "权重",
  is_public: "公开设置",
  rubric: "评分量表",
  items: "评分维度",
  name: "名称",
  description: "评分描述",
  max_score: "满分",
  expected_updated_at: "版本更新时间",
};
export function validationMessages(details: unknown): string[] {
  if (!details || typeof details !== "object") return [];
  if ("requirements" in details && Array.isArray(details.requirements))
    return details.requirements.filter(
      (value): value is string => typeof value === "string",
    );
  if (!Array.isArray(details)) return [];
  return details.flatMap((item) => {
    if (!item || typeof item.field !== "string") return [];
    const field = item.field
      .split(".")
      .filter((part: string) => !["body", "version"].includes(part))
      .map((part: string) =>
        /^\d+$/.test(part)
          ? `第 ${Number(part) + 1} 项`
          : fieldNames[part] || "字段",
      )
      .join(" · ");
    const type = String(item.type || "");
    const hint =
      type === "extra_forbidden"
        ? "包含未支持的内容，请刷新后重试"
        : type === "string_too_short" || type === "missing"
          ? "不能为空"
          : type === "string_too_long" || type === "too_long"
            ? "超过长度或数量限制"
            : type.includes("decimal")
              ? "请检查数值范围与小数位数"
              : "请检查内容或数值范围";
    return [`${field}：${hint}`];
  });
}
