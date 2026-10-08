import { useEffect, useMemo, useState } from "react";
import { api, pageImage, type Decision, type Element, type ElementStats, type PageProfile } from "./api";
import PageOverlay from "./PageOverlay";

const FEATURE_LABELS: [keyof PageProfile["features"], string][] = [
  ["text_chars", "텍스트 문자 수"],
  ["text_area_ratio", "텍스트 영역 비율"],
  ["images", "이미지 수"],
  ["image_area_ratio", "이미지 영역 비율"],
  ["drawings", "벡터 드로잉 수"],
  ["tables", "표 수"],
  ["table_area_ratio", "표 영역 비율"],
  ["table_text_share", "표 안 텍스트 비율"],
];
// Labels whose default parser (strategy_rules.yaml) is a VLM parser.
const VLM_LABELS = new Set(["scanned", "diagram", "chart", "image_heavy"]);

function LabelBadge({ label }: { label: string }) {
  return <span className={`label-badge l-${label}`}>{label}</span>;
}

// Stacking order, bottom to top. Other types (e.g. pptx_notes) go last with a neutral color.
const TYPE_ORDER = ["title", "text", "table", "figure"];
const typeRank = (t: string) => (TYPE_ORDER.includes(t) ? TYPE_ORDER.indexOf(t) : TYPE_ORDER.length);

