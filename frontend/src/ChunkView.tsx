import { useEffect, useState } from "react";
import { api, type Chunk } from "./api";
import ChunkDetail, { chunkKind } from "./ChunkDetail";

const PAGE = 100;
const TYPES = ["", "text", "title", "table", "figure"];

function Histogram({ bins }: { bins: { lo: number; hi: number; n: number }[] }) {
  const max = Math.max(1, ...bins.map((b) => b.n));
  return (
    <div className="hist">
      <div className="hist-title">청크 길이 분포 (추정 토큰)</div>
      <div className="hist-bars">
        {bins.map((b) => (
          <div key={b.lo} className="hist-col" title={`${b.lo}–${b.hi >= 1e9 ? "∞" : b.hi} tokens: ${b.n} chunks`}>
            <span className="hist-n">{b.n}</span>
            <span className="hist-bar" style={{ height: `${(b.n / max) * 100}%` }} />
            <span className="hist-lab">
              {b.lo}–{b.hi >= 1e9 ? "" : b.hi}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function ChunkView({ runId, docId, stats }: { runId: string; docId: string; stats: Record<string, any> | undefined }) {
  const [type, setType] = useState("");
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<Chunk[]>([]);
  const [total, setTotal] = useState(0);
  const [selected, setSelected] = useState<Chunk | null>(null);

  useEffect(() => {
    const t = window.setTimeout(() => setQuery(q), 300);
    return () => window.clearTimeout(t);
  }, [q]);

  useEffect(() => {
    api.chunks(runId, { type, q: query, limit: PAGE }).then((r) => {
      setItems(r.items);
      setTotal(r.total);
      setSelected((cur) => cur ?? r.items[0] ?? null);
    });
  }, [runId, type, query]);

  const more = () => api.chunks(runId, { type, q: query, limit: PAGE, offset: items.length }).then((r) => setItems((prev) => [...prev, ...r.items]));

  return (
    <div className="chunk-view">
      {stats && (
        <div className="chunk-stats">
          <div className="card stat-card">
            <h3>청킹 결과</h3>
            <div className="big">{stats.count} chunks</div>
            <div className="muted">전략 {stats.strategy}</div>
            <div className="muted">
              tokens min {stats.tokens_min} · avg {stats.tokens_avg} · max {stats.tokens_max}
            </div>
            <div className="muted">
              짧음 {stats.too_short} · 김 {stats.too_long}
            </div>
          </div>
          {stats.histogram && (
            <div className="card">
              <Histogram bins={stats.histogram} />
            </div>
          )}
        </div>
      )}

      <div className="chunk-split">
        <section className="card chunk-list">
          <div className="chunk-filters">
            <select value={type} onChange={(e) => setType(e.target.value)}>
              {TYPES.map((t) => (
                <option key={t} value={t}>
                  {t || "모든 유형"}
                </option>
              ))}
            </select>
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="본문·섹션 검색" />
          </div>
          <div className="muted">{total}개</div>
          <ol>
            {items.map((c) => {
              const kind = chunkKind(c.element_types);
              return (
                <li key={c.id} className={selected?.id === c.id ? "sel" : ""} onClick={() => setSelected(c)}>
                  <div className="chunk-row-head">
                    <span className={`type-dot t-${kind}`} />
                    <span className="num">#{c.seq}</span>
                    <span className="muted">
                      p.{c.pages.map((p) => p + 1).join(",")} · {c.tokens} tok
                    </span>
                  </div>
                  {c.section && <div className="chunk-row-sec">{c.section}</div>}
                  <div className="chunk-row-text">{c.text.slice(0, 120)}</div>
                </li>
              );
            })}
          </ol>
          {items.length < total && <button onClick={more}>더 보기</button>}
        </section>
        <section className="card">{selected ? <ChunkDetail docId={docId} chunk={selected} /> : <div className="muted">청크를 선택하세요.</div>}</section>
      </div>
    </div>
  );
}
