"""La API y la página del chat.

    GET  /                               chat (web/chat.html)
    POST /api/chat                       mensaje → respuesta (RAG), reporte (agente) o derivación
    GET  /api/chat/{id}                  mensajes de una conversación (para retomarla al recargar)
    GET  /api/reportes/{id}              reporte de validación (JSON)
    POST /api/reportes/{id}/revision     decisión humana: confirmar o descartar cada hallazgo (una sola vez)
    GET  /api/trazas/{trace_id}          pasos del flujo de un mensaje
    GET  /api/documentos                 estándares indexados (código, versión, reglas por documento)
    GET  /health · GET /metrics

La API aplica a sí misma lo que exigen los estándares: errores con Problem Details sin trazas (API-RES-002),
cabeceras de seguridad (SEG-CFG-001), límite de tasa con 429 y Retry-After (API-SEG-003) y contratos de entrada que
rechazan campos desconocidos (API-SEG-004).
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import metricas
from app.agente import AgenteValidador
from app.chat import Chat, YaRevisado
from app.config import WEB_DIR, Settings
from app.db import NoExiste, Repositorio
from app.embeddings import crear_embedder
from app.llm import crear_llm
from app.modelos import MensajeChat, Revision
from app.rag import RAG
from app.router import crear_router
from app.traza import Trazador

CABECERAS = {
    # Google Fonts (tipografía Rubik) es el único origen externo permitido; si no carga, se usa la fuente del sistema
    "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                               "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
                               "img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Cache-Control": "no-store",
}


@dataclass
class Servicios:
    settings: Settings
    chat: Chat
    rag: RAG
    repo: Repositorio


def construir_servicios(settings: Settings | None = None) -> Servicios:
    settings = settings or Settings()
    settings.validar()
    embedder = crear_embedder(settings)
    rag = RAG(settings.indice_path, embedder, settings.rag_min_score, settings.rag_top_k)
    repo = Repositorio(settings.db_path)
    trazador = Trazador(repo, settings.trazas_path)
    llm = crear_llm(settings)
    chat = Chat(settings, rag, llm, crear_router(settings, embedder), AgenteValidador(rag, llm, trazador), repo, trazador)
    return Servicios(settings, chat, rag, repo)


class LimiteTasa:
    """Ventana deslizante en memoria por IP. Suficiente para un solo proceso; con varias réplicas iría en Redis."""

    def __init__(self, por_minuto: int):
        self.por_minuto, self.eventos = por_minuto, defaultdict(deque)

    def permitir(self, clave: str) -> int:
        """0 si se permite; si no, segundos a esperar."""
        ahora, cola = time.monotonic(), self.eventos[clave]
        while cola and ahora - cola[0] > 60:
            cola.popleft()
        if len(cola) >= self.por_minuto:
            return int(60 - (ahora - cola[0])) + 1
        cola.append(ahora)
        return 0


def problema(status: int, titulo: str, detalle: str, request: Request, headers: dict | None = None) -> JSONResponse:
    """Error en formato Problem Details (RFC 9457), sin trazas de pila ni detalles internos."""
    cuerpo = {"type": "about:blank", "title": titulo, "status": status, "detail": detalle, "instance": request.url.path}
    return JSONResponse(cuerpo, status_code=status, media_type="application/problem+json", headers=headers)


def create_app(servicios: Servicios | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.s = servicios or construir_servicios()
        app.state.limite = LimiteTasa(app.state.s.settings.limite_por_minuto)
        metricas.inicializar_series()
        metricas.REPORTES_PENDIENTES.set(app.state.s.repo.contar_pendientes())
        yield

    app = FastAPI(title="Chat de estándares de desarrollo", lifespan=lifespan)

    @app.middleware("http")
    async def seguridad(request: Request, call_next):
        respuesta = await call_next(request)
        respuesta.headers.update(CABECERAS)
        return respuesta

    @app.exception_handler(StarletteHTTPException)       # cubre también los errores internos de FastAPI/Starlette
    async def http_error(request: Request, e: StarletteHTTPException):
        return problema(e.status_code, {400: "Solicitud inválida", 404: "No encontrado", 405: "Método no permitido",
                                        409: "Conflicto", 422: "Regla de negocio incumplida"}.get(e.status_code, "Error"),
                        str(e.detail), request)

    @app.exception_handler(RequestValidationError)
    async def validacion(request: Request, e: RequestValidationError):
        errores = [{"campo": ".".join(map(str, x["loc"][1:])), "mensaje": x["msg"]} for x in e.errors()]
        return JSONResponse({"type": "about:blank", "title": "Solicitud inválida", "status": 400,
                             "detail": "La solicitud no cumple el contrato", "errors": errores,
                             "instance": request.url.path}, status_code=400, media_type="application/problem+json")

    @app.exception_handler(Exception)
    async def no_controlado(request: Request, e: Exception):
        logging.getLogger("estandares").exception("Error no controlado en %s", request.url.path)
        return problema(500, "Error interno", "Ocurrió un error inesperado. Revisa los logs del servidor.", request)

    def svc(request: Request) -> Servicios:
        return request.app.state.s

    @app.get("/", include_in_schema=False)
    def pagina():
        return FileResponse(WEB_DIR / "chat.html")

    @app.get("/health")
    def health(s: Servicios = Depends(svc)):
        return {"status": "ok", "llm": s.settings.llm_provider, "embedder": s.rag.embedder.nombre, "dim": s.rag.dim,
                "fragmentos": len(s.rag.fragmentos), "min_score": s.rag.min_score,
                "reportes_pendientes": s.repo.contar_pendientes()}

    @app.get("/metrics", include_in_schema=False)
    def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/api/chat")
    def chat(m: MensajeChat, request: Request, s: Servicios = Depends(svc)):
        espera = request.app.state.limite.permitir(request.client.host if request.client else "?")
        if espera:
            metricas.LIMITE_TASA.inc()
            return problema(429, "Demasiadas solicitudes", f"Límite de {s.settings.limite_por_minuto} mensajes por "
                            "minuto", request, headers={"Retry-After": str(espera)})
        try:
            return s.chat.enviar(m.conversacion_id, m.mensaje, m.categorias)
        except NoExiste:
            raise HTTPException(404, f"No existe la conversación {m.conversacion_id}") from None

    @app.get("/api/chat/{id_}")
    def leer_chat(id_: int, s: Servicios = Depends(svc)):
        if not s.repo.existe_conversacion(id_):
            raise HTTPException(404, f"No existe la conversación {id_}")
        return {"conversacion_id": id_, "mensajes": s.repo.mensajes(id_)}

    @app.get("/api/reportes/{id_}")
    def reporte(id_: int, s: Servicios = Depends(svc)):
        try:
            r = s.repo.reporte(id_)
        except NoExiste:
            raise HTTPException(404, f"No existe el reporte {id_}") from None
        return {"id": r["id"], "conversacion_id": r["conversacion_id"], "trace_id": r["trace_id"],
                "estado": r["estado"], "revision": r["revision"], **{"resultado": r["datos"]}}

    @app.post("/api/reportes/{id_}/revision")
    def revisar(id_: int, revision: Revision, s: Servicios = Depends(svc)):
        try:
            return s.chat.revisar(id_, revision)
        except NoExiste:
            raise HTTPException(404, f"No existe el reporte {id_}") from None
        except YaRevisado as e:
            raise HTTPException(409, str(e)) from None
        except ValueError as e:
            raise HTTPException(422, str(e)) from None

    @app.get("/api/trazas/{trace_id}")
    def trazas(trace_id: str, s: Servicios = Depends(svc)):
        pasos = s.repo.trazas(trace_id)
        if not pasos:
            raise HTTPException(404, f"No hay trazas para {trace_id}")
        return {"trace_id": trace_id, "pasos": pasos}

    @app.get("/api/documentos")
    def documentos(s: Servicios = Depends(svc)):
        docs: dict[str, dict] = {}
        for f in s.rag.fragmentos:
            d = docs.setdefault(f.doc_codigo, {"codigo": f.doc_codigo, "titulo": f.doc_titulo, "version": f.doc_version,
                                               "fecha": f.doc_fecha, "categoria": f.categoria, "reglas": 0,
                                               "secciones": 0})
            d["reglas" if f.tipo == "regla" else "secciones"] += 1
        return sorted(docs.values(), key=lambda d: d["codigo"])

    return app


app = create_app()
