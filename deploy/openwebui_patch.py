#!/usr/bin/env python3
"""Open WebUI 패치: 콘텐츠 추출 엔진이 External(IngestLens)일 때 IngestLens가 처리하는 파일만 보내고,
나머지 파일은 Open WebUI 자체 로더로 읽게 한다. IngestLens가 만든 청크는 Open WebUI가 다시 자르지 않는다.

Open WebUI 0.13.3 소스에 맞춰 만들었다. Open WebUI가 도는 곳(컨테이너 안 등)에서 실행한다:

    python3 openwebui_patch.py            # 패치 (이미 했으면 도우미 모듈만 새로 쓴다)
    python3 openwebui_patch.py --check    # 상태만 본다
    python3 openwebui_patch.py --revert   # 원래대로 되돌린다
    python3 openwebui_patch.py --root /app/backend/open_webui   # 위치를 직접 줄 때

바꾸는 곳(고치기 전에 모든 기준 문장이 있는지 먼저 확인하고, 하나라도 없으면 아무것도 바꾸지 않는다):
- retrieval/loaders/main.py: External 로더를 고르는 조건에 "IngestLens가 처리하는 확장자인가"를 더한다.
  아니면 아래 분기로 내려가 Open WebUI 기본 로더(PDF, docx, md, html, 코드 ...)가 읽는다.
- routers/retrieval.py save_docs_to_vector_db: metadata `loader == "ingestlens"`인 청크는 텍스트 분할기를 건너뛴다.
  그래서 Open WebUI의 청크 설정(CHUNK_SIZE 등)은 기본값대로 두고 다른 파일에 쓰면 된다.
- retrieval/loaders/ingestlens_route.py: 새 파일(판단 코드). 확장자 목록은 IngestLens의 GET {URL}/formats에서
  받아 5분 동안 기억한다. 환경 변수 INGESTLENS_EXTENSIONS(쉼표 목록, 확장자 없는 파일은 noext)로 고정할 수도 있다.

원래 파일은 같은 폴더에 `.ingestlens-orig`로 남긴다. 표준 라이브러리만 쓴다.
"""

import argparse
import importlib.util
import json
import shutil
import sys
from pathlib import Path

PATCH_VERSION = 1
MARK = "INGESTLENS-PATCH"
TESTED = "0.13.3"
BACKUP = ".ingestlens-orig"

ROUTE_MODULE = '''"""IngestLens routing, added by IngestLens' deploy/openwebui_patch.py (not part of Open WebUI). INGESTLENS-PATCH v%(v)d

With the External content extraction engine pointing at IngestLens, only the files IngestLens handles go there;
Open WebUI's own loaders read the rest. Chunks that come back from IngestLens are stored without re-splitting.
"""

import logging
import os
import threading
import time

import requests

log = logging.getLogger(__name__)

PATCH_VERSION = %(v)d
# Used while IngestLens cannot be asked (GET {url}/formats) and INGESTLENS_EXTENSIONS is not set.
DEFAULT_EXTENSIONS = frozenset(
    ["pdf", "png", "jpg", "jpeg", "tif", "tiff", "bmp", "docx", "pptx", "xlsx", "txt", "log", "csv", "tsv", "dat", "bin"]
)
TTL_S = 300
RETRY_S = 30

_cache = {}
_lock = threading.Lock()


def _from_env():
    raw = os.environ.get("INGESTLENS_EXTENSIONS", "").strip()
    if not raw:
        return None
    exts = {e.strip().lower().lstrip(".") for e in raw.split(",") if e.strip()}
    return frozenset(exts - {"noext"}), "noext" in exts


def _formats(url, api_key):
    fixed = _from_env()
    if fixed is not None:
        return fixed
    now = time.monotonic()
    with _lock:
        hit = _cache.get(url)
        if hit and now < hit[0]:
            return hit[1]
    try:
        headers = {"Authorization": "Bearer " + api_key} if api_key else {}
        r = requests.get(url.rstrip("/") + "/formats", headers=headers, timeout=5)
        r.raise_for_status()
        data = r.json()
        fmt = frozenset(str(e).lower() for e in data["extensions"]), bool(data.get("no_extension", True))
        until = now + TTL_S
    except Exception as e:
        log.warning("IngestLens formats unavailable (%%s); using the built-in list", e)
        fmt, until = (DEFAULT_EXTENSIONS, True), now + RETRY_S
    with _lock:
        _cache[url] = (until, fmt)
    return fmt


def ingestlens_handles(filename, url, api_key):
    """True when IngestLens should read this file; False lets Open WebUI's loaders read it."""
    name = os.path.basename(filename or "")
    ext = os.path.splitext(name)[1].lower().lstrip(".")
    exts, no_ext = _formats(url, api_key)
    ok = (ext in exts) if ext else no_ext
    log.info("IngestLens route: %%s -> %%s", name, "IngestLens" if ok else "Open WebUI loaders")
    return ok


def is_ingestlens_chunk(doc):
    return (getattr(doc, "metadata", None) or {}).get("loader") == "ingestlens"
''' % {"v": PATCH_VERSION}

