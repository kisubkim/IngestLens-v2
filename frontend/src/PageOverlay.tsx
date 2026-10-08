import { useState } from "react";
import { pageImage } from "./api";

export interface OverlayBox {
  key: string | number;
  bbox: number[];
  cls: string; // e.g. "t-table" or "t-chunk"
}

const DPI = 110;

/** Page render with bbox rectangles. Bboxes are PDF points; the image is rendered at DPI, so points = px * 72 / DPI. */
export default function PageOverlay({
  docId,
  page,
  boxes,
  hot,
  onHover,
}: {
  docId: string;
  page: number;
  boxes: OverlayBox[];
  hot?: string | number | null;
  onHover?: (key: string | number | null) => void;
}) {
  const [size, setSize] = useState<{ src: string; w: number; h: number } | null>(null);
  const src = pageImage(docId, page, DPI);
  const viewBox = size && size.src === src ? `0 0 ${(size.w * 72) / DPI} ${(size.h * 72) / DPI}` : undefined;
  return (
    <div className="page-canvas">
      <img src={src} alt={`page ${page + 1}`} onLoad={(e) => setSize({ src, w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })} />
      {viewBox && (
        <svg viewBox={viewBox} preserveAspectRatio="none">
          {boxes.map((b) => {
            const [x0, y0, x1, y1] = b.bbox;
            return (
              <rect
                key={b.key}
                x={x0}
                y={y0}
                width={x1 - x0}
                height={y1 - y0}
                className={`bbox ${b.cls} ${hot === b.key ? "hot" : ""}`}
                onMouseEnter={() => onHover?.(b.key)}
                onMouseLeave={() => onHover?.(null)}
              />
            );
          })}
        </svg>
      )}
    </div>
  );
}
