"""PdfEngine over ToolPDF: a separate program (its own repository and license) called over its documented HTTP
API (its README is the contract). This module links no PDF library.

Files reach the engine in one of two ways (`transfer`):
  shared  the engine mounts `data_dir` as its shared folder, so a file under it is named by its relative path
          and outputs are written straight into it
  http    files are uploaded once and named by their sha256; outputs are downloaded
Files outside `data_dir` are uploaded in either mode.

Options (ToolPDF >= 0.2.0) are sent only to an engine that serves GET /v1/options. An older engine gets the
request it always got: extract's crop settings go back to the old top-level fields, the rest is dropped, and a
password cannot be sent (EngineError).
"""

import base64
import hashlib
import threading
from pathlib import Path

import httpx

from .base import STRATEGIES, EngineError, PasswordError

# extract: options key -> the 0.1.x top-level field
LEGACY_EXTRACT = {("tables", "crop_empty_ratio"): "max_empty_cell_ratio", ("image", "crops"): "crops",
                  ("image", "format"): "image_format", ("image", "render_dpi"): "render_dpi",
                  ("image", "crop_dpi"): "crop_dpi"}


class ToolPDFError(EngineError):
    """ToolPDF refused or failed a request; the message carries its status and detail."""


class ToolPDFEngine:
    name = "toolpdf"

    def __init__(self, url: str, api_key: str = "", transfer: str = "http", data_dir: Path | None = None,
                 timeout_s: float = 600):
        if transfer not in ("http", "shared"):
            raise ValueError(f"transfer must be http or shared, not {transfer!r}")
        self.url, self.transfer = url.rstrip("/"), transfer
        self.data_dir = Path(data_dir).resolve() if data_dir else None
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.http = httpx.Client(base_url=self.url, headers=headers, timeout=timeout_s)
        self._sha: dict[tuple, str] = {}
        self._lock = threading.Lock()
        self._options: dict | None | bool = False  # False = not asked yet; None = engine has no options

    # ---------- files ----------

    def _relative(self, path: Path) -> str | None:
        if self.data_dir is None:
            return None
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
            msg = f"ToolPDF {r.request.url.path} {r.status_code}: {detail}"
            raise PasswordError(msg) if r.status_code == 403 else ToolPDFError(msg)
        return r

    def _post(self, endpoint: str, path: Path, body: dict) -> httpx.Response:
        r = self.http.post(endpoint, json={"source": self.source(path), **body})
        if r.status_code == 404 and "unknown file_id" in r.text:
            # the engine's cache dropped the upload (size limit or restart): send it again
            with self._lock:
                self._sha.clear()
            r = self.http.post(endpoint, json={"source": self.source(path), **body})
        return self._check(r)

    def _with_options(self, body: dict, options: dict | None) -> dict:
        """Options for an engine that takes them; an older engine cannot open an encrypted PDF."""
        options = {g: v for g, v in (options or {}).items() if v}
        if self.options_schema():
            if options:
                body["options"] = options
        elif (options.get("document") or {}).get("password"):
            raise EngineError("ToolPDF older than 0.2.0 cannot open encrypted PDFs (options.document.password)")
        return body

    # ---------- interface ----------

    def health(self, timeout_s: float = 3) -> dict:
        return self._check(self.http.get("/v1/health", timeout=timeout_s)).json()

    def options_schema(self) -> dict | None:
        """The engine's GET /v1/options, or None for an engine older than 0.2.0. Asked once; reset() asks again
        (e.g. after the engine was upgraded)."""
        if self._options is False:
            r = self.http.get("/v1/options")
            self._options = None if r.status_code in (404, 405) else self._check(r).json()
        return self._options

    def reset(self) -> None:
        self._options = False

    def capabilities(self) -> dict:
        schema = self.options_schema()
        soffice = self.health().get("libreoffice")
        return {"options": bool(schema), "password": bool(schema), "table_strategies": list(STRATEGIES) if schema else ["lines"],
                "normalize": ["image", "native"] + (["libreoffice"] if soffice else []), "libreoffice": soffice}

    def info(self, src: Path, options: dict | None = None) -> dict:
        return self._post("/v1/info", src, self._with_options({}, options)).json()

    def text(self, src: Path, limit: int = 6000, options: dict | None = None) -> str:
        return self._post("/v1/text", src, self._with_options({"limit": limit}, options)).json()["text"]

    def profile(self, src: Path, pages: list[int] | None = None, options: dict | None = None) -> list[dict]:
        return self._post("/v1/profile", src, self._with_options({"pages": pages}, options)).json()["pages"]

    def extract(self, src: Path, pages: list[dict], heading_min_size: float | None, figures: dict,
                options: dict | None = None) -> dict[int, dict]:
        body = {"pages": pages, "heading_min_size": heading_min_size,
                "figures_min_area_ratio": figures["min_area_ratio"], "figures_max_per_page": figures["max_per_page"],
                "figures_on_all_pages": figures["on_all_pages"]}
        if self.options_schema() is None:  # 0.1.x request: crop settings as top-level fields
            for (g, k), field in LEGACY_EXTRACT.items():
                if k in ((options or {}).get(g) or {}):
                    body[field] = options[g][k]
            options = {"document": (options or {}).get("document")}
        out = {}
        for p, prep in self._post("/v1/extract", src, self._with_options(body, options)).json()["pages"].items():
            for crop in prep["crops"]:
                crop["image"] = base64.b64decode(crop["image"])
            out[int(p)] = prep
        return out

    def render(self, src: Path, page: int, dpi: int = 96, fmt: str = "png", clip: list[float] | None = None,
               pad: float = 0, highlight: list[list[float]] | None = None, options: dict | None = None) -> bytes:
        body = self._with_options({"page": page, "dpi": dpi, "format": fmt, "clip": clip, "pad": pad,
                                   "highlight": highlight}, options)
        r = self.http.post("/v1/render", json={"source": self.source(src), **body})
        if r.status_code == 404 and "page out of range" in r.text:
            raise IndexError(page)
        if r.status_code == 404 and "unknown file_id" in r.text:
            r = self._post("/v1/render", src, body)
        return self._check(r).content

    def normalize(self, src: Path, filename: str, method: str, out: Path, hints: bool = True,
                  xlsx_rows_per_page: int = 24, xlsx_max_rows: int = 5000) -> dict:
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

