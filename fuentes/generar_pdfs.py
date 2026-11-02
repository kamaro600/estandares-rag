"""Genera los PDFs de estándares de prueba y data/catalogo.json desde una sola fuente (fuentes/est_*.py).

Uso:   python -m fuentes.generar_pdfs

Cada PDF imita un estándar corporativo real: portada, control de cambios, índice, encabezado y pie de página en
todas las hojas. Ese "ruido" es intencional: la ingesta del chat tendrá que filtrarlo.

Después de generar, se relee cada PDF con pypdf (lo mismo que hará la ingesta) para verificar que el identificador
de cada regla se extrae y para registrar su página en el catálogo. El catálogo es la verdad de referencia para las
pruebas de la ingesta (criterio C1) y para armar el set de oro (C3).
`invariant=1` hace que los PDFs sean idénticos byte a byte en cada ejecución.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Frame, KeepTogether, NextPageTemplate, PageBreak,
                                PageTemplate, Paragraph, Preformatted, Spacer, Table, TableStyle)
from reportlab.platypus.tableofcontents import TableOfContents

from fuentes import comun, est_api, est_dsk, est_ref, est_seg, est_web

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "data" / "pdfs"
CATALOGO = RAIZ / "data" / "catalogo.json"
REGISTRO = RAIZ / "data" / "documentos.json"
DOCUMENTOS = [est_seg.DOC, est_ref.DOC, est_web.DOC, est_api.DOC, est_dsk.DOC]

ENCABEZADO_REGLA = "{numero} {id} · {titulo}"      # la ingesta reconocerá este patrón
AZUL = colors.HexColor("#1F3864")
MAX_COLUMNAS_CODIGO = 100

_base = getSampleStyleSheet()
E = {
    "titulo": ParagraphStyle("titulo", parent=_base["Title"], fontSize=24, leading=30, textColor=AZUL),
    "subtitulo": ParagraphStyle("subtitulo", parent=_base["Normal"], fontSize=14, leading=18, alignment=TA_CENTER,
                                textColor=colors.HexColor("#444444")),
    "portada": ParagraphStyle("portada", parent=_base["Normal"], fontSize=11, leading=16, alignment=TA_CENTER),
    "cap": ParagraphStyle("cap", parent=_base["Heading1"], fontSize=15, leading=19, textColor=AZUL,
                          spaceBefore=10, spaceAfter=8),
    "regla": ParagraphStyle("regla", parent=_base["Heading3"], fontSize=11, leading=14, textColor=AZUL,
                            spaceBefore=10, spaceAfter=2),
    "meta": ParagraphStyle("meta", parent=_base["Normal"], fontSize=8.5, leading=11,
                           textColor=colors.HexColor("#555555"), spaceAfter=4),
    "cuerpo": ParagraphStyle("cuerpo", parent=_base["BodyText"], fontSize=10, leading=14, spaceAfter=4),
    "etiqueta": ParagraphStyle("etiqueta", parent=_base["Normal"], fontSize=8.5, leading=11, spaceBefore=3),
    "codigo": ParagraphStyle("codigo", fontName="Courier", fontSize=8, leading=10),
    "celda": ParagraphStyle("celda", parent=_base["Normal"], fontSize=9, leading=12),
    "toc0": ParagraphStyle("toc0", parent=_base["Normal"], fontSize=10.5, leading=16, leftIndent=0.3 * cm),
}


# ---------------------------------------------------------------------------------------------------- validación
def _verificar_texto(doc: dict) -> None:
    """Las fuentes estándar de PDF (Helvetica, Courier) solo tienen los caracteres de WinAnsi (cp1252):
    un '→' o un '≥' saldría como un cuadro negro y la ingesta leería basura."""
    errores = []

    def revisar(origen: str, texto: str | None) -> None:
        if not texto:
            return
        try:
            texto.encode("cp1252")
        except UnicodeEncodeError as e:
            errores.append(f"{origen}: carácter no soportado {texto[e.start]!r}")

    def recorrer(origen: str, valor) -> None:
        if isinstance(valor, str):
            revisar(origen, valor)
        elif isinstance(valor, dict):
            for k, v in valor.items():
                recorrer(f"{origen}.{k}", v)
        elif isinstance(valor, (list, tuple)):
            for i, v in enumerate(valor):
                recorrer(f"{origen}[{i}]", v)

    recorrer(doc["codigo"], doc)
    ids = [r["id"] for c in doc["capitulos"] for r in c["reglas"]]
    if len(ids) != len(set(ids)):
        errores.append(f"{doc['codigo']}: identificadores de regla repetidos")
    for c in doc["capitulos"]:
        for r in c["reglas"]:
            for tipo in ("mal", "bien"):
                for linea in (r[tipo] or "").splitlines():
                    if len(linea) > MAX_COLUMNAS_CODIGO:
                        errores.append(f"{r['id']}.{tipo}: línea de {len(linea)} columnas (máx. {MAX_COLUMNAS_CODIGO})")
    if errores:
        raise ValueError("\n".join(errores))


# ---------------------------------------------------------------------------------------------------- maquetación
def _texto(t: str) -> str:
    """Escapa el texto para Paragraph y convierte `código` en fuente monoespaciada."""
    return re.sub(r"`([^`]+)`", r'<font face="Courier" size="9">\1</font>', escape(t))


class NumeradoCanvas(rl_canvas.Canvas):
    """Canvas que conoce el total de páginas para escribir "Página N de M" (dos pasadas sobre las páginas)."""

    doc_meta: dict = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._paginas = []

    def showPage(self):
        self._paginas.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._paginas)
        for estado in self._paginas:
            self.__dict__.update(estado)
            if self._pageNumber > 1:                          # la portada no lleva encabezado ni pie
                self._decorar(total)
            super().showPage()
        super().save()

    def _decorar(self, total: int) -> None:
        d = self.doc_meta
        ancho, alto = A4
        self.saveState()
        self.setStrokeColor(AZUL)
        self.setLineWidth(0.6)
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#555555"))
        self.drawString(2 * cm, alto - 1.3 * cm, f"{d['codigo']} · {d['titulo']}")
        self.drawRightString(ancho - 2 * cm, alto - 1.3 * cm, f"Versión {d['version']} · {d['fecha']}")
        self.line(2 * cm, alto - 1.45 * cm, ancho - 2 * cm, alto - 1.45 * cm)
        self.line(2 * cm, 1.55 * cm, ancho - 2 * cm, 1.55 * cm)
        self.drawString(2 * cm, 1.1 * cm, f"{comun.EMPRESA} · Uso interno · {comun.AVISO}")
        self.drawRightString(ancho - 2 * cm, 1.1 * cm, f"Página {self._pageNumber} de {total}")
        self.restoreState()


class Plantilla(BaseDocTemplate):
    def __init__(self, archivo: str, doc: dict):
        super().__init__(archivo, pagesize=A4, title=f"{doc['codigo']} {doc['titulo']}", author=comun.EMPRESA,
                         subject=doc["subtitulo"], keywords=doc["categoria"], creator=comun.AREA,
                         leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2.1 * cm, bottomMargin=2.1 * cm,
                         invariant=1)
        marco = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="normal")
        self.addPageTemplates([PageTemplate(id="portada", frames=[marco]),
                               PageTemplate(id="contenido", frames=[marco])])

    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph) and flowable.style.name == "cap":
            self.notify("TOCEntry", (0, flowable.getPlainText(), self.page))


def _tabla(filas: list[list], anchos: list[float]) -> Table:
    datos = [[Paragraph(_texto(str(c)) if i else f"<b>{escape(str(c))}</b>", E["celda"]) for c in fila]
             for i, fila in enumerate(filas)]
    t = Table(datos, colWidths=anchos, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D9E2F3")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#8EA9DB")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def _bloque_codigo(etiqueta: str, color: str, codigo: str, ancho: float) -> KeepTogether:
    caja = Table([[Preformatted(codigo, E["codigo"])]], colWidths=[ancho])
    caja.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F4F4F4")),
        ("LINEBEFORE", (0, 0), (0, -1), 2, colors.HexColor(color)),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return KeepTogether([Paragraph(f'<font color="{color}"><b>{etiqueta}</b></font>', E["etiqueta"]), caja])


def _historia(doc: dict, ancho: float) -> tuple[list, list[dict]]:
    h: list = []
    # Portada
    h += [Spacer(1, 4 * cm), Paragraph(escape(comun.EMPRESA), E["portada"]),
          Paragraph(escape(comun.AREA), E["portada"]), Spacer(1, 2 * cm),
          Paragraph(escape(doc["titulo"]), E["titulo"]), Paragraph(escape(doc["subtitulo"]), E["subtitulo"]),
          Spacer(1, 2.5 * cm),
          _tabla([["Código", "Versión", "Fecha de aprobación", "Estado"],
                  [doc["codigo"], doc["version"], doc["fecha"], "Vigente"]], [ancho / 4] * 4),
          Spacer(1, 0.6 * cm),
          Paragraph(f"Aprobado por: {escape(doc['aprobado_por'])}", E["portada"]),
          Spacer(1, 3 * cm),
          Paragraph(f"<i>{escape(comun.AVISO)}. La empresa y las reglas son un ejemplo para pruebas de un "
                    f"asistente RAG; no corresponden a ninguna organización real.</i>", E["portada"]),
          NextPageTemplate("contenido"), PageBreak()]
    # Control de cambios e índice
    h += [Paragraph("Control de cambios", E["cap"]),
          _tabla([["Versión", "Fecha", "Descripción del cambio"]] + [list(f) for f in doc["historial"]],
                 [2 * cm, 2.6 * cm, ancho - 4.6 * cm]),
          Spacer(1, 0.8 * cm), Paragraph("<b>Contenido</b>", E["cuerpo"])]
    toc = TableOfContents(dotsMinLevel=0)
    toc.levelStyles = [E["toc0"]]
    h += [toc, PageBreak()]
    # Secciones introductorias
    defs = comun.DEFINICIONES_COMUNES + doc.get("definiciones", [])
    h += [Paragraph("1. Objetivo", E["cap"]), Paragraph(_texto(doc["objetivo"]), E["cuerpo"]),
          Paragraph("2. Alcance", E["cap"]), Paragraph(_texto(doc["alcance"]), E["cuerpo"]),
          Paragraph("3. Definiciones y niveles de cumplimiento", E["cap"]),
          _tabla([["Término", "Definición"]] + [list(d) for d in defs], [3.5 * cm, ancho - 3.5 * cm])]

    reglas: list[dict] = []
    n = 4
    for capitulo in doc["capitulos"]:
        h += [CondPageBreak(6 * cm), Paragraph(f"{n}. {escape(capitulo['titulo'])}", E["cap"])]
        if capitulo.get("intro"):
            h.append(Paragraph(_texto(capitulo["intro"]), E["cuerpo"]))
        for m, r in enumerate(capitulo["reglas"], 1):
            numero = f"{n}.{m}"
            meta = [f"<b>Nivel:</b> {escape(r['nivel'])}"]
            if r["aplica"]:
                meta.append(f"<b>Aplica a:</b> {escape(r['aplica'])}")
            if r["refs"]:
                meta.append(f"<b>Referencias:</b> {escape(r['refs'])}")
            cabecera = [CondPageBreak(3.5 * cm),
                        Paragraph(escape(ENCABEZADO_REGLA.format(numero=numero, **r)), E["regla"]),
                        Paragraph("  |  ".join(meta), E["meta"])]
            parrafos = [Paragraph(_texto(p), E["cuerpo"]) for p in r["texto"].split("\n\n")]
            h += [KeepTogether(cabecera + parrafos[:1])] + parrafos[1:]
            if r["mal"]:
                h.append(_bloque_codigo("Ejemplo incorrecto", "#C00000", r["mal"], ancho))
            if r["bien"]:
                h.append(_bloque_codigo("Ejemplo correcto", "#2E7D32", r["bien"], ancho))
            reglas.append({"id": r["id"], "titulo": r["titulo"], "seccion": numero, "capitulo": capitulo["titulo"],
                           "nivel": r["nivel"], "aplica": r["aplica"], "referencias": r["refs"],
                           "tiene_ejemplos": bool(r["mal"] or r["bien"])})
        n += 1
    for titulo, texto in doc.get("cierre", []):
        h += [CondPageBreak(4 * cm), Paragraph(f"{n}. {escape(titulo)}", E["cap"]), Paragraph(_texto(texto), E["cuerpo"])]
        n += 1
    return h, reglas


# ---------------------------------------------------------------------------------------------------- generación
def generar(doc: dict) -> dict:
    _verificar_texto(doc)
    DESTINO.mkdir(parents=True, exist_ok=True)
    ruta = DESTINO / doc["archivo"]
    plantilla = Plantilla(str(ruta), doc)
    historia, reglas = _historia(doc, plantilla.width)
    NumeradoCanvas.doc_meta = doc
    plantilla.multiBuild(historia, canvasmaker=NumeradoCanvas)

    # Verificación con el mismo extractor que usará la ingesta
    paginas = [p.extract_text() or "" for p in PdfReader(str(ruta)).pages]
    faltan = []
    for r in reglas:
        rx = re.compile(rf"^{re.escape(r['seccion'])} {re.escape(r['id'])} ", re.M)
        r["pagina"] = next((i for i, t in enumerate(paginas, 1) if rx.search(t)), None)
        if r["pagina"] is None:
            faltan.append(r["id"])
    if faltan:
        raise RuntimeError(f"{doc['archivo']}: pypdf no encuentra el encabezado de {faltan}")
    return {"codigo": doc["codigo"], "titulo": doc["titulo"], "subtitulo": doc["subtitulo"],
            "version": doc["version"], "fecha": doc["fecha"], "categoria": doc["categoria"],
            "archivo": f"data/pdfs/{doc['archivo']}", "paginas": len(paginas),
            "patron_regla": r"^(\d+\.\d+) ([A-Z]{3}-[A-Z0-9]+-[A-Z0-9]+) · (.+)$",
            "reglas": reglas}


def main() -> None:
    catalogo = {"empresa": comun.EMPRESA, "aviso": comun.AVISO, "documentos": []}
    for doc in DOCUMENTOS:
        info = generar(doc)
        catalogo["documentos"].append(info)
        ejemplos = sum(r["tiene_ejemplos"] for r in info["reglas"])
        print(f"{info['archivo']:<55} {info['paginas']:>3} págs · {len(info['reglas']):>2} reglas · "
              f"{ejemplos:>2} con código")
    CATALOGO.write_text(json.dumps(catalogo, ensure_ascii=False, indent=2), encoding="utf-8")
    # Registro que lee la ingesta (app/ingesta.py). Con los PDFs oficiales este archivo se mantiene a mano.
    registro = {"documentos": [{k: d[k] for k in ("codigo", "titulo", "version", "fecha", "categoria")}
                               | {"archivo": Path(d["archivo"]).name, "vigente": True,
                                  "patron_regla": d["patron_regla"]} for d in catalogo["documentos"]]}
    REGISTRO.write_text(json.dumps(registro, ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(len(d["reglas"]) for d in catalogo["documentos"])
    print(f"Catálogo: {CATALOGO.relative_to(RAIZ)} · {len(DOCUMENTOS)} documentos · {total} reglas")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError) as e:
        sys.exit(f"Error: {e}")
