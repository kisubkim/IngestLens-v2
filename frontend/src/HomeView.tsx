import { useEffect, useState } from "react";
import { api, displayName, type Doc, type Overview } from "./api";

export function fmtBytes(bytes: number | null | undefined) {
  if (bytes === null || bytes === undefined) return "없음";
  if (bytes >= 2 ** 30) return `${(bytes / 2 ** 30).toFixed(1)} GB`;
  if (bytes >= 2 ** 20) return `${(bytes / 2 ** 20).toFixed(1)} MB`;
  return `${Math.ceil(bytes / 1024)} KB`;
}

const STATUS_LABEL: Record<string, string> = { succeeded: "성공", failed: "실패", running: "실행 중", queued: "대기", cancelled: "취소" };

/** First screen: what is stored and indexed. `version` changes whenever the document list changes. */
export default function HomeView({ version, onOpen }: { version: string; onOpen: (doc: Doc) => void }) {
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .overview()
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e) => setError(String(e)));
  }, [version]);

  if (!data) return <div className="placeholder">{error ?? "불러오는 중…"}</div>;
  const { documents, runs, vectors, storage } = data;
  const maxStore = Math.max(1, ...storage.items.map((i) => i.bytes ?? 0));

  return (
    <div className="home">
      <h2>임베딩 DB 현황</h2>
      {!documents.count && (
        <div className="placeholder home-empty">아직 올린 문서가 없습니다. 왼쪽 "문서 업로드"로 PDF, Office, 이미지 파일을 올리세요.</div>
      )}

      <div className="home-cards">
        <div className="card stat-card">
          <h3>문서</h3>
          <div className="big">{documents.count}개</div>
          <div className="muted">
            원본 {fmtBytes(documents.bytes)} · {documents.pages.toLocaleString()}페이지
          </div>
          <div className="muted">
            {Object.entries(documents.by_format)
              .map(([f, n]) => `${f} ${n}`)
              .join(" · ")}
          </div>
        </div>
        <div className="card stat-card">
          <h3>임베딩</h3>
          <div className="big">{vectors.total.toLocaleString()} 벡터</div>
          <div className="muted">청크 {data.chunks.toLocaleString()}개 (문서별 최신 실행)</div>
          <div className={vectors.embedding_configured ? "muted" : "warn-text"}>
            모델 {vectors.embedding_model}
            {!vectors.embedding_configured && " (테스트용, 검색 품질 낮음)"}
          </div>
        </div>
        <div className="card stat-card">
          <h3>실행</h3>
          <div className="big">{runs.total}회</div>
          <div className="muted">
            {Object.entries(runs.by_status)
              .map(([s, n]) => `${STATUS_LABEL[s] ?? s} ${n}`)
              .join(" · ") || "실행 기록 없음"}
          </div>
        </div>
        <div className="card stat-card">
          <h3>디스크 사용량</h3>
          <div className="big">{fmtBytes(storage.bytes)}</div>
          <div className="muted mono">{storage.data_dir}</div>
        </div>
      </div>

      <div className="home-split">
        <section className="card">
          <h3>저장 공간</h3>
          <table className="eval-table">
            <tbody>
              {storage.items.map((i) => (
                <tr key={i.key}>
                  <th>{i.label}</th>
                  <td className="bar-cell">
                    <span className="usage-bar" style={{ width: `${((i.bytes ?? 0) / maxStore) * 100}%` }} />
                  </td>
                  <td className="num">{fmtBytes(i.bytes)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {vectors.collections.length > 0 && (
            <>
              <h3 className="sub">벡터 컬렉션</h3>
              <table className="eval-table">
                <tbody>
                  {vectors.collections.map((c) => (
                    <tr key={c.name}>
                      <th className="mono">{c.model}</th>
                      <td className="muted">{c.dim ? `${c.dim}차원` : ""}</td>
                      <td className="num">{c.points.toLocaleString()} 벡터</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </section>

        <section className="card">
          <h3>최근 문서</h3>
          {data.recent.length ? (
            <table className="eval-table recent-docs">
              <tbody>
                {data.recent.map((d) => (
                  <tr key={d.id} onClick={() => onOpen(d)}>
                    <th title={d.filename}>{displayName(d.filename)}</th>
                    <td className="muted">
                      {fmtBytes(d.size)}
                      {d.page_count ? ` · ${d.page_count}p` : ""}
                    </td>
                    <td className="num muted">{d.chunks ? `청크 ${d.chunks}` : ""}</td>
                    <td>{d.latest_run ? <span className={`badge ${d.latest_run.status}`}>{d.latest_run.status}</span> : <span className="badge">미실행</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="muted">없음</div>
          )}
        </section>
      </div>
    </div>
  );
}
