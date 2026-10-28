# API 이미지(#168). 배포 절차와 이유는 deploy_rules.md 「배포 구성」.
# 빌드 맥락은 저장소 루트다 — 장소 적재 명령(places.load)이 docs/constraints.md를 읽는다(/docs/constraints.md로 넣는다):
#   docker build -f backend/Dockerfile -t pingo-api .
# 이미지에 들어가는 파일은 backend/Dockerfile.dockerignore가 정한다. 비밀값은 넣지 않는다(실행할 때 환경 변수로).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PINGO_LOAD_DOTENV=0

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install -r requirements.txt

COPY docs/constraints.md /docs/constraints.md
COPY backend/ .

# 루트가 아닌 사용자로 돈다
RUN useradd --create-home --uid 10001 pingo && chown -R pingo /app
USER pingo

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"

# 프로세스 1개(워커 1)로 돈다 — 메모리 요청 상한, 서버 시작 시 정리, 관찰 lease가 이 전제에서 안전하다(deploy_rules.md 「타협」).
# 앞단 프록시(Caddy)만 이 컨테이너에 닿으므로 그 주소를 믿고 X-Forwarded-For를 읽는다(게스트 가입 IP 상한, #472).
CMD ["uvicorn", "main:asgi_app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--timeout-graceful-shutdown", "10"]
