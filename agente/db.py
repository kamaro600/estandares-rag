"""Persistencia del chat con SQLite (librería estándar): conversaciones, mensajes y trazas.

Todo el SQL vive aquí y es parametrizado (?), nunca concatenado (SEG-INY-001). sqlite3 es síncrono y la API atiende
en varios hilos: una conexión protegida con un candado. Las revisiones del agente siguen en memoria (la aprobación
llega en la misma sesión); el chat guarda su resumen en el mensaje, así que la conversación sobrevive a un reinicio.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

ESQUEMA = """
CREATE TABLE IF NOT EXISTS conversaciones (id INTEGER PRIMARY KEY AUTOINCREMENT, creada REAL NOT NULL);
CREATE TABLE IF NOT EXISTS mensajes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, conversacion_id INTEGER NOT NULL REFERENCES conversaciones(id),
    creado REAL NOT NULL, rol TEXT NOT NULL, texto TEXT NOT NULL, meta TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS trazas (
    trace_id TEXT PRIMARY KEY, conversacion_id INTEGER, creada REAL NOT NULL, eventos TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_mensajes ON mensajes(conversacion_id, id);
"""


class NoExiste(LookupError):
    """La conversación pedida no existe (la API responde 404)."""
    pass


class Repositorio:
    """Conversaciones, mensajes (con su meta en JSON) y trazas en SQLite. Todo el SQL es parametrizado."""
    def __init__(self, ruta: Path | str):
        if str(ruta) != ":memory:":
            Path(ruta).parent.mkdir(parents=True, exist_ok=True)
        self.cx = sqlite3.connect(str(ruta), check_same_thread=False)
        self.cx.row_factory = sqlite3.Row
        self.candado = threading.Lock()
        with self.candado:
            self.cx.executescript(ESQUEMA)

    def crear_conversacion(self) -> int:
        with self.candado, self.cx:
            return int(self.cx.execute("INSERT INTO conversaciones (creada) VALUES (?)", (time.time(),)).lastrowid)

    def existe(self, conversacion_id: int) -> bool:
        with self.candado:
            return self.cx.execute("SELECT 1 FROM conversaciones WHERE id = ?", (conversacion_id,)).fetchone() is not None

    def agregar(self, conversacion_id: int, rol: str, texto: str, meta: dict | None = None) -> dict:
        with self.candado, self.cx:
            cur = self.cx.execute("INSERT INTO mensajes (conversacion_id, creado, rol, texto, meta) VALUES (?,?,?,?,?)",
                                  (conversacion_id, time.time(), rol, texto, json.dumps(meta or {}, ensure_ascii=False)))
            fila = self.cx.execute("SELECT * FROM mensajes WHERE id = ?", (cur.lastrowid,)).fetchone()
        return {**dict(fila), "meta": json.loads(fila["meta"])}

    def mensajes(self, conversacion_id: int) -> list[dict]:
        with self.candado:
            filas = self.cx.execute("SELECT * FROM mensajes WHERE conversacion_id = ? ORDER BY id",
                                    (conversacion_id,)).fetchall()
        return [{**dict(f), "meta": json.loads(f["meta"])} for f in filas]

    def guardar_traza(self, trace_id: str, conversacion_id: int | None, eventos: list[dict]) -> None:
        with self.candado, self.cx:
            self.cx.execute("INSERT OR REPLACE INTO trazas (trace_id, conversacion_id, creada, eventos) VALUES (?,?,?,?)",
                            (trace_id, conversacion_id, time.time(), json.dumps(eventos, ensure_ascii=False)))

    def traza(self, trace_id: str) -> dict:
        with self.candado:
            fila = self.cx.execute("SELECT * FROM trazas WHERE trace_id = ?", (trace_id,)).fetchone()
        if fila is None:
            raise NoExiste(trace_id)
        return {"trace_id": fila["trace_id"], "conversacion_id": fila["conversacion_id"],
                "eventos": json.loads(fila["eventos"])}
