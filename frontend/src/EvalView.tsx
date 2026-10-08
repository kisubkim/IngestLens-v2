import { Fragment, useEffect, useMemo, useState } from "react";
import { api, type EvalCheck, type VlmEvalItem, type VlmEvalResult } from "./api";

const MAX_SELECTED = 4;

type Metric = { label: string; get: (r: VlmEvalItem) => number | null | undefined; fmt: (v: number) => string; lower?: boolean };

const pct = (v: number) => `${Math.round(v * 100)}%`;
const sec = (v: number) => `${v.toFixed(1)}s`;

function metrics(items: VlmEvalItem[]): Metric[] {
  const checkIds = [...new Set(items.flatMap((r) => Object.keys(r.summary.by_check)))];
  const labelOf = (id: string) => items.map((r) => r.summary.by_check[id]?.label).find(Boolean) ?? id;
  return [
    { label: "종합 점수", get: (r) => r.summary.score, fmt: pct },
    { label: "통과한 항목", get: (r) => r.summary.checks_passed / r.summary.checks_total, fmt: pct },
    ...checkIds.map((id) => ({ label: labelOf(id), get: (r: VlmEvalItem) => r.summary.by_check[id]?.score, fmt: pct })),
    { label: "OCR 문자 오류율 (낮을수록 좋음)", get: (r) => r.summary.ocr_cer, fmt: (v) => v.toFixed(3), lower: true },
    { label: "VLM 1회 평균 시간", get: (r) => r.summary.vlm_avg_seconds, fmt: sec, lower: true },
    { label: "파싱 단계 시간", get: (r) => r.summary.parse_seconds, fmt: sec, lower: true },
    { label: "VLM 오류", get: (r) => r.summary.vlm_errors, fmt: String, lower: true },
    { label: "max_tokens 잘림", get: (r) => r.summary.vlm_truncated, fmt: String, lower: true },
  ];
}

function fmtValue(v: any): string {
  if (v === null || v === undefined) return "";
  if (Array.isArray(v)) return v.filter((x) => x !== "" && x !== null).join(", ") || "없음";
  if (typeof v === "object") return v.missing?.length ? `누락: ${v.missing.join(", ")}` : "";
  return String(v);
}

function CheckCell({ c }: { c?: EvalCheck }) {
  if (!c) return <td className="muted">—</td>;
  const value = fmtValue(c.value);
  return (
    <td className={c.pass ? "pass" : "fail"}>
      <span className="mark">{c.pass ? "✓" : "✗"}</span> {pct(c.score)}
      {value && <div className="muted">{value}</div>}
    </td>
  );
}

