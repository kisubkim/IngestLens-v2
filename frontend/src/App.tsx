import { useCallback, useEffect, useRef, useState } from "react";
import { adminKey, api, ApiError, displayName, type Doc } from "./api";
import RunView from "./RunView";
import EvalView from "./EvalView";
import HomeView from "./HomeView";
import StatusView, { StatusBadge, useBackendStatus } from "./StatusView";
import SettingsView from "./SettingsView";

const ACCEPT_EXT = [".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".hwp", ".png", ".jpg", ".jpeg", ".tif", ".tiff"];

type Panel = "doc" | "settings" | "evals" | "status";
const HASH_PANELS = ["#evals", "#settings", "#status"];

function fmtSize(bytes: number) {
  return bytes >= 2 ** 20 ? `${(bytes / 2 ** 20).toFixed(1)} MB` : `${Math.ceil(bytes / 1024)} KB`;
}

function splitFiles(files: File[]) {
  const ok: File[] = [];
  const skipped: string[] = [];
  for (const file of files) {
    const name = file.name.toLowerCase();
    if (ACCEPT_EXT.some((ext) => name.endsWith(ext))) ok.push(file);
    else skipped.push(file.name);
  }
  return { ok, skipped };
}

export default function App() {
  const [docs, setDocs] = useState<Doc[]>([]);
  const [selected, setSelected] = useState<Doc | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(0);
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Documents added by upload that wait for "순서대로 실행", in upload order.
  const [pending, setPending] = useState<string[]>([]);
  // #evals and #settings open those screens directly, so they can be linked and bookmarked.
  const [panel, setPanel] = useState<Panel>(() => (HASH_PANELS.includes(location.hash) ? (location.hash.slice(1) as Panel) : "doc"));
  const backend = useBackendStatus();
  useEffect(() => {
    history.replaceState(null, "", panel === "doc" ? location.pathname : `#${panel}`);
  }, [panel]);
  const fileInput = useRef<HTMLInputElement>(null);
  const dragDepth = useRef(0);

  const refresh = useCallback(() => api.documents().then(setDocs).catch((e) => setError(String(e))), []);
  useEffect(() => {
    refresh();
  }, [refresh]);

  // Keep the sidebar badges current while queued runs wait their turn on the server.
  const active = docs.some((d) => d.latest_run && ["queued", "running"].includes(d.latest_run.status));
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(refresh, 2000);
    return () => clearInterval(timer);
  }, [active, refresh]);

  const select = (d: Doc) => {
    setPanel("doc");
    setSelected(d);
    setRunId(d.latest_run?.id ?? null);
  };

  const upload = async (files: File[]) => {
    if (!files.length || busy) return;
    const { ok, skipped } = splitFiles(files);
    const skippedMsg = skipped.length ? `지원하지 않는 형식은 올리지 않았습니다: ${skipped.join(", ")}` : null;
    if (!ok.length) {
      setError(skippedMsg);
      return;
    }
    setBusy(true);
    setUploading(ok.length);
    setError(null);
    try {
      const uploaded = await api.upload(ok);
      setPending((prev) => [...new Set([...prev, ...uploaded.map((d) => d.id)])]);
      await refresh();
      const created = uploaded.filter((d) => !d.duplicate);
      select((created.length ? created : uploaded).at(-1)!);
      if (skippedMsg) setError(skippedMsg);
    } catch (e) {
      setError(skippedMsg ? `${skippedMsg}\n${String(e)}` : String(e));
    } finally {
      setBusy(false);
      setUploading(0);
    }
  };

  const remove = async () => {
    if (!selected) return;
    const ok = window.confirm(
      `"${displayName(selected.filename)}"을(를) 삭제합니다.\n\n올린 원본, 변환 PDF, 페이지 이미지, 모든 실행 기록과 파싱·청크 결과, 임베딩 벡터가 함께 지워지며 되돌릴 수 없습니다.`,
    );
    if (!ok) return;
    setError(null);
    try {
      try {
        await api.deleteDocument(selected.id);
      } catch (e) {
        // The server has RAG_API_KEY and this tab has no (or a wrong) key yet: ask once, remember it, retry.
        if (!(e instanceof ApiError && e.status === 401)) throw e;
        const key = window.prompt("문서를 삭제하려면 관리자 키(서버의 RAG_API_KEY)를 입력하세요.");
        if (!key) return;
        try {
          await api.deleteDocument(selected.id, key);
        } catch (e2) {
          adminKey.set("");
          throw e2;
        }
        adminKey.set(key);
      }
      setPending((prev) => prev.filter((id) => id !== selected.id));
      setSelected(null);
      setRunId(null);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const start = async () => {
    if (!selected) return;
    setError(null);
    try {
      const run = await api.startRun(selected.id);
      setRunId(run.id);
      refresh();
    } catch (e) {
      setError(String(e));
    }
  };

  // The server runs them one at a time in this order; show the first one while the rest wait.
  const startAll = async () => {
    if (!pending.length) return;
    setError(null);
    try {
      const runs = await api.startRuns(pending);
      setPending([]);
      await refresh();
      const first = docs.find((d) => d.id === runs[0].document_id);
      setPanel("doc");
      if (first) setSelected(first);
      setRunId(runs[0].id);
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <div className="layout">
      <aside
        className={dragOver ? "sidebar dragover" : "sidebar"}
        onDragEnter={(e) => {
          e.preventDefault();
          dragDepth.current += 1;
          setDragOver(true);
        }}
        onDragOver={(e) => e.preventDefault()}
        onDragLeave={() => {
          dragDepth.current -= 1;
          if (dragDepth.current <= 0) {
            dragDepth.current = 0;
            setDragOver(false);
          }
        }}
        onDrop={(e) => {
          e.preventDefault();
          dragDepth.current = 0;
          setDragOver(false);
          upload(Array.from(e.dataTransfer.files));
        }}
      >
        <h1 className="home-link" title="첫 화면(임베딩 DB 현황)" onClick={() => {
          setPanel("doc");
          setSelected(null);
          setRunId(null);
        }}>
          IngestLens
        </h1>
        <button className="primary" disabled={busy} onClick={() => fileInput.current?.click()}>
          {busy ? `업로드 중… ${uploading}개` : "문서 업로드"}
        </button>
        <input
          ref={fileInput}
          type="file"
          hidden
          multiple
          accept={ACCEPT_EXT.join(",")}
          onChange={(e) => {
            upload(Array.from(e.target.files ?? []));
            e.target.value = "";
          }}
        />
        {pending.length > 0 && (
          <div className="pending-bar">
            <button className="primary" disabled={busy} onClick={startAll}>
              추가한 {pending.length}개 순서대로 실행
            </button>
            <button onClick={() => setPending([])}>비우기</button>
          </div>
        )}
        <ul className="doc-list">
          {docs.map((d) => (
            <li key={d.id} className={selected?.id === d.id ? "active" : ""} onClick={() => select(d)}>
              <div className="doc-name" title={d.filename}>{displayName(d.filename)}</div>
              <div className="doc-meta">
                {fmtSize(d.size)}
                {d.page_count ? ` · ${d.page_count}p` : ""}
                {pending.includes(d.id) && <span className="badge">대기 {pending.indexOf(d.id) + 1}</span>}
                {d.latest_run && <span className={`badge ${d.latest_run.status}`}>{d.latest_run.status}</span>}
              </div>
            </li>
          ))}
          {!docs.length && <li className="empty">업로드된 문서가 없습니다.</li>}
        </ul>
        <StatusBadge overall={backend.overall} active={panel === "status"} onClick={() => setPanel("status")} />
        <button className={panel === "evals" ? "settings-link active" : "settings-link"} onClick={() => setPanel("evals")}>
          VLM 평가 비교
        </button>
        <button className={panel === "settings" ? "settings-link active" : "settings-link"} onClick={() => setPanel("settings")}>
          저장 위치 설정
        </button>
      </aside>

      <main className="main">
        {error && <div className="error-box">{error}</div>}
        {panel === "settings" && (
          <SettingsView
            docCount={docs.length}
            onCleared={() => {
              setSelected(null);
              setRunId(null);
              setPending([]);
              refresh();
            }}
          />
        )}
        {panel === "evals" && <EvalView />}
        {panel === "status" && <StatusView state={backend} />}
        {panel === "doc" && !selected && (
          <HomeView version={docs.map((d) => `${d.id}:${d.latest_run?.status ?? ""}`).join(",")} onOpen={select} />
        )}
        {panel === "doc" && selected && (
          <>
            <header className="doc-header">
              <div>
                <h2 title={selected.filename}>{displayName(selected.filename)}</h2>
                <span className="muted">{fmtSize(selected.size)}</span>
              </div>
              <div className="header-actions">
                <button className="danger" onClick={remove}>
                  문서 삭제
                </button>
                <button className="primary" onClick={start}>
                  {runId ? "다시 실행" : "파이프라인 실행"}
                </button>
              </div>
            </header>
            {runId ? (
              <RunView key={runId} runId={runId} documentId={selected.id} onFinished={refresh} />
            ) : (
              <div className="placeholder">아직 실행 기록이 없습니다.</div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
