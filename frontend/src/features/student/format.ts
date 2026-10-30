/** 面向学生的日期与剩余时间文案。界面是中文，统一用 2026-10-28 15:31 这类格式，避免美式 10/28/2026 被误读。 */
function pad(value: number) {
  return String(value).padStart(2, "0");
}

/** 2026-10-28 15:31 */
export function formatDateTime(value: string | number | Date) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** 15:31 */
export function formatTime(value: string | number | Date) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** 截止时间剩余多久：3 天后截止 / 5 小时后截止 / 即将截止 / 已截止 */
export function remainingLabel(
  deadline: string,
  now: string | number | Date = Date.now(),
) {
  const diff = new Date(deadline).getTime() - new Date(now).getTime();
  if (Number.isNaN(diff)) return "";
  if (diff <= 0) return "已截止";
  const hours = diff / 3_600_000;
  if (hours < 1) return "即将截止";
  if (hours < 48) return `${Math.round(hours)} 小时后截止`;
  return `${Math.round(hours / 24)} 天后截止`;
}