export default function EvalView() {
  const [items, setItems] = useState<VlmEvalItem[] | null>(null);
  const [dir, setDir] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [details, setDetails] = useState<Record<string, VlmEvalResult>>({});
  const [error, setError] = useState<string | null>(null);
  const [dataset, setDataset] = useState<string | null>(null);

  useEffect(() => {
    api
      .vlmEvals()
      .then((res) => {
        setItems(res.items);
        setDir(res.dir);
        const first = res.items[0]?.dataset ?? null;
        setDataset(first);
        setSelected(res.items.filter((r) => r.dataset === first).slice(0, 2).map((r) => r.file));
        if (res.errors.length) setError(res.errors.map((e) => `${e.file}: ${e.error}`).join("\n"));
      })
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    for (const file of selected) {
      if (details[file]) continue;
      api
        .vlmEval(file)
        .then((r) => setDetails((prev) => ({ ...prev, [file]: r })))
        .catch((e) => setError(String(e)));
    }
  }, [selected, details]);

  const chosen = useMemo(
    () => selected.map((f) => items?.find((r) => r.file === f)).filter((r): r is VlmEvalItem => !!r),
    [selected, items],
  );
  const loaded = chosen.map((r) => details[r.file]).filter((r): r is VlmEvalResult => !!r);

  if (!items) return <div className="placeholder">{error ?? "불러오는 중…"}</div>;

  const datasetNames = [...new Set(items.map((r) => r.dataset ?? ""))];
  const shown = items.filter((r) => (r.dataset ?? "") === (dataset ?? ""));
  const pickDataset = (d: string) => {
    setDataset(d);
    setSelected(items.filter((r) => (r.dataset ?? "") === d).slice(0, 2).map((r) => r.file));
  };

  const toggle = (file: string) =>
    setSelected((prev) =>
      prev.includes(file) ? prev.filter((f) => f !== file) : prev.length >= MAX_SELECTED ? prev : [...prev, file],
    );

  const datasets = new Set(chosen.map((r) => r.dataset_version));
  const prompts = new Set(chosen.map((r) => r.prompts_sha));
  const cases = loaded.length
    ? [...new Map(loaded.flatMap((r) => r.pages).map((p) => [`${p.doc}#${p.id}`, p])).values()]
    : [];

  return (
    <div className="evals">
      <h2>VLM 평가 비교</h2>
      {error && <div className="error-box">{error}</div>}
      <p className="muted">
        같은 평가 세트(합성 <code>evals/vlm/</code>, 실제 문서 <code>evals/samples/</code>)를 모델마다 돌린 결과를 나란히 비교합니다. 결과 파일 위치: <code>{dir}</code>
        <br />새 결과 만들기: <code>python scripts/eval_vlm.py [--cases evals/samples/cases.json] --models &lt;models.yaml&gt; --name "&lt;이름&gt;" --notes "&lt;GPU, 양자화 등&gt;"</code>
      </p>

      <div className="card">
        <h3>결과 파일 (최대 {MAX_SELECTED}개 선택)</h3>
        {datasetNames.length > 1 && (
          <div className="dataset-tabs">
            평가 세트:
            {datasetNames.map((d) => (
              <button key={d} className={d === dataset ? "active" : ""} onClick={() => pickDataset(d)}>
                {d} <span className="muted">{items.filter((r) => (r.dataset ?? "") === d).length}</span>
              </button>
            ))}
          </div>
        )}
        {shown.length ? (
          <table className="eval-table">
            <thead>
              <tr>
                <th />
                <th>이름</th>
                <th>VLM 모델</th>
                <th>실행 시각</th>
                <th>종합</th>
                <th>통과</th>
                <th>VLM 평균</th>
                <th>메모</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.file} className={selected.includes(r.file) ? "selected" : ""} onClick={() => toggle(r.file)}>
                  <td>
                    <input type="checkbox" readOnly checked={selected.includes(r.file)} />
                  </td>
                  <td>{r.name}</td>
                  <td className="mono">{r.models.vlm?.model ?? "없음"}</td>
                  <td className="num">{new Date(r.created_at).toLocaleString()}</td>
                  <td className="num">{pct(r.summary.score)}</td>
                  <td className="num">
                    {r.summary.checks_passed}/{r.summary.checks_total}
                  </td>
                  <td className="num">{r.summary.vlm_avg_seconds !== null ? sec(r.summary.vlm_avg_seconds) : "—"}</td>
                  <td className="muted">{r.notes}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="muted">결과 파일이 없습니다.</div>
        )}
      </div>

      {datasets.size > 1 && (
        <div className="notice">평가 세트 버전이 서로 다른 결과가 섞여 있습니다. 같은 문서로 잰 결과가 아니므로 점수를 그대로 비교할 수 없습니다.</div>
      )}
      {prompts.size > 1 && (
        <div className="notice">prompt가 서로 다른 결과가 섞여 있습니다. 차이가 모델 때문인지 prompt 때문인지 구분해서 보세요.</div>
      )}

      {chosen.length > 0 && (
        <div className="card">
          <h3>요약</h3>
          <table className="eval-table compare">
            <thead>
              <tr>
                <th />
                {chosen.map((r) => (
                  <th key={r.file}>
                    {r.name}
                    <div className="muted mono">
                      {r.models.vlm?.model} · {r.git_commit ?? "?"} · 세트 {r.dataset_version}
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {metrics(chosen).map((m) => {
                const vals = chosen.map((r) => m.get(r));
                const nums = vals.filter((v): v is number => typeof v === "number");
                const best = nums.length > 1 ? (m.lower ? Math.min(...nums) : Math.max(...nums)) : null;
                return (
                  <tr key={m.label}>
                    <th>{m.label}</th>
                    {vals.map((v, i) => (
                      <td key={chosen[i].file} className={`num ${v === best && nums.some((n) => n !== best) ? "best" : ""}`}>
                        {typeof v === "number" ? m.fmt(v) : "—"}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {cases.map((c) => {
        const per = loaded.map((r) => r.pages.find((p) => p.doc === c.doc && p.id === c.id));
        const checkIds = [...new Set(per.flatMap((p) => p?.checks.map((k) => k.id) ?? []))];
        return (
          <div className="card" key={`${c.doc}#${c.id}`}>
            <h3>
              {c.title} <span className="muted">· {c.doc} {c.page}페이지</span>
            </h3>
            <table className="eval-table compare">
              <thead>
                <tr>
                  <th />
                  {loaded.map((r) => (
                    <th key={r.file}>{r.name}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr>
                  <th>페이지 점수</th>
                  {per.map((p, i) => (
                    <td key={loaded[i].file} className="num">
                      {p?.score !== null && p?.score !== undefined ? pct(p.score) : "—"}
                      {p?.vlm_seconds ? <span className="muted"> · VLM {sec(p.vlm_seconds)}</span> : null}
                    </td>
                  ))}
                </tr>
                {checkIds.map((id) => (
                  <tr key={id}>
                    <th>{per.flatMap((p) => p?.checks ?? []).find((k) => k.id === id)?.label}</th>
                    {per.map((p, i) => (
                      <CheckCell key={loaded[i].file} c={p?.checks.find((k) => k.id === id)} />
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            <details>
              <summary>출력 비교</summary>
              <div className="eval-outputs" style={{ gridTemplateColumns: `repeat(${loaded.length + (c.expected_text ? 1 : 0)}, minmax(0, 1fr))` }}>
                {c.expected_text && (
                  <div>
                    <h4>정답</h4>
                    <pre>{c.expected_text}</pre>
                  </div>
                )}
                {per.map((p, i) => (
                  <div key={loaded[i].file}>
                    <h4>
                      {loaded[i].name} <span className="muted">· 분류 {p?.label ?? "—"}</span>
                    </h4>
                    {p?.elements.map((e, j) => (
                      <Fragment key={j}>
                        <div className="muted mono">
                          {e.type} · {e.source_tool}
                          {e.meta.figure_type ? ` · TYPE ${e.meta.figure_type}` : ""}
                        </div>
                        <pre>{e.content}</pre>
                      </Fragment>
                    ))}
                  </div>
                ))}
              </div>
            </details>
          </div>
        );
      })}
    </div>
  );
}
