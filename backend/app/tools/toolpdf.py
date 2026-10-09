"""Client for the PDF engine ToolPDF: a separate program (its own repository and license) called over its
documented HTTP API. Every PDF operation of the pipeline goes through here; this app links no PDF library.

Files reach the engine in one of two ways (RAG_TOOLPDF_TRANSFER):
  shared  the engine mounts data_dir as its shared folder, so a file under data_dir is named by its stored
          (relative) path and outputs are written straight into data_dir
  http    files are uploaded once and named by their sha256; outputs are downloaded
Files outside data_dir (tests, scripts) are uploaded in either mode.

Engine options (ToolPDF >= 0.2.0, README "옵션"): table finding and image settings come from the rules
(`engine.tables`, `engine.image`). They are sent only to an engine that serves GET /v1/options; an older engine
gets the request it always got. `extract` then carries crop settings inside `options` instead of the old
top-level fields, because the engine refuses the same setting given twice with different values.
"""

import base64
import hashlib
import threading
from functools import lru_cache
from pathlib import Path

import httpx

from ..config import rules_cfg, settings


# The pipeline's parser names -> the engine's extraction mode.
PARSER_MODE = {"vlm_ocr": "ocr", "vlm_figures": "figures"}
# Image options the engine's /v1/render accepts (the rest of engine.image is for extract crops).
RENDER_IMAGE_KEYS = ("jpeg_quality", "annots")


def engine_rules() -> dict:
    """The rules' `engine` section: {"tables": {...}, "image": {...}}."""
    return rules_cfg().get("engine") or {}


class ToolPDFError(RuntimeError):
    """The engine refused or failed a request; the message carries its status and detail."""


