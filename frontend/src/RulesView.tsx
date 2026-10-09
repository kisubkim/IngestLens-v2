import { useEffect, useMemo, useState } from "react";
import { adminKey, api, ApiError, displayName, type Doc, type ProfilerRule, type RuleField, type RulesState } from "./api";

type Rules = Record<string, any>;

const getPath = (o: any, path: string[]) => path.reduce((v, k) => (v == null ? undefined : v[k]), o);

function setPath(o: Rules, path: string[], value: unknown): Rules {
  if (!path.length) return value as Rules;
  const [k, ...rest] = path;
  return { ...o, [k]: setPath(o?.[k] ?? {}, rest, value) };
}

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

function fmt(v: unknown) {
  if (typeof v === "boolean") return v ? "켬" : "끔";
  if (v && typeof v === "object") return "(기본 목록)";
  return String(v);
}

/** One profiler rule's conditions as rows: min_text_chars: 50 -> {kind: "min", feature: "text_chars", value: 50}. */
function conditions(when: Record<string, number>) {
  return Object.entries(when).map(([key, value]) => {
    const i = key.indexOf("_");
    return { kind: key.slice(0, i), feature: key.slice(i + 1), value };
  });
}

function RuleListEditor({ value, onChange, state, disabled }: {
  value: ProfilerRule[];
  onChange: (v: ProfilerRule[]) => void;
  state: RulesState;
  disabled: boolean;
}) {
  const features = Object.keys(state.features);
  const update = (i: number, rule: ProfilerRule) => onChange(value.map((r, j) => (j === i ? rule : r)));
  const move = (i: number, d: number) => {
    const next = [...value];
    [next[i], next[i + d]] = [next[i + d], next[i]];
    onChange(next);
  };
  const setCond = (i: number, rows: { kind: string; feature: string; value: number }[]) =>
    update(i, { ...value[i], when: Object.fromEntries(rows.map((c) => [`${c.kind}_${c.feature}`, c.value])) });

  return (
    <div className="rule-list">
      <table className="settings-table rule-table">
        <thead>
          <tr>
            <th>순서</th>
            <th>규칙 id</th>
            <th>라벨</th>
            <th>조건 (모두 맞아야 함)</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {value.map((r, i) => {
            const rows = conditions(r.when);
            return (
              <tr key={i}>
                <td>{i + 1}</td>
                <td>
                  <input className="mono" value={r.id} disabled={disabled} onChange={(e) => update(i, { ...r, id: e.target.value })} />
                </td>
                <td>
                  <select value={r.label} disabled={disabled} onChange={(e) => update(i, { ...r, label: e.target.value })}>
                    {state.labels.map((l) => <option key={l}>{l}</option>)}
                  </select>
                </td>
                <td>
                  {rows.map((c, k) => (
                    <div key={k} className="cond-row">
                      <select value={c.feature} disabled={disabled}
                        onChange={(e) => setCond(i, rows.map((x, j) => (j === k ? { ...x, feature: e.target.value } : x)))}>
                        {features.map((f) => <option key={f} value={f}>{state.features[f]} ({f})</option>)}
                      </select>
                      <select value={c.kind} disabled={disabled}
                        onChange={(e) => setCond(i, rows.map((x, j) => (j === k ? { ...x, kind: e.target.value } : x)))}>
                        <option value="min">≥</option>
                        <option value="max">≤</option>
                      </select>
                      <input type="number" min={0} step="any" value={c.value} disabled={disabled}
                        onChange={(e) => setCond(i, rows.map((x, j) => (j === k ? { ...x, value: Number(e.target.value) } : x)))} />
                      <button className="link" disabled={disabled || rows.length < 2} title="조건 지우기"
                        onClick={() => setCond(i, rows.filter((_, j) => j !== k))}>✕</button>
                    </div>
                  ))}
                  <button className="link" disabled={disabled}
                    onClick={() => setCond(i, [...rows, { kind: "min", feature: features.find((f) => !rows.some((x) => x.feature === f)) ?? features[0], value: 0 }])}>
                    + 조건
                  </button>
                </td>
                <td className="row-actions">
                  <button disabled={disabled || i === 0} title="위로" onClick={() => move(i, -1)}>↑</button>
                  <button disabled={disabled || i === value.length - 1} title="아래로" onClick={() => move(i, 1)}>↓</button>
                  <button className="danger" disabled={disabled || value.length < 2} title="규칙 지우기"
                    onClick={() => onChange(value.filter((_, j) => j !== i))}>지우기</button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <button disabled={disabled} onClick={() => onChange([...value, { id: `rule_${value.length + 1}`, label: "text", when: { min_text_chars: 200 } }])}>
        + 규칙 추가 (맨 아래)
      </button>
    </div>
  );
}

function FieldEditor({ f, value, def, onChange, state, disabled }: {
  f: RuleField;
  value: any;
  def: any;
  onChange: (v: unknown) => void;
  state: RulesState;
  disabled: boolean;
}) {
  const changed = !same(value, def);
  const id = `rule-${f.path.join("-")}`;
  let input;
  if (f.type === "rule_list") input = <RuleListEditor value={value} onChange={onChange} state={state} disabled={disabled} />;
  else if (f.type === "parser_map")
    input = (
      <table className="settings-table parser-map">
        <tbody>
          {state.labels.map((l) => (
            <tr key={l}>
              <td>{l}</td>
              <td>
                <select value={value?.[l]} disabled={disabled} onChange={(e) => onChange({ ...value, [l]: e.target.value })}>
                  {state.parsers.map((p) => <option key={p}>{p}</option>)}
                </select>
                {value?.[l] !== def?.[l] && <span className="badge pending">기본 {def?.[l]}</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  else if (f.type === "bool")
    input = (
      <label className="check">
        <input id={id} type="checkbox" checked={!!value} disabled={disabled} onChange={(e) => onChange(e.target.checked)} /> 켬
      </label>
    );
  else if (f.type === "choice")
    input = (
      <select id={id} value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
        {f.choices!.map((c) => <option key={c}>{c}</option>)}
      </select>
    );
  else if (f.type === "regex")
    input = <input id={id} className="mono" value={value ?? ""} disabled={disabled} onChange={(e) => onChange(e.target.value)} />;
  else
    input = (
      <input id={id} type="number" min={f.min} max={f.max} step={f.step ?? 1} value={value ?? ""} disabled={disabled}
        onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))} />
    );

  return (
    <div className={changed ? "setting-row rule-field changed" : "setting-row rule-field"}>
      <label htmlFor={id}>
        {f.label}
        {changed && <span className="badge pending">바꿈</span>}
        <code className="rule-path">{f.path.join(".")}</code>
      </label>
      {input}
      <div className="muted">
        {f.help}
        {f.type !== "rule_list" && f.type !== "parser_map" && (
          <>
            {" "}기본값 <b>{fmt(def)}</b>
            {f.min !== undefined && ` · 범위 ${f.min}~${f.max}`}
          </>
        )}
        {changed && (
          <button className="link" disabled={disabled} onClick={() => onChange(def)}>
            기본값으로
          </button>
        )}
      </div>
    </div>
  );
}

export default function RulesView({ agent, onAgent, selectedDoc, onRerun }: {
  agent: string;
  onAgent: (agent: string) => void;
  selectedDoc: Doc | null;
  onRerun: () => void;
}) {
  const [state, setState] = useState<RulesState | null>(null);
  const [draft, setDraft] = useState<Rules | null>(null);
  const [apiKey, setApiKey] = useState(() => adminKey.get());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const apply = (s: RulesState) => {
    setState(s);
    setDraft(structuredClone(s.rules));
  };
  useEffect(() => {
    api.rules().then(apply).catch((e) => setError(String(e)));
  }, []);

  const fields = useMemo(() => state?.fields.filter((f) => f.agent === agent) ?? [], [state, agent]);
  if (!state || !draft) return <div className="placeholder">{error ?? "불러오는 중…"}</div>;

  const canEdit = state.editable_here || state.key_required;
  const dirty = !same(draft, state.rules);
  const tabChanged = (key: string) => state.fields.some((f) => f.agent === key && !same(getPath(draft, f.path), getPath(state.defaults, f.path)));
  const info = state.agents.find((a) => a.key === agent) ?? state.agents[0];

  const run = async (fn: () => Promise<RulesState>, message: string) => {
    setSaving(true);
    setError(null);
    setSaved(null);
    try {
      apply(await fn());
      adminKey.set(apiKey);
      setSaved(message);
    } catch (e) {
      setError(e instanceof ApiError || e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };
  const save = () => run(() => api.updateRules(draft, apiKey || undefined), "저장했습니다. 지금부터 시작하는 실행에 바로 적용됩니다.");
  const resetAll = () => {
    if (!window.confirm("화면에서 바꾼 규칙을 모두 지우고 기본값(config/strategy_rules.yaml)으로 되돌립니다. 계속할까요?")) return;
    run(() => api.resetRules(apiKey || undefined), "모든 규칙을 기본값으로 되돌렸습니다.");
  };
  const tabDefaults = () => {
    let next = draft;
    for (const f of fields) next = setPath(next, f.path, structuredClone(getPath(state.defaults, f.path)));
    setDraft(next);
  };

  return (
    <div className="settings rules">
      <h2>에이전트 규칙</h2>
      <p className="muted">
        각 단계(에이전트)가 판단에 쓰는 값입니다. 저장하면 서버를 다시 시작하지 않고 <b>바로 적용</b>되어, 다음에 시작하는 실행부터 새 값으로
        판단합니다. 판단 기준 설명은 docs/AGENTS.md, 각 실행이 어떤 값으로 판단했는지는 실행 화면의 "근거"에 남습니다.
      </p>
      {error && <div className="error-box" style={{ whiteSpace: "pre-line" }}>{error}</div>}
      {state.override_error && (
        <div className="error-box">
          바꾼 규칙 파일({state.override_file})을 쓸 수 없어 기본 규칙으로 처리하고 있습니다: {state.override_error}. 화면에서 다시 저장하거나
          "모두 기본값으로"를 누르세요.
        </div>
      )}
      {state.active_runs > 0 && (
        <div className="notice">
          지금 실행 중이거나 대기 중인 작업이 {state.active_runs}개 있습니다. 저장하면 그 작업은 아직 시작하지 않은 단계부터 새 값을 씁니다.
        </div>
      )}
      {saved && (
        <div className="notice ok-notice">
          {saved} (규칙 버전 <code>{state.rules_version}</code>)
          {selectedDoc && (
            <button className="primary" onClick={onRerun}>
              "{displayName(selectedDoc.filename)}" 다시 실행
            </button>
          )}
        </div>
      )}

      <nav className="view-tabs">
        {state.agents.map((a) => (
          <button key={a.key} className={a.key === agent ? "on" : ""} onClick={() => onAgent(a.key)}>
            {a.label}
            {tabChanged(a.key) && <span className="dot" title="기본값과 다른 값이 있음" />}
          </button>
        ))}
      </nav>

      <section className="card">
        <h3>
          {info.label} <span className="muted">({info.key})</span>
        </h3>
        <p className="muted">{info.about}</p>
        {!canEdit && (
          <p className="muted">이 서버가 돌아가는 PC에서 접속했을 때만 바꿀 수 있습니다. 다른 PC에서 바꾸려면 서버에 RAG_API_KEY를 설정하세요.</p>
        )}
        {fields.map((f) => (
          <FieldEditor key={f.path.join(".")} f={f} state={state} disabled={!canEdit || saving}
            value={getPath(draft, f.path)} def={getPath(state.defaults, f.path)}
            onChange={(v) => {
              setSaved(null);
              setDraft((d) => setPath(d!, f.path, v));
            }} />
        ))}
        {fields.length > 0 && (
          <button disabled={!canEdit || saving} onClick={tabDefaults}>
            이 단계 값 모두 기본값으로
          </button>
        )}
      </section>

      <section className="card">
        {state.key_required && (
          <div className="setting-row">
            <label htmlFor="rules-key">관리자 키 (RAG_API_KEY)</label>
            <input id="rules-key" type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
          </div>
        )}
        <div className="setting-actions">
          <button className="primary" disabled={!dirty || saving || !canEdit} onClick={save}>
            {saving ? "저장 중…" : "저장하고 적용"}
          </button>
          <button disabled={!dirty || saving} onClick={() => setDraft(structuredClone(state.rules))}>
            저장 전으로 되돌리기
          </button>
          <button className="danger" disabled={!state.overridden || saving || !canEdit} onClick={resetAll}>
            모두 기본값으로
          </button>
          {dirty && <span className="muted">저장하지 않은 변경이 있습니다.</span>}
        </div>
        <p className="muted">
          기본값: config/strategy_rules.yaml. 바꾼 값만 <span className="mono">{state.override_file}</span>에 저장합니다
          {state.overridden ? ` (기본값과 다른 항목 ${state.changed.length}개).` : " (지금은 바꾼 값 없음)."} 규칙 버전{" "}
          <code>{state.rules_version}</code>
        </p>
      </section>
    </div>
  );
}
