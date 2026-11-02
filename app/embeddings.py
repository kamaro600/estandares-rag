"""Convertir texto en vectores. Dos implementaciones con la MISMA interfaz (C2).

- OpenAIEmbedder: text-embedding-3-small (1536 dimensiones). Por qué este modelo:
    * multilingüe: los estándares están en español y mezclan términos en inglés (async, token, CORS, SELECT *);
    * relación calidad/costo: el corpus completo (unos 200 fragmentos) se indexa por centavos;
    * misma familia que el LLM: una sola clave y un solo acuerdo de tratamiento de datos con el proveedor.
  Alternativa sin enviar datos fuera: un modelo local de sentence-transformers (como el lab 01); basta con otra
  clase que cumpla la interfaz `Embedder` y re-indexar.
- HashEmbedder: sin red y sin costo. "Hashing" de palabras y trigramas: parecido LÉXICO, no semántico. Existe para
  que pytest y la demo corran sin clave.

Ambos devuelven vectores normalizados (norma 1): así el producto punto ES la similitud coseno.
"""
from __future__ import annotations

import time
import unicodedata
import zlib
from typing import Protocol

import numpy as np

from app import metricas
from app.privacidad import enmascarar

DIMENSIONES = {"text-embedding-3-small": 1536, "text-embedding-3-large": 3072, "text-embedding-ada-002": 1536}


class EmbeddingError(RuntimeError):
    pass


class Embedder(Protocol):
    nombre: str      # se guarda en el índice: si cambias de embedder, el índice viejo deja de servir
    dim: int

    def embed(self, textos: list[str]) -> np.ndarray: ...


def normalizar_filas(m: np.ndarray) -> np.ndarray:
    normas = np.linalg.norm(m, axis=1, keepdims=True)
    return (m / np.where(normas == 0, 1, normas)).astype(np.float32)


def sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")


# Palabras vacías: en un embedder léxico, "de", "la", "que" hacen parecidos a textos que no tienen nada en común
VACIAS = set("""a al algo como con cual cuales cuando de del debo debe deben donde el ella en entre es esta este esto
estos hay la las le les lo los mas me mi mis muy no o para pero por puedo que se si sin sobre su sus tambien te tu un
una uno unos y ya the of to and in is for""".split())


class HashEmbedder:
    def __init__(self, dim: int = 1024):
        self.dim = dim
        self.nombre = f"hash-{dim}"

    def _rasgos(self, texto: str) -> list[str]:
        palabras = [p for p in "".join(c if c.isalnum() else " " for c in sin_tildes(texto)).split() if p not in VACIAS]
        rasgos = [f"w:{p}" for p in palabras]
        for p in palabras:
            p = f"<{p}>"
            rasgos += [f"g:{p[i:i + 3]}" for i in range(len(p) - 2)]
        return rasgos

    def embed(self, textos: list[str]) -> np.ndarray:
        m = np.zeros((len(textos), self.dim), dtype=np.float32)
        for fila, texto in enumerate(textos):
            for r in self._rasgos(texto):
                h = zlib.crc32(r.encode("utf-8"))           # crc32 y no hash(): hash() cambia en cada ejecución
                m[fila, h % self.dim] += 1.0 if (h >> 31) & 1 else -1.0
        return normalizar_filas(m)


class OpenAIEmbedder:
    LOTE = 96

    def __init__(self, settings, client=None):
        from openai import OpenAI

        self.modelo = settings.openai_embedding_model
        self.nombre = f"openai-{self.modelo}"
        self.dim = DIMENSIONES.get(self.modelo, 0)
        self.precio = settings.precio_openai_embeddings
        self.client = client or OpenAI(api_key=settings.openai_api_key, timeout=settings.openai_timeout_s, max_retries=2)

    def embed(self, textos: list[str]) -> np.ndarray:
        import openai

        filas = []
        for i in range(0, len(textos), self.LOTE):
            t0 = time.perf_counter()
            try:
                r = self.client.embeddings.create(model=self.modelo, input=[enmascarar(t) for t in textos[i:i + self.LOTE]])
            except openai.APIError as e:
                metricas.API_ERRORES.labels("openai_emb", type(e).__name__).inc()
                raise EmbeddingError(f"OpenAI embeddings falló: {type(e).__name__}: {e}") from e
            finally:
                metricas.API_LATENCIA.labels("openai_emb").observe(time.perf_counter() - t0)
            tokens = r.usage.prompt_tokens if r.usage else 0
            metricas.TOKENS.labels("openai_emb", "input").inc(tokens)
            metricas.COSTO.labels("openai_emb").inc(tokens * self.precio / 1e6)
            filas += [d.embedding for d in sorted(r.data, key=lambda d: d.index)]
        m = normalizar_filas(np.array(filas, dtype=np.float32))
        if self.dim and m.shape[1] != self.dim:
            raise EmbeddingError(f"{self.modelo} devolvió {m.shape[1]} dimensiones; se esperaban {self.dim}")
        self.dim = m.shape[1]
        return m


def crear_embedder(settings) -> Embedder:
    return OpenAIEmbedder(settings) if settings.embeddings_provider == "openai" else HashEmbedder()
