import { useEffect, useMemo, useState } from "react";
import { api, streamRun, type Decision, type Run, type RunEvent } from "./api";
import ChunkView from "./ChunkView";
import EmbeddingView from "./EmbeddingView";
import ParseReport from "./ParseReport";
import SearchView from "./SearchView";

const STEP_LABELS: Record<string, string> = {
  intake: "형식 판별",
  profile: "콘텐츠 분석",
  strategy: "전략 결정",
  parse: "파싱",
  chunk: "청킹",
  embed: "임베딩",
};

type StepState = "pending" | "running" | "done" | "failed" | "stopped";
type Filter = "all" | "decision" | "warning";
type View = "progress" | "parse" | "chunk" | "embed" | "search";

function stepStates(steps: string[], events: RunEvent[]): Record<string, StepState> {
  const s: Record<string, StepState> = Object.fromEntries(steps.map((k) => [k, "pending"]));
  for (const e of events) {
    if (!e.step) continue;
    if (e.type === "step_started") s[e.step] = "running";
    if (e.type === "step_finished") s[e.step] = "done";
    if (e.type === "error") s[e.step] = "failed";
  }
  // A cancelled run leaves its current step "running"; show it as stopped.
  if (events.some((e) => e.type === "run_finished")) for (const k of steps) if (s[k] === "running") s[k] = "stopped";
  return s;
}

function Value({ v }: { v: unknown }) {
  if (v === null || v === undefined) return <span className="muted">—</span>;
  if (typeof v === "object") return <code className="json">{JSON.stringify(v)}</code>;
  return <>{String(v)}</>;
}