# (file, the exact original text, its replacement). Each original must occur exactly once.
EDITS = [
    (
        "retrieval/loaders/main.py",
        "from open_webui.retrieval.loaders.external_document import ExternalDocumentLoader\n",
        "from open_webui.retrieval.loaders.external_document import ExternalDocumentLoader\n"
        f"from open_webui.retrieval.loaders.ingestlens_route import ingestlens_handles  # {MARK}\n",
    ),
    (
        "retrieval/loaders/main.py",
        "            and self.config['rag.external_document_loader_api_key']\n"
        "        ):\n"
        "            loader = ExternalDocumentLoader(\n",
        "            and self.config['rag.external_document_loader_api_key']\n"
        f"            # {MARK}: only the files IngestLens handles; the rest fall through to Open WebUI's loaders\n"
        "            and ingestlens_handles(\n"
        "                filename,\n"
        "                self.config['rag.external_document_loader_url'],\n"
        "                self.config['rag.external_document_loader_api_key'],\n"
        "            )\n"
        "        ):\n"
        "            loader = ExternalDocumentLoader(\n",
    ),
    (
        "routers/retrieval.py",
        "    if split:\n"
        "        if config['rag.enable_markdown_header_text_splitter']:\n",
        f"    # {MARK}: chunks made by IngestLens are stored as they are; only the others go through the splitters\n"
        "    from open_webui.retrieval.loaders.ingestlens_route import is_ingestlens_chunk\n"
        "\n"
        "    ingestlens_docs = [doc for doc in docs if split and is_ingestlens_chunk(doc)]\n"
        "    if ingestlens_docs:\n"
        "        docs = [doc for doc in docs if not is_ingestlens_chunk(doc)]\n"
        "    if split and docs:\n"
        "        if config['rag.enable_markdown_header_text_splitter']:\n",
    ),
    (
        "routers/retrieval.py",
        "    if len(docs) == 0:\n"
        "        raise ValueError(ERROR_MESSAGES.EMPTY_CONTENT)\n"
        "\n"
        "    texts = [sanitize_text_for_db(doc.page_content) for doc in docs]\n",
        f"    docs = ingestlens_docs + docs  # {MARK}\n"
        "\n"
        "    if len(docs) == 0:\n"
        "        raise ValueError(ERROR_MESSAGES.EMPTY_CONTENT)\n"
        "\n"
        "    texts = [sanitize_text_for_db(doc.page_content) for doc in docs]\n",
    ),
]
MODULE = "retrieval/loaders/ingestlens_route.py"


def find_root(given):
    if given:
        return Path(given)
    for c in (Path("/app/backend/open_webui"),):
        if (c / "retrieval" / "loaders" / "main.py").is_file():
            return c
    spec = importlib.util.find_spec("open_webui")
    if spec and spec.submodule_search_locations:
        return Path(list(spec.submodule_search_locations)[0])
    sys.exit("[오류] Open WebUI(open_webui 패키지)를 찾지 못했습니다. --root 로 위치를 주세요.")


