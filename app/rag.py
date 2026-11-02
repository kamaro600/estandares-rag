"""Búsqueda en el índice de estándares (la "R" de RAG)  (C2 y C3).

Tres formas de recuperar:
  buscar(consulta, categorias)  → por SIMILITUD, opcionalmente filtrada por categoría (web, api, seguridad…).
  por_id("WEB-BD-005")          → EXACTA: el agente validador trae la regla que incumple el código, sin depender de
                                  que la similitud la encuentre. También se usa si el usuario menciona un id.
  relacionadas(fragmentos)      → reglas citadas dentro de los fragmentos ("ver SEG-INY-001").

Compuerta de relevancia: los fragmentos con similitud bajo `min_score` se descartan. Si no queda ninguno, el chat
responde "no está en los estándares" SIN llamar al LLM (no hay evidencia: cualquier respuesta sería inventada).

El índice cabe en memoria (unos 200 fragmentos): NumPy y un producto punto bastan. Si el corpus creciera a miles de
documentos, se cambia por pgvector (lab 04) sin tocar esta interfaz.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

from app import metricas
from app.embeddings import Embedder
from app.modelos import Fragmento

PESO_SECCION = 0.85
RX_ID_REGLA = re.compile(r"\b[A-Z]{3}-[A-Z0-9]{2,10}-[A-Z0-9]{2,10}\b")


class IndiceError(RuntimeError):
    pass


def similitudes(matriz: np.ndarray, q: np.ndarray) -> np.ndarray:
    """Coseno de q contra cada fila (todo está normalizado: coseno = producto punto). Multiplicar y sumar en lugar de
    `matriz @ q` evita advertencias falsas de BLAS con numpy 2.x en algunos equipos (lección del lab 06)."""
    return (matriz * q).sum(axis=1)


class RAG:
    def __init__(self, indice_path: Path, embedder: Embedder, min_score: float, top_k: int):
        if not indice_path.exists():
            raise IndiceError(f"No existe el índice {indice_path}. Ejecuta: python -m app.ingesta")
        with np.load(indice_path) as z:
            self.vectores = z["vectores"]
            nombre, dim = str(z["embedder"]), int(z["dim"])
            self.fragmentos = [Fragmento(**f) for f in json.loads(str(z["fragmentos"]))]
        if nombre != embedder.nombre:
            raise IndiceError(f"El índice se creó con '{nombre}' y ahora usas '{embedder.nombre}'. Los vectores de "
                              f"modelos distintos no son comparables: ejecuta python -m app.ingesta")
        if self.vectores.shape != (len(self.fragmentos), dim):
            raise IndiceError(f"Índice corrupto: {self.vectores.shape} vectores para {len(self.fragmentos)} fragmentos")
        if embedder.dim and embedder.dim != dim:                            # verificación de dimensión al iniciar
            raise IndiceError(f"El embedder produce {embedder.dim} dimensiones y el índice tiene {dim}")
        self.embedder, self.min_score, self.top_k, self.dim = embedder, min_score, top_k, dim
        self._por_id = {f.id: i for i, f in enumerate(self.fragmentos)}
        self._categorias = np.array([f.categoria for f in self.fragmentos])
        # La REGLA es la unidad normativa. Las secciones generales (objetivo, definiciones…) se repiten casi iguales en
        # cada documento y, por su vocabulario genérico ("obligatorio", "regla"), aparecen en muchas búsquedas: pesan
        # un poco menos para que no desplacen a la regla que responde. Medido con eval/evaluar.py.
        self._peso = np.array([1.0 if f.tipo == "regla" else PESO_SECCION for f in self.fragmentos], dtype=np.float32)
        for c in set(self._categorias):
            metricas.INDICE_FRAGMENTOS.labels(c).set(int((self._categorias == c).sum()))

    def _copia(self, i: int, score: float) -> Fragmento:
        return Fragmento(**{**vars(self.fragmentos[i]), "score": round(float(score), 4)})

    def buscar(self, consulta: str, k: int | None = None, categorias: list[str] | None = None,
               min_score: float | None = None) -> list[Fragmento]:
        q = self.embedder.embed([consulta])[0]
        if q.shape[0] != self.dim:
            raise IndiceError(f"Dimensión de la consulta ({q.shape[0]}) distinta de la del índice ({self.dim})")
        scores = similitudes(self.vectores, q) * self._peso
        if categorias:
            scores = np.where(np.isin(self._categorias, categorias), scores, -1.0)
        orden = np.argsort(-scores)[: k or self.top_k]
        umbral = self.min_score if min_score is None else min_score
        if len(orden):
            metricas.RAG_SCORE.observe(float(max(scores[orden[0]], 0)))
        res = [self._copia(i, scores[i]) for i in orden if scores[i] >= umbral]
        # un id de regla escrito en la pregunta ("¿qué dice WEB-BD-005?") se trae exacto, primero
        exactos = [self.por_id(i) for i in dict.fromkeys(RX_ID_REGLA.findall(consulta))]
        exactos = [f for f in exactos if f and (not categorias or f.categoria in categorias)]
        res = exactos + [f for f in res if f.id not in {e.id for e in exactos}]
        if not res:
            metricas.RAG_SIN_CONTEXTO.inc()
        for f in res:
            metricas.RAG_CATEGORIA.labels(f.categoria).inc()
        return res

    def por_id(self, id_: str) -> Fragmento | None:
        i = self._por_id.get(id_)
        return None if i is None else self._copia(i, 1.0)

    def relacionadas(self, fragmentos: list[Fragmento], maximo: int = 3) -> list[Fragmento]:
        """Reglas que los fragmentos mencionan ("ver SEG-INY-001") y que no están ya en la lista."""
        ya = {f.id for f in fragmentos}
        ids = [i for f in fragmentos for i in RX_ID_REGLA.findall(f.texto + " " + f.referencias) if i not in ya]
        return [f for f in (self.por_id(i) for i in dict.fromkeys(ids)) if f][:maximo]
