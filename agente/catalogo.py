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
    """Una regla (o una sección general, con id {doc}-Snn y nivel Informativo) con todo lo necesario para citarla."""
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


def _forma(linea: str) -> str:
    return re.sub(r"\d+", "#", linea.strip())


def _repetidas(paginas: list[str]) -> set[str]:
    """Encabezados y pies sin conocer su texto: líneas del BORDE de la página (3 primeras, 4 últimas) que se repiten
    en el 60 % de las páginas o más, con los números reemplazados por # ("Página 3 de 13" = "Página # de #").
    Solo en el borde: "Nivel: Obligatorio | Aplica a: API" también se repite, pero en medio del contenido."""
    if len(paginas) < 3:
        return set()
    conteo: dict[str, int] = {}
    for p in paginas:
        lineas = [l for l in p.splitlines() if l.strip()]
        for f in {_forma(l) for l in lineas[:3] + lineas[-4:]}:
            conteo[f] = conteo.get(f, 0) + 1
    return {f for f, n in conteo.items() if n / len(paginas) >= 0.6}


def _lineas_por_pagina(pdf: Path) -> tuple[dict, list[tuple[int, str]]]:
    lector = PdfReader(str(pdf))
    textos = [p.extract_text() or "" for p in lector.pages]
    if sum(len(t.strip()) for t in textos) < 50:
        raise ValueError(f"{pdf.name}: el PDF no tiene texto extraíble (¿escaneado? requiere OCR antes de indexarlo)")
    portada = " ".join(textos[0].split())
    m = RE_CABECERA.search(portada)
    if not m:
        raise ValueError(f"{pdf.name}: no encuentro código, versión y fecha en la portada")
    meta = {"documento": m.group(1), "version": m.group(2), "fecha": m.group(3)}
    repetidas = _repetidas(textos[1:])
    lineas = []
    for n, texto in enumerate(textos[1:], start=2):  # 1: portada. El índice (pág. 2) no abre reglas ni secciones.
        for linea in texto.splitlines():
            if linea.strip() and not RE_PIE.match(linea.strip()) and _forma(linea) not in repetidas:
                lineas.append((n, linea.rstrip()))
    return meta, lineas


RE_PUNTOS = re.compile(r"(\.\s*){3,}\d*\s*$|^[\s.]*\d*\s*$")   # puntos guía del índice: "Alcance . . . . 3"
TODOS_LOS_TIPOS = ["web", "api", "escritorio", "movil"]


def _cabecera(cuerpo: list[str]) -> str:
    """La línea "Nivel: … | Referencias: …" a veces se parte en dos o tres líneas."""
    cab = cuerpo.pop(0).strip() if cuerpo else ""
    while cuerpo and RE_CONTINUA_REF.match(cuerpo[0].strip()):
        cab += " " + cuerpo.pop(0).strip()
    return cab


