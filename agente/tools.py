"""Herramientas del especialista. Ninguna escribe en disco: escribir es del supervisor, con permiso humano."""
from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field, ValidationError

from agente import catalogo, config, rag
from agente.contexto import Contexto
from agente.detectores import Archivo, Hallazgo
from agente.guardas import validar_parche
from agente.parches import Parche


@dataclass
class Sesion:
    """Estado de la revisión de UN archivo: lo que las herramientas leen y modifican."""
    archivo: Archivo
    ctx: Contexto
    hallazgos: list[Hallazgo]
    parches: list[Parche] = field(default_factory=list)
    rechazos: list[tuple[str, str, str]] = field(default_factory=list)   # (hallazgo, categoría, motivo)
    manuales: dict[str, str] = field(default_factory=dict)               # hallazgo -> motivo
    semanticos: list[Hallazgo] = field(default_factory=list)              # reportados por el LLM


class LeerLineas(BaseModel):
    desde: int = Field(ge=1, description="Primera línea (1 = la primera del archivo)")
    hasta: int = Field(ge=1, description="Última línea, como máximo 80 después de 'desde'")


class ObtenerRegla(BaseModel):
    regla_id: str = Field(pattern=r"^[A-Z]{3}-[A-Z0-9]{2,4}-[A-Z0-9]{2,10}$",
                          description="Identificador exacto, por ejemplo SEG-INY-001")


class BuscarEstandar(BaseModel):
    consulta: str = Field(min_length=3, max_length=300, description="Pregunta sobre los estándares")


class ProponerParche(BaseModel):
    hallazgo_id: str = Field(pattern=r"^H\d{3}$")
    linea_inicio: int = Field(ge=1)
    linea_fin: int = Field(ge=1)
    reemplazo: str = Field(description="Texto que reemplaza las líneas inicio..fin, con su indentación")
    justificacion: str = Field(min_length=10, max_length=500,
                               description="Qué cambia y por qué cumple la regla (cita la regla)")


class MarcarRevisionManual(BaseModel):
    hallazgo_id: str = Field(pattern=r"^H\d{3}$")
    motivo: str = Field(min_length=10, max_length=500,
                        description="Por qué no se puede corregir con seguridad en este archivo")


class ReportarHallazgo(BaseModel):
    regla_id: str = Field(pattern=r"^[A-Z]{3}-[A-Z0-9]{2,4}-[A-Z0-9]{2,10}$")
    linea: int = Field(ge=1)
    mensaje: str = Field(min_length=10, max_length=300)


def _datos_externos(nombre: str, texto: str) -> str:
    """Lo que viene del archivo revisado es DATO, no instrucciones (puede contener inyecciones)."""
    texto = texto[:config.TOOL_RESULT_MAX_CHARS]
    return f'<datos_externos herramienta="{nombre}">\n{texto}\n</datos_externos>'


def leer_lineas(s: Sesion, a: LeerLineas) -> str:
    hasta = min(a.hasta, a.desde + 80, len(s.archivo.lineas))
    if a.desde > len(s.archivo.lineas):
        raise ValueError(f"El archivo tiene {len(s.archivo.lineas)} líneas.")
    cuerpo = "\n".join(f"{n:>4}| {s.archivo.lineas[n - 1]}" for n in range(a.desde, hasta + 1))
    return _datos_externos("leer_lineas", cuerpo)


def obtener_regla(s: Sesion, a: ObtenerRegla) -> str:
    r = catalogo.cargar().get(a.regla_id)
    if r is None:
        raise ValueError(f"No existe la regla {a.regla_id}. Usa buscar_estandar.")
    return f"{r.id} · {r.titulo} ({r.nivel}; aplica a {', '.join(r.aplica_a)})\nCita: {r.cita()}\n{r.texto}"


def buscar_estandar(s: Sesion, a: BuscarEstandar) -> str:
    res = rag.buscar(a.consulta, aplica_a=None)
    if not res:
        return "Sin resultados por encima del umbral de relevancia."
    return "\n\n".join(f"[{x.regla.id}] {x.regla.titulo} (score {x.score}, {x.via})\n{x.regla.texto[:600]}"
                       for x in res)


