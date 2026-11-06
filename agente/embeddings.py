"""Embeddings: léxicos locales (feature hashing, sin red ni costo) o semánticos de OpenAI.

El índice y las consultas DEBEN usar el mismo proveedor y modelo: vectores de modelos distintos no se comparan.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

import numpy as np

from agente import config, metricas

DIM = 2048
_PALABRA = re.compile(r"[a-z0-9_]+")
# Palabras que no aportan significado a la búsqueda.
_VACIAS = set("de la el los las un una y o a en con por para que se del al es no su sus lo como".split())


def normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in sin_tildes if not unicodedata.combining(c))


def raiz(palabra: str) -> str:
    """Raíz mínima: "contraseñas" y "contraseña" deben caer en la misma cubeta."""
    if len(palabra) > 5 and palabra.endswith("es"):
        palabra = palabra[:-2]
    elif len(palabra) > 4 and palabra.endswith("s"):
        palabra = palabra[:-1]
    return palabra[:8]


def tokens(texto: str) -> list[str]:
    palabras = [raiz(p) for p in _PALABRA.findall(normalizar(texto)) if p not in _VACIAS and len(p) > 1]
    bigramas = [f"{a}_{b}" for a, b in zip(palabras, palabras[1:])]
    return palabras + bigramas


def _cubeta(token: str) -> tuple[int, float]:
    h = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    n = int.from_bytes(h, "little")
    return n % DIM, (1.0 if (n >> 63) & 1 else -1.0)


def embed(texto: str) -> np.ndarray:
    v = np.zeros(DIM, dtype=np.float32)
    for t in tokens(texto):
        i, signo = _cubeta(t)
        v[i] += signo
    norma = float(np.linalg.norm(v))
    return v / norma if norma else v


def embed_lote(textos: list[str]) -> np.ndarray:
    return np.vstack([embed(t) for t in textos]) if textos else np.zeros((0, DIM), dtype=np.float32)


def descriptor() -> str:
    """Identifica el espacio de vectores: se guarda en el índice y se compara en cada consulta."""
    st = config.Settings()
    return f"openai:{st.openai_embedding_model}" if st.embeddings_provider == "openai" else f"hash:{DIM}"


# Por qué text-embedding-3-small: multilingüe (los estándares están en español y mezclan términos en inglés como
# async, CORS o SELECT *), barato (el corpus completo se indexa por centavos) y medido con eval/rag_oro.json.
DIMENSIONES = {"text-embedding-3-small": 1536, "text-embedding-3-large": 3072, "text-embedding-ada-002": 1536}


def dimension() -> int | None:
    """Dimensión que DEBE tener cada vector del proveedor configurado (None si el modelo no es conocido)."""
    st = config.Settings()
    return DIMENSIONES.get(st.openai_embedding_model) if st.embeddings_provider == "openai" else DIM


class EmbeddingError(RuntimeError):
    pass


def _cliente_openai():
    # solo se importa si EMBEDDINGS_PROVIDER=openai
    return config.importar_sdk("openai").OpenAI(api_key=config.Settings().openai_api_key, max_retries=2, timeout=60)


def vectorizar(textos: list[str]) -> np.ndarray:
    """Matriz de vectores normalizados con el proveedor configurado (lotes de 100 para OpenAI).
    Hacia OpenAI sale el texto enmascarado (secretos y datos personales), igual que hacia el LLM."""
    from agente.privacidad import enmascarar  # noqa: PLC0415  (privacidad importa metricas, que no importa esto)
    st = config.Settings()
    if st.embeddings_provider != "openai":
        return embed_lote(textos)
    openai = config.importar_sdk("openai")
    cliente, filas = _cliente_openai(), []
    for i in range(0, len(textos), 100):
        try:
            r = cliente.embeddings.create(model=st.openai_embedding_model,
                                          input=[enmascarar(t) for t in textos[i:i + 100]])
        except openai.APIError as e:
            raise EmbeddingError(f"OpenAI embeddings falló: {type(e).__name__}: {e}") from e
        filas += [d.embedding for d in sorted(r.data, key=lambda d: d.index)]
        tokens = getattr(getattr(r, "usage", None), "prompt_tokens", 0) or 0
        metricas.COSTO.inc(tokens * st.precio_embeddings / 1e6, proveedor="openai_embeddings")
    m = np.asarray(filas, dtype=np.float32)
    esperada = dimension()
    if esperada and m.shape[1] != esperada:
        raise EmbeddingError(f"{st.openai_embedding_model} devolvió {m.shape[1]} dimensiones; se esperaban {esperada}")
    return m / np.clip(np.linalg.norm(m, axis=1, keepdims=True), 1e-12, None)
