import { useCallback, useEffect, useState } from "react";
import { api, type BackendStatus, type StatusState } from "./api";

const POLL_MS = 15000;

const STATE_LABEL: Record<StatusState, string> = { ok: "정상", warn: "주의", off: "꺼짐", error: "오류" };
const OVERALL_LABEL = { ok: "백엔드 정상", warn: "일부 주의", error: "일부 오류", down: "백엔드 연결 안 됨" } as const;

export type Overall = keyof typeof OVERALL_LABEL;

/** Polls /api/status. A failed request means the backend itself is unreachable. */
export function useBackendStatus() {
  const [status, setStatus] = useState<BackendStatus | null>(null);
  const [down, setDown] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (refresh = false) => {
    setLoading(true);
    try {
      setStatus(await api.status(refresh));
      setDown(null);
    } catch (e) {
      setDown(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(() => load(), POLL_MS);
    return () => clearInterval(timer);
  }, [load]);

  const overall: Overall | null = down ? "down" : status ? status.overall : null;
  return { status, down, overall, loading, reload: () => load(true) };
}

export function StatusBadge({ overall, onClick, active }: { overall: Overall | null; onClick: () => void; active: boolean }) {
  return (
    <button className={`status-badge ${overall ?? "pending"} ${active ? "active" : ""}`} onClick={onClick} title="백엔드 상태 자세히 보기">
      <span className="dot" />
      {overall ? OVERALL_LABEL[overall] : "상태 확인 중…"}
    </button>
  );
}

export default function StatusView({ state }: { state: ReturnType<typeof useBackendStatus> }) {
  const { status, down, overall, loading, reload } = state;
  return (
    <div className="status-view">
      <header className="doc-header">
        <div>
          <h2>백엔드 상태</h2>
          <span className="muted">
            {POLL_MS / 1000}초마다 자동으로 확인합니다
            {status && ` · 마지막 확인 ${new Date(status.checked_at).toLocaleTimeString()} · 버전 ${status.version}`}
          </span>
        </div>
        <button onClick={reload} disabled={loading}>
          {loading ? "확인 중…" : "지금 확인"}
        </button>
      </header>

      {overall && (
        <div className={`status-summary ${overall}`}>
          <span className="dot" />
          {OVERALL_LABEL[overall]}
          {down && <span className="muted"> · {down}</span>}
        </div>
      )}
      {down && (
        <div className="notice">
          화면은 열렸지만 API 서버가 응답하지 않습니다. 서버가 꺼졌거나 다시 시작하는 중일 수 있습니다. Docker로 실행했다면{" "}
          <code>docker compose ps</code>와 <code>docker compose logs app</code>으로 확인하세요.
        </div>
      )}

      {status && (
        <>
          <section className="card">
            <h3>구성 요소</h3>
            <table className="eval-table">
              <thead>
                <tr>
                  <th>항목</th>
                  <th>상태</th>
                  <th>내용</th>
                  <th>응답</th>
                </tr>
              </thead>
              <tbody>
                {status.items.map((i) => (
                  <tr key={i.key}>
                    <th>{i.label}</th>
                    <td>
                      <span className={`state-pill ${i.state}`}>{STATE_LABEL[i.state]}</span>
                    </td>
                    <td className="detail">{i.detail}</td>
                    <td className="num muted">{i.latency_ms !== null ? `${i.latency_ms}ms` : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
          <section className="card">
            <h3>실행 대기열</h3>
            <div>
              실행 중 <b className="num">{status.runs.running}</b>건 · 대기 <b className="num">{status.runs.queued}</b>건
            </div>
          </section>
          <p className="muted">
            꺼짐은 models.yaml에 주소를 비워 둔 항목입니다. 파이프라인은 멈추지 않고 대체 방식으로 처리하며, 그 사실을 실행의 근거 탭에 남깁니다.
            주의는 서버는 응답하지만 설정한 모델이 그 서버에 없다는 뜻입니다.
          </p>
        </>
      )}
    </div>
  );
}
