"""Un parche = reemplazar un rango de líneas. Se valida, se aprueba y recién entonces se aplica."""
from __future__ import annotations

import difflib

from pydantic import BaseModel


class Parche(BaseModel):
    id: str = ""
    archivo: str
    hallazgo_id: str
    regla_id: str
    linea_inicio: int
    linea_fin: int
    reemplazo: str
    justificacion: str
    origen: str                 # determinista | llm
    estado: str = "propuesto"   # propuesto | rechazado | aprobado | denegado | aplicado | conflicto
    motivo: str = ""


def aplicar(lineas: list[str], parches: list[Parche]) -> tuple[list[str], list[Parche]]:
    """Aplica de abajo hacia arriba para que los números de línea no se corran.

    Devuelve las líneas nuevas y los parches que chocaron con otro (no se aplican).
    """
    resultado = list(lineas)
    ocupadas: list[tuple[int, int]] = []
    conflictos = []
    for p in sorted(parches, key=lambda p: (p.linea_inicio, p.id)):
        if any(not (p.linea_fin < a or p.linea_inicio > b) for a, b in ocupadas):
            conflictos.append(p)
        else:
            ocupadas.append((p.linea_inicio, p.linea_fin))
    for p in sorted((p for p in parches if p not in conflictos), key=lambda p: -p.linea_inicio):
        resultado[p.linea_inicio - 1:p.linea_fin] = p.reemplazo.split("\n")
    return resultado, conflictos


def diff(nombre: str, antes: list[str], despues: list[str]) -> str:
    return "".join(difflib.unified_diff(
        [l + "\n" for l in antes], [l + "\n" for l in despues],
        fromfile=f"a/{nombre}", tofile=f"b/{nombre}", n=1))
