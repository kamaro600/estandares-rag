"""Búsqueda en los estándares: exacta por identificador y por similitud con la consulta."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from agente import catalogo, config, embeddings, metricas

RE_ID = re.compile(r"\b[A-Z]{3}-[A-Z0-9]{2,4}-[A-Z0-9]{2,10}\b")
# Las secciones generales (objetivo, alcance, "relación con otros estándares") se parecen a muchas preguntas por su
# vocabulario genérico: pesan un poco menos para no desplazar a la regla que responde.
PESO_SECCION = 0.85
# Dos estándares con reglas del mismo tema (WEB-BD-002 y DSK-BD-001) pueden contradecirse, y lo que decide cuál
# aplica está en otra parte: la introducción del capítulo y "Relación con otros estándares". La similitud con la
# pregunta no las trae ("¿cómo nombro las tablas?" no se parece a "prevalece"), así que se agregan por regla.
MAX_COMPLEMENTOS = 4


@dataclass
class Resultado:
    regla: catalogo.Regla
    score: float
    via: str  # "id" (exacta) o "similitud"


@lru_cache(maxsize=1)
def _indice() -> tuple[list[str], np.ndarray, str, dict]:
    if not config.INDICE_PATH.exists():
        raise FileNotFoundError("Falta data/indice.npz: ejecuta  python -m agente.ingesta")
    with np.load(config.INDICE_PATH) as datos:
        huellas = json.loads(str(datos["huellas"])) if "huellas" in datos.files else {}
        return [str(i) for i in datos["ids"]], datos["vectores"], str(datos["descriptor"]), huellas


def verificar_indice() -> None:
    """El índice debe corresponder a los embeddings y a los PDF actuales. La API lo comprueba al arrancar."""
    from agente.ingesta import huellas  # noqa: PLC0415  (ingesta importa este módulo indirectamente)
    ids, matriz, descriptor, guardadas = _indice()
    if descriptor != embeddings.descriptor():
        raise RuntimeError(f"El índice se construyó con {descriptor} y la consulta usaría {embeddings.descriptor()}: "
                           "vuelve a ejecutar  python -m agente.ingesta")
    esperada = embeddings.dimension()
    if matriz.shape != (len(ids), matriz.shape[1]) or (esperada and matriz.shape[1] != esperada):
        raise RuntimeError(f"Índice con forma {matriz.shape}; los embeddings actuales tienen {esperada} dimensiones: "
                           "vuelve a ejecutar  python -m agente.ingesta")
    if guardadas != huellas():
        raise RuntimeError("Cambiaron los PDF de data/estandares desde la última ingesta: "
                           "vuelve a ejecutar  python -m agente.ingesta")


def buscar(consulta: str, k: int = config.RAG_TOP_K, aplica_a: str | None = None,
           min_score: float | None = None, incluir_secciones: bool = False) -> list[Resultado]:
    """Híbrida: los identificadores citados se traen por id; el resto, por similitud.
    incluir_secciones=True (el chat) busca también en objetivo, alcance y relación entre estándares."""
    if min_score is None:
        min_score = config.Settings().rag_min_score   # lee RAG_MIN_SCORE del entorno en cada llamada
    reglas = catalogo.cargar()
    generales = catalogo.secciones() if incluir_secciones else {}
    exactos = [Resultado(reglas[i], 1.0, "id") for i in dict.fromkeys(RE_ID.findall(consulta)) if i in reglas]
    ids, matriz, descriptor, _ = _indice()
    if descriptor != embeddings.descriptor():   # barato: en cada consulta (las huellas de los PDF, solo al arrancar)
        raise RuntimeError(f"El índice se construyó con {descriptor} y la consulta usaría {embeddings.descriptor()}: "
                           "vuelve a ejecutar  python -m agente.ingesta")
    scores = matriz @ embeddings.vectorizar([consulta])[0]
    vistos = {r.regla.id for r in exactos}
    candidatos = []
    for pos, score in enumerate(scores):
        regla = reglas.get(ids[pos]) or generales.get(ids[pos])
        if regla is None:
            continue
        candidatos.append((float(score) * (PESO_SECCION if regla.id in generales else 1.0), regla))
    similares = []
    for score, regla in sorted(candidatos, key=lambda x: -x[0]):
        if len(exactos) + len(similares) >= k or score < min_score:
            break
        if regla.id in vistos or (aplica_a and aplica_a not in regla.aplica_a):
            continue
        similares.append(Resultado(regla, round(score, 3), "similitud"))
    if not exactos and not similares:
        metricas.RAG_SIN_CONTEXTO.inc()
    resultados = (exactos + similares)[:k]
    return resultados + complementos(resultados, generales) if generales else resultados


def complementos(resultados: list[Resultado], generales: dict) -> list[Resultado]:
    """Si hay reglas de dos o más estándares sobre el mismo tema (el segundo segmento del id: BD, NET, ARQ…), agrega
    la introducción de su capítulo y su "Relación con otros estándares", que dicen cuál prevalece y cuándo."""
    por_tema: dict[str, list[Resultado]] = {}
    for r in resultados:
        if r.regla.id not in generales:
            por_tema.setdefault(r.regla.id.split("-")[1], []).append(r)
    presentes, extra = {r.regla.id for r in resultados}, []
    for grupo in por_tema.values():
        if len({r.regla.documento for r in grupo}) < 2:
            continue
        for r in grupo:
            doc = r.regla.documento
            relacion = [g.id for g in generales.values() if g.documento == doc and g.titulo.startswith("Relación")]
            capitulo = f"{doc}-S{int(r.regla.seccion.split('.')[0]):02d}"
            for sid in relacion + [capitulo]:
                if sid in generales and sid not in presentes and len(extra) < MAX_COMPLEMENTOS:
                    presentes.add(sid)
                    extra.append(Resultado(generales[sid], r.score, "relacion"))
    if extra:
        metricas.RAG_COMPLEMENTOS.inc(len(extra))
    return extra
