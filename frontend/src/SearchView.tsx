import { useEffect, useState } from "react";
import { api, type SearchHit, type SearchMode, type SearchResult } from "./api";
import ChunkDetail, { chunkKind } from "./ChunkDetail";

const MODES: [SearchMode, string][] = [
  ["hybrid", "Hybrid (RRF)"],
  ["dense", "Dense"],
  ["lexical", "BM25"],
];

function fmt(v: number | null, digits = 3) {
  return v === null || v === undefined ? "—" : v.toFixed(digits);
}

function ScoreTable({ hit, mode }: { hit: SearchHit; mode: SearchMode }) {
  const s = hit.scores;
  return (
    <table className="score-table">
      <thead>
        <tr>
          <th>dense</th>
          <th>BM25</th>
          {mode === "hybrid" && <th>RRF</th>}
          {s.rerank !== null && <th>rerank</th>}
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>
            {fmt(s.dense)} <span className="muted">{s.dense_rank ? `#${s.dense_rank}` : ""}</span>
          </td>
          <td>
            {fmt(s.lexical, 2)} <span className="muted">{s.lexical_rank ? `#${s.lexical_rank}` : ""}</span>
          </td>
          {mode === "hybrid" && <td>{fmt(s.fused, 4)}</td>}
          {s.rerank !== null && <td>{fmt(s.rerank)}</td>}
        </tr>
      </tbody>
    </table>
  );
}

export default function SearchView({ runId, docId }: { runId: string; docId: string }) {
  const [q, setQ] = useState("");
  const [mode, setMode] = useState<SearchMode>("hybrid");
  const [topK, setTopK] = useState(5);
  const [dw, setDw] = useState(1);
  const [lw, setLw] = useState(1);
  const [rerank, setRerank] = useState(false);
  const [reranker, setReranker] = useState<string | null>(null);
  const [res, setRes] = useState<SearchResult | null>(null);
  const [selected, setSelected] = useState<SearchHit | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.capabilities().then((c) => setReranker(c.reranker));
  }, []);

  const run = async () => {
    if (!q.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.search({ query: q, run_id: runId, top_k: topK, mode, rerank, dense_weight: dw, lexical_weight: lw });
      setRes(r);
      setSelected(r.hits[0] ?? null);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const orderBy = res?.reranker ? `rerank (${res.reranker})` : res?.mode === "hybrid" ? "RRF 융합 점수" : res?.mode === "dense" ? "cosine 유사도" : "BM25 점수";

  return (
    <div className="search-view">
      <section className="card search-form">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            run();
          }}
        >
          <input className="q" value={q} onChange={(e) => setQ(e.target.value)} placeholder="질의를 입력하세요" />
          <button type="submit" className="primary" disabled={busy}>
            {busy ? "검색 중…" : "검색"}
          </button>
        </form>
        <div className="search-opts">
          <span className="seg">
            {MODES.map(([m, label]) => (
              <button key={m} type="button" className={mode === m ? "on" : ""} onClick={() => setMode(m)}>
                {label}
              </button>
            ))}
          </span>
          <label>
            top-k
            <select value={topK} onChange={(e) => setTopK(Number(e.target.value))}>
              {[3, 5, 10, 20].map((k) => (
                <option key={k}>{k}</option>
              ))}
            </select>
          </label>
          {mode === "hybrid" && (
            <>
              <label>
                dense 가중치
                <input type="number" min={0} max={5} step={0.5} value={dw} onChange={(e) => setDw(Number(e.target.value))} />
              </label>
              <label>
                BM25 가중치
                <input type="number" min={0} max={5} step={0.5} value={lw} onChange={(e) => setLw(Number(e.target.value))} />
              </label>
            </>
          )}
          <label className={reranker ? "" : "muted"} title={reranker ? "" : "models.yaml reranker.base_url 미설정"}>
            <input type="checkbox" checked={rerank} disabled={!reranker} onChange={(e) => setRerank(e.target.checked)} />
            rerank {reranker ? `(${reranker})` : "(미설정)"}
          </label>
        </div>
        {res && (
          <div className="muted search-meta">
            후보 {res.candidates ?? 0}개 → 상위 {res.hits.length}개 · 순위 기준: {orderBy}
            {res.model && ` · 임베딩 ${res.model}`}
            {Object.entries(res.timings_ms).map(([k, v]) => ` · ${k} ${v}ms`)}
          </div>
        )}
        {res?.notes.map((n) => (
          <div key={n} className="muted warn-text">
            {n}
          </div>
        ))}
        {error && <div className="error-box">{error}</div>}
      </section>

      {res && (
        <div className="search-split">
          <section className="card hit-list">
            {res.hits.map((h) => (
              <div key={h.chunk_id} className={`hit-card ${selected?.chunk_id === h.chunk_id ? "sel" : ""}`} onClick={() => setSelected(h)}>
                <div className="hit-head">
                  <span className="rank">{h.rank}</span>
                  <span className={`kind-tag t-${chunkKind(h.element_types)}`}>{chunkKind(h.element_types)}</span>
                  <span className="muted">
                    p.{h.pages.map((p) => p + 1).join(",")} · #{h.seq}
                  </span>
                  {h.section && <span className="muted hit-sec">· {h.section}</span>}
                </div>
                <ScoreTable hit={h} mode={res.mode} />
                <div className="hit-text">{h.text.slice(0, 160)}</div>
              </div>
            ))}
            {!res.hits.length && <div className="muted">결과 없음</div>}
          </section>
          <section className="card">
            {selected ? (
              <ChunkDetail docId={docId} chunk={{ ...selected, id: selected.chunk_id }} />
            ) : (
              <div className="muted">결과를 선택하세요.</div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
