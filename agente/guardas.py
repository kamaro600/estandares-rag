"""El LLM propone, el código dispone: cada parche se acepta o se rechaza con un motivo legible."""
from __future__ import annotations

import re
from collections import Counter

from agente import config
from agente.contexto import Contexto
from agente.detectores import Archivo, Hallazgo, analizar, es_comentario
from agente.parches import Parche, aplicar

SUPRESION = re.compile(r"#pragma\s+warning\s+disable|SuppressMessage|eslint-disable|@ts-ignore|@ts-nocheck|NOSONAR", re.I)


CATEGORIAS = ("no_existe", "regla", "rango", "tamano", "vacio", "supresion", "comentado",
              "identico", "sigue_presente", "introduce_nuevos")


def validar_parche(archivo: Archivo, parche: Parche, hallazgos: list[Hallazgo],
                   ctx: Contexto) -> tuple[str, str] | None:
    """None si el parche es aceptable; si no, (categoría, motivo). El especialista lee el motivo y corrige;
    la categoría (lista cerrada) va a las métricas."""
    h = next((x for x in hallazgos if x.id == parche.hallazgo_id), None)
    if h is None:
        return "no_existe", f"No existe el hallazgo {parche.hallazgo_id} en {archivo.nombre}."
    if parche.regla_id != h.regla_id:
        return "regla", f"El hallazgo {h.id} es de la regla {h.regla_id}, no de {parche.regla_id}."
    total = len(archivo.lineas)
    if not (1 <= parche.linea_inicio <= parche.linea_fin <= total):
        return "rango", f"Rango {parche.linea_inicio}-{parche.linea_fin} fuera del archivo (1-{total})."
    if not (parche.linea_inicio <= h.linea <= parche.linea_fin):
        return "rango", f"El rango {parche.linea_inicio}-{parche.linea_fin} no incluye la línea {h.linea} del hallazgo."
    nuevas = parche.reemplazo.split("\n")
    if parche.linea_fin - parche.linea_inicio + 1 > config.MAX_LINEAS_PARCHE or len(nuevas) > config.MAX_LINEAS_PARCHE:
        return "tamano", f"El parche supera {config.MAX_LINEAS_PARCHE} líneas: corrige solo lo necesario."
    if not parche.reemplazo.strip():
        return "vacio", "Borrar el código no es corregirlo: propone el reemplazo."
    if SUPRESION.search(parche.reemplazo):
        return "supresion", "Suprimir la advertencia no corrige el incumplimiento (WEB-NET-006 exige justificar supresiones)."
    if all(not l.strip() or es_comentario(archivo.lenguaje, l) for l in nuevas):
        return "comentado", "Comentar el código no lo corrige: el reemplazo no tiene código."
    originales = archivo.lineas[parche.linea_inicio - 1:parche.linea_fin]
    if [l.rstrip() for l in nuevas] == [l.rstrip() for l in originales]:
        return "identico", "El reemplazo es idéntico al original."

    # Re-análisis: el hallazgo debe desaparecer y no deben aparecer incumplimientos nuevos.
    lineas_nuevas, _ = aplicar(archivo.lineas, [parche])
    nuevo = Archivo(archivo.nombre, "\n".join(lineas_nuevas), archivo.lenguaje)
    despues = analizar(nuevo, ctx)
    fin_nuevo = parche.linea_inicio + len(nuevas) - 1
    sigue = [x for x in despues if x.detector == h.detector and parche.linea_inicio <= x.linea <= fin_nuevo]
    if sigue:
        return "sigue_presente", f"El incumplimiento sigue presente en la línea {sigue[0].linea}: {sigue[0].mensaje}"
    clave = lambda x: (x.detector, x.regla_id)  # noqa: E731
    antes_c = Counter(clave(x) for x in hallazgos)
    antes_c[clave(h)] -= 1
    despues_c = Counter(clave(x) for x in despues)
    nuevos = [k for k, n in despues_c.items() if n > antes_c.get(k, 0)]
    if nuevos:
        return "introduce_nuevos", "El parche introduce incumplimientos nuevos: " + ", ".join(f"{r} ({d})" for d, r in nuevos)
    return None