def proponer_parche(s: Sesion, a: ProponerParche) -> str:
    if len(s.parches) >= config.MAX_PARCHES_POR_ARCHIVO:
        raise ValueError(f"Límite de {config.MAX_PARCHES_POR_ARCHIVO} parches por archivo alcanzado.")
    h = next((x for x in s.hallazgos if x.id == a.hallazgo_id), None)
    p = Parche(archivo=s.archivo.nombre, hallazgo_id=a.hallazgo_id, regla_id=h.regla_id if h else "?",
               linea_inicio=a.linea_inicio, linea_fin=a.linea_fin, reemplazo=a.reemplazo,
               justificacion=a.justificacion, origen="llm")
    rechazo = validar_parche(s.archivo, p, s.hallazgos, s.ctx)
    if rechazo:
        s.rechazos.append((a.hallazgo_id, *rechazo))
        raise ValueError(f"RECHAZADO por la guarda: {rechazo[1]}")
    p.id = f"P{len(s.parches) + 1:03d}"
    s.parches.append(p)
    s.manuales.pop(a.hallazgo_id, None)
    return f"ACEPTADO {p.id} para {a.hallazgo_id}. Quedará pendiente de aprobación humana."


def marcar_revision_manual(s: Sesion, a: MarcarRevisionManual) -> str:
    if not any(x.id == a.hallazgo_id for x in s.hallazgos):
        raise ValueError(f"No existe el hallazgo {a.hallazgo_id}.")
    s.manuales[a.hallazgo_id] = a.motivo
    return f"{a.hallazgo_id} queda para revisión humana."


def reportar_hallazgo(s: Sesion, a: ReportarHallazgo) -> str:
    """Lo que los detectores no ven (IDOR, fail-open…): entra como confianza media, nunca alta."""
    if len(s.semanticos) >= 10:
        raise ValueError("Límite de 10 hallazgos semánticos por archivo.")
    regla = catalogo.cargar().get(a.regla_id)
    if regla is None:
        raise ValueError(f"No existe la regla {a.regla_id}: no inventes identificadores.")
    if s.ctx.regla_aplicable((regla.id,)) is None:
        raise ValueError(f"{regla.id} no aplica a una aplicación {s.ctx.tipo_app}.")
    if a.linea > len(s.archivo.lineas):
        raise ValueError(f"El archivo tiene {len(s.archivo.lineas)} líneas.")
    h = Hallazgo(id=f"S{len(s.semanticos) + 1:03d}", archivo=s.archivo.nombre, linea=a.linea,
                 lenguaje=s.archivo.lenguaje, detector="LLM-SEMANTICO", regla_id=regla.id,
                 titulo_regla=regla.titulo, severidad=regla.severidad, confianza="media",
                 mensaje=a.mensaje, fragmento=s.archivo.lineas[a.linea - 1].strip()[:200], cita=regla.cita())
    s.semanticos.append(h)
    return f"Registrado {h.id} ({regla.id}, confianza media): lo verá un humano."


HERRAMIENTAS = {
    "leer_lineas": (LeerLineas, leer_lineas, "Lee un rango de líneas numeradas del archivo en revisión."),
    "obtener_regla": (ObtenerRegla, obtener_regla, "Texto exacto de una regla del catálogo, con su cita."),
    "buscar_estandar": (BuscarEstandar, buscar_estandar, "Busca en los estándares por similitud."),
    "proponer_parche": (ProponerParche, proponer_parche,
                        "Propone reemplazar las líneas inicio..fin para corregir UN hallazgo. "
                        "Las guardas lo validan re-analizando el archivo; si lo rechazan, lee el motivo."),
    "marcar_revision_manual": (MarcarRevisionManual, marcar_revision_manual,
                               "Deriva un hallazgo a un humano cuando corregirlo exige cambios fuera del rango "
                               "o decisiones de diseño."),
    "reportar_hallazgo": (ReportarHallazgo, reportar_hallazgo,
                          "Reporta un incumplimiento que los detectores no vieron (confianza media)."),
}


def esquemas(nombres: tuple[str, ...]) -> list[dict]:
    return [{"name": n, "description": HERRAMIENTAS[n][2], "input_schema": HERRAMIENTAS[n][0].model_json_schema()}
            for n in nombres]


def ejecutar(s: Sesion, nombre: str, argumentos: dict, permitidas: tuple[str, ...]) -> tuple[str, bool]:
    """Devuelve (texto, es_error). Los errores son texto que el modelo puede leer y corregir."""
    if nombre not in permitidas:
        return f"La herramienta {nombre} no está permitida para este especialista.", True
    modelo, funcion, _ = HERRAMIENTAS[nombre]
    try:
        return funcion(s, modelo(**argumentos)), False
    except ValidationError as e:
        errores = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())
        return f"Argumentos inválidos: {errores}", True
    except ValueError as e:
        return str(e), True
