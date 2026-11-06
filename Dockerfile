FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY agente/ agente/
COPY data/estandares/ data/estandares/
COPY data/rutas.json data/rutas.json
# Índice inicial sin claves (embeddings hash): la imagen arranca aunque no haya .env.
RUN python -m agente.ingesta
RUN useradd --create-home app && mkdir -p salida && chown -R app /app
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=60s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
# Al arrancar, con las claves del .env: si los embeddings configurados no son los del índice (p. ej. openai), se
# re-indexa una vez; si el índice ya corresponde, no se gasta nada. Después, la API.
CMD ["sh", "-c", "python -m agente.ingesta --si-falta && exec uvicorn agente.api:crear_app --factory --host 0.0.0.0 --port 8000"]
