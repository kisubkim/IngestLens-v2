import { useEffect, useMemo, useState } from "react";
import { api, type EmbeddingPoint, type Neighbor, type Projection } from "./api";
import { chunkKind, type ChunkKind } from "./ChunkDetail";

const W = 640;
const H = 440;
const PAD = 28;
const KINDS: ChunkKind[] = ["text", "table", "figure", "title"]; // fixed order = fixed color per kind

export default function EmbeddingView({ runId, model }: { runId: string; model?: string }) {
  const [proj, setProj] = useState<Projection | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hover, setHover] = useState<EmbeddingPoint | null>(null);
  const [selected, setSelected] = useState<EmbeddingPoint | null>(null);
  const [neighbors, setNeighbors] = useState<Neighbor[]>([]);

  useEffect(() => {
    api.embeddings(runId).then(setProj).catch((e) => setError(String(e)));
  }, [runId]);

  useEffect(() => {
    if (!selected) return setNeighbors([]);
    api.neighbors(runId, selected.chunk_id, 5).then(setNeighbors);
  }, [runId, selected]);

  const scale = useMemo(() => {
    const pts = proj?.points ?? [];
    const xs = pts.map((p) => p.x);
    const ys = pts.map((p) => p.y);
    const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    const sx = (x: number) => PAD + ((x - x0) / (x1 - x0 || 1)) * (W - 2 * PAD);
    const sy = (y: number) => H - PAD - ((y - y0) / (y1 - y0 || 1)) * (H - 2 * PAD);
    return { sx, sy };
  }, [proj]);

  if (error) return <div className="error-box">{error}</div>;
  if (!proj) return <div className="placeholder">불러오는 중…</div>;
  if (!proj.count) return <div className="placeholder">{proj.note ?? "벡터가 없습니다."}</div>;

  const byId = new Map(proj.points.map((p) => [p.chunk_id, p]));
  const nbIds = new Set(neighbors.map((n) => n.chunk_id));
  const counts = KINDS.map((k) => [k, proj.points.filter((p) => chunkKind(p.element_types) === k).length] as const).filter(([, n]) => n);
  const ev = proj.explained_variance ?? [0, 0];

  return (
    <div className="embed-view">
      <div className="cards">
        <section className="card">
          <h3>임베딩 모델</h3>
          <div className="big">{model ?? "—"}</div>
          <div className="muted">
            dim {proj.dim} · {proj.count} vectors
          </div>
          {model === "dev-hash" && <div className="muted warn-text">개발용 임베딩: 분포는 문자 3-gram 유사도만 반영</div>}
        </section>
        <section className="card">
          <h3>벡터 norm</h3>
          <div className="big">{proj.norm?.mean}</div>
          <div className="muted">
            min {proj.norm?.min} · max {proj.norm?.max}
          </div>
        </section>
        <section className="card">
          <h3>2D 투영 (PCA)</h3>
          <div className="big">{((ev[0] + ev[1]) * 100).toFixed(1)}%</div>
          <div className="muted">
            PC1 {(ev[0] * 100).toFixed(1)}% · PC2 {(ev[1] * 100).toFixed(1)}% 분산 설명
          </div>
        </section>
      </div>

      <div className="embed-split">
        <section className="card scatter-card">
          <div className="legend">
            {counts.map(([k, n]) => (
              <span key={k} className="legend-item">
                <span className={`type-dot t-${k}`} />
                {k} <span className="muted">{n}</span>
              </span>
            ))}
            <span className="muted legend-hint">점을 클릭하면 가까운 청크 5개를 표시</span>
          </div>
          <div className="scatter-wrap">
            <svg viewBox={`0 0 ${W} ${H}`} className="scatter" onMouseLeave={() => setHover(null)}>
              <rect x={PAD} y={PAD} width={W - 2 * PAD} height={H - 2 * PAD} className="plot-frame" />
              <text x={W - PAD} y={H - 8} className="axis-label" textAnchor="end">
                PC1
              </text>
              <text x={8} y={PAD - 10} className="axis-label">
                PC2
              </text>
              {selected &&
                neighbors.map((n) => {
                  const p = byId.get(n.chunk_id);
                  return p ? <line key={n.chunk_id} x1={scale.sx(selected.x)} y1={scale.sy(selected.y)} x2={scale.sx(p.x)} y2={scale.sy(p.y)} className="nb-line" /> : null;
                })}
              {proj.points.map((p) => (
                <circle
                  key={p.chunk_id}
                  cx={scale.sx(p.x)}
                  cy={scale.sy(p.y)}
                  r={selected?.chunk_id === p.chunk_id ? 8 : 5}
                  className={`pt t-${chunkKind(p.element_types)} ${selected?.chunk_id === p.chunk_id ? "sel" : ""} ${nbIds.has(p.chunk_id) ? "nb" : ""} ${selected && !nbIds.has(p.chunk_id) && selected.chunk_id !== p.chunk_id ? "dim" : ""}`}
                  onMouseEnter={() => setHover(p)}
                  onClick={() => setSelected(p)}
                />
              ))}
            </svg>
            {hover && (
              <div className="tooltip" style={{ left: `${(scale.sx(hover.x) / W) * 100}%`, top: `${(scale.sy(hover.y) / H) * 100}%` }}>
                <div>
                  <strong>#{hover.seq}</strong> · {chunkKind(hover.element_types)} · p.{hover.pages.map((x) => x + 1).join(",")} · {hover.tokens} tok
                </div>
                {hover.section && <div className="muted">{hover.section}</div>}
                <div>{hover.preview.slice(0, 90)}</div>
              </div>
            )}
          </div>
        </section>

        <section className="card">
          {selected ? (
            <>
              <h3>선택한 청크</h3>
              <div className="nb-self">
                <strong>#{selected.seq}</strong> <span className="muted">p.{selected.pages.map((x) => x + 1).join(",")}</span>
                {selected.section && <span className="muted"> · {selected.section}</span>}
                <div>{selected.preview}</div>
              </div>
              <h3>가장 가까운 청크 (cosine)</h3>
              <ol className="nb-list">
                {neighbors.map((n) => (
                  <li key={n.chunk_id} onClick={() => byId.get(n.chunk_id) && setSelected(byId.get(n.chunk_id)!)}>
                    <span className="num score">{n.score.toFixed(3)}</span>
                    <span className={`type-dot t-${chunkKind(n.element_types)}`} />
                    <span className="muted">
                      #{byId.get(n.chunk_id)?.seq} · p.{n.pages.map((x) => x + 1).join(",")}
                    </span>
                    <div className="nb-preview">{n.preview}</div>
                  </li>
                ))}
              </ol>
            </>
          ) : (
            <div className="muted">왼쪽 그림에서 점을 선택하세요.</div>
          )}
        </section>
      </div>
    </div>
  );
}