class Engine:
    def __init__(self, url: str, api_key: str, transfer: str, data_dir: Path, timeout_s: float):
        if transfer not in ("http", "shared"):
            raise ValueError(f"RAG_TOOLPDF_TRANSFER must be http or shared, not {transfer!r}")
        self.url, self.transfer, self.data_dir = url.rstrip("/"), transfer, data_dir.resolve()
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.http = httpx.Client(base_url=self.url, headers=headers, timeout=timeout_s)
        self._sha: dict[tuple, str] = {}
        self._lock = threading.Lock()
        self._options: dict | None | bool = False  # False = not asked yet; None = engine has no options

    # ---------- files ----------

    def _relative(self, path: Path) -> str | None:
        try:
            return Path(path).resolve().relative_to(self.data_dir).as_posix()
        except ValueError:
            return None

    def _sha256(self, path: Path) -> str:
        st = path.stat()
        key = (str(path.resolve()), st.st_mtime_ns, st.st_size)
        with self._lock:
            if key in self._sha:
                return self._sha[key]
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        with self._lock:
            self._sha[key] = h.hexdigest()
        return self._sha[key]

    def _upload(self, path: Path) -> str:
        sha = self._sha256(path)
        if self.http.head(f"/v1/files/{sha}").status_code != 200:
            with open(path, "rb") as f:
                r = self.http.post("/v1/files", content=f)
            self._check(r)
        return sha

    def source(self, path: Path) -> dict:
        rel = self._relative(path) if self.transfer == "shared" else None
        return {"path": rel} if rel else {"file_id": self._upload(Path(path))}

    # ---------- requests ----------

    @staticmethod
    def _check(r: httpx.Response) -> httpx.Response:
        if r.status_code >= 400:
            r.read()  # a streamed response has not read its error body yet
            try:
                detail = r.json().get("detail")
            except ValueError:
                detail = r.text[:300]
            raise ToolPDFError(f"ToolPDF {r.request.url.path} {r.status_code}: {detail}")
        return r

    def _post(self, endpoint: str, path: Path, body: dict) -> httpx.Response:
        r = self.http.post(endpoint, json={"source": self.source(path), **body})
        if r.status_code == 404 and "unknown file_id" in r.text:
            # the engine's cache dropped the upload (size limit or restart): send it again
            with self._lock:
                self._sha.clear()
            r = self.http.post(endpoint, json={"source": self.source(path), **body})
        return self._check(r)

    def health(self, timeout_s: float = 3) -> dict:
        return self._check(self.http.get("/v1/health", timeout=timeout_s)).json()

    def option_support(self) -> dict | None:
        """The engine's GET /v1/options ({version, endpoints: {api: {schema, defaults}}}), or None for an engine
        older than 0.2.0. Asked once per process; reset() asks again (e.g. after the engine was upgraded)."""
        if self._options is False:
            r = self.http.get("/v1/options")
            self._options = None if r.status_code in (404, 405) else self._check(r).json()
        return self._options

    def reset(self) -> None:
        self._options = False

    def info(self, pdf: Path) -> dict:
        """{encrypted, page_count, pages: [[w, h], ...]}"""
        return self._post("/v1/info", pdf, {}).json()

    def text(self, pdf: Path, limit: int = 6000) -> str:
        return self._post("/v1/text", pdf, {"limit": limit}).json()["text"]

    def profile(self, pdf: Path, pages: list[int] | None = None) -> list[dict]:
        """[{page, features}]. Table counts follow the rules' table options, like extract."""
        body: dict = {"pages": pages}
        if self.option_support():
            body["options"] = {"tables": dict(engine_rules().get("tables") or {})}
        return self._post("/v1/profile", pdf, body).json()["pages"]

    def extract(self, pdf: Path, pages: list[tuple[int, str, int]], heading_min: float | None, pcfg: dict,
                vlm_on: bool, vcfg: dict) -> dict[int, dict]:
        """Per page: native elements, OCR fallback, figure regions and VLM jobs with crops (bytes).
        pages: (page, parser, drawing count); the parser picks the engine's mode. A table job's "target" is the
        element it may replace (resolved from the engine's index)."""
        body = {"pages": [{"page": p, "mode": PARSER_MODE.get(parser, "text"), "drawings": d} for p, parser, d in pages],
                "heading_min_size": heading_min,
                "figures_min_area_ratio": pcfg["figures"]["min_area_ratio"], "figures_max_per_page": pcfg["figures"]["max_per_page"],
                "figures_on_all_pages": pcfg["figures"]["enrich_native_pages"]}
        crop = {"crops": vlm_on, "format": vcfg.get("image_format", "jpeg"),
                "render_dpi": vcfg.get("render_dpi", 150), "crop_dpi": vcfg.get("crop_dpi", 170)}
        if self.option_support():
            rules = engine_rules()
            body["options"] = {
                "tables": {**(rules.get("tables") or {}), "crop_empty_ratio": pcfg["tables"]["max_empty_cell_ratio"]},
                "image": {**(rules.get("image") or {}), **crop},
            }
        else:  # 0.1.x request
            body |= {"max_empty_cell_ratio": pcfg["tables"]["max_empty_cell_ratio"], "crops": crop["crops"],
                     "image_format": crop["format"], "render_dpi": crop["render_dpi"], "crop_dpi": crop["crop_dpi"]}
        out = {}
        for p, prep in self._post("/v1/extract", pdf, body).json()["pages"].items():
            prep["jobs"] = prep.pop("crops")
            for job in prep["jobs"]:
                job["image"] = base64.b64decode(job["image"])
                if job["kind"] == "table":
                    job["target"] = prep["elements"][job["target"]]
            out[int(p)] = prep
        return out

    def render(self, pdf: Path, page: int, dpi: int, fmt: str = "png", clip: list[float] | None = None, pad: float = 0,
               highlight: list[list[float]] | None = None) -> bytes:
        body = {"page": page, "dpi": dpi, "format": fmt, "clip": clip, "pad": pad, "highlight": highlight}
        if self.option_support():
            image = engine_rules().get("image") or {}
            body["options"] = {"image": {k: image[k] for k in RENDER_IMAGE_KEYS if k in image}}
        r = self.http.post("/v1/render", json={"source": self.source(pdf), **body})
        if r.status_code == 404 and "page out of range" in r.text:
            raise IndexError(page)
        if r.status_code == 404 and "unknown file_id" in r.text:
            r = self._post("/v1/render", pdf, body)
        return self._check(r).content

    def normalize(self, src: Path, filename: str, method: str, out: Path, hints: bool = True,
                  xlsx_rows_per_page: int = 24, xlsx_max_rows: int = 5000) -> dict:
        """Convert an image or Office file to the PDF `out`. Returns {hints, encrypted, page_count, pages}."""
        out = Path(out)
        rel = self._relative(out) if self.transfer == "shared" else None
        body = {"filename": filename, "method": method, "hints": hints, "xlsx_rows_per_page": xlsx_rows_per_page,
                "xlsx_max_rows": xlsx_max_rows, "output": {"path": rel} if rel else None}
        res = self._post("/v1/normalize", src, body).json()
        if not rel:
            out.parent.mkdir(parents=True, exist_ok=True)
            with self.http.stream("GET", f"/v1/files/{res['output']['file_id']}") as r:
                self._check(r)
                with open(out, "wb") as f:
                    for chunk in r.iter_bytes(1 << 20):
                        f.write(chunk)
        return res


@lru_cache
def engine() -> Engine:
    return Engine(settings.toolpdf_url, settings.toolpdf_api_key, settings.toolpdf_transfer, settings.data_dir,
                  settings.toolpdf_timeout_s)
