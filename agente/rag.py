"""Búsqueda en los estándares: exacta por identificador y por similitud con la consulta."""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from agente import catalogo, config, embeddings

RE_ID = re.compile(r"\b[A-Z]{3}-[A-Z0-9]{2,4}-[A-Z0-9]{2,10}\b")


@dataclass
class Resultado:
    regla: catalogo.Regla
    score: float
    via: str  # "id" (exacta) o "similitud"


@lru_cache(maxsize=1)
def _indice() -> tuple[list[str], np.ndarray, str]:
    if not config.INDICE_PATH.exists():
        raise FileNotFoundError("Falta data/indice.npz: ejecuta  python -m agente.ingesta")
    datos = np.load(config.INDICE_PATH)
    return [str(i) for i in datos["ids"]], datos["vectores"], str(datos["descriptor"])


def verificar_indice() -> None:
    """El índice y las consultas deben usar los mismos embeddings. La API lo comprueba al arrancar."""
    descriptor = _indice()[2]
    if descriptor != embeddings.descriptor():
        raise RuntimeError(f"El índice se construyó con {descriptor} y la consulta usaría {embeddings.descriptor()}: "
                           "vuelve a ejecutar  python -m agente.ingesta")


def buscar(consulta: str, k: int = config.RAG_TOP_K, aplica_a: str | None = None,
           min_score: float | None = None) -> list[Resultado]:
    """Híbrida: los identificadores citados se traen por id; el resto, por similitud."""
    if min_score is None:
        min_score = config.Settings().rag_min_score   # lee RAG_MIN_SCORE del entorno en cada llamada
    reglas = catalogo.cargar()
    exactos = [Resultado(reglas[i], 1.0, "id") for i in dict.fromkeys(RE_ID.findall(consulta)) if i in reglas]
    verificar_indice()
    ids, matriz, _ = _indice()
    scores = matriz @ embeddings.vectorizar([consulta])[0]
    vistos = {r.regla.id for r in exactos}
    similares = []
    for pos in np.argsort(-scores):
        if len(exactos) + len(similares) >= k or scores[pos] < min_score:
            break
        regla = reglas[ids[pos]]
        if regla.id in vistos or (aplica_a and aplica_a not in regla.aplica_a):
            continue
        similares.append(Resultado(regla, round(float(scores[pos]), 3), "similitud"))
    return (exactos + similares)[:k]
