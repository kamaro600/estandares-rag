"""Las pruebas NUNCA llaman a OpenAI: no gastan dinero ni necesitan internet. Usan el embedder hash y un LLM espía
(el simulador, más un registro de llamadas y respuestas preparadas). El índice se construye UNA vez por sesión con
los PDFs reales de data/pdfs.
"""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

# Aislamiento del .env del desarrollador: app.config carga .env SIN pisar variables ya definidas, así que se fijan
# aquí antes de importar app.*. Vacío = valor por defecto (p. ej. el umbral calibrado para el embedder hash).
for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "INDICE_PATH", "DB_PATH", "TRAZAS_PATH", "PDF_DIR", "REGISTRO_PATH",
          "RAG_MIN_SCORE", "RAG_TOP_K", "ROUTER_MIN_SCORE", "HISTORIAL_MAX", "LIMITE_POR_MINUTO"):
    os.environ[k] = ""
os.environ.update(LLM_PROVIDER="mock", EMBEDDINGS_PROVIDER="hash", ANTHROPIC_MODEL="claude-opus-5-5",
                  ANTHROPIC_EFFORT="medium", ANTHROPIC_FALLBACK="default")

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def catalogo() -> dict:
    return json.loads((RAIZ / "data" / "catalogo.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def indice(tmp_path_factory) -> Path:
    from app.config import Settings
    from app.embeddings import HashEmbedder
    from app.ingesta import construir_indice
    ruta = tmp_path_factory.mktemp("indice") / "indice.npz"
    os.environ["INDICE_PATH"] = str(ruta)
    construir_indice(Settings(), HashEmbedder())
    return ruta


@pytest.fixture
def settings(indice, tmp_path, monkeypatch):
    from app.config import Settings
    monkeypatch.setenv("INDICE_PATH", str(indice))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "estandares.db"))
    monkeypatch.setenv("TRAZAS_PATH", str(tmp_path / "trazas.jsonl"))
    return Settings()


@pytest.fixture
def rag(settings):
    from app.embeddings import HashEmbedder
    from app.rag import RAG
    return RAG(settings.indice_path, HashEmbedder(), settings.rag_min_score, settings.rag_top_k)


class LLMEspia:
    """MockLLM que registra cada llamada. `preparar(nombre, datos | excepción)` fija la próxima respuesta."""

    def __init__(self):
        from app.llm import MockLLM
        self.base, self.llamadas, self.preparadas = MockLLM(), [], {}
        self.nombre = self.modelo = "espia"

    def preparar(self, nombre, respuesta):
        self.preparadas[nombre] = respuesta

    def generar(self, instrucciones, contexto, esquema, nombre):
        from app.llm import RespuestaLLM
        self.llamadas.append(SimpleNamespace(nombre=nombre, contexto=contexto, instrucciones=instrucciones))
        if nombre in self.preparadas:
            r = self.preparadas.pop(nombre)
            if isinstance(r, Exception):
                raise r
            return RespuestaLLM(r, "espia", 10, 5)
        return self.base.generar(instrucciones, contexto, esquema, nombre)

    def de(self, nombre):
        return [c for c in self.llamadas if c.nombre == nombre]


@pytest.fixture
def espia():
    return LLMEspia()


@pytest.fixture
def servicios(settings, rag, espia):
    from app.agente import AgenteValidador
    from app.chat import Chat
    from app.db import Repositorio
    from app.main import Servicios
    from app.router import crear_router
    from app.traza import Trazador
    repo = Repositorio(settings.db_path)
    trazador = Trazador(repo, settings.trazas_path)
    chat = Chat(settings, rag, espia, crear_router(settings, rag.embedder), AgenteValidador(rag, espia, trazador),
                repo, trazador)
    return Servicios(settings, chat, rag, repo)


@pytest.fixture
def cliente(servicios):
    from fastapi.testclient import TestClient
    from app.main import create_app
    with TestClient(create_app(servicios)) as c:
        yield c


def crear_pdf(ruta: Path, paginas: list[list[str]]) -> Path:
    """PDF mínimo con reportlab: una lista de líneas por página (para probar formatos distintos al del corpus)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(ruta), pagesize=A4, invariant=1)
    for lineas in paginas:
        y = A4[1] - 60
        for linea in lineas:
            c.drawString(50, y, linea)
            y -= 16
        c.showPage()
    c.save()
    return ruta