function DecisionDetail({ d }: { d: Decision }) {
  return (
    <div className="decision">
      <div className="decision-head">
        <span className="step-tag">{STEP_LABELS[d.step] ?? d.step}</span>
        <strong>{d.subject}</strong>
      </div>
      <div className="choice">{d.choice}</div>
      <dl className="kv">
        <dt>규칙</dt>
        <dd>
          <code>{d.rule_id ?? "—"}</code>
        </dd>
        <dt>신뢰도</dt>
        <dd>
          {d.confidence !== null ? (
            <span className="conf">
              <span className="conf-bar" style={{ width: `${d.confidence * 100}%` }} />
              {(d.confidence * 100).toFixed(0)}%
            </span>
          ) : (
            "—"
          )}
        </dd>
      </dl>
      {d.reasoning && <p className="reasoning">{d.reasoning}</p>}
      <h4>근거 입력값</h4>
      <table className="inputs">
        <tbody>
          {Object.entries(d.inputs).map(([k, v]) => (
            <tr key={k}>
              <th>{k}</th>
              <td>
                <Value v={v} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {d.alternatives.length > 0 && (
        <>
          <h4>선택하지 않은 대안</h4>
          <ul className="alts">
            {d.alternatives.map((a, i) => (
              <li key={i}>
                <strong>{a.choice}</strong> — {a.reason_rejected}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function SummaryCards({ summary }: { summary: Record<string, any> }) {
  const { profile, plan, parse, chunk, embed, office } = summary;
  return (
    <div className="cards">
      {office && (
        <section className="card">
          <h3>Office 구조</h3>
          <div className="big">
            {office.kind} · {office.renderer === "native" ? "직접 렌더링" : "LibreOffice"}
          </div>
          {office.kind === "pptx" && (
            <div className="muted">
              슬라이드 {office.slides} · 노트 {office.with_notes} · 차트 {office.charts}
            </div>
          )}
          {office.kind === "docx" && (
            <div className="muted">
              헤딩 {office.headings} · 이미지 {office.images}
            </div>
          )}
          {office.kind === "xlsx" &&
            (office.sheets as { sheet: string; rows: number; cols: number; truncated: boolean }[]).map((sh) => (
              <div key={sh.sheet} className="muted">
                {sh.sheet}: {sh.rows}행 × {sh.cols}열{sh.truncated ? " (잘림)" : ""}
              </div>
            ))}
        </section>
      )}
      {profile && (
        <section className="card">
          <h3>문서 프로파일</h3>
          <div className="big">{profile.document_type}</div>
          {Object.entries(profile.label_ratios as Record<string, number>).map(([k, r]) => (
            <div key={k} className="ratio-row">
              <span>{k}</span>
              <span className="ratio-track">
                <span className="ratio-fill" style={{ width: `${r * 100}%` }} />
              </span>
              <span className="num">{profile.label_counts[k]}p</span>
            </div>
          ))}
        </section>
      )}
      {plan && (
        <section className="card">
          <h3>처리 전략</h3>
          <div className="big">{plan.chunking.strategy}</div>
          <div className="muted">
            target {plan.chunking.target_tokens} tok · overlap {plan.chunking.overlap_tokens}
          </div>
          {Object.entries(plan.parser_usage as Record<string, number>).map(([k, n]) => (
            <div key={k} className="kv-row">
              <code>{k}</code>
              <span className="num">{n}p</span>
            </div>
          ))}
        </section>
      )}
      {parse && (
        <section className="card">
          <h3>파싱</h3>
          <div className="big">{parse.elements} elements</div>
          {Object.entries(parse.by_type as Record<string, number>).map(([k, n]) => (
            <div key={k} className="kv-row">
              <span>{k}</span>
              <span className="num">{n}</span>
            </div>
          ))}
          {parse.vlm_enabled ? (
            <div className="muted">
              VLM {parse.vlm_calls}회 · 오류 {parse.vlm_errors} · 평균 {parse.vlm_avg_seconds ?? "—"}s · 그림 {parse.figures_described}/
              {parse.figure_regions}
              {parse.tables_reextracted ? ` · 표 재추출 ${parse.tables_reextracted}` : ""}
            </div>
          ) : (
            parse.figure_regions > 0 && <div className="muted warn-text">VLM 미설정: 그림 {parse.figure_regions}개 설명 안 됨</div>
          )}
        </section>
      )}
      {chunk && chunk.count > 0 && (
        <section className="card">
          <h3>청킹</h3>
          <div className="big">{chunk.count} chunks</div>
          <div className="muted">
            tokens min {chunk.tokens_min} · avg {chunk.tokens_avg} · max {chunk.tokens_max}
          </div>
          <div className="muted">
            짧음 {chunk.too_short} · 김 {chunk.too_long}
          </div>
        </section>
      )}
      {embed && (
        <section className="card">
          <h3>임베딩</h3>
          <div className="big">{embed.model}</div>
          <div className="muted">
            dim {embed.dim} · {embed.count} vectors · {embed.chunks_per_s ?? "—"}/s
          </div>
          <div className="muted">
            norm {embed.norm_min}–{embed.norm_max}
          </div>
        </section>
      )}
    </div>
  );
}

export default function RunView({ runId, documentId, onFinished }: { runId: string; documentId: string; onFinished: () => void }) {
  const [run, setRun] = useState<Run | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [selected, setSelected] = useState<Decision | null>(null);
  const [view, setView] = useState<View>("progress");

  useEffect(() => {
    api.run(runId).then(setRun);
    return streamRun(runId, (ev) => {
      setEvents((prev) => (prev.some((p) => p.id === ev.id) ? prev : [...prev, ev]));
      if (ev.type === "step_started" || ev.type === "step_finished" || ev.type === "run_finished" || ev.type === "error") api.run(runId).then(setRun);
      if (ev.type === "run_finished") onFinished();
    });
  }, [runId, onFinished]);

  const steps = run?.steps ?? Object.keys(STEP_LABELS);
  const states = useMemo(() => stepStates(steps, events), [steps, events]);
  const progress = useMemo(() => {
    const p: Record<string, { done: number; total: number; vlm?: number }> = {};
    for (const e of events)
      if (e.type === "progress" && e.step && e.data.total) p[e.step] = { done: e.data.done, total: e.data.total, vlm: e.data.vlm_calls };
    return p;
  }, [events]);

  // The report needs page profiles (profile step) and elements (parse step); a finished run also has what it has.
  const finished = !!run && !["queued", "running"].includes(run.status);
  const ready: Record<View, boolean> = {
    progress: true,
    parse: states.parse === "done" || finished,
    chunk: states.chunk === "done",
    embed: states.embed === "done",
    search: states.embed === "done",
  };

  // Progress events drive the node bars; the log shows only the latest one per step.
  const lastProgress = new Set(Object.keys(progress).map((s) => events.findLast((e) => e.type === "progress" && e.step === s)?.id));
  const shown = events.filter((e) =>
    filter === "all"
      ? e.type !== "progress" || lastProgress.has(e.id)
      : filter === "decision"
        ? e.type === "decision"
        : e.type === "warning" || e.type === "error",
  );

  return (
    <div className="run">
      <div className="pipeline">
        {steps.map((s, i) => (
          <div key={s} className="pipe-item">
            <div className={`node ${states[s]}`}>
              <div className="node-name">{STEP_LABELS[s] ?? s}</div>
              <div className="node-sub">{s}</div>
              {progress[s] && states[s] === "running" && (
                <>
                  <div className="node-progress">
                    <span style={{ width: `${(progress[s].done / progress[s].total) * 100}%` }} />
                  </div>
                  <div className="node-count">
                    {progress[s].done}/{progress[s].total}
                    {progress[s].vlm ? ` · VLM ${progress[s].vlm}` : ""}
                  </div>
                </>
              )}
            </div>
            {i < steps.length - 1 && <div className="arrow" />}
          </div>
        ))}
        <span className={`badge ${run?.status ?? "queued"}`}>{run?.status ?? "…"}</span>
        {(run?.status === "running" || run?.status === "queued") && (
          <button className="cancel" onClick={() => api.cancelRun(runId).catch(() => undefined)}>
            실행 취소
          </button>
        )}
      </div>
      {run?.error && <div className="error-box">{run.error}</div>}

      <nav className="view-tabs">
        {(
          [
            ["progress", "진행 현황"],
            ["parse", "파싱 리포트"],
            ["chunk", "청킹"],
            ["embed", "임베딩"],
            ["search", "검색"],
          ] as [View, string][]
        ).map(([v, label]) => (
          <button key={v} className={view === v ? "on" : ""} disabled={!ready[v]} onClick={() => setView(v)}>
            {label}
          </button>
        ))}
      </nav>

      {view === "parse" && ready.parse ? (
        <ParseReport runId={runId} docId={documentId} />
      ) : view === "chunk" && ready.chunk ? (
        <ChunkView runId={runId} docId={documentId} stats={run?.summary.chunk} />
      ) : view === "embed" && ready.embed ? (
        <EmbeddingView runId={runId} model={run?.summary.embed?.model} />
      ) : view === "search" && ready.search ? (
        <SearchView runId={runId} docId={documentId} />
      ) : (
        <>
      {run && <SummaryCards summary={run.summary} />}

      <div className="split">
        <section className="card timeline">
          <div className="timeline-head">
            <h3>진행 로그</h3>
            <div className="tabs">
              {(["all", "decision", "warning"] as Filter[]).map((f) => (
                <button key={f} className={filter === f ? "on" : ""} onClick={() => setFilter(f)}>
                  {f === "all" ? "전체" : f === "decision" ? "결정" : "경고/오류"}
                </button>
              ))}
            </div>
          </div>
          <ol>
            {shown.map((e) => (
              <li
                key={e.id}
                className={`ev ${e.type} ${selected && e.type === "decision" && e.data.id === selected.id ? "sel" : ""}`}
                onClick={() => e.type === "decision" && setSelected(e.data as Decision)}
              >
                <span className="ts">{new Date(e.ts).toLocaleTimeString()}</span>
                <span className="ev-step">{e.step ? (STEP_LABELS[e.step] ?? e.step) : "run"}</span>
                <span className="ev-type">{e.type}</span>
                <span className="ev-msg">
                  {e.message}
                  {e.type === "step_finished" && e.data.seconds !== undefined && <span className="muted"> ({e.data.seconds}s)</span>}
                </span>
              </li>
            ))}
          </ol>
        </section>
        <section className="card detail">
          {selected ? <DecisionDetail d={selected} /> : <div className="muted">왼쪽 로그에서 결정 항목을 선택하면 근거가 표시됩니다.</div>}
        </section>
      </div>

        </>
      )}
    </div>
  );
}