def owui_version(root):
    try:
        import importlib.metadata
        return importlib.metadata.version("open-webui")
    except Exception:
        pass
    for p in (root.parent.parent / "package.json", root.parent / "package.json"):
        try:
            return json.loads(p.read_text(encoding="utf-8"))["version"]
        except Exception:
            continue
    return "알 수 없음"


def read(path):
    """The text with LF line ends (a Windows checkout may have CRLF)."""
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def write(path, text, crlf=False):
    path.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))


def is_crlf(path):
    return b"\r\n" in path.read_bytes()


def state(root):
    files = sorted({f for f, _, _ in EDITS})
    patched = [f for f in files if MARK in read(root / f)]
    if not patched:
        return "none"
    return "all" if len(patched) == len(files) else "partial"


def check(root):
    st = state(root)
    mod = root / MODULE
    print(f"Open WebUI {owui_version(root)} ({root})")
    print({"none": "패치 안 됨", "all": "패치됨", "partial": "일부만 패치됨(--revert 후 다시 하세요)"}[st])
    if mod.is_file():
        line = read(mod).splitlines()[0]
        print("도우미 모듈:", line[line.find("v"):] if MARK in line else "있음(버전 표시 없음)")
    return st


def apply(root):
    version = owui_version(root)
    print(f"Open WebUI {version} ({root})")
    if not version.startswith("0.13."):
        print(f"[주의] 이 패치는 Open WebUI {TESTED}에 맞춰 만들었습니다. 기준 문장이 모두 있을 때만 고칩니다.")
    st = state(root)
    if st == "partial":
        sys.exit("[오류] 일부 파일만 패치되어 있습니다. --revert 로 되돌린 뒤 다시 실행하세요.")
    if st == "none":
        texts = {}
        for f, old, _ in EDITS:
            texts.setdefault(f, read(root / f))
            n = texts[f].count(old)
            if n != 1:
                sys.exit(f"[오류] {f}에서 고칠 곳을 찾지 못했습니다(일치 {n}곳). 이 Open WebUI 버전에는 맞지 않습니다. "
                         "아무것도 바꾸지 않았습니다.")
        for f, old, new in EDITS:
            texts[f] = texts[f].replace(old, new, 1)
        for f, text in texts.items():
            src = root / f
            backup = src.with_name(src.name + BACKUP)
            crlf = is_crlf(src)
            if not backup.exists():
                shutil.copy2(src, backup)
            write(src, text, crlf)
            print("고침:", f)
    else:
        print("이미 패치되어 있습니다. 도우미 모듈만 새로 씁니다.")
    write(root / MODULE, ROUTE_MODULE)
    print("씀:", MODULE)
    print("완료. Open WebUI를 다시 시작하세요(예: docker restart open-webui).")


def revert(root):
    for f in sorted({f for f, _, _ in EDITS}):
        src = root / f
        backup = src.with_name(src.name + BACKUP)
        if backup.exists():
            shutil.copy2(backup, src)
            backup.unlink()
            print("되돌림:", f)
        elif MARK in read(src):
            sys.exit(f"[오류] {f}의 원본({backup.name})이 없어 되돌릴 수 없습니다.")
    mod = root / MODULE
    if mod.exists():
        mod.unlink()
        print("지움:", MODULE)
    print("완료. Open WebUI를 다시 시작하세요.")


def main():
    ap = argparse.ArgumentParser(description="Open WebUI에서 IngestLens가 처리하는 파일만 IngestLens로 보내는 패치")
    ap.add_argument("--root", help="open_webui 패키지 폴더 (기본: /app/backend/open_webui 또는 설치된 패키지)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="상태만 본다")
    g.add_argument("--revert", action="store_true", help="원래대로 되돌린다")
    a = ap.parse_args()
    root = find_root(a.root)
    if a.check:
        check(root)
    elif a.revert:
        revert(root)
    else:
        apply(root)


if __name__ == "__main__":
    main()
