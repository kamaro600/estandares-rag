"""API HTTP (Starlette) y página web: revisar código, aprobar parches y descargar lo corregido.

La API nunca escribe archivos: devuelve el contenido corregido y el navegador lo descarga.
"""
from __future__ import annotations

import threading
import uuid
from collections import OrderedDict
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Route

from agente import catalogo, config, metricas, rag
from agente.config import Settings
from agente.contexto import Contexto
from agente.detectores import EXTENSIONES, LENGUAJES, cargar_detectores
from agente.llm import crear_llm
from agente.reporte import a_dict
from agente.supervisor import Supervisor
from agente.trace import Tracer
from agente.workers import REVISION_SEMANTICA

MAX_CUERPO = config.MAX_ARCHIVOS * config.MAX_BYTES_ARCHIVO
MAX_REVISIONES_EN_MEMORIA = 20   # las más antiguas se olvidan: la aprobación debe llegar antes
WEB_DIR = Path(__file__).parent / "web"
# La página solo carga recursos propios: ni CDN ni scripts en línea (SEG/WEB: cabeceras de seguridad).
# Para la página: qué se puede adjuntar, agrupado como el alcance de EST-SEG-001 §2.
FAMILIAS = (
    ("Web", "Angular y ASP.NET Core", (".ts", ".html", ".js", ".cshtml", ".razor", ".cs", ".json", ".config", ".csproj")),
    ("APIs", "Código y contrato OpenAPI 3", (".cs", ".yaml", ".yml", ".json")),
    ("Base de datos", "SQL Server", (".sql",)),
    ("Escritorio", "WPF y WinForms", (".cs", ".xaml", ".resx", ".config")),
    ("Móvil", ".NET MAUI, Android e iOS", (".xaml", ".kt", ".kts", ".gradle", ".swift", ".xml", ".plist")),
    ("Pipelines", "Azure DevOps y similares", (".yml", ".yaml")),
    ("Automatización", "PowerShell", (".ps1", ".psm1", ".psd1")),
    ("Contenedores", "Docker", (".dockerfile",)),
)
CABECERAS_WEB = {"Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'; base-uri 'none'",
                 "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}


class ArchivoEntrada(BaseModel):
    nombre: str = Field(min_length=1, max_length=260)
    contenido: str = Field(max_length=config.MAX_BYTES_ARCHIVO)


class SolicitudRevision(BaseModel):
    tipo_app: str = Field(default="web", pattern="^(web|api|escritorio|movil)$")
    modo_bd: str = Field(default="nueva", pattern="^(nueva|legada)$")
    usar_llm: bool = True
    archivos: list[ArchivoEntrada] = Field(min_length=1, max_length=config.MAX_ARCHIVOS)


class Aprobado(BaseModel):
    archivo: str
    parche: str = Field(pattern=r"^P\d{3}$")


class SolicitudAprobacion(BaseModel):
    aprobados: list[Aprobado] = Field(default_factory=list, max_length=config.MAX_ARCHIVOS * 20)


def _problema(status: int, titulo: str, detalle: str, **extra) -> JSONResponse:
    """Errores en Problem Details (RFC 9457), como exige API-RES-002 a las APIs de la empresa."""
    return JSONResponse({"type": "about:blank", "title": titulo, "status": status, "detail": detalle, **extra},
                        status_code=status, media_type="application/problem+json")


async def revisar(request: Request) -> JSONResponse:
    if int(request.headers.get("content-length") or 0) > MAX_CUERPO:
        return _problema(413, "Petición demasiado grande", f"Máximo {MAX_CUERPO} bytes.")
    try:
        solicitud = SolicitudRevision.model_validate(await request.json())
    except ValidationError as e:
        errores = {".".join(map(str, x["loc"])): x["msg"] for x in e.errors()}
        return _problema(400, "Solicitud inválida", "Revisa los campos indicados.", errors=errores)
    except ValueError:
        return _problema(400, "Solicitud inválida", "El cuerpo no es JSON válido.")
    llm = request.app.state.llm if solicitud.usar_llm else None
    sup = Supervisor(Contexto(solicitud.tipo_app, solicitud.modo_bd), llm, Tracer())
    # El análisis y el LLM son síncronos: en un hilo aparte para no bloquear el bucle de eventos.
    rev = await run_in_threadpool(sup.revisar, [(a.nombre, a.contenido) for a in solicitud.archivos],
                                  solicitud.usar_llm)
    metricas.REVISIONES.inc(veredicto=rev.veredicto())
    revision_id = _guardar(request.app, rev, sup)
    resultado = {"revision_id": revision_id, **a_dict(rev)}
    resultado["modelo"] = None if llm is None else _etiqueta_modelo(llm)
    return JSONResponse(resultado)


def _etiqueta_modelo(llm) -> str:
    return "mock" if llm.proveedor == "mock" else f"{llm.proveedor}:{llm.modelo}"


def _guardar(app, rev, sup) -> str:
    """La revisión queda en memoria para que un humano apruebe sus parches después."""
    revision_id = uuid.uuid4().hex
    with app.state.candado:
        app.state.revisiones[revision_id] = {"rev": rev, "sup": sup, "decidida": False}
        while len(app.state.revisiones) > MAX_REVISIONES_EN_MEMORIA:
            app.state.revisiones.popitem(last=False)
    return revision_id


async def aprobar(request: Request) -> JSONResponse:
    """La aprobación humana por HTTP: solo se aplican los parches enviados; el resto queda denegado."""
    try:
        solicitud = SolicitudAprobacion.model_validate(await request.json())
    except ValidationError as e:
        errores = {".".join(map(str, x["loc"])): x["msg"] for x in e.errors()}
        return _problema(400, "Solicitud inválida", "Revisa los campos indicados.", errors=errores)
    except ValueError:
        return _problema(400, "Solicitud inválida", "El cuerpo no es JSON válido.")
    with request.app.state.candado:
        guardada = request.app.state.revisiones.get(request.path_params["revision_id"])
        if guardada is None:
            return _problema(404, "Revisión no encontrada",
                             f"Se guardan las últimas {MAX_REVISIONES_EN_MEMORIA} revisiones y se pierden al "
                             "reiniciar el servidor. Vuelve a revisar.")
        if guardada["decidida"]:
            return _problema(409, "Revisión ya decidida", "Cada revisión se aprueba una sola vez.")
        rev, sup = guardada["rev"], guardada["sup"]
        existentes = {(r.archivo.nombre, p.id) for r in rev.resultados for p in r.parches}
        pedidos = {(a.archivo, a.parche) for a in solicitud.aprobados}
        if pedidos - existentes:
            return _problema(400, "Parche inexistente", "Solo se pueden aprobar parches de esta revisión.",
                             desconocidos=[f"{a} {p}" for a, p in sorted(pedidos - existentes)])
        guardada["decidida"] = True
    cambios = await run_in_threadpool(sup.corregir, rev, lambda p, h: (p.archivo, p.id) in pedidos)
    return JSONResponse({**a_dict(rev), "revision_id": request.path_params["revision_id"],
                         "corregidos": [{"archivo": c.nombre, "contenido": c.contenido, "diff": c.diff}
                                        for c in cambios]})


async def info(request: Request) -> JSONResponse:
    llm = request.app.state.llm
    lenguajes = {l: {"lenguaje": l, "extensiones": sorted(e for e, x in EXTENSIONES.items() if x == l),
                     "patrones": sum(l in p.lenguajes for p in cargar_detectores()),
                     "revision_semantica": l in REVISION_SEMANTICA} for l in sorted(set(EXTENSIONES.values()))}
    return JSONResponse({"modelo": _etiqueta_modelo(llm), "extensiones": sorted(EXTENSIONES),
                         "lenguajes": list(lenguajes.values()), "familias": [{"nombre": n, "detalle": d, "extensiones": list(e)}
                                                                            for n, d, e in FAMILIAS],
                         "max_archivos": config.MAX_ARCHIVOS, "max_bytes_archivo": config.MAX_BYTES_ARCHIVO,
                         "reglas": len(catalogo.cargar())})


def _estatico(nombre: str, tipo: str):
    async def servir(request: Request) -> Response:
        return Response((WEB_DIR / nombre).read_bytes(), media_type=tipo, headers=CABECERAS_WEB)
    return servir


async def regla(request: Request) -> JSONResponse:
    r = catalogo.cargar().get(request.path_params["regla_id"].upper())
    if r is None:
        return _problema(404, "Regla no encontrada", "Usa /v1/buscar?q=… para buscar por tema.")
    return JSONResponse({**r.model_dump(), "cita": r.cita()})


async def buscar(request: Request) -> JSONResponse:
    q = request.query_params.get("q", "").strip()
    if not 3 <= len(q) <= 300:
        return _problema(400, "Consulta inválida", "q debe tener entre 3 y 300 caracteres.")
    return JSONResponse({"items": [{"id": x.regla.id, "titulo": x.regla.titulo, "score": x.score, "via": x.via,
                                    "cita": x.regla.cita()} for x in rag.buscar(q)]})


async def salud(request: Request) -> JSONResponse:
    return JSONResponse({"estado": "ok", "reglas": len(catalogo.cargar())})


async def metrics(request: Request) -> PlainTextResponse:
    return PlainTextResponse(metricas.exponer(), media_type="text/plain; version=0.0.4")


def crear_app(settings: Settings | None = None) -> Starlette:
    config.load_env()
    settings = (settings or Settings()).validar()
    catalogo.cargar()        # falla al arrancar, no en la primera petición, si falta la ingesta
    rag.verificar_indice()   # … o si el índice se hizo con otros embeddings
    app = Starlette(routes=[
        Route("/", _estatico("index.html", "text/html; charset=utf-8")),
        Route("/app.js", _estatico("app.js", "text/javascript; charset=utf-8")),
        Route("/app.css", _estatico("app.css", "text/css; charset=utf-8")),
        Route("/v1/info", info),
        Route("/v1/revisiones", revisar, methods=["POST"]),
        Route("/v1/revisiones/{revision_id}/aprobacion", aprobar, methods=["POST"]),
        Route("/v1/reglas/{regla_id}", regla),
        Route("/v1/buscar", buscar),
        Route("/health", salud),
        Route("/metrics", metrics),
    ])
    app.state.settings = settings
    app.state.llm = crear_llm(settings)
    app.state.revisiones, app.state.candado = OrderedDict(), threading.Lock()
    metricas.inicializar_series(tuple(sorted(LENGUAJES)))
    return app
