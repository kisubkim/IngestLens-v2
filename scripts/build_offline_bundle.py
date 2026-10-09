"""Build the offline deployment bundle: one tar file to carry to a server without internet.

    python scripts/build_offline_bundle.py [--version 20261005] [--out release]

Steps: build the app image (docker/app.Dockerfile), `docker save` it gzipped, copy deploy/ (compose file, models.yaml,
install.sh, model-server.sh, README) and the model server (docker/model-server/server.py), copy ToolPDF's own release
folder as toolpdf/, write .env with the versions and SHA256SUMS, and pack everything into
release/ingestlens-<version>-offline.tar.
The PDF engine ToolPDF (AGPL-3.0) is a separate program and is not built here: its release folder (Docker image, .sif,
ToolPDF source, PyMuPDF source, license files) comes from ToolPDF's `docker/release.sh` and is copied unchanged, so the
bundle carries the sources the AGPL asks for. Default: the newest $TOOLPDF_DIR/release/toolpdf-* (TOOLPDF_DIR defaults to
../ToolPDF); --toolpdf-release picks another one.
With --singularity it also builds the GPU model-server image and adds sif/ingestlens-app.sif and
sif/ingestlens-model-server.sif (converted with Apptainer in a container), run by singularity.sh without root or Docker. --no-docker (with --singularity) leaves the Docker image out.
--pdf-engine local makes the bundle without ToolPDF: the app's own PDF engine (permissive libraries only) does all
PDF work, deploy/docker-compose.local-engine.yml becomes docker-compose.yml, .env and singularity.env say
RAG_PDF_ENGINE=local, and the archive is release/ingestlens-<version>-local-offline.tar. Same app image either way.
Model weights are not included (see deploy/README.md).
"""

import argparse
import gzip
import hashlib
import os
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WSL_DISTRO = os.environ.get("INGESTLENS_WSL_DISTRO", "Ubuntu-24.04")


def _docker_prefix() -> list[str]:
    """`docker` on PATH; on Windows without it, the Docker Engine inside WSL (no Docker Desktop needed)."""
    if shutil.which("docker") or os.name != "nt" or not shutil.which("wsl.exe"):
        return ["docker"]
    return ["wsl.exe", "-d", WSL_DISTRO, "-u", "root", "--cd", str(ROOT), "--", "docker"]


DOCKER = _docker_prefix()
_WIN_PATH = re.compile(r"^[A-Za-z]:[\\/]")


def _arg(a: str) -> str:
    """When docker runs in WSL, Windows paths in its arguments ("D:/x/image.tar", "D:/x:/work") become /mnt/d/..."""
    if DOCKER[0] == "docker" or not _WIN_PATH.match(a):
        return a
    host, sep, rest = a[2:].partition(":")
    return f"/mnt/{a[0].lower()}" + host.replace("\\", "/") + sep + rest


def docker(*args: str) -> None:
    run(*DOCKER, *(_arg(a) for a in args))