def extraer(pdf: Path) -> tuple[list[Regla], list[Regla], list[str]]:
    """(reglas, secciones generales, descartados). Las secciones generales (objetivo, alcance, definiciones,
    "Relación con otros estándares") no son reglas, pero dicen qué estándar prevalece cuando dos chocan: el chat
    las necesita para responder. Un fragmento con un intento de prompt injection NO se indexa (inyección indirecta)."""
    from agente import inyeccion  # noqa: PLC0415
    meta, lineas = _lineas_por_pagina(pdf)
    reglas: list[Regla] = []
    secciones: list[Regla] = []
    descartados: list[str] = []
    actual: dict | None = None
    seccion: dict | None = None

    def cerrar_seccion() -> None:
        nonlocal seccion
        texto = "\n".join(l.strip() for l in seccion["cuerpo"]) if seccion else ""
        if len(texto) >= 40:   # un capítulo sin introducción (o la palabra suelta de un título partido) no es sección
            if inyeccion.detectar(texto).bloquear:
                descartados.append(f"{meta['documento']} §{seccion['seccion']}")
            else:
                secciones.append(Regla(id=f"{meta['documento']}-S{int(seccion['seccion']):02d}",
                                       titulo=seccion["titulo"], nivel="Informativo", aplica_a=TODOS_LOS_TIPOS,
                                       referencias=[], seccion=seccion["seccion"], pagina=seccion["pagina"],
                                       texto=texto, **meta))
        seccion = None

    def cerrar() -> None:
        if actual is None:
            return
        cuerpo = actual.pop("cuerpo")
        while cuerpo and not cuerpo[0].strip().startswith("Nivel:"):  # título en dos líneas
            actual["titulo"] += " " + cuerpo.pop(0).strip()
        m = RE_NIVEL.search(_cabecera(cuerpo))
        if not m:
            raise ValueError(f"{actual['id']}: no encuentro la línea 'Nivel: … | Aplica a: …'")
        texto = "\n".join(l.strip() for l in cuerpo)
        if inyeccion.detectar(texto).bloquear:
            descartados.append(actual["id"])
            return
        reglas.append(Regla(
            nivel=m.group(1),
            aplica_a=[a.strip().lower().replace("móvil", "movil") for a in m.group(2).split(",")],
            referencias=[r.strip() for r in (m.group(3) or "").split(";") if r.strip()],
            texto=texto,
            **meta, **actual,
        ))

    for i, (pagina, linea) in enumerate(lineas):
        m = RE_REGLA.match(linea)
        siguiente = lineas[i + 1][1] if i + 1 < len(lineas) else ""
        if m:
            cerrar()
            cerrar_seccion()
            actual = {"seccion": m.group(1), "id": m.group(2), "titulo": m.group(3),
                      "pagina": pagina, "cuerpo": []}
        elif RE_CAPITULO.match(linea):   # "8. Implementación en ASP.NET Core": termina la regla
            cerrar()
            cerrar_seccion()
            actual = None
            es_indice = RE_PUNTOS.search(linea) or ("." in siguiente and RE_PUNTOS.fullmatch(siguiente.strip()))
            if not es_indice:   # un capítulo real (no su entrada en el índice): puede tener texto propio
                num, titulo = linea.strip().split(". ", 1)
                seccion = {"seccion": num, "titulo": titulo.strip(), "pagina": pagina, "cuerpo": []}
        elif actual is not None:
            actual["cuerpo"].append(linea)
        elif seccion is not None and not RE_PUNTOS.fullmatch(linea.strip()):
            seccion["cuerpo"].append(linea)
    cerrar()
    cerrar_seccion()
    return reglas, secciones, descartados


# ---------------------------------------------------------------- manuales sin identificadores de regla
# Un manual escrito en Word ("3.5.1. Autorización de nivel de objeto roto", "CAPITULO III") no trae ids ni niveles.
# Se declara aquí, por el inicio del nombre del archivo: qué código de documento recibe y con qué prefijo se generan
# los ids de sus reglas. Cada sección numerada final (sin subsecciones) es una regla: 3.5.1 → BPA-305-01 y
# 2.1 → BPA-201-00. Son secciones generales (como "Alcance" en los otros estándares, peso 0.85 en la búsqueda):
# los capítulos de "secciones" completos, las introducciones de capítulo y las subsecciones de "informativos", que
# describen sin prescribir (quiénes son responsables, qué riesgos hay, qué es OWASP). Un texto genérico como 3.4
# se parece a muchas preguntas: como regla desplazaba a la práctica que responde (BOLA → 3.5.1).
# El manual no declara niveles: todas sus reglas quedan como "Recomendado".
MANUALES = {
    "EST_BP": {"documento": "EST-BPA-001", "prefijo": "BPA", "secciones": {1, 5},
               "informativos": {"2.3", "3.1", "3.4"},
               "consumidor": "4.2"},   # "Para consumo de APIs": aplica a cualquier aplicación que consuma una API
}
RE_TITULO_MANUAL = re.compile(r"^\s*(\d)\.(\d{1,2})\.(?:(\d{1,2})\.?)?\s+(\S.{2,})$")
RE_CAPITULO_MANUAL = re.compile(r"^\s*(\d)\.\s+(\S.{3,})$")       # "3. ANÁLISIS DE RIESGOS…"
RE_ROTULO_CAPITULO = re.compile(r"^\s*CAP[IÍ]TULO\s+[IVXL]+\s*$", re.I)
RE_FECHA_MANUAL = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")
RE_REF_OWASP = re.compile(r"\bAPI\d{1,2}:\d{4}\b")
VINETAS = re.compile("[\uf000-\uf0ff]")   # viñetas de Word (fuente Symbol) que pypdf extrae como uso privado


