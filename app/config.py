"""Configuración central. Todo lo ajustable vive aquí y se lee de .env (nunca del código).

Windows: el Bloc de notas guarda UTF-8 con BOM y PowerShell 5.1 (`echo X=1 > .env`) guarda UTF-16. python-dotenv, por
sí solo, lee mal esos archivos. Por eso `.env` se decodifica a mano antes de cargarlo (igual que en el lab 07).
"""
from __future__ import annotations

import io
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
WEB_DIR = BASE_DIR / "web"

# Umbral de relevancia por embedder: la escala de similitud depende del modelo (text-embedding-3-small da cosenos
# de 0.3-0.7 a textos relacionados; el embedder hash, léxico, da valores más bajos). Se calibra con eval/evaluar.py.
# Calibrados con eval/gold.json (python -m eval.evaluar), centro de la meseta de mejor exactitud:
#   openai text-embedding-3-small: meseta 0.30–0.45 (2026-11-01: hit@5 0.97, abstención 1.0) → 0.375
#   hash: 0.25 (exactitud 0.73)
MIN_SCORE_POR_EMBEDDER = {"openai": 0.375, "hash": 0.25}
ROUTER_MIN_POR_EMBEDDER = {"openai": 0.35, "hash": 0.20}


class ConfigError(RuntimeError):
    """Configuración inválida o incompleta (falta una clave, proveedor desconocido…)."""


def decode_env_bytes(raw: bytes) -> str:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):   # UTF-16 (con BOM)
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig")                   # UTF-8, con o sin BOM


def load_env(path: Path | None = None) -> None:
    """Carga .env sin pisar variables que ya estén definidas en el sistema (override=False)."""
    path = path or BASE_DIR / ".env"
    if path.exists():
        load_dotenv(stream=io.StringIO(decode_env_bytes(path.read_bytes())), override=False)


def _txt(nombre: str, defecto: str = "") -> str:
    return os.getenv(nombre, defecto).strip()


def _num(nombre: str, defecto: float) -> float:
    valor = _txt(nombre)
    try:
        return float(valor) if valor else defecto
    except ValueError:
        raise ConfigError(f"{nombre}={valor!r} no es un número") from None


class Settings:
    """Se construye al llamar `Settings()`, así las pruebas pueden cambiar variables y crear otra."""

    def __init__(self) -> None:
        # --- proveedores ---------------------------------------------------------------------------------------
        self.llm_provider = _txt("LLM_PROVIDER", "anthropic").lower()            # anthropic | openai | mock
        self.embeddings_provider = _txt("EMBEDDINGS_PROVIDER", "openai").lower() # openai | hash

        # --- OpenAI --------------------------------------------------------------------------------------------
        self.openai_api_key = _txt("OPENAI_API_KEY")
        self.openai_model = _txt("OPENAI_MODEL", "gpt-5.4-mini")
        self.openai_embedding_model = _txt("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
        self.openai_reasoning_effort = _txt("OPENAI_REASONING_EFFORT").lower()
        self.openai_timeout_s = _num("OPENAI_TIMEOUT_S", 60)
        self.openai_max_output_tokens = int(_num("OPENAI_MAX_OUTPUT_TOKENS", 3000))

        # --- Anthropic (Claude) ---------------------------------------------------------------------------------
        self.anthropic_api_key = _txt("ANTHROPIC_API_KEY")
        self.anthropic_model = _txt("ANTHROPIC_MODEL", "claude-opus-5-5")
        self.anthropic_effort = _txt("ANTHROPIC_EFFORT", "medium").lower()     # low | medium | high | xhigh | max
        self.anthropic_fallback = _txt("ANTHROPIC_FALLBACK", "default")         # vacío = sin respaldo ante rechazos
        self.anthropic_timeout_s = _num("ANTHROPIC_TIMEOUT_S", 120)
        self.anthropic_max_tokens = int(_num("ANTHROPIC_MAX_TOKENS", 16000))

        # --- corpus e índice -----------------------------------------------------------------------------------
        self.pdf_dir = Path(_txt("PDF_DIR") or DATA_DIR / "pdfs")
        self.registro_path = Path(_txt("REGISTRO_PATH") or DATA_DIR / "documentos.json")
        self.indice_path = Path(_txt("INDICE_PATH") or DATA_DIR / "indice.npz")

        # --- RAG -----------------------------------------------------------------------------------------------
        tipo = "openai" if self.embeddings_provider == "openai" else "hash"
        self.rag_top_k = int(_num("RAG_TOP_K", 5))
        self.rag_min_score = _num("RAG_MIN_SCORE", MIN_SCORE_POR_EMBEDDER[tipo])
        self.historial_max = int(_num("HISTORIAL_MAX", 6))                       # mensajes previos que ve el LLM

        # --- router y agente -----------------------------------------------------------------------------------
        self.router_min_score = _num("ROUTER_MIN_SCORE", ROUTER_MIN_POR_EMBEDDER[tipo])
        self.max_caracteres_codigo = int(_num("MAX_CARACTERES_CODIGO", 15000))

        # --- aplicación ----------------------------------------------------------------------------------------
        self.db_path = Path(_txt("DB_PATH") or DATA_DIR / "estandares.db")
        self.trazas_path = Path(_txt("TRAZAS_PATH") or DATA_DIR / "trazas.jsonl")
        self.limite_por_minuto = int(_num("LIMITE_POR_MINUTO", 30))             # mensajes por IP

        # --- costos (USD por millón de tokens) -----------------------------------------------------------------
        self.precio_openai_input = _num("PRECIO_OPENAI_INPUT", 0)
        self.precio_openai_output = _num("PRECIO_OPENAI_OUTPUT", 0)
        self.precio_openai_embeddings = _num("PRECIO_OPENAI_EMBEDDINGS", 0)
        self.precio_anthropic_input = _num("PRECIO_ANTHROPIC_INPUT", 0)
        self.precio_anthropic_output = _num("PRECIO_ANTHROPIC_OUTPUT", 0)

    def validar(self) -> None:
        """Falla al arrancar con un mensaje claro, en vez de fallar en la primera solicitud."""
        for campo, validas in {"llm_provider": {"anthropic", "openai", "mock"},
                               "embeddings_provider": {"openai", "hash"}}.items():
            if getattr(self, campo) not in validas:
                raise ConfigError(f"{campo.upper()}={getattr(self, campo)!r}; opciones: {sorted(validas)}")
        if self.llm_provider == "anthropic" and not self.anthropic_api_key:
            raise ConfigError("LLM_PROVIDER=anthropic pero ANTHROPIC_API_KEY está vacío en .env")
        if "openai" in (self.llm_provider, self.embeddings_provider) and not self.openai_api_key:
            raise ConfigError("LLM_PROVIDER/EMBEDDINGS_PROVIDER=openai pero OPENAI_API_KEY está vacío en .env")
        if self.anthropic_effort not in ("low", "medium", "high", "xhigh", "max"):
            raise ConfigError(f"ANTHROPIC_EFFORT={self.anthropic_effort!r}; opciones: low, medium, high, xhigh, max")
        if not 0 <= self.rag_min_score < 1:
            raise ConfigError(f"RAG_MIN_SCORE={self.rag_min_score} debe estar entre 0 y 1")


load_env()
