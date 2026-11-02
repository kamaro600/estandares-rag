"""Persistencia con SQLite (módulo sqlite3 de la librería estándar). TODO el SQL vive aquí y es parametrizado (?).

Tablas: conversaciones, mensajes (rol = usuario | asistente | sistema), reportes (resultado del agente validador +
revisión humana) y trazas (pasos de cada turno, por trace_id).
`sqlite3` es síncrono; FastAPI ejecuta los endpoints `def` en varios hilos: una conexión protegida con un Lock.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

ESQUEMA = """
CREATE TABLE IF NOT EXISTS conversaciones (id INTEGER PRIMARY KEY AUTOINCREMENT, creada_en REAL NOT NULL);
CREATE TABLE IF NOT EXISTS mensajes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, conversacion_id INTEGER NOT NULL REFERENCES conversaciones(id),
    creado_en REAL NOT NULL, rol TEXT NOT NULL, texto TEXT NOT NULL, meta TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reportes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, conversacion_id INTEGER NOT NULL REFERENCES conversaciones(id),
    trace_id TEXT NOT NULL, creado_en REAL NOT NULL, estado TEXT NOT NULL, datos TEXT NOT NULL,
    revision TEXT);
CREATE TABLE IF NOT EXISTS trazas (
    id INTEGER PRIMARY KEY AUTOINCREMENT, trace_id TEXT NOT NULL, conversacion_id INTEGER, ts REAL NOT NULL,
    paso TEXT NOT NULL, datos TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_mensajes ON mensajes(conversacion_id, id);
CREATE INDEX IF NOT EXISTS ix_trazas ON trazas(trace_id, id);
"""


class NoExiste(LookupError):
    pass


class Repositorio:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.cx = sqlite3.connect(str(path), check_same_thread=False)
        self.cx.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.cx.executescript(ESQUEMA)

    # ------------------------------------------------------------------------------------------ conversaciones
    def crear_conversacion(self) -> int:
        with self.lock, self.cx:
            return int(self.cx.execute("INSERT INTO conversaciones (creada_en) VALUES (?)", (time.time(),)).lastrowid)

    def existe_conversacion(self, id_: int) -> bool:
        with self.lock:
            return self.cx.execute("SELECT 1 FROM conversaciones WHERE id = ?", (id_,)).fetchone() is not None

    def agregar_mensaje(self, conversacion_id: int, rol: str, texto: str, meta: dict | None = None) -> dict:
        with self.lock, self.cx:
            cur = self.cx.execute("INSERT INTO mensajes (conversacion_id, creado_en, rol, texto, meta) VALUES (?,?,?,?,?)",
                                  (conversacion_id, time.time(), rol, texto, json.dumps(meta or {}, ensure_ascii=False)))
            fila = self.cx.execute("SELECT * FROM mensajes WHERE id = ?", (cur.lastrowid,)).fetchone()
        return {**dict(fila), "meta": json.loads(fila["meta"])}

    def mensajes(self, conversacion_id: int) -> list[dict]:
        with self.lock:
            filas = self.cx.execute("SELECT * FROM mensajes WHERE conversacion_id = ? ORDER BY id",
                                    (conversacion_id,)).fetchall()
        return [{**dict(f), "meta": json.loads(f["meta"])} for f in filas]

    # ------------------------------------------------------------------------------------------ reportes
    def guardar_reporte(self, conversacion_id: int, trace_id: str, datos: dict) -> int:
        with self.lock, self.cx:
            return int(self.cx.execute(
                "INSERT INTO reportes (conversacion_id, trace_id, creado_en, estado, datos) VALUES (?,?,?,?,?)",
                (conversacion_id, trace_id, time.time(), datos["estado"], json.dumps(datos, ensure_ascii=False))).lastrowid)

    def reporte(self, id_: int) -> dict:
        with self.lock:
            fila = self.cx.execute("SELECT * FROM reportes WHERE id = ?", (id_,)).fetchone()
        if fila is None:
            raise NoExiste
        return {**dict(fila), "datos": json.loads(fila["datos"]),
                "revision": json.loads(fila["revision"]) if fila["revision"] else None}

    def revisar_reporte(self, id_: int, datos: dict, revision: dict) -> bool:
        """Decisión única: solo actualiza si sigue PROPUESTO (el WHERE evita que dos revisores pisen la decisión)."""
        with self.lock, self.cx:
            cur = self.cx.execute("UPDATE reportes SET estado = 'REVISADO', datos = ?, revision = ? "
                                  "WHERE id = ? AND estado = 'PROPUESTO'",
                                  (json.dumps(datos, ensure_ascii=False), json.dumps(revision, ensure_ascii=False), id_))
            return cur.rowcount == 1

    def ultimo_reporte(self, conversacion_id: int) -> dict | None:
        with self.lock:
            fila = self.cx.execute("SELECT id FROM reportes WHERE conversacion_id = ? ORDER BY id DESC LIMIT 1",
                                   (conversacion_id,)).fetchone()
        return self.reporte(fila["id"]) if fila else None

    def contar_pendientes(self) -> int:
        with self.lock:
            return int(self.cx.execute("SELECT COUNT(*) FROM reportes WHERE estado = 'PROPUESTO'").fetchone()[0])

    # ------------------------------------------------------------------------------------------ trazas
    def registrar_traza(self, trace_id: str, conversacion_id: int | None, paso: str, datos: dict) -> None:
        with self.lock, self.cx:
            self.cx.execute("INSERT INTO trazas (trace_id, conversacion_id, ts, paso, datos) VALUES (?,?,?,?,?)",
                            (trace_id, conversacion_id, time.time(), paso, json.dumps(datos, ensure_ascii=False)))

    def trazas(self, trace_id: str) -> list[dict]:
        with self.lock:
            filas = self.cx.execute("SELECT ts, paso, datos FROM trazas WHERE trace_id = ? ORDER BY id",
                                    (trace_id,)).fetchall()
        return [{"ts": f["ts"], "paso": f["paso"], "datos": json.loads(f["datos"])} for f in filas]
