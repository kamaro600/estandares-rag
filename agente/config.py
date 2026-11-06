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
# Las rutas generadas se pueden redirigir por variable de entorno (las pruebas usan una carpeta temporal y
# así nunca pisan el índice real, que puede ser de OpenAI).
CATALOGO_PATH = Path(os.getenv("CATALOGO_PATH") or DATA_DIR / "catalogo.json")
SECCIONES_PATH = Path(os.getenv("SECCIONES_PATH") or DATA_DIR / "secciones.json")
INDICE_PATH = Path(os.getenv("INDICE_PATH") or DATA_DIR / "indice.npz")
SALIDA_DIR = Path(os.getenv("SALIDA_DIR") or BASE_DIR / "salida")
DB_PATH = Path(os.getenv("DB_PATH") or SALIDA_DIR / "chat.db")

# ---- Límites: cada uno protege contra un modo de fallo concreto ----
MAX_REACT_ITERS = 8            # un especialista que da vueltas sin terminar
MAX_REPEATED_CALLS = 2         # la misma herramienta con los mismos argumentos
MAX_ARCHIVOS = 50              # una revisión que intenta leer todo el disco
MAX_BYTES_ARCHIVO = 200_000    # un archivo gigante que dispara el costo
MAX_LINEAS_PARCHE = 30         # un "parche" que reescribe el archivo entero
MAX_PARCHES_POR_ARCHIVO = 20   # un especialista que propone sin fin
TOOL_RESULT_MAX_CHARS = 3000   # un resultado que diluye el contexto
RAG_TOP_K = 4
# Umbral de relevancia por embedder: cada modelo tiene su propia escala de similitud. Calibrados con
# python -m eval.eval_rag (centro del rango con mejor exactitud) con eval/rag_oro.json: openai, meseta 0.40–0.50.
RAG_MIN_SCORE_POR_EMBEDDER = {"hash": 0.08, "openai": 0.45}
# Router (python -m eval.eval_router): con openai, exactitud 1.0 entre 0.30 y 0.55; 0.35 deja el 76 % al semántico.
ROUTER_MIN_POR_EMBEDDER = {"hash": 0.20, "openai": 0.35}
MAX_CARACTERES_MENSAJE = 20_000   # un mensaje del chat (puede traer código pegado)

TIPOS_APP = ("web", "api", "escritorio", "movil")
MODOS_BD = ("nueva", "legada")
PROVEEDORES = ("mock", "anthropic", "openai")
EMBEDDINGS = ("hash", "openai")
ESFUERZOS = ("", "low", "medium", "high")
ESFUERZOS_CLAUDE = ("", "low", "medium", "high", "xhigh", "max")


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
    valor = (os.getenv(nombre, "").strip() or str(defecto)).replace(",", ".")   # vacío = valor por defecto
    try:
        return float(valor)
    except ValueError as exc:
        raise ValueError(f"{nombre}={valor!r} no es un número") from exc


def _txt(nombre: str, defecto: str = "", minusculas: bool = False) -> str:
    valor = os.getenv(nombre, defecto).strip()
    return valor.lower() if minusculas else valor


def _embedder() -> str:
    return "openai" if _txt("EMBEDDINGS_PROVIDER", "hash", True) == "openai" else "hash"


@dataclass
class Settings:
    """Configuración leída del entorno (.env) al instanciarse: proveedor, modelo, umbrales, límites y precios.

    Los umbrales vacíos toman el valor calibrado para el embedder elegido. validar() detiene el arranque
    con un mensaje claro si falta una clave o un valor está fuera de rango.
    """
    llm_provider: str = field(default_factory=lambda: _txt("LLM_PROVIDER", "mock", True))
    llm_model: str = field(default_factory=lambda: _txt("LLM_MODEL", "claude-opus-5-5"))
    anthropic_api_key: str = field(default_factory=lambda: _txt("ANTHROPIC_API_KEY"))
    # Claude: profundidad del razonamiento (en Opus 5.5 siempre está activo) y respaldo ante rechazos de seguridad
    anthropic_effort: str = field(default_factory=lambda: _txt("ANTHROPIC_EFFORT", "medium", True))
    anthropic_fallback: str = field(default_factory=lambda: _txt("ANTHROPIC_FALLBACK", "default"))
    llm_max_tokens: int = field(default_factory=lambda: int(_float("LLM_MAX_TOKENS", 16000)))
    llm_timeout_s: float = field(default_factory=lambda: _float("LLM_TIMEOUT_S", 120))
    openai_api_key: str = field(default_factory=lambda: _txt("OPENAI_API_KEY"))
    openai_model: str = field(default_factory=lambda: _txt("OPENAI_MODEL"))
    openai_reasoning_effort: str = field(default_factory=lambda: _txt("OPENAI_REASONING_EFFORT", "", True))
    embeddings_provider: str = field(default_factory=lambda: _txt("EMBEDDINGS_PROVIDER", "hash", True))
    openai_embedding_model: str = field(default_factory=lambda: _txt("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"))
    tipo_app: str = field(default_factory=lambda: _txt("TIPO_APP", "web", True))
    modo_bd: str = field(default_factory=lambda: _txt("MODO_BD", "nueva", True))
    rag_min_score: float = field(default_factory=lambda: _float("RAG_MIN_SCORE", RAG_MIN_SCORE_POR_EMBEDDER[_embedder()]))
    # Chat
    router_min_score: float = field(default_factory=lambda: _float("ROUTER_MIN_SCORE", ROUTER_MIN_POR_EMBEDDER[_embedder()]))
    historial_max: int = field(default_factory=lambda: int(_float("HISTORIAL_MAX", 6)))
    limite_por_minuto: int = field(default_factory=lambda: int(_float("LIMITE_POR_MINUTO", 30)))
    # Costo estimado (USD por millón de tokens): solo para la métrica, verifica los precios vigentes
    precio_llm_entrada: float = field(default_factory=lambda: _float("PRECIO_LLM_ENTRADA", 0))
    precio_llm_salida: float = field(default_factory=lambda: _float("PRECIO_LLM_SALIDA", 0))
    precio_embeddings: float = field(default_factory=lambda: _float("PRECIO_EMBEDDINGS", 0))

    def validar(self) -> "Settings":
        """Comprueba proveedor, claves, esfuerzo y rangos; devuelve self para encadenar Settings().validar()."""
        if self.llm_provider not in PROVEEDORES:
            raise ValueError(f"LLM_PROVIDER debe ser uno de {PROVEEDORES}, no {self.llm_provider!r}")
        if self.llm_provider == "anthropic" and not self.anthropic_api_key:
            raise ValueError("LLM_PROVIDER=anthropic exige ANTHROPIC_API_KEY en .env")
        if self.anthropic_effort not in ESFUERZOS_CLAUDE:
            raise ValueError(f"ANTHROPIC_EFFORT debe ser vacío, low, medium, high, xhigh o max, no {self.anthropic_effort!r}")
        if not 0 <= self.rag_min_score < 1 or not 0 <= self.router_min_score < 1:
            raise ValueError("RAG_MIN_SCORE y ROUTER_MIN_SCORE deben estar entre 0 y 1")
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
