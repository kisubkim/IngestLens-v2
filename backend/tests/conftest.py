import atexit
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

import pytest

# Settings are read at import time, so point the app at a throwaway data dir first.
DATA_DIR = tempfile.mkdtemp(prefix="rag-test-")
os.environ["RAG_DATA_DIR"] = DATA_DIR
os.environ["RAG_SETTINGS_FILE"] = str(Path(tempfile.mkdtemp(prefix="rag-settings-")) / "settings.local.yaml")

FIXTURES = Path(__file__).parent / "fixtures"
REPO = Path(__file__).resolve().parents[2]


def _start_engine() -> None:
    """The PDF engine (ToolPDF) for the test session, in shared-folder mode over the throwaway data dir.
    RAG_TOOLPDF_URL set = use that running engine instead. Otherwise ToolPDF is looked up in TOOLPDF_HOME,
    by default next to this repository (../ToolPDF), and started with its own virtualenv."""
    if os.environ.get("RAG_TOOLPDF_URL"):
        return
    home = Path(os.environ.get("TOOLPDF_HOME", REPO.parent / "ToolPDF"))
    py = next((p for p in (home / ".venv" / "Scripts" / "python.exe", home / ".venv" / "bin" / "python") if p.exists()), None)
    if py is None:
        sys.exit(f"Tests need the PDF engine ToolPDF: set RAG_TOOLPDF_URL to a running engine, or put ToolPDF "
                 f"with its .venv at {home} (or set TOOLPDF_HOME).")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    cache = tempfile.mkdtemp(prefix="toolpdf-test-cache-")
    env = {**os.environ, "TOOLPDF_SHARED_ROOT": DATA_DIR, "TOOLPDF_CACHE_DIR": cache, "TOOLPDF_WORKERS": "0"}
    proc = subprocess.Popen([str(py), "-m", "uvicorn", "toolpdf.server:app", "--host", "127.0.0.1", "--port", str(port),
                             "--log-level", "warning"], cwd=home, env=env)
    atexit.register(lambda: (proc.terminate(), proc.wait(10), shutil.rmtree(cache, ignore_errors=True)))
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(url + "/v1/health", timeout=1)
            break
        except OSError:
            if proc.poll() is not None:
                sys.exit(f"ToolPDF exited with code {proc.returncode}")
            time.sleep(0.1)
    os.environ["RAG_TOOLPDF_URL"] = url
    os.environ.setdefault("RAG_TOOLPDF_TRANSFER", "shared")


_start_engine()


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """Pages: 0 text, 1 text, 2 table, 3 diagram, 4 scanned, 5 text with figure + caption.
    Made once with ToolPDF's tests/conftest.py build_sample_pdf (same content as the original IngestLens fixture)."""
    path = tmp_path / "sample.pdf"
    # A trailing comment makes every copy unique: uploads deduplicate by sha256, and each test expects a new document.
    path.write_bytes((FIXTURES / "sample.pdf").read_bytes() + f"\n% {uuid.uuid4()}\n".encode())
    return path
