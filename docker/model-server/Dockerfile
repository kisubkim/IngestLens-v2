# IngestLens 모델 서버 이미지 (개발용 docker-compose.yml 에서 CPU reranker 로 쓴다).
# 운영 서버에서는 Docker 없이 vLLM Python 환경에서 server.py 를 바로 실행한다(deploy/README.md).
# 빌드 컨텍스트는 docker/ 이다 (certs/ 를 함께 쓰려고).
FROM python:3.12-slim
# docker/certs/*.crt 를 신뢰한다 (백신·프록시가 HTTPS 를 가로채는 PC 용). 이 이미지는 시작할 때
# Hugging Face 에서 모델을 받으므로 실행 중에도 인증서가 필요하다. 개발 전용이라 배포 묶음에는 넣지 않는다.
COPY certs/ /usr/local/share/ca-certificates/extra/
RUN update-ca-certificates
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HF_HOME=/models \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    PIP_CERT=/etc/ssl/certs/ca-certificates.crt \
    MS_DEVICE=cpu MS_PORT=8080
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir transformers fastapi "uvicorn[standard]"
WORKDIR /srv
COPY model-server/server.py .
EXPOSE 8080
CMD ["python", "server.py"]