def run(*cmd: str) -> None:
    """Output goes straight to the console: docker build progress is long, and its bytes are not cp949-safe."""
    print("$", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def save_image(image: str, dest: Path) -> None:
    """docker save | gzip, streamed so a multi-GB image never sits in memory."""
    print(f"$ docker save {image} | gzip > {dest.relative_to(ROOT)}", flush=True)
    with subprocess.Popen([*DOCKER, "save", image], stdout=subprocess.PIPE) as p, gzip.open(dest, "wb", compresslevel=6) as out:
        shutil.copyfileobj(p.stdout, out, length=1 << 20)
    if p.returncode:
        raise SystemExit(f"docker save {image} failed")


def to_sif(image: str, dest: Path, out: Path, apptainer_image: str) -> None:
    """docker save -> `apptainer build x.sif docker-archive://x.tar`, run inside the official Apptainer image."""
    work = (out / "_sif_work").resolve()
    work.mkdir(parents=True, exist_ok=True)
    tar = work / "image.tar"
    docker("save", "-o", str(tar), image)
    docker("run", "--rm", "--privileged", "-v", f"{work}:/work", apptainer_image,
        "apptainer", "build", "--force", "/work/image.sif", "docker-archive:///work/image.tar")
    shutil.move(str(work / "image.sif"), dest)
    shutil.rmtree(work)


def toolpdf_release(arg: Path | None) -> Path:
    """ToolPDF's release folder (release/toolpdf-<version>/ from its docker/release.sh): the given one or the newest."""
    if arg:
        rel = arg
    else:
        home = Path(os.environ.get("TOOLPDF_DIR") or ROOT.parent / "ToolPDF")
        found = sorted((home / "release").glob("toolpdf-*/"), key=lambda p: p.stat().st_mtime)
        if not found:
            raise SystemExit(f"ToolPDF 배포 폴더가 없습니다: {home / 'release'}\n"
                             "ToolPDF 저장소에서 docker/release.sh 로 먼저 만들거나 --toolpdf-release 로 위치를 지정하세요.")
        rel = found[-1]
    if not list(rel.glob("toolpdf-*-docker.tar.gz")) or not list(rel.glob("toolpdf-*.sif")):
        raise SystemExit(f"{rel} 에 ToolPDF 이미지(-docker.tar.gz, .sif)가 없습니다.")
    return rel


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", help="image tag (default: build date, e.g. 20261005; the commit goes into VERSION and the image label)")
    ap.add_argument("--out", type=Path, default=ROOT / "release")
    ap.add_argument("--singularity", action="store_true",
                    help="also build the GPU model-server image and convert both images to Singularity/Apptainer .sif files")
    ap.add_argument("--torch-cuda", default="cu128", help="CUDA build of torch for the model server (cu128, or cu126 for older drivers)")
    ap.add_argument("--apptainer-image", default="ghcr.io/apptainer/apptainer:latest", help="image that runs `apptainer build`")
    ap.add_argument("--no-docker", action="store_true",
                    help="leave the Docker image out of the bundle (Singularity-only servers); needs --singularity")
    ap.add_argument("--toolpdf-release", type=Path,
                    help="ToolPDF release folder (default: newest $TOOLPDF_DIR/release/toolpdf-*, TOOLPDF_DIR=../ToolPDF)")
    ap.add_argument("--pdf-engine", choices=["toolpdf", "local"], default="toolpdf",
                    help="toolpdf: bundle ToolPDF's release next to the app (default); local: no ToolPDF, the app's own engine")
    a = ap.parse_args()
    if a.no_docker and not a.singularity:
        ap.error("--no-docker leaves no image to run; use it together with --singularity")
    with_toolpdf = a.pdf_engine == "toolpdf"
    tp_rel = toolpdf_release(a.toolpdf_release) if with_toolpdf else None
    tp_version = tp_rel.name.removeprefix("toolpdf-") if tp_rel else ""

    commit = git("rev-parse", "--short", "HEAD") or "unknown"
    dirty = bool(git("status", "--porcelain"))
    version = a.version or f"{date.today():%Y%m%d}"
    if dirty:
        print("[경고] 커밋하지 않은 변경이 있습니다. 이미지에는 지금 작업 폴더의 내용이 들어갑니다.", file=sys.stderr)

    name = f"ingestlens-{version}" + ("" if with_toolpdf else "-local")
    bundle = a.out / name
    if bundle.exists():
        shutil.rmtree(bundle)
    bundle.mkdir(parents=True)

    # The Docker image is built either way: the .sif files are converted from it.
    image = f"ingestlens:{version}"
    docker("build", "-f", "docker/app.Dockerfile", "--build-arg", f"VERSION={version}",
        "--build-arg", f"GIT_COMMIT={commit}{'-dirty' if dirty else ''}", "-t", image, "-t", "ingestlens:latest", ".")
    if not a.no_docker:
        (bundle / "images").mkdir()
        save_image(image, bundle / "images" / f"ingestlens-app-{version}.tar.gz")

    if a.singularity:
        ms_image = f"ingestlens-model-server:{version}"
        docker("build", "-f", "docker/model-server/release.Dockerfile",
            "--build-arg", f"TORCH_INDEX=https://download.pytorch.org/whl/{a.torch_cuda}",
            "--build-arg", f"VERSION={version}", "-t", ms_image, "docker")
        (bundle / "sif").mkdir()
        to_sif(image, bundle / "sif" / "ingestlens-app.sif", a.out, a.apptainer_image)
        to_sif(ms_image, bundle / "sif" / "ingestlens-model-server.sif", a.out, a.apptainer_image)

    compose = "docker-compose.yml" if with_toolpdf else "docker-compose.local-engine.yml"
    for f in (ROOT / "deploy").iterdir():
        if f.is_file() and not f.name.startswith("docker-compose"):
            # A Windows checkout may have CRLF; on the server `. ./model-server.env` would then keep a '\r' in every value.
            (bundle / f.name).write_bytes(f.read_bytes().replace(b"\r\n", b"\n"))
    (bundle / "docker-compose.yml").write_bytes((ROOT / "deploy" / compose).read_bytes().replace(b"\r\n", b"\n"))
    (bundle / "model-server").mkdir()
    shutil.copy2(ROOT / "docker" / "model-server" / "server.py", bundle / "model-server" / "server.py")
    shutil.copy2(ROOT / "LICENSE", bundle / "LICENSE")
    shutil.copy2(ROOT / "NOTICE.md", bundle / "NOTICE.md")
    if with_toolpdf:
        # Unchanged, with its own BUNDLE.md and SHA256SUMS: the ToolPDF and PyMuPDF sources travel with the images.
        print(f"$ copy {tp_rel} -> toolpdf/", flush=True)
        shutil.copytree(tp_rel, bundle / "toolpdf")
    env = (ROOT / "deploy" / ".env.example").read_text(encoding="utf-8")
    env = env.replace("INGESTLENS_VERSION=\n", f"INGESTLENS_VERSION={version}\n")
    env = env.replace("TOOLPDF_VERSION=\n", f"TOOLPDF_VERSION={tp_version}\n")
    if not with_toolpdf:
        env = env.replace("RAG_PDF_ENGINE=auto\n", "RAG_PDF_ENGINE=local\n")
    (bundle / ".env").write_text(env, encoding="utf-8", newline="\n")
    # Singularity shares the host network: the model server is 127.0.0.1, not host.docker.internal.
    sing = (bundle / "models.yaml").read_text(encoding="utf-8").replace("host.docker.internal", "127.0.0.1")
    (bundle / "models.singularity.yaml").write_text(sing, encoding="utf-8", newline="\n")
    # The engine's port is open on the host network under Singularity, so the bundle ships with a random key.
    senv = (bundle / "singularity.env.example").read_text(encoding="utf-8")
    if with_toolpdf:
        senv = senv.replace("TOOLPDF_SIF=toolpdf/toolpdf-<버전>.sif\n", f"TOOLPDF_SIF=toolpdf/toolpdf-{tp_version}.sif\n")
        senv = senv.replace("TOOLPDF_API_KEY=\n", f"TOOLPDF_API_KEY={secrets.token_urlsafe(24)}\n")
    else:
        senv = senv.replace("RAG_PDF_ENGINE=auto\n", "RAG_PDF_ENGINE=local\n")
        senv = senv.replace("TOOLPDF_SIF=toolpdf/toolpdf-<버전>.sif\n", "TOOLPDF_SIF=\n")
    (bundle / "singularity.env").write_text(senv, encoding="utf-8", newline="\n")
    engine_line = f"toolpdf {tp_version}" if with_toolpdf else "pdf engine local (no ToolPDF)"
    (bundle / "VERSION").write_text(f"{version}\ncommit {commit}{' (dirty)' if dirty else ''}\nbuilt {date.today()}\n"
                                    f"{engine_line}\n",
                                    encoding="utf-8", newline="\n")

    files = sorted(p for p in bundle.rglob("*") if p.is_file())
    # .env and models.yaml are meant to be edited on the server, so install.sh must not report them as corrupt.
    checked = [p for p in files if p.name not in (".env", "models.yaml", "models.singularity.yaml", "singularity.env")]
    (bundle / "SHA256SUMS").write_text("".join(f"{sha256(p)}  {p.relative_to(bundle).as_posix()}\n" for p in checked),
                                       encoding="utf-8", newline="\n")

    archive = a.out / f"{name}-offline.tar"
    with tarfile.open(archive, "w") as tar:  # images are already gzipped; a second compression gains nothing
        for p in sorted(bundle.rglob("*")):
            info = tar.gettarinfo(p, arcname=p.relative_to(a.out).as_posix())
            if p.suffix == ".sh":
                info.mode = 0o755
            if p.is_file():
                with p.open("rb") as f:
                    tar.addfile(info, f)
            else:
                tar.addfile(info)

    print()
    print(f"배포 묶음: {archive.relative_to(ROOT)} ({archive.stat().st_size / 2**20:.0f} MB)")
    for p in files:
        print(f"  {p.relative_to(bundle).as_posix():<55} {p.stat().st_size / 2**20:8.1f} MB")
    print(f"PDF 엔진: ToolPDF {tp_version} ({tp_rel})" if with_toolpdf else "PDF 엔진: 앱 안의 내장 엔진 (ToolPDF 없음)")
    print(f"서버에서: tar xf <묶음>.tar && cd {name} && ./install.sh, 모델 서버는 ./model-server.sh start (자세히: README.md)")


if __name__ == "__main__":
    main()
