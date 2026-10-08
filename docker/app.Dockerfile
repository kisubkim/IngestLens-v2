# IngestLens 앱 이미지: 프론트 빌드 + FastAPI 백엔드. 로컬 개발(docker-compose.yml)과 오프라인 배포에 같은 이미지를 쓴다.
# PDF 라이브러리는 넣지 않는다. 문서를 PDF로 바꾸고 읽고 그리는 일(LibreOffice 포함)은 PDF 엔진 ToolPDF 가 한다.
#
# docker/certs/*.crt (백신·프록시가 HTTPS 를 가로채는 빌드 PC 용)는 npm·pip 가 패키지를 받는 동안에만 bind mount 로 쓴다.
# 이미지 레이어에는 남지 않으므로, 이 PC에서 빌드한 이미지를 그대로 운영 서버에 배포해도 된다.

FROM node:22-slim AS ui
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=bind,source=docker/certs,target=/tmp/certs \
    cat /tmp/certs/*.crt > /tmp/extra-ca.pem 2>/dev/null; \
    NODE_EXTRA_CA_CERTS=/tmp/extra-ca.pem npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ARG VERSION=dev
ARG GIT_COMMIT=unknown
LABEL org.opencontainers.image.title="IngestLens" \
      org.opencontainers.image.description="RAG 수집 파이프라인 (문서 분석, 파싱, 청킹, 임베딩)과 웹 화면" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${GIT_COMMIT}" \
      org.opencontainers.image.source="https://github.com/kisubkim/IngestLens-v2" \
      org.opencontainers.image.licenses="MIT"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    RAG_DATA_DIR=/data \
    RAG_SETTINGS_FILE=/data/settings.local.yaml \
    INGESTLENS_VERSION=${VERSION}
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN --mount=type=bind,source=docker/certs,target=/tmp/certs \
    cat /etc/ssl/certs/ca-certificates.crt /tmp/certs/*.crt > /tmp/ca.pem 2>/dev/null; \
    PIP_CERT=/tmp/ca.pem pip install --no-cache-dir -r backend/requirements.txt && rm -f /tmp/ca.pem
COPY backend/ backend/
COPY config/ config/
COPY LICENSE NOTICE.md ./
COPY --from=ui /src/frontend/dist frontend/dist
WORKDIR /app/backend
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"
# --app-dir: Singularity/Apptainer starts in the caller's folder, not WORKDIR. INGESTLENS_PORT: Singularity shares
# the host network, so the port is chosen here instead of by a port mapping.
CMD ["sh", "-c", "exec python -m uvicorn --app-dir /app/backend app.main:app --host 0.0.0.0 --port ${INGESTLENS_PORT:-8000}"]
