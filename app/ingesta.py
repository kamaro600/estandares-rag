"""PDF de estándares → texto → fragmentos por REGLA → embeddings → data/indice.npz  (C1 y C2)

Uso:   python -m app.ingesta              re-indexa siempre
       python -m app.ingesta --si-falta   solo si no hay índice, cambió el embedder o cambió algún PDF
       python -m app.ingesta --verificar  extrae y muestra el reporte de extracción, sin embeddings ni costo

Por qué un fragmento por REGLA y no cada N caracteres: cada regla es una unidad de sentido con identificador propio
(WEB-BD-005). Cortar a mitad de una regla deja "está prohibido el prefijo" sin el prefijo. Además la cita es exacta:
regla + documento + versión + página, y el agente puede traer una regla por su id (`RAG.por_id`).

Limpieza (los PDFs corporativos traen ruido):
  - encabezado y pie de página: se detectan como líneas que se REPITEN en la mayoría de páginas (con los números
    reemplazados por #), sin conocer el texto exacto. Funciona igual con los PDFs oficiales.
  - portada, control de cambios e índice: todo lo que está antes del primer capítulo "1. …" real.
  - entradas del índice: un título seguido de una línea de puntos guía (". . . . 7").
Si un PDF no tiene reglas con el patrón del registro, se corta por secciones numeradas y, si tampoco hay, por
párrafos con solape (modo genérico): la ingesta no falla con un PDF de otro formato.

Seguridad: un fragmento con un intento de prompt injection (inyección indirecta) NO se indexa y se reporta.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
from pypdf import PdfReader

from app import inyeccion
from app.config import ConfigError, Settings
from app.embeddings import Embedder, crear_embedder
from app.modelos import Fragmento

PATRON_REGLA_DEFECTO = r"^(\d+\.\d+) ([A-Z]{3}-[A-Z0-9]+-[A-Z0-9]+) · (.+)$"
RX_CAPITULO = re.compile(r"^(\d{1,2})\. ([A-ZÁÉÍÓÚÑ¿].{1,100})$")
RX_PUNTOS = re.compile(r"^[\s.]*\d*\s*$")                          # línea de puntos guía del índice
RX_META = re.compile(r"^Nivel: (?P<nivel>\w+)(?: \| Aplica a: (?P<aplica>.*?))?(?: \| Referencias: (?P<refs>.*))?$")
RX_CONTINUA_REF = re.compile(r"^(ASVS|OWASP|MASVS|EST-|API\d|A\d\d:)")
MIN_REPETICION = 0.6           # una línea en el 60 % de las páginas o más es encabezado/pie
BORDE_INICIO, BORDE_FIN = 3, 4 # líneas de cada extremo de la página donde se buscan encabezados y pies
LINEA_LLENA = 85               # una línea de metadatos o de título así de larga probablemente continúa abajo
MAX_CARACTERES = 2500          # un fragmento más largo se parte (en el corpus de prueba ninguna regla llega)
SOLAPE = 200                   # caracteres repetidos entre partes consecutivas de un fragmento largo


@dataclass
class ReporteDoc:
    archivo: str
    codigo: str
    paginas: int
    modo: str = ""                       # reglas | secciones | generico
    reglas: int = 0
    secciones: int = 0
    paginas_sin_texto: list[int] = field(default_factory=list)
    descartados: list[str] = field(default_factory=list)      # fragmentos excluidos por inyección
    advertencias: list[str] = field(default_factory=list)


# ------------------------------------------------------------------------------------------------- registro
def cargar_registro(settings: Settings) -> dict[str, dict]:
    """data/documentos.json: metadatos de cada PDF (código, versión, categoría, patrón de reglas)."""
    if not settings.registro_path.exists():
        return {}
    datos = json.loads(settings.registro_path.read_text(encoding="utf-8"))
    return {d["archivo"]: d for d in datos.get("documentos", [])}


def metadatos(pdf: Path, registro: dict[str, dict]) -> dict:
    meta = registro.get(pdf.name)
    if meta:
        return meta
    return {"codigo": pdf.stem, "titulo": pdf.stem.replace("_", " "), "version": "", "fecha": "",
            "categoria": "general", "vigente": True, "patron_regla": PATRON_REGLA_DEFECTO, "no_registrado": True}


# ------------------------------------------------------------------------------------------------- extracción
def _forma(linea: str) -> str:
    return re.sub(r"\d+", "#", linea.strip())


def _slug(texto: str) -> str:
    t = "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:40]


def _bordes(pagina: str) -> list[str]:
    """Las primeras y últimas líneas de la página: donde pypdf deja el encabezado y el pie (según el PDF, al inicio
    o al final del texto). Solo ahí se busca repetición: "Nivel: Obligatorio" o "Ejemplo correcto" también se
    repiten en casi todas las páginas, pero en medio del contenido, y no deben borrarse."""
    lineas = [l for l in pagina.splitlines() if l.strip()]
    return lineas[:BORDE_INICIO] + lineas[-BORDE_FIN:]


def lineas_limpias(paginas: list[str]) -> list[tuple[int, str]]:
    """[(página, línea)] sin encabezados/pies repetidos, sin líneas vacías y sin las entradas del índice."""
    repetidas: set[str] = set()
    if len(paginas) >= 3:
        conteo = Counter(f for p in paginas for f in {_forma(l) for l in _bordes(p)})
        repetidas = {f for f, n in conteo.items() if n / len(paginas) >= MIN_REPETICION}
    crudas = []
    for i, p in enumerate(paginas, 1):
        bordes = set(_bordes(p))
        crudas += [(i, l.rstrip()) for l in p.splitlines()
                   if l.strip() and not (l in bordes and _forma(l) in repetidas)]
    limpias = []
    for k, (pag, linea) in enumerate(crudas):
        siguiente = crudas[k + 1][1] if k + 1 < len(crudas) else ""
        if "." in linea and RX_PUNTOS.match(linea) and ". ." in linea.replace("  ", " "):
            continue                                                         # puntos guía del índice
        if re.search(r"(\.\s){3,}\.?\s*\d+\s*$", linea):
            continue                                                         # "Título . . . . 7" en una línea
        if RX_CAPITULO.match(linea.strip()) and "." in siguiente and RX_PUNTOS.match(siguiente):
            continue                                                         # entrada del índice en dos líneas
        limpias.append((pag, linea))
    return limpias


def _nuevo(meta: dict, tipo: str, id_: str, seccion: str, titulo: str, pagina: int) -> dict:
    return {"id": id_, "doc_codigo": meta["codigo"], "doc_titulo": meta["titulo"], "doc_version": meta["version"],
            "doc_fecha": meta["fecha"], "categoria": meta["categoria"], "tipo": tipo, "seccion": seccion,
            "titulo": titulo, "pagina": pagina, "lineas": [], "nivel": "", "aplica": "", "referencias": "",
            "estado": "texto"}


def _partir(f: dict) -> list[dict]:
    """Un fragmento de más de MAX_CARACTERES se parte por líneas con SOLAPE; cada parte conserva su página."""
    texto = "\n".join(l for _p, l in f["lineas"])
    if len(texto) <= MAX_CARACTERES:
        return [f | {"texto": texto}]
    partes, actual, largo = [], [], 0
    for pag, linea in f["lineas"]:
        if actual and largo + len(linea) > MAX_CARACTERES:
            partes.append(actual)
            solape, total = [], 0
            for x in reversed(actual):                                       # arrastra el final de la parte anterior
                if total >= SOLAPE:
                    break
                solape.insert(0, x)
                total += len(x[1])
            actual, largo = list(solape), total
        actual.append((pag, linea))
        largo += len(linea) + 1
    partes.append(actual)
    return [f | {"id": f"{f['id']}~{n}" if n > 1 else f["id"], "pagina": p[0][0],
                 "texto": "\n".join(l for _p, l in p)} for n, p in enumerate(partes, 1)]


def extraer_fragmentos(pdf: Path, meta: dict) -> tuple[list[Fragmento], ReporteDoc]:
    paginas = [p.extract_text() or "" for p in PdfReader(str(pdf)).pages]
    rep = ReporteDoc(pdf.name, meta["codigo"], len(paginas))
    rep.paginas_sin_texto = [i for i, t in enumerate(paginas, 1) if len(t.strip()) < 20]
    if len(rep.paginas_sin_texto) == len(paginas):
        raise ValueError(f"{pdf.name}: ninguna página tiene texto extraíble (¿PDF escaneado? requiere OCR)")
    if rep.paginas_sin_texto:
        rep.advertencias.append(f"páginas sin texto (¿imágenes?): {rep.paginas_sin_texto}")
    if meta.get("no_registrado"):
        rep.advertencias.append("no está en data/documentos.json: categoría 'general' y sin versión")

    rx_regla = re.compile(meta.get("patron_regla") or PATRON_REGLA_DEFECTO)
    lineas = lineas_limpias(paginas)
    inicio = next((k for k, (_p, l) in enumerate(lineas) if re.match(r"^1\. \S", l.strip())), 0)
    crudos: list[dict] = []
    actual = _nuevo(meta, "seccion", f"{meta['codigo']}#0-inicio", "0", "Inicio", lineas[inicio][0] if lineas else 1)
    crudos.append(actual)
    for pag, linea in lineas[inicio:]:
        texto = linea.strip()
        m_regla, m_cap = rx_regla.match(texto), RX_CAPITULO.match(texto)
        if m_regla:
            actual = _nuevo(meta, "regla", m_regla.group(2), m_regla.group(1), m_regla.group(3).strip(), pag)
            actual["estado"] = "titulo"                                      # el título puede seguir en otra línea
            crudos.append(actual)
        elif m_cap and not texto.endswith("."):
            num, titulo = m_cap.groups()
            actual = _nuevo(meta, "seccion", "", num, titulo.strip(), pag)
            actual["estado"] = "titulo_seccion"
            crudos.append(actual)
        elif actual["estado"] == "titulo_seccion" and len(actual["titulo"]) > 45 and texto[:1].islower() \
                and len(texto.split()) <= 3:
            actual["titulo"] = f"{actual['titulo']} {texto}"                 # título de capítulo en dos líneas
        elif actual["tipo"] == "regla" and actual["estado"] == "titulo" and (m := RX_META.match(texto)):
            actual.update(nivel=m["nivel"], aplica=(m["aplica"] or "").strip(), referencias=(m["refs"] or "").strip(),
                          estado="meta", largo_meta=len(texto))
        elif actual["tipo"] == "regla" and actual["estado"] == "titulo":
            actual["titulo"] = f"{actual['titulo']} {texto}"                 # título de regla en dos líneas
        elif actual["estado"] == "meta" and RX_CONTINUA_REF.match(texto) and actual["largo_meta"] >= LINEA_LLENA:
            actual["referencias"] = f"{actual['referencias']} {texto}".strip()   # referencias en dos líneas
            actual["largo_meta"] = 0
        else:
            actual["estado"] = "texto"
            actual["lineas"].append((pag, linea))
        if actual["tipo"] == "seccion" and not actual["id"] and actual["estado"] != "titulo_seccion":
            actual["id"] = f"{meta['codigo']}#{actual['seccion']}-{_slug(actual['titulo'])}"
    for c in crudos:
        c["id"] = c["id"] or f"{meta['codigo']}#{c['seccion']}-{_slug(c['titulo'])}"

    rep.reglas = sum(c["tipo"] == "regla" for c in crudos)
    rep.secciones = sum(c["tipo"] == "seccion" and bool(c["lineas"]) for c in crudos)
    rep.modo = "reglas" if rep.reglas else "secciones" if rep.secciones > 1 else "generico"
    if not rep.reglas:
        rep.advertencias.append("no se encontraron reglas con el patrón del registro: se corta por secciones/párrafos")

    fragmentos = []
    for c in crudos:
        if not c["lineas"] and c["tipo"] != "regla":
            continue                                                         # capítulo sin introducción
        for parte in _partir(c):
            if parte["tipo"] == "seccion" and rep.modo == "generico":
                parte["tipo"] = "fragmento"
            det = inyeccion.detectar(parte["texto"])
            if det.bloquear:
                rep.descartados.append(f"{parte['id']} ({', '.join(det.tipos)})")
                continue
            fragmentos.append(Fragmento(**{k: v for k, v in parte.items() if k not in ("lineas", "estado", "largo_meta")}))
    return fragmentos, rep


# ------------------------------------------------------------------------------------------------- índice
def texto_para_embedding(f: Fragmento) -> str:
    cabecera = f"{f.doc_titulo} ({f.doc_codigo} v{f.doc_version}, {f.categoria})."
    nombre = f"{f.id} · {f.titulo}." if f.tipo == "regla" else f"{f.titulo}."
    return f"{cabecera} {nombre} {f.texto}"[:8000]


def huella(pdf: Path) -> str:
    return hashlib.sha256(pdf.read_bytes()).hexdigest()


def documentos(settings: Settings) -> list[tuple[Path, dict]]:
    if not settings.pdf_dir.exists():
        raise FileNotFoundError(f"No existe la carpeta {settings.pdf_dir}")
    registro = cargar_registro(settings)
    docs = [(pdf, metadatos(pdf, registro)) for pdf in sorted(settings.pdf_dir.glob("*.pdf"))]
    docs = [(p, m) for p, m in docs if m.get("vigente", True)]
    if not docs:
        raise FileNotFoundError(f"No hay PDFs vigentes en {settings.pdf_dir}")
    return docs


def extraer_todo(settings: Settings) -> tuple[list[Fragmento], list[ReporteDoc]]:
    fragmentos, reportes = [], []
    for pdf, meta in documentos(settings):
        frags, rep = extraer_fragmentos(pdf, meta)
        fragmentos += frags
        reportes.append(rep)
    ids = Counter(f.id for f in fragmentos)
    repetidos = [i for i, n in ids.items() if n > 1]
    if repetidos:
        raise ValueError(f"Identificadores de regla repetidos entre documentos: {repetidos[:10]}")
    return fragmentos, reportes


def construir_indice(settings: Settings, embedder: Embedder) -> dict:
    fragmentos, reportes = extraer_todo(settings)
    vectores = embedder.embed([texto_para_embedding(f) for f in fragmentos])
    manifiesto = {pdf.name: huella(pdf) for pdf, _m in documentos(settings)}
    settings.indice_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(settings.indice_path, vectores=vectores, embedder=np.array(embedder.nombre),
             dim=np.array(vectores.shape[1]), manifiesto=np.array(json.dumps(manifiesto)),
             fragmentos=np.array(json.dumps([asdict(f) for f in fragmentos], ensure_ascii=False)))
    return {"fragmentos": len(fragmentos), "dim": int(vectores.shape[1]), "embedder": embedder.nombre,
            "documentos": [asdict(r) for r in reportes]}


def indice_vigente(settings: Settings, embedder: Embedder) -> tuple[bool, str]:
    if not settings.indice_path.exists():
        return False, "no existe el índice"
    with np.load(settings.indice_path) as z:
        if str(z["embedder"]) != embedder.nombre:
            return False, f"el índice es de {z['embedder']} y el embedder actual es {embedder.nombre}"
        anterior = json.loads(str(z["manifiesto"]))
    actual = {pdf.name: huella(pdf) for pdf, _m in documentos(settings)}
    if anterior != actual:
        cambios = sorted(set(anterior.items()) ^ set(actual.items()))
        return False, f"cambiaron los PDFs: {sorted({c[0] for c in cambios})}"
    return True, "vigente"


def _imprimir(reportes: list[dict]) -> None:
    for r in reportes:
        print(f"  {r['archivo']:<46} {r['paginas']:>3} págs · modo {r['modo']:<9} · {r['reglas']:>3} reglas · "
              f"{r['secciones']:>2} secciones")
        for a in r["advertencias"]:
            print(f"      ! {a}")
        for d in r["descartados"]:
            print(f"      ✗ descartado por posible prompt injection: {d}")


def main(argv: list[str]) -> None:
    settings = Settings()
    if "--verificar" in argv:
        fragmentos, reportes = extraer_todo(settings)
        _imprimir([asdict(r) for r in reportes])
        print(f"Extracción OK: {len(fragmentos)} fragmentos (sin embeddings).")
        return
    if settings.embeddings_provider == "openai" and not settings.openai_api_key:
        raise ConfigError("EMBEDDINGS_PROVIDER=openai pero OPENAI_API_KEY está vacío en .env")
    embedder = crear_embedder(settings)
    if "--si-falta" in argv:
        vigente, motivo = indice_vigente(settings, embedder)
        if vigente:
            print(f"Índice vigente ({embedder.nombre}): no se re-indexa.")
            return
        print(f"Re-indexando: {motivo}")
    r = construir_indice(settings, embedder)
    _imprimir(r["documentos"])
    print(f"Índice creado: {r['fragmentos']} fragmentos · {r['dim']} dimensiones · embedder {r['embedder']} · "
          f"{settings.indice_path}")


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except (ConfigError, FileNotFoundError, ValueError) as e:     # mensaje claro, sin traza de Python
        sys.exit(f"Error: {e}")