def _oracion(titulo: str) -> str:
    """"ANÁLISIS DE RIESGOS ASOCIADOS A LA IMPLEMENTACIÓN DE API'S." → "Análisis de riesgos … de API's"."""
    if not titulo.isupper():
        return titulo.rstrip(". ")
    return re.sub(r"\bapi\b", "API", titulo.capitalize(), flags=re.I).rstrip(". ")


def _manual(pdf: Path) -> dict | None:
    return next((m for prefijo, m in MANUALES.items() if pdf.name.startswith(prefijo)), None)


def extraer_manual(pdf: Path, conf: dict) -> tuple[list[Regla], list[Regla], list[str]]:
    """(reglas, secciones generales, descartados) de un manual sin ids: la estructura la dan los números."""
    from agente import inyeccion  # noqa: PLC0415
    textos = [p.extract_text() or "" for p in PdfReader(str(pdf)).pages]
    if sum(len(t.strip()) for t in textos) < 50:
        raise ValueError(f"{pdf.name}: el PDF no tiene texto extraíble (¿escaneado? requiere OCR antes de indexarlo)")
    portada = " ".join(textos[0].split())   # la tabla "Datos de la versión": versión y fecha de aprobación
    fecha = RE_FECHA_MANUAL.search(portada)
    version = re.search(r"\b(\d+(?:\.\d+)?)\s+Jefe\b", portada)
    meta = {"documento": conf["documento"], "version": version.group(1) if version else "1",
            "fecha": f"{fecha.group(3)}-{fecha.group(2)}-{fecha.group(1)}" if fecha else ""}
    repetidas = _repetidas(textos[1:])
    titulos: list[dict] = []   # cada título numerado con su cuerpo; "capitulo" para "3. ANÁLISIS…"
    ultimo: tuple = ()
    for pagina, texto in enumerate(textos[1:], start=2):
        for linea in texto.splitlines():
            limpia = VINETAS.sub("•", linea).rstrip()
            if not limpia.strip() or _forma(limpia) in repetidas or RE_ROTULO_CAPITULO.match(limpia):
                continue
            m, c = RE_TITULO_MANUAL.match(limpia), RE_CAPITULO_MANUAL.match(limpia)
            numero = (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)) if m else \
                     (int(c.group(1)), 0, 0) if c and c.group(2)[:4].isupper() else None
            if numero and numero > ultimo:   # los títulos solo avanzan: "3.2., evitando…" en el texto no es título
                ultimo = numero
                titulos.append({"numero": numero, "titulo": (m or c).group(4 if m else 2).strip(),
                                "pagina": pagina, "cuerpo": []})
            elif titulos:
                previo = titulos[-1]
                corta = len(limpia.strip()) < 25 and not previo["cuerpo"]
                if corta and (limpia.strip()[0] in "(" or limpia.strip()[0].islower() or limpia.strip().startswith("API")):
                    previo["titulo"] += " " + limpia.strip()   # título partido: "…de las" / "API's."
                else:
                    previo["cuerpo"].append(limpia.strip())

    def seccion_de(numero: tuple) -> str:
        return ".".join(str(n) for n in numero if n) if numero[1] else str(numero[0])

    def hijos_de(t: dict) -> list[dict]:
        a, b, _ = t["numero"]
        return [x for x in titulos if x is not t and (x["numero"][0] == a if not b else x["numero"][:2] == (a, b))]

    reglas, secciones, descartados = [], [], []
    for t in titulos:
        a, b, c = t["numero"]
        seccion, hijos, texto = seccion_de(t["numero"]), hijos_de(t) if not c else [], "\n".join(t["cuerpo"])
        if b and a in conf["secciones"]:
            continue   # 1. subtítulo de un capítulo informativo: ya va dentro de la sección de su capítulo
        if not b and a in conf["secciones"]:   # 2. capítulo informativo completo (objetivo y alcance, bibliografía)
            texto = "\n".join([texto] + [f"{seccion_de(x['numero'])} {x['titulo']}\n" + "\n".join(x["cuerpo"])
                                         for x in hijos]).strip()
        elif (hijos or not b) and len(texto) < 40:
            continue   # 3. un título que solo agrupa a otros ("3.5. Vulnerabilidades…"), sin texto propio
        es_seccion = not b or bool(hijos) or seccion in conf["informativos"]   # 4. introducciones y contexto
        if inyeccion.detectar(texto).bloquear:
            descartados.append(f"{meta['documento']} §{seccion}")
            continue
        if es_seccion:
            sid = f"{meta['documento']}-S{a:02d}" + (f"{b:02d}" if b else "")
            secciones.append(Regla(id=sid, titulo=_oracion(t["titulo"]), nivel="Informativo", aplica_a=TODOS_LOS_TIPOS,
                                   referencias=[], seccion=seccion, pagina=t["pagina"], texto=texto, **meta))
            continue
        # 5. una práctica: sección numerada final con contenido prescriptivo
        consumidor = seccion.startswith(conf["consumidor"] + ".")
        reglas.append(Regla(id=f"{conf['prefijo']}-{a}{b:02d}-{c:02d}", titulo=t["titulo"].rstrip(". "),
                            nivel="Recomendado", aplica_a=TODOS_LOS_TIPOS if consumidor else ["api"],
                            referencias=sorted(set(RE_REF_OWASP.findall(texto))),
                            seccion=seccion_de(t["numero"]), pagina=t["pagina"], texto=texto, **meta))
    return reglas, secciones, descartados


