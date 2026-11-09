export const stateLabels: Record<string, string> = {
  COMPLETED: "완료",
  RUNNING: "실행 중",
  SCHEDULED: "예약·대기",
  PENDING: "준비 중",
  FAILED: "실패",
  CANCELLED: "취소",
  CANCELLING: "취소 중",
  CRASHED: "실행 오류",
  PAUSED: "일시정지",
};
export function dateLabel(value?: string | number | null) {
  if (value === null || value === undefined || value === "") return "—";
  return new Date(value).toLocaleString("ko-KR");
}
export function durationLabel(seconds?: number | null) {
  if (seconds === null || seconds === undefined) return "—";
  const rounded = Math.max(0, Math.floor(seconds));
  if (rounded < 60) return `${rounded}초`;
  if (rounded < 3600) return `${Math.floor(rounded / 60)}분 ${rounded % 60}초`;
  return `${Math.floor(rounded / 3600)}시간 ${Math.floor((rounded % 3600) / 60)}분`;
}
export function metricLabel(value: number | undefined, percentage = false) {
  return value === undefined
    ? "—"
    : percentage
      ? `${(value * 100).toFixed(1)}%`
      : value.toFixed(3);
}

export function runDurationLabel(run?: {
  state_type: string;
  start_time: string | null;
  total_run_time?: number;
}): string {
  if (!run) return "—";
  if (run.state_type === "RUNNING" && run.start_time) {
    return durationLabel(
      (Date.now() - new Date(run.start_time).getTime()) / 1000,
    );
  }
  return durationLabel(run.total_run_time);
}