function ParseStats({ stats, current, onPick }: { stats: ElementStats; current: number | null; onPick: (page: number) => void }) {
  const max = Math.max(1, ...stats.pages.map((p) => p.total));
  const types = Object.keys(stats.by_type).sort((a, b) => typeRank(a) - typeRank(b));
  const vlmPages = stats.pages.filter((p) => Object.keys(p.by_tool).some((t) => t.startsWith("vlm_"))).length;
  const step = Math.ceil(stats.pages.length / 30); // label every n-th page so numbers do not overlap
  return (
    <div className="chunk-stats parse-stats">
      <div className="card stat-card">
        <h3>파싱 결과</h3>
        <div className="big">{stats.total} elements</div>
        <div className="type-counts">
          {types.map((t) => (
            <span key={t}>
              <span className={`type-dot t-${t}`} /> {t} {stats.by_type[t]}
            </span>
          ))}
        </div>
        <div className="muted">
          {stats.pages.length}페이지 · 평균 {(stats.total / Math.max(1, stats.pages.length)).toFixed(1)}개/페이지
        </div>
        <div className="muted">VLM으로 읽은 페이지 {vlmPages}</div>
        {stats.empty_pages.length > 0 && (
          <div className="empty-pages">
            element 없음:{" "}
            {stats.empty_pages.map((p) => (
              <button key={p} className="link" onClick={() => onPick(p)}>
                p.{p + 1}
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="card">
        <div className="hist-title">페이지별 element 개수 (막대를 누르면 그 페이지로 이동)</div>
        <div className="page-bars">
          {stats.pages.map((p) => (
            <button
              key={p.page}
              className={`page-bar ${current === p.page ? "sel" : ""} ${p.total ? "" : "empty"}`}
              onClick={() => onPick(p.page)}
              title={`페이지 ${p.page + 1}${p.label ? ` (${p.label})` : ""}: ${p.total}개\n${Object.entries(p.by_type)
                .map(([t, n]) => `${t} ${n}`)
                .join(", ")}\n${Object.entries(p.by_tool)
                .map(([t, n]) => `${t} ${n}`)
                .join(", ")}`}
            >
              <span className="page-bar-n">{p.total || ""}</span>
              <span className="page-bar-stack" style={{ height: `${(p.total / max) * 100}%` }}>
                {Object.entries(p.by_type)
                  .sort(([a], [b]) => typeRank(b) - typeRank(a))
                  .map(([t, n]) => (
                    <span key={t} className={`seg t-${t}`} style={{ flexGrow: n }} />
                  ))}
              </span>
              <span className="page-bar-lab">{p.page % step === 0 || current === p.page ? p.page + 1 : ""}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function PageDetail({ runId, docId, profile, onNav }: { runId: string; docId: string; profile: PageProfile; onNav: (d: number) => void }) {
  const [elements, setElements] = useState<Element[]>([]);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [hover, setHover] = useState<number | null>(null);
  const page = profile.page;

  useEffect(() => {
    api.elements(runId, page).then(setElements);
    api.decisions(runId, `page ${page + 1}`).then(setDecisions);
  }, [runId, page]);

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement) return;
      if (e.key === "ArrowLeft") onNav(-1);
      if (e.key === "ArrowRight") onNav(1);
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onNav]);

  const f = profile.features;
  const ev = f.evidence;

  return (
    <div className="page-detail">
      <div className="page-detail-head">
        <button onClick={() => onNav(-1)}>←</button>
        <strong>페이지 {page + 1}</strong>
        <button onClick={() => onNav(1)}>→</button>
        <LabelBadge label={profile.label} />
        <code>{profile.parser}</code>
        <span className="muted">
          규칙 <code>{profile.rule_id}</code> · 신뢰도 {(profile.confidence * 100).toFixed(0)}%
        </span>
      </div>
      {VLM_LABELS.has(profile.label) && !profile.parser?.startsWith("vlm_") && (
        <div className="fallback-note">
          이 유형은 VLM 파서 대상이지만 VLM endpoint가 설정되지 않아 <code>{profile.parser}</code>로 대체했습니다. 그림 내용은
          추출되지 않습니다. (진행 현황 → "parser selection" 결정 참고)
        </div>
      )}

      <div className="page-detail-body">
        <PageOverlay
          docId={docId}
          page={page}
          boxes={elements.map((el) => ({ key: el.id, bbox: el.bbox, cls: `t-${el.type}` }))}
          hot={hover}
          onHover={(k) => setHover(k as number | null)}
        />

        <div className="page-side">
          <section>
            <h4>분류 근거</h4>
            <table className="inputs">
              <tbody>
                {FEATURE_LABELS.map(([k, label]) => {
                  const cond = Object.entries(ev.conditions).find(([ck]) => ck.split("_").slice(1).join("_") === k);
                  return (
                    <tr key={k} className={cond ? "hit-row" : ""}>
                      <th>{label}</th>
                      <td className="num">{String(f[k])}</td>
                      <td className="muted">{cond ? `${cond[0].startsWith("min") ? "≥" : "≤"} ${cond[1].threshold}` : ""}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <div className="rule-chain">
              {ev.evaluated.map((r) => (
                <span key={r.rule} className={r.matched ? "rule on" : "rule"}>
                  {r.matched ? "✓" : "✗"} {r.rule}
                </span>
              ))}
              {!ev.evaluated.some((r) => r.matched) && <span className="rule on">→ 기본값 {profile.rule_id}</span>}
            </div>
            {decisions.map((d) => (
              <div key={d.id} className="page-decision">
                <strong>{d.choice}</strong> <code>{d.rule_id}</code>
                {d.reasoning && <div className="muted">{d.reasoning}</div>}
              </div>
            ))}
          </section>

          <section>
            <h4>추출 결과 ({elements.length} elements)</h4>
            <div className="elements">
              {elements.map((el) => (
                <div
                  key={el.id}
                  className={`element t-${el.type} ${hover === el.id ? "hot" : ""}`}
                  onMouseEnter={() => setHover(el.id)}
                  onMouseLeave={() => setHover(null)}
                >
                  <div className="element-head">
                    <span className={`type-dot t-${el.type}`} />
                    {el.type}
                    {el.meta?.figure_type && <span className="tag">{el.meta.figure_type}</span>}
                    {el.meta?.reextracted && <span className="tag">VLM 재추출 (빈 셀 {Math.round((el.meta.empty_cell_ratio ?? 0) * 100)}%)</span>}
                    <span className="muted">
                      · {el.source_tool}
                      {el.meta?.region_source && ` · 영역 ${el.meta.region_source}`}
                      {el.meta?.vlm_seconds !== undefined && ` · ${el.meta.vlm_seconds}s`}
                    </span>
                  </div>
                  <pre>{el.content}</pre>
                </div>
              ))}
              {!elements.length && <div className="muted">추출된 element가 없습니다.</div>}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

export default function ParseReport({ runId, docId }: { runId: string; docId: string }) {
  const [pages, setPages] = useState<PageProfile[]>([]);
  const [filter, setFilter] = useState<string | null>(null);
  const [current, setCurrent] = useState<number | null>(null);
  const [stats, setStats] = useState<ElementStats | null>(null);

  useEffect(() => {
    api.pages(runId).then((ps) => {
      setPages(ps);
      setCurrent((cur) => cur ?? ps[0]?.page ?? null);
    });
    api.elementStats(runId).then(setStats).catch(() => setStats(null));
  }, [runId]);

  const pick = (page: number) => {
    setFilter(null);
    setCurrent(page);
  };

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const p of pages) c[p.label] = (c[p.label] ?? 0) + 1;
    return c;
  }, [pages]);
  const shown = filter ? pages.filter((p) => p.label === filter) : pages;

  const nav = (d: number) => {
    if (current === null) return;
    const i = shown.findIndex((p) => p.page === current);
    const next = shown[i + d];
    if (next) setCurrent(next.page);
  };

  if (!pages.length) return <div className="placeholder">프로파일링 결과가 아직 없습니다.</div>;
  const profile = pages.find((p) => p.page === current);

  return (
    <div className="parse-report">
      <div className="report-toolbar">
        <div className="chips">
          <button className={filter === null ? "on" : ""} onClick={() => setFilter(null)}>
            전체 {pages.length}
          </button>
          {Object.entries(counts).map(([label, n]) => (
            <button key={label} className={filter === label ? "on" : ""} onClick={() => setFilter(label)}>
              <LabelBadge label={label} /> {n}
            </button>
          ))}
        </div>
        <a href={`/api/runs/${runId}/parsed.md`} target="_blank" rel="noreferrer">
          파싱 결과 Markdown 보기
        </a>
      </div>

      {stats && <ParseStats stats={stats} current={current} onPick={pick} />}

      <div className="thumb-grid">
        {shown.map((p) => (
          <button key={p.page} className={`thumb ${current === p.page ? "sel" : ""}`} onClick={() => pick(p.page)}>
            <img loading="lazy" src={pageImage(docId, p.page, 40)} alt={`page ${p.page + 1}`} />
            <div className="thumb-meta">
              <span>{p.page + 1}</span>
              <LabelBadge label={p.label} />
            </div>
            <div className="thumb-sub">
              <code>{p.parser}</code>
              <span className={p.confidence < 0.6 ? "low" : ""}>{(p.confidence * 100).toFixed(0)}%</span>
            </div>
          </button>
        ))}
      </div>

      {profile && <PageDetail runId={runId} docId={docId} profile={profile} onNav={nav} />}
    </div>
  );
}
