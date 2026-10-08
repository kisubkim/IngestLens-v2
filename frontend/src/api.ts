export type RunStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export interface Run {
  id: string;
  document_id: string;
  status: RunStatus;
  current_step: string | null;
  error: string | null;
  summary: Record<string, any>;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  steps?: string[];
}

export interface Doc {
  id: string;
  filename: string;
  size: number;
  format: string | null;
  page_count: number | null;
  created_at: string;
  latest_run: Run | null;
  duplicate?: boolean;
}

// Open WebUI stores uploads as "<uuid4>_<original name>" and sends that name to the document loader.
const OPENWEBUI_PREFIX = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}_(?=.)/i;

/** The name to show: the stored filename without Open WebUI's id prefix (the stored name is unchanged). */
export const displayName = (filename: string) => filename.replace(OPENWEBUI_PREFIX, "");

export interface RunEvent {
  id: number;
  run_id: string;
  ts: string;
  type: "step_started" | "step_finished" | "progress" | "decision" | "warning" | "error" | "run_finished";
  step: string | null;
  message: string;
  data: Record<string, any>;
}

export interface Decision {
  id: number;
  step: string;
  subject: string;
  choice: string;
  rule_id: string | null;
  inputs: Record<string, any>;
  alternatives: { choice: string; reason_rejected: string }[];
  confidence: number | null;
  reasoning: string;
  ts: string;
}

export interface Chunk {
  id: string;
  seq: number;
  text: string;
  tokens: number;
  pages: number[];
  bboxes: { page: number; bbox: number[] }[];
  section: string | null;
  element_types: string[];
  strategy_id: string;
}

export interface SearchHit {
  rank: number;
  chunk_id: string;
  seq: number;
  text: string;
  tokens: number;
  pages: number[];
  bboxes: { page: number; bbox: number[] }[];
  section: string | null;
  element_types: string[];
  scores: {
    dense: number | null;
    dense_rank: number | null;
    lexical: number | null;
    lexical_rank: number | null;
    fused: number | null;
    rerank: number | null;
  };
}

export type SearchMode = "hybrid" | "dense" | "lexical";

export interface SearchResult {
  run_id: string | null;
  mode: SearchMode;
  model?: string;
  collection?: string;
  reranker?: string;
  candidates?: number;
  notes: string[];
  timings_ms: Record<string, number>;
  hits: SearchHit[];
}

export interface EmbeddingPoint {
  chunk_id: string;
  x: number;
  y: number;
  seq: number;
  pages: number[];
  section: string | null;
  element_types: string[];
  tokens: number;
  preview: string;
  norm: number;
}

export interface Projection {
  collection: string;
  dim?: number;
  count: number;
  explained_variance?: number[];
  norm?: { min: number; mean: number; max: number };
  points: EmbeddingPoint[];
  note?: string;
}

export interface Neighbor {
  chunk_id: string;
  score: number;
  pages: number[];
  section: string | null;
  element_types: string[];
  preview: string;
}


export interface PageProfile {
  page: number;
  label: string;
  rule_id: string;
  confidence: number;
  parser: string | null;
  features: {
    text_chars: number;
    text_area_ratio: number;
    images: number;
    image_area_ratio: number;
    drawings: number;
    tables: number;
    table_area_ratio: number;
    table_text_share?: number;
    size_hist: Record<string, number>;
    evidence: {
      conditions: Record<string, { threshold: number; actual: number }>;
      evaluated: { rule: string; matched: boolean }[];
    };
  };
}

export interface Element {
  id: number;
  page: number;
  seq: number;
  type: "text" | "title" | "table" | "figure";
  bbox: [number, number, number, number];
  content: string;
  source_tool: string;
  meta: {
    figure_type?: string;
    caption?: string;
    region_source?: string;
    area_ratio?: number;
    vlm_seconds?: number;
    empty_cell_ratio?: number;
    reextracted?: boolean;
  } | null;
}

export type StorageKey = "data_dir" | "db_url" | "qdrant_url";

export interface StorageItem {
  key: StorageKey;
  label: string;
  effective: string;
  configured: string;
  source: "env" | "dotenv" | "file" | "default";
  locked: boolean;
  pending: boolean;
  hint: string;
}