def pdfs(carpeta: Path = config.ESTANDARES_DIR) -> list[Path]:
    """Los PDF que se indexan: los estándares EST-*.pdf y los manuales declarados en MANUALES."""
    return sorted(p for p in carpeta.glob("EST*.pdf") if p.name.startswith("EST-") or _manual(p))


def codigo_de(pdf: Path) -> str:
    """El código de documento de un PDF: el del manual declarado, o el inicio del nombre (EST-API-001_…)."""
    conf = _manual(pdf)
    return conf["documento"] if conf else pdf.name.split("_", 1)[0]


def construir(carpeta: Path = config.ESTANDARES_DIR) -> tuple[list[Regla], list[Regla], list[str]]:
    """(reglas, secciones generales, descartados por posible prompt injection) de todos los PDF."""
    archivos = pdfs(carpeta)
    if not archivos:
        raise FileNotFoundError(f"No hay PDFs EST-*.pdf en {carpeta}")
    reglas, secciones, descartados = [], [], []
    for pdf in archivos:
        conf = _manual(pdf)
        r, s, d = extraer_manual(pdf, conf) if conf else extraer(pdf)
        reglas, secciones, descartados = reglas + r, secciones + s, descartados + d
    ids = [r.id for r in reglas + secciones]
    repetidos = sorted({i for i in ids if ids.count(i) > 1})
    if repetidos:
        raise ValueError(f"Identificadores repetidos: {repetidos}")
    return reglas, secciones, descartados


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


@lru_cache(maxsize=1)
def secciones(ruta: str = str(config.SECCIONES_PATH)) -> dict[str, Regla]:
    """Secciones generales (no son reglas: el agente no las usa para hallazgos; el chat sí, para responder)."""
    p = Path(ruta)
    if not p.exists():
        return {}
    return {d["id"]: Regla(**d) for d in json.loads(p.read_text(encoding="utf-8"))}
