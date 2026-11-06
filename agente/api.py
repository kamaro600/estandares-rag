"""API HTTP (Starlette) y página web: chat sobre los estándares, revisar código, aprobar parches y descargar.

La API nunca escribe archivos del usuario: devuelve el contenido corregido y el navegador lo descarga.
Aplica a sí misma lo que exigen los estándares: errores en Problem Details (API-RES-002), cabeceras de seguridad
(SEG-CFG-001), límite de tasa con 429 y Retry-After (API-SEG-003) y contratos que validan la entrada (API-SEG-004).
"""
from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict, defaultdict, deque
from pathlib import Path

from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Route

from agente import catalogo, config, embeddings, metricas, rag
from agente.config import Settings
from agente.contexto import Contexto
from agente.contratos import MensajeChat, SolicitudAprobacion, SolicitudRevision
from agente.conversacion import Chat
from agente.db import NoExiste, Repositorio
from agente.detectores import EXTENSIONES, cargar_detectores
from agente.llm import crear_llm
from agente.reporte import a_dict
from agente.router import Router
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
)
CABECERAS_WEB = {"Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'; base-uri 'none'",
                 "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}


def _problema(status: int, titulo: str, detalle: str, headers: dict | None = None, **extra) -> JSONResponse:
    """Errores en Problem Details (RFC 9457), como exige API-RES-002 a las APIs de la empresa."""
    return JSONResponse({"type": "about:blank", "title": titulo, "status": status, "detail": detalle, **extra},
                        status_code=status, media_type="application/problem+json", headers=headers)


class LimiteTasa:
    """Ventana deslizante en memoria por IP. Basta para un proceso; con varias réplicas iría en Redis."""

    def __init__(self, por_minuto: int):
        self.por_minuto, self.eventos, self.candado = por_minuto, defaultdict(deque), threading.Lock()

    def esperar(self, clave: str) -> int:
        """0 si se permite; si no, segundos que hay que esperar."""
        ahora = time.monotonic()
        with self.candado:
            cola = self.eventos[clave]
            while cola and ahora - cola[0] > 60:
                cola.popleft()
            if len(cola) >= self.por_minuto:
                return int(60 - (ahora - cola[0])) + 1
            cola.append(ahora)
            return 0


def _limitado(request: Request) -> JSONResponse | None:
    espera = request.app.state.limite.esperar(request.client.host if request.client else "?")
    if not espera:
        return None
    metricas.LIMITE_TASA.inc()
    return _problema(429, "Demasiadas solicitudes", f"Límite de {request.app.state.limite.por_minuto} por minuto.",
                     headers={"Retry-After": str(espera)})


async def _json_valido(request: Request, modelo):
    """(objeto validado, None) o (None, respuesta de error en Problem Details)."""
    try:
        return modelo.model_validate(await request.json()), None
    except ValidationError as e:
        errores = {".".join(map(str, x["loc"])): x["msg"] for x in e.errors()}
        return None, _problema(400, "Solicitud inválida", "Revisa los campos indicados.", errors=errores)
    except ValueError:
        return None, _problema(400, "Solicitud inválida", "El cuerpo no es JSON válido.")


def _ejecutar_revision(app, solicitud: SolicitudRevision, tracer: Tracer, conversacion_id: int | None = None):
    """El agente sobre una solicitud ya validada: Supervisor → especialistas → guardas. Síncrono (va en un hilo)."""
    llm = app.state.llm if solicitud.usar_llm else None
    sup = Supervisor(Contexto(solicitud.tipo_app, solicitud.modo_bd), llm, tracer)
    rev = sup.revisar([(a.nombre, a.contenido) for a in solicitud.archivos], solicitud.usar_llm)
    metricas.REVISIONES.inc(veredicto=rev.veredicto())
    return _guardar(app, rev, sup, conversacion_id), a_dict(rev)


async def revisar(request: Request) -> JSONResponse:
    """POST /v1/revisiones: valida el contrato, ejecuta el agente en un hilo y devuelve el resultado con su trace_id."""
    if int(request.headers.get("content-length") or 0) > MAX_CUERPO:
        return _problema(413, "Petición demasiado grande", f"Máximo {MAX_CUERPO} bytes.")
    if (limitado := _limitado(request)) is not None:
        return limitado
    solicitud, error = await _json_valido(request, SolicitudRevision)
    if error:
        return error
    tracer = Tracer()
    # El análisis y el LLM son síncronos: en un hilo aparte para no bloquear el bucle de eventos.
    revision_id, resultado = await run_in_threadpool(_ejecutar_revision, request.app, solicitud, tracer)
    request.app.state.repo.guardar_traza(tracer.id, None, tracer.eventos)
    tracer.guardar()
    llm = request.app.state.llm if solicitud.usar_llm else None
    return JSONResponse({"revision_id": revision_id, "trace_id": tracer.id, **resultado,
                         "modelo": None if llm is None else _etiqueta_modelo(llm)})


def _etiqueta_modelo(llm) -> str:
    return "mock" if llm.proveedor == "mock" else f"{llm.proveedor}:{llm.modelo}"


def _guardar(app, rev, sup, conversacion_id: int | None = None) -> str:
    """La revisión queda en memoria para que un humano apruebe sus parches después."""
    revision_id = uuid.uuid4().hex
    with app.state.candado:
        app.state.revisiones[revision_id] = {"rev": rev, "sup": sup, "decidida": False,
                                             "conversacion_id": conversacion_id}
        while len(app.state.revisiones) > MAX_REVISIONES_EN_MEMORIA:
            app.state.revisiones.popitem(last=False)
    return revision_id


async def aprobar(request: Request) -> JSONResponse:
    """La aprobación humana por HTTP: solo se aplican los parches enviados; el resto queda denegado."""
    solicitud, error = await _json_valido(request, SolicitudAprobacion)
    if error:
        return error
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
    reporte = a_dict(rev)
    respuesta = {**reporte, "revision_id": request.path_params["revision_id"],
                 "corregidos": [{"archivo": c.nombre, "contenido": c.contenido, "diff": c.diff} for c in cambios]}
    if guardada.get("conversacion_id"):   # la decisión humana vuelve al chat de origen
        respuesta["mensaje_chat"] = request.app.state.chat.notificar_aprobacion(
            guardada["conversacion_id"], request.path_params["revision_id"], reporte, len(cambios))
    return JSONResponse(respuesta)


async def chat(request: Request) -> JSONResponse:
    """POST /v1/chat: un turno de la conversación."""
    if (limitado := _limitado(request)) is not None:
        return limitado
    m, error = await _json_valido(request, MensajeChat)
    if error:
        return error
    try:
        return JSONResponse(await run_in_threadpool(request.app.state.chat.enviar, m.conversacion_id, m.mensaje,
                                                    m.tipo_app, m.modo_bd))
    except NoExiste:
        return _problema(404, "Conversación no encontrada", f"No existe la conversación {m.conversacion_id}.")


async def leer_chat(request: Request) -> JSONResponse:
    repo, cid = request.app.state.repo, request.path_params["conversacion_id"]
    if not repo.existe(cid):
        return _problema(404, "Conversación no encontrada", f"No existe la conversación {cid}.")
    return JSONResponse({"conversacion_id": cid, "mensajes": repo.mensajes(cid)})


async def traza(request: Request) -> JSONResponse:
    try:
        return JSONResponse(request.app.state.repo.traza(request.path_params["trace_id"]))
    except NoExiste:
        return _problema(404, "Traza no encontrada", "Las trazas se guardan por mensaje del chat y por revisión.")


async def info(request: Request) -> JSONResponse:
    """GET /v1/info: lo que la página necesita saber (modelo, extensiones aceptadas, límites y estándares cargados)."""
    llm = request.app.state.llm
    lenguajes = {l: {"lenguaje": l, "extensiones": sorted(e for e, x in EXTENSIONES.items() if x == l),
                     "patrones": sum(l in p.lenguajes for p in cargar_detectores()),
                     "revision_semantica": l in REVISION_SEMANTICA} for l in sorted(set(EXTENSIONES.values()))}
    return JSONResponse({"modelo": _etiqueta_modelo(llm), "extensiones": sorted(EXTENSIONES),
                         "lenguajes": list(lenguajes.values()), "familias": [{"nombre": n, "detalle": d, "extensiones": list(e)}
                                                                            for n, d, e in FAMILIAS],
                         "max_archivos": config.MAX_ARCHIVOS, "max_bytes_archivo": config.MAX_BYTES_ARCHIVO,
                         "reglas": len(catalogo.cargar()), "documentos": _documentos(), "embeddings": embeddings.descriptor()})


def _documentos() -> list[dict]:
    """Los estándares cargados, con su versión, cuántas reglas aportan y el PDF del que salen (panel lateral).
    El archivo se muestra porque el código de un manual sin código propio (EST-BPA-001) lo asigna MANUALES."""
    archivos = {catalogo.codigo_de(p): p.name for p in catalogo.pdfs()}
    docs: dict[str, dict] = {}
    for r in catalogo.cargar().values():
        docs.setdefault(r.documento, {"codigo": r.documento, "version": r.version, "reglas": 0,
                                      "archivo": archivos.get(r.documento, "")})["reglas"] += 1
    return sorted(docs.values(), key=lambda d: d["codigo"])


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
    return JSONResponse({"estado": "ok", "reglas": len(catalogo.cargar()), "secciones": len(catalogo.secciones()),
                         "embeddings": embeddings.descriptor(), "modelo": _etiqueta_modelo(request.app.state.llm),
                         "rag_min_score": request.app.state.settings.rag_min_score})


async def metrics(request: Request) -> PlainTextResponse:
    return PlainTextResponse(metricas.exponer(), media_type="text/plain; version=0.0.4")


def crear_app(settings: Settings | None = None) -> Starlette:
    """Fábrica de la aplicación (uvicorn agente.api:crear_app --factory).

    Falla al arrancar, no en la primera petición, si la configuración es inválida, falta la ingesta o el
    índice no corresponde a los embeddings o a los PDF actuales.
    """
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
        Route("/v1/chat", chat, methods=["POST"]),
        Route("/v1/chat/{conversacion_id:int}", leer_chat),
        Route("/v1/trazas/{trace_id}", traza),
        Route("/health", salud),
        Route("/metrics", metrics),
    ])
    app.state.settings = settings
    app.state.llm = crear_llm(settings)
    app.state.revisiones, app.state.candado = OrderedDict(), threading.Lock()
    app.state.limite = LimiteTasa(settings.limite_por_minuto)
    app.state.repo = Repositorio(config.DB_PATH)
    app.state.chat = Chat(settings, app.state.llm, app.state.repo, Router(settings.router_min_score),
                          lambda s, t, c: _ejecutar_revision(app, s, t, c))
    metricas.inicializar_series(tuple(sorted(set(EXTENSIONES.values()))))
    return app
