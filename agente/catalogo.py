"""Los estándares como datos: del PDF a un catálogo de reglas con cita exacta."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel
from pypdf import PdfReader

from agente import config

# "7.2 WEB-BD-002 · Nombres de tablas"  →  sección, id, título
RE_REGLA = re.compile(r"^\s*(\d+\.\d+)\s+([A-Z]{3}-[A-Z0-9]{2,4}-[A-Z0-9]{2,10})\s+·\s+(.+?)\s*$")
RE_CAPITULO = re.compile(r"^\s*\d{1,2}\.\s+[A-ZÁÉÍÓÚ].{3,85}$")
RE_CONTINUA_REF = re.compile(r"^(A\d{2}:\d{4}|API\d{1,2}:\d{4}|MASVS-[A-Z]+|ASVS V|OWASP|EST-[A-Z]{3}-\d{3})[A-Za-z0-9 .:;\-]*$")
RE_NIVEL = re.compile(r"Nivel:\s*(Obligatorio|Recomendado|Prohibido)\s*\|\s*Aplica a:\s*([^|]+?)\s*(?:\|\s*Referencias:\s*(.+))?$")
RE_PIE = re.compile(r"^(Empresa Ejemplo S\.A\. · Uso interno|EST-[A-Z]{3}-\d{3} · .+Versión)")
RE_CABECERA = re.compile(r"(EST-[A-Z]{3}-\d{3})\s+(\d+\.\d+)\s+(\d{4}-\d{2}-\d{2})")
# Severidad que usa el agente: un "Prohibido" es una regla obligatoria en sentido negativo.
SEVERIDAD = {"Obligatorio": "bloqueante", "Prohibido": "bloqueante", "Recomendado": "advertencia"}


class Regla(BaseModel):
    id: str
    titulo: str
    nivel: str
    aplica_a: list[str]
    referencias: list[str]
    documento: str
    version: str
    fecha: str
    seccion: str
    pagina: int
    texto: str

    @property
    def severidad(self) -> str:
        return SEVERIDAD.get(self.nivel, "advertencia")

    def cita(self) -> str:
        return f"{self.documento} v{self.version} §{self.seccion} {self.id}, pág. {self.pagina}"


def _lineas_por_pagina(pdf: Path) -> tuple[dict, list[tuple[int, str]]]:
    lector = PdfReader(str(pdf))
    portada = " ".join(lector.pages[0].extract_text().split())
    m = RE_CABECERA.search(portada)
    if not m:
        raise ValueError(f"{pdf.name}: no encuentro código, versión y fecha en la portada")
    meta = {"documento": m.group(1), "version": m.group(2), "fecha": m.group(3)}
    lineas = []
    for n, pagina in enumerate(lector.pages[2:], start=3):  # 1: portada, 2: índice
        for linea in pagina.extract_text().splitlines():
            if linea.strip() and not RE_PIE.match(linea.strip()):
                lineas.append((n, linea.rstrip()))
    return meta, lineas


def _cabecera(cuerpo: list[str]) -> str:
    """La línea "Nivel: … | Referencias: …" a veces se parte en dos o tres líneas."""
    cab = cuerpo.pop(0).strip() if cuerpo else ""
    while cuerpo and RE_CONTINUA_REF.match(cuerpo[0].strip()):
        cab += " " + cuerpo.pop(0).strip()
    return cab


def extraer_reglas(pdf: Path) -> list[Regla]:
    """Un fragmento = una regla: corta por la estructura del documento, no por caracteres."""
    meta, lineas = _lineas_por_pagina(pdf)
    reglas: list[Regla] = []
    actual: dict | None = None

    def cerrar() -> None:
        if actual is None:
            return
        cuerpo = actual.pop("cuerpo")
        while cuerpo and not cuerpo[0].strip().startswith("Nivel:"):  # título en dos líneas
            actual["titulo"] += " " + cuerpo.pop(0).strip()
        m = RE_NIVEL.search(_cabecera(cuerpo))
        if not m:
            raise ValueError(f"{actual['id']}: no encuentro la línea 'Nivel: … | Aplica a: …'")
        reglas.append(Regla(
            nivel=m.group(1),
            aplica_a=[a.strip().lower().replace("móvil", "movil") for a in m.group(2).split(",")],
            referencias=[r.strip() for r in (m.group(3) or "").split(";") if r.strip()],
            texto="\n".join(l.strip() for l in cuerpo),
            **meta, **actual,
        ))

    for pagina, linea in lineas:
        m = RE_REGLA.match(linea)
        if m:
            cerrar()
            actual = {"seccion": m.group(1), "id": m.group(2), "titulo": m.group(3),
                      "pagina": pagina, "cuerpo": []}
        elif RE_CAPITULO.match(linea):   # "8. Implementación en ASP.NET Core": termina la regla
            cerrar()
            actual = None
        elif actual is not None:
            actual["cuerpo"].append(linea)
    cerrar()
    return reglas


def construir_catalogo(carpeta: Path = config.ESTANDARES_DIR) -> list[Regla]:
    pdfs = sorted(carpeta.glob("EST-*.pdf"))
    if not pdfs:
        raise FileNotFoundError(f"No hay PDFs EST-*.pdf en {carpeta}")
    reglas = [r for pdf in pdfs for r in extraer_reglas(pdf)]
    ids = [r.id for r in reglas]
    repetidos = sorted({i for i in ids if ids.count(i) > 1})
    if repetidos:
        raise ValueError(f"Identificadores repetidos: {repetidos}")
    return reglas


def guardar(reglas: list[Regla], destino: Path = config.CATALOGO_PATH) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    datos = [r.model_dump() for r in reglas]
    destino.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")


@lru_cache(maxsize=1)
def cargar(ruta: str = str(config.CATALOGO_PATH)) -> dict[str, Regla]:
    p = Path(ruta)
    if not p.exists():
        raise FileNotFoundError(f"Falta {p.name}: ejecuta  python -m agente.ingesta")
    return {d["id"]: Regla(**d) for d in json.loads(p.read_text(encoding="utf-8"))}
