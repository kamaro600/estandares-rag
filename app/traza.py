"""Trazabilidad del flujo chat → router → RAG → agente → revisión humana (C5: "el flujo queda trazado").

Cada mensaje del usuario recibe un `trace_id`. Cada pieza registra un PASO con lo que decidió y por qué (ruta y
confianza, fragmentos recuperados y sus scores, hallazgos, tokens, duración). Se guarda en SQLite (consultable en
GET /api/trazas/{trace_id}) y en data/trazas.jsonl (una línea por paso, fácil de enviar a un SIEM o a Loki).

Qué NO se guarda en la traza: el texto del mensaje ni el código (ya están en la tabla de mensajes, con su control de
acceso). La traza es metadatos de decisión, no una copia de los datos.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from app.db import Repositorio

log = logging.getLogger("estandares.traza")


def nuevo_trace_id() -> str:
    return uuid.uuid4().hex


class Trazador:
    def __init__(self, repo: Repositorio, jsonl: Path | None = None):
        self.repo, self.jsonl = repo, jsonl
        if jsonl:
            jsonl.parent.mkdir(parents=True, exist_ok=True)

    def registrar(self, trace_id: str, paso: str, conversacion_id: int | None = None, **datos) -> None:
        self.repo.registrar_traza(trace_id, conversacion_id, paso, datos)
        if self.jsonl:
            linea = {"ts": round(time.time(), 3), "trace_id": trace_id, "conversacion_id": conversacion_id,
                     "paso": paso, **datos}
            with self.jsonl.open("a", encoding="utf-8") as f:
                f.write(json.dumps(linea, ensure_ascii=False) + "\n")
        log.info("trace=%s paso=%s %s", trace_id, paso, datos)

    @contextmanager
    def paso(self, trace_id: str, paso: str, conversacion_id: int | None = None):
        """Mide la duración del bloque y registra lo que el bloque agregue al diccionario."""
        datos: dict = {}
        t0 = time.perf_counter()
        try:
            yield datos
        finally:
            datos["ms"] = round((time.perf_counter() - t0) * 1000, 1)
            self.registrar(trace_id, paso, conversacion_id, **datos)
