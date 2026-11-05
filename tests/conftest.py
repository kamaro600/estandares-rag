"""Las pruebas nunca llaman a una API real ni tocan los datos reales del proyecto.

- Fuerzan el simulador y los embeddings hash ANTES de importar nada (el .env del desarrollador puede decir openai).
- Redirigen catálogo, secciones, índice, base del chat y salida a una carpeta temporal, y construyen ahí el índice
  una sola vez: data/indice.npz (que puede ser de OpenAI) nunca se pisa. Los subprocesos (uvicorn, la CLI)
  heredan estas variables.
"""
import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="lab07-pruebas-"))
os.environ.update({
    "LLM_PROVIDER": "mock", "EMBEDDINGS_PROVIDER": "hash", "RAG_MIN_SCORE": "0.08", "ROUTER_MIN_SCORE": "",
    "TIPO_APP": "web", "MODO_BD": "nueva", "ANTHROPIC_API_KEY": "", "OPENAI_API_KEY": "",
    "ANTHROPIC_EFFORT": "medium", "ANTHROPIC_FALLBACK": "default", "LIMITE_POR_MINUTO": "1000",
    "CATALOGO_PATH": str(_TMP / "catalogo.json"), "SECCIONES_PATH": str(_TMP / "secciones.json"),
    "INDICE_PATH": str(_TMP / "indice.npz"), "DB_PATH": str(_TMP / "chat.db"), "SALIDA_DIR": str(_TMP / "salida"),
})


def pytest_sessionstart(session):
    import contextlib
    import io

    from agente import ingesta
    if not hasattr(ingesta, "main"):   # pasos 2 y 3 de la guía: la ingesta todavía es un archivo vacío
        return
    with contextlib.redirect_stdout(io.StringIO()):
        ingesta.main([])
