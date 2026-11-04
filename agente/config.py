"""Configuración y límites de seguridad del agente corrector de estándares."""
from __future__ import annotations

import io
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
ESTANDARES_DIR = DATA_DIR / "estandares"
CATALOGO_PATH = DATA_DIR / "catalogo.json"
INDICE_PATH = DATA_DIR / "indice.npz"
SALIDA_DIR = BASE_DIR / "salida"

# ---- Límites: cada uno protege contra un modo de fallo concreto ----
MAX_REACT_ITERS = 8            # un especialista que da vueltas sin terminar
MAX_REPEATED_CALLS = 2         # la misma herramienta con los mismos argumentos
MAX_ARCHIVOS = 50              # una revisión que intenta leer todo el disco
MAX_BYTES_ARCHIVO = 200_000    # un archivo gigante que dispara el costo
MAX_LINEAS_PARCHE = 30         # un "parche" que reescribe el archivo entero
MAX_PARCHES_POR_ARCHIVO = 20   # un especialista que propone sin fin
TOOL_RESULT_MAX_CHARS = 3000   # un resultado que diluye el contexto
RAG_TOP_K = 4
RAG_MIN_SCORE = 0.08           # calibrado en el paso 6 con eval/rag_oro.json

TIPOS_APP = ("web", "api", "escritorio", "movil")
MODOS_BD = ("nueva", "legada")
PROVEEDORES = ("mock", "anthropic", "openai")
EMBEDDINGS = ("hash", "openai")
ESFUERZOS = ("", "low", "medium", "high")


def importar_sdk(paquete: str):
    """Importa un SDK opcional con un mensaje que dice qué instalar, en vez de un traceback."""
    import importlib  # noqa: PLC0415
    try:
        return importlib.import_module(paquete)
    except ImportError:
        raise RuntimeError(f"Falta el paquete '{paquete}' en el entorno activo. Con el entorno activado: "
                           "python -m pip install -r requirements.txt") from None


def consola_segura() -> None:
    """En Windows, la salida redirigida (pytest, un pipeline, '> reporte.txt') usa cp1252 por defecto.

    Redirigida: siempre UTF-8, que es lo que espera quien la lee (y no cae con '→' ni '·').
    En una consola real: la codificación de la consola, reemplazando lo que no pueda mostrar.
    """
    for flujo in (sys.stdout, sys.stderr):
        if not hasattr(flujo, "reconfigure"):
            continue
        if flujo.isatty():
            flujo.reconfigure(errors="replace")
        else:
            flujo.reconfigure(encoding="utf-8", errors="replace")


def decode_env_bytes(raw: bytes) -> str:
    """Lee .env en UTF-8, UTF-8 con BOM o UTF-16 (lo que crea PowerShell 5.1)."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig")


def load_env(path: Path | None = None) -> None:
    """Carga .env sin pisar variables ya definidas en el sistema."""
    path = path or BASE_DIR / ".env"
    if path.exists():
        load_dotenv(stream=io.StringIO(decode_env_bytes(path.read_bytes())), override=False)


def _float(nombre: str, defecto: float) -> float:
    valor = os.getenv(nombre, str(defecto)).strip().replace(",", ".")
    try:
        return float(valor)
    except ValueError as exc:
        raise ValueError(f"{nombre}={valor!r} no es un número") from exc


@dataclass
class Settings:
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "mock").strip().lower())
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "claude-sonnet-5-5").strip())
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", "").strip())
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", "").strip())
    openai_model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "").strip())
    openai_reasoning_effort: str = field(default_factory=lambda: os.getenv("OPENAI_REASONING_EFFORT", "").strip().lower())
    embeddings_provider: str = field(default_factory=lambda: os.getenv("EMBEDDINGS_PROVIDER", "hash").strip().lower())
    openai_embedding_model: str = field(
        default_factory=lambda: os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small").strip())
    tipo_app: str = field(default_factory=lambda: os.getenv("TIPO_APP", "web").strip().lower())
    modo_bd: str = field(default_factory=lambda: os.getenv("MODO_BD", "nueva").strip().lower())
    rag_min_score: float = field(default_factory=lambda: _float("RAG_MIN_SCORE", RAG_MIN_SCORE))

    def validar(self) -> "Settings":
        if self.llm_provider not in PROVEEDORES:
            raise ValueError(f"LLM_PROVIDER debe ser uno de {PROVEEDORES}, no {self.llm_provider!r}")
        if self.llm_provider == "anthropic" and not self.anthropic_api_key:
            raise ValueError("LLM_PROVIDER=anthropic exige ANTHROPIC_API_KEY en .env")
        if self.llm_provider == "openai" and not (self.openai_api_key and self.openai_model):
            raise ValueError("LLM_PROVIDER=openai exige OPENAI_API_KEY y OPENAI_MODEL en .env")
        if self.openai_reasoning_effort not in ESFUERZOS:
            raise ValueError(f"OPENAI_REASONING_EFFORT debe ser vacío, low, medium o high, no {self.openai_reasoning_effort!r}")
        if self.embeddings_provider not in EMBEDDINGS:
            raise ValueError(f"EMBEDDINGS_PROVIDER debe ser uno de {EMBEDDINGS}, no {self.embeddings_provider!r}")
        if self.embeddings_provider == "openai" and not self.openai_api_key:
            raise ValueError("EMBEDDINGS_PROVIDER=openai exige OPENAI_API_KEY en .env")
        if self.tipo_app not in TIPOS_APP:
            raise ValueError(f"TIPO_APP debe ser uno de {TIPOS_APP}, no {self.tipo_app!r}")
        if self.modo_bd not in MODOS_BD:
            raise ValueError(f"MODO_BD debe ser uno de {MODOS_BD}, no {self.modo_bd!r}")
        return self
