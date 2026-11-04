"""Análisis determinista: cada patrón apunta a una regla del catálogo."""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import PurePath

from pydantic import BaseModel

from agente.contexto import Contexto, prioridad

# Cada extensión sale del alcance de los estándares (EST-SEG-001 §2): web Angular + ASP.NET Core, APIs,
# móviles (.NET MAUI, Android con Kotlin, iOS con Swift) y escritorio (.NET WPF y WinForms).
EXTENSIONES = {
    ".cs": "csharp", ".xaml": "xaml", ".ts": "typescript", ".html": "html",
    ".sql": "tsql", ".json": "config", ".config": "config", ".csproj": "config",
    ".cshtml": "razor", ".razor": "razor",                      # SEG-INY-003: Html.Raw en Razor
    ".js": "javascript",                                       # EST-SEG-001 (JavaScript, npm audit)
    ".resx": "xml", ".xml": "xml", ".plist": "xml",            # DSK-NET-006 (.resx), Android, iOS, XML
    ".yml": "yaml", ".yaml": "yaml",                           # API-DIS-005 (OpenAPI 3), pipelines
    ".kt": "kotlin", ".kts": "kotlin", ".gradle": "kotlin",    # Android (Kotlin) · EST-SEG-001 cap. 11
    ".swift": "swift",                                         # iOS (Swift) · EST-SEG-001 cap. 11
}
# Archivos que solo existen en una app móvil: se evalúan con las reglas de Móvil aunque la revisión sea web.
ARCHIVOS_MOVILES = ("androidmanifest.xml", "network_security_config.xml", "info.plist")
LENGUAJES_MOVILES = ("kotlin", "swift")


def detectar_lenguaje(nombre: str) -> str | None:
    p = PurePath(nombre.replace("\\", "/"))
    if p.name.lower().endswith(".xaml.cs"):
        return "csharp"
    return EXTENSIONES.get(p.suffix.lower())


def es_movil(archivo: "Archivo") -> bool:
    nombre = PurePath(archivo.nombre.replace("\\", "/")).name.lower()
    return archivo.lenguaje in LENGUAJES_MOVILES or nombre in ARCHIVOS_MOVILES or nombre.endswith(".plist")


class Hallazgo(BaseModel):
    id: str
    archivo: str
    linea: int
    lenguaje: str
    detector: str
    regla_id: str
    titulo_regla: str
    severidad: str          # bloqueante | advertencia
    confianza: str          # alta | media (media = revisar: puede ser falso positivo)
    mensaje: str
    fragmento: str
    cita: str
    relacionadas: list[str] = []
    autofix: str | None = None   # línea corregida propuesta por código, si existe


@dataclass(frozen=True)
class Patron:
    codigo: str
    lenguajes: tuple[str, ...]
    reglas: tuple[str, ...]
    regex: re.Pattern
    mensaje: str
    confianza: str = "alta"
    relacionadas: tuple[str, ...] = ()
    modo_bd: str | None = None
    segun_bd: bool = False
    excluir: re.Pattern | None = None
    verificar: Callable[[re.Match, "Archivo"], bool] | None = None
    autofix: Callable[[str, re.Match], str | None] | None = None


@dataclass
class Archivo:
    nombre: str
    contenido: str
    lenguaje: str = ""
    lineas: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.contenido = self.contenido.replace("\r\n", "\n")
        self.lineas = self.contenido.split("\n")
        self.lenguaje = self.lenguaje or detectar_lenguaje(self.nombre) or ""


# Detectores de archivo completo: f(archivo, ctx) -> [(codigo, linea, reglas, mensaje, confianza, opciones)]
DetectorArchivo = Callable[[Archivo, Contexto], list[dict]]
PATRONES: list[Patron] = []
DETECTORES_ARCHIVO: dict[str, list[DetectorArchivo]] = {}

_C = re.compile(r"^\s*(//|\*|/\*)")
_COMENTARIO = {
    "csharp": _C, "typescript": _C, "javascript": _C, "kotlin": _C, "swift": _C,
    "tsql": re.compile(r"^\s*--"), "xaml": re.compile(r"^\s*<!--"), "html": re.compile(r"^\s*<!--"),
    "xml": re.compile(r"^\s*<!--"), "config": re.compile(r"^\s*(//|<!--)"),
    "razor": re.compile(r"^\s*(@\*|<!--|//)"), "yaml": re.compile(r"^\s*#"),
}


def _sin_comentario_final(linea: str) -> str:
    """Corta en // solo si no está dentro de una cadena ("https://…" no es un comentario)."""
    abierta, i = None, 0
    while i < len(linea):
        c = linea[i]
        if abierta:
            if c == "\\":
                i += 1
            elif c == abierta:
                abierta = None
        elif c in "\"'`":
            abierta = c
        elif linea.startswith("//", i):
            return linea[:i]
        i += 1
    return linea


