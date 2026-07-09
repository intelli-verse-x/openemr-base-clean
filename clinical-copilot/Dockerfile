FROM python:3.11-slim

WORKDIR /app

# System deps for aiomysql/cryptography are pure-python or wheels; keep image lean.
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e . || pip install --no-cache-dir \
    fastapi "uvicorn[standard]" pydantic pydantic-settings aiomysql httpx openai \
    langfuse python-json-logger prometheus-client

COPY app ./app

EXPOSE 8500
# /ready validates OpenEMR DB + LLM + observability reachability.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8500/health').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8500"]