export interface StorageState {
  settings_file: string;
  items: StorageItem[];
  database: string;
  vector_store: string;
  usage: { key: string; label: string; path: string; bytes: number | null }[];
  restart_required: boolean;
  key_required: boolean;
  editable_here: boolean;
  active_runs: number;
}

export interface EvalCheck {
  id: string;
  label: string;
  score: number;
  pass: boolean;
  value: any;
}

export interface VlmEvalSummary {
  score: number;
  checks_passed: number;
  checks_total: number;
  by_check: Record<string, { label: string; score: number; passed: number; total: number }>;
  ocr_cer: number | null;
  ingest_seconds: number;
  parse_seconds: number;
  vlm_calls: number;
  vlm_errors: number;
  vlm_truncated: number;
  vlm_avg_seconds: number | null;
}

export interface VlmEvalItem {
  file: string;
  name: string;
  notes: string;
  created_at: string;
  git_commit: string | null;
  models: Record<string, Record<string, any>>;
  prompts_sha: string;
  dataset: string | null;
  dataset_version: string | null;
  summary: VlmEvalSummary;
}

export interface VlmEvalPage {
  doc: string;
  page: number;
  id: string;
  title: string;
  score: number | null;
  checks: EvalCheck[];
  label: string | null;
  vlm_seconds: number | null;
  elements: { type: string; source_tool: string; content: string; meta: Record<string, any> }[];
  expected_text: string | null;
}

export interface VlmEvalResult extends VlmEvalItem {
  pages: VlmEvalPage[];
}

export interface ElementStats {
  total: number;
  by_type: Record<string, number>;
  pages: {
    page: number;
    label: string | null;
    parser: string | null;
    total: number;
    chars: number;
    by_type: Record<string, number>;
    by_tool: Record<string, number>;
  }[];
  empty_pages: number[];
}

export interface Overview {
  documents: { count: number; bytes: number; pages: number; by_format: Record<string, number> };
  runs: { total: number; by_status: Record<string, number> };
  chunks: number;
  vectors: {
    total: number;
    collections: { name: string; model: string; dim: number | null; points: number }[];
    embedding_model: string;
    embedding_configured: boolean;
  };
  storage: { items: { key: string; label: string; path: string; bytes: number | null }[]; bytes: number; data_dir: string };
  recent: (Doc & { chunks: number })[];
}

export interface PurgeResult {
  documents: number;
  runs: number;
  chunks: number;
  elements: number;
}

/** Turn the server's refusal into a sentence the user can act on. */
export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

/** RAG_API_KEY typed on the settings screen or at a delete prompt, kept for this browser tab only. */
export const adminKey = {
  get(): string {
    try {
      return sessionStorage.getItem("ingestlens.adminKey") ?? "";
    } catch {
      return "";
    }
  },
  set(key: string) {
    try {
      if (key) sessionStorage.setItem("ingestlens.adminKey", key);
      else sessionStorage.removeItem("ingestlens.adminKey");
    } catch {
      /* storage blocked: the key is just asked again next time */
    }
  },
};

async function purgeJson(res: Response): Promise<PurgeResult> {
  if (res.ok) return res.json();
  const reason =
    res.status === 409
      ? "실행 중이거나 대기 중인 문서가 있어 삭제할 수 없습니다. 먼저 실행을 취소하세요."
      : res.status === 403
        ? "삭제는 서버가 돌아가는 PC에서만 할 수 있습니다. 다른 PC에서 하려면 서버에 RAG_API_KEY를 설정하세요."
        : res.status === 401
          ? "API 키가 맞지 않습니다."
          : `${res.status} ${await res.text()}`;
  throw new ApiError(reason, res.status);
}

export type StatusState ="ok" | "warn" | "off" | "error";

export interface BackendStatus {
  overall: "ok" | "warn" | "error";
  version: string;
  checked_at: string;
  items: { key: string; label: string; state: StatusState; detail: string; latency_ms: number | null }[];
  runs: { running: number; queued: number };
}

export const pageImage =(docId: string, page: number, dpi = 96) => `/api/documents/${docId}/pages/${page}.png?dpi=${dpi}`;

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

