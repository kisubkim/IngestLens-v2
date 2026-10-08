import { useEffect, useState } from "react";
import PageOverlay from "./PageOverlay";

export type ChunkKind = "figure" | "table" | "title" | "text";

/** One color per chunk: figure/table win over text because they are the atomic, special chunks. */
export function chunkKind(types: string[]): ChunkKind {
  if (types.includes("figure")) return "figure";
  if (types.includes("table")) return "table";
  if (types.length && types.every((t) => t === "title")) return "title";
  return "text";
}

export interface ChunkLike {
  id: string;
  text: string;
  tokens: number;
  pages: number[];
  bboxes: { page: number; bbox: number[] }[];
  section: string | null;
  element_types: string[];
}

export default function ChunkDetail({ docId, chunk, children }: { docId: string; chunk: ChunkLike; children?: React.ReactNode }) {
  const [page, setPage] = useState(chunk.pages[0] ?? 0);
  useEffect(() => setPage(chunk.pages[0] ?? 0), [chunk.id, chunk.pages]);
  const kind = chunkKind(chunk.element_types);
  const boxes = chunk.bboxes.filter((b) => b.page === page).map((b, i) => ({ key: i, bbox: b.bbox, cls: `t-${kind}` }));

  return (
    <div className="chunk-detail">
      <div className="chunk-detail-head">
        <code>{chunk.id}</code>
        <span className={`kind-tag t-${kind}`}>{kind}</span>
        <span className="muted">
          {chunk.tokens} tok · p.{chunk.pages.map((p) => p + 1).join(", ")}
          {chunk.section && ` · ${chunk.section}`}
        </span>
        {chunk.pages.length > 1 && (
          <span className="page-pick">
            {chunk.pages.map((p) => (
              <button key={p} className={p === page ? "on" : ""} onClick={() => setPage(p)}>
                {p + 1}
              </button>
            ))}
          </span>
        )}
      </div>
      {children}
      <div className="chunk-detail-body">
        <PageOverlay docId={docId} page={page} boxes={boxes} />
        <pre className="chunk-text">{chunk.text}</pre>
      </div>
    </div>
  );
}
