# 운영용 모델 서버 이미지 (GPU, CUDA 포함 torch). 오프라인 배포 묶음의 Singularity 이미지로 변환해 쓴다.
#   apptainer run --nv model-server.sif --embed-model /models/bge-m3 --rerank-model /models/bge-reranker-v2-m3
# 모델은 이미지에 넣지 않는다(바인드로 넣는다). 빌드 컨텍스트는 docker/ 이다.
#
# TORCH_INDEX: cu128 은 A100(sm80), H100(sm90), RTX 50(sm120)을 지원한다. 서버 NVIDIA 드라이버가 오래되어
# cu128 이 안 돌면 cu126 으로 다시 빌드한다(scripts/build_offline_bundle.py --torch-cuda cu126).
FROM python:3.12-slim
ARG TORCH_INDEX=https://download.pytorch.org/whl/cu128
ARG VERSION=dev
LABEL org.opencontainers.image.title="IngestLens model server" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.source="https://github.com/kisubkim/IngestLens-v2" \
      org.opencontainers.image.licenses="MIT"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 MS_PORT=8090
# 빌드 PC의 추가 인증서(docker/certs/*.crt)는 패키지를 받는 동안만 쓰고 이미지에 남기지 않는다.
RUN --mount=type=bind,source=certs,target=/tmp/certs \
    cat /etc/ssl/certs/ca-certificates.crt /tmp/certs/*.crt > /tmp/ca.pem 2>/dev/null; \
    PIP_CERT=/tmp/ca.pem pip install --no-cache-dir torch --index-url ${TORCH_INDEX} \
 && PIP_CERT=/tmp/ca.pem pip install --no-cache-dir transformers fastapi "uvicorn[standard]" \
 && rm -f /tmp/ca.pem
COPY model-server/server.py /srv/server.py
EXPOSE 8090
ENTRYPOINT ["python", "/srv/server.py"]