export const api = {
  documents: () => fetch("/api/documents").then(json<Doc[]>),
  upload: (files: File[]) => {
    const body = new FormData();
    for (const file of files) body.append("files", file);
    return fetch("/api/documents/batch", { method: "POST", body }).then(json<Doc[]>);
  },
  startRun: (docId: string) => fetch(`/api/documents/${docId}/runs`, { method: "POST" }).then(json<Run>),
  startRuns: (docIds: string[]) =>
    fetch("/api/documents/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ document_ids: docIds }),
    }).then(json<Run[]>),
  storage: () => fetch("/api/settings/storage").then(json<StorageState>),
  updateStorage: (changes: Partial<Record<StorageKey, string>>, apiKey?: string) =>
    fetch("/api/settings/storage", {
      method: "PUT",
      headers: { "Content-Type": "application/json", ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}) },
      body: JSON.stringify(changes),
    }).then(json<StorageState>),
  run: (runId: string) => fetch(`/api/runs/${runId}`).then(json<Run>),
  cancelRun: (runId: string) => fetch(`/api/runs/${runId}/cancel`, { method: "POST" }).then(json<{ cancelled: boolean }>),
  pages: (runId: string) => fetch(`/api/runs/${runId}/pages`).then(json<PageProfile[]>),
  elements: (runId: string, page: number) => fetch(`/api/runs/${runId}/elements?page=${page}`).then(json<Element[]>),
  decisions: (runId: string, subject: string) =>
    fetch(`/api/runs/${runId}/decisions?subject=${encodeURIComponent(subject)}`).then(json<Decision[]>),
  search: (body: {
    query: string;
    run_id?: string;
    document_id?: string;
    top_k?: number;
    mode?: SearchMode;
    rerank?: boolean;
    dense_weight?: number;
    lexical_weight?: number;
  }) =>
    fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json<SearchResult>),
  capabilities: () => fetch("/api/search/capabilities").then(json<{ embedding_model: string; reranker: string | null }>),
  chunks: (runId: string, params: { offset?: number; limit?: number; page?: number; type?: string; q?: string } = {}) => {
    const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== "").map(([k, v]) => [k, String(v)]));
    return fetch(`/api/runs/${runId}/chunks?${qs}`).then(json<{ total: number; items: Chunk[] }>);
  },
  embeddings: (runId: string) => fetch(`/api/runs/${runId}/embeddings`).then(json<Projection>),
  neighbors: (runId: string, chunkId: string, k = 5) => fetch(`/api/runs/${runId}/chunks/${chunkId}/neighbors?k=${k}`).then(json<Neighbor[]>),
  vlmEvals: () =>
    fetch("/api/evals/vlm").then(json<{ dir: string; items: VlmEvalItem[]; errors: { file: string; error: string }[] }>),
  overview: () => fetch("/api/overview").then(json<Overview>),
  elementStats: (runId: string) => fetch(`/api/runs/${runId}/element-stats`).then(json<ElementStats>),
  deleteDocument: (docId: string, apiKey: string = adminKey.get()) =>
    fetch(`/api/documents/${docId}`, { method: "DELETE", headers: apiKey ? { Authorization: `Bearer ${apiKey}` } : {} }).then(purgeJson),
  deleteAll: (apiKey?: string) =>
    fetch("/api/documents?confirm=all", { method: "DELETE", headers: apiKey ? { Authorization: `Bearer ${apiKey}` } : {} }).then(purgeJson),
  status: (refresh = false) => fetch(`/api/status${refresh ? "?refresh=true" : ""}`).then(json<BackendStatus>),
  vlmEval: (file: string) => fetch(`/api/evals/vlm/${encodeURIComponent(file)}`).then(json<VlmEvalResult>),
};

/** Subscribe to a run's event stream. Reconnects from the last seen id; stops after run_finished. */
export function streamRun(runId: string, onEvent: (e: RunEvent) => void): () => void {
  let last = 0;
  let closed = false;
  let es: EventSource | null = null;
  let retry: number | undefined;

  const open = () => {
    es = new EventSource(`/api/runs/${runId}/stream?after=${last}`);
    es.addEventListener("run_event", (msg) => {
      const ev: RunEvent = JSON.parse((msg as MessageEvent).data);
      last = ev.id;
      onEvent(ev);
      if (ev.type === "run_finished") stop();
    });
    es.onerror = () => {
      es?.close();
      if (!closed) retry = window.setTimeout(open, 2000);
    };
  };
  const stop = () => {
    closed = true;
    window.clearTimeout(retry);
    es?.close();
  };
  open();
  return stop;
}