def es_comentario(lenguaje: str, linea: str) -> bool:
    rx = _COMENTARIO.get(lenguaje)
    return bool(rx and rx.match(linea))


def codigo_de(lenguaje: str, linea: str) -> str:
    """La línea sin comentarios: el agente no debe 'corregir' comentando el código."""
    if es_comentario(lenguaje, linea):
        return ""
    if lenguaje in ("csharp", "typescript", "javascript", "kotlin", "swift"):
        return _sin_comentario_final(linea)
    if lenguaje == "tsql":
        return linea.split("--", 1)[0]
    return linea


def registrar(*patrones: Patron) -> None:
    PATRONES.extend(patrones)


def registrar_archivo(lenguaje: str):
    def deco(f: DetectorArchivo) -> DetectorArchivo:
        DETECTORES_ARCHIVO.setdefault(lenguaje, []).append(f)
        return f
    return deco


def _hallazgo(archivo: Archivo, ctx: Contexto, n: int, codigo: str, reglas: tuple[str, ...],
              mensaje: str, confianza: str, relacionadas=(), segun_bd=False, autofix=None) -> Hallazgo | None:
    regla = ctx.regla_aplicable(reglas, segun_bd=segun_bd)
    if regla is None:
        return None
    return Hallazgo(
        id="", archivo=archivo.nombre, linea=n, lenguaje=archivo.lenguaje, detector=codigo,
        regla_id=regla.id, titulo_regla=regla.titulo, severidad=regla.severidad, confianza=confianza,
        mensaje=mensaje, fragmento=archivo.lineas[n - 1].strip()[:200], cita=regla.cita(),
        relacionadas=[r for r in relacionadas if r != regla.id], autofix=autofix,
    )


def cargar_detectores() -> list[Patron]:
    """Importar cada módulo registra sus patrones (se hace al primer uso, no al importar el paquete)."""
    from agente.detectores import csharp, movil, tsql, typescript, web, xaml_config  # noqa: F401, PLC0415
    return PATRONES


def analizar(archivo: Archivo, ctx: Contexto) -> list[Hallazgo]:
    cargar_detectores()

    if not archivo.lenguaje:
        return []
    hallazgos: list[Hallazgo] = []
    for n, linea in enumerate(archivo.lineas, start=1):
        codigo = codigo_de(archivo.lenguaje, linea)
        if not codigo.strip():
            continue
        for p in PATRONES:
            if archivo.lenguaje not in p.lenguajes or (p.modo_bd and p.modo_bd != ctx.modo_bd):
                continue
            m = p.regex.search(codigo)
            if not m or (p.excluir and p.excluir.search(codigo)) or (p.verificar and not p.verificar(m, archivo)):
                continue
            fix = p.autofix(linea, m) if p.autofix else None
            h = _hallazgo(archivo, ctx, n, p.codigo, p.reglas, p.mensaje, p.confianza,
                          p.relacionadas, p.segun_bd, fix if fix != linea else None)
            if h:
                hallazgos.append(h)
    for detector in DETECTORES_ARCHIVO.get(archivo.lenguaje, []):
        for d in detector(archivo, ctx):
            if d.get("modo_bd") and d["modo_bd"] != ctx.modo_bd:
                continue
            h = _hallazgo(archivo, ctx, d["linea"], d["codigo"], d["reglas"], d["mensaje"],
                          d.get("confianza", "alta"), d.get("relacionadas", ()), d.get("segun_bd", False),
                          d.get("autofix"))
            if h:
                hallazgos.append(h)
    return _resolver(hallazgos)


def _resolver(hallazgos: list[Hallazgo]) -> list[Hallazgo]:
    """Una línea con dos hallazgos de la misma regla o de reglas relacionadas: queda el que prevalece."""
    finales: list[Hallazgo] = []
    for h in sorted(hallazgos, key=lambda h: (h.linea, prioridad(h.regla_id), h.detector)):
        repetido = next((f for f in finales if f.linea == h.linea and (
            f.regla_id == h.regla_id or h.regla_id in f.relacionadas or f.regla_id in h.relacionadas)), None)
        if repetido:
            if repetido.regla_id == h.regla_id and h.mensaje not in repetido.mensaje:
                repetido.mensaje += " " + h.mensaje       # dos problemas de la misma regla: un hallazgo
            elif repetido.regla_id != h.regla_id:
                repetido.relacionadas = sorted(set(repetido.relacionadas) | {h.regla_id})
            continue
        finales.append(h)
    for i, h in enumerate(finales, start=1):
        h.id = f"H{i:03d}"
    return finales
