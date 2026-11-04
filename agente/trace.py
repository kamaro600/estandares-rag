"""Traza auditable: un evento JSON por línea, con contadores de llamadas y tokens."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from agente import config


class Tracer:
    def __init__(self, destino: Path | None = None, consola: bool = False):
        self.eventos: list[dict] = []
        self.llamadas_llm = 0
        self.tokens_entrada = 0
        self.tokens_salida = 0
        self.consola = consola
        self.inicio = time.perf_counter()
        sello = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")  # sin ':' (no válido en Windows)
        self.ruta = destino or config.SALIDA_DIR / "trazas" / f"revision-{sello}.jsonl"

    def evento(self, tipo: str, **datos) -> None:
        e = {"t": round(time.perf_counter() - self.inicio, 3), "tipo": tipo, **datos}
        self.eventos.append(e)
        if self.consola:
            resumen = " ".join(f"{k}={v}" for k, v in datos.items() if not isinstance(v, (list, dict)))
            print(f"  [{tipo}] {resumen[:150]}")

    def llm(self, rol: str, tokens_entrada: int, tokens_salida: int) -> None:
        self.llamadas_llm += 1
        self.tokens_entrada += tokens_entrada
        self.tokens_salida += tokens_salida
        self.evento("llm", rol=rol, tokens_entrada=tokens_entrada, tokens_salida=tokens_salida)

    def guardar(self) -> Path:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        with open(self.ruta, "w", encoding="utf-8", newline="\n") as f:
            for e in self.eventos:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        return self.ruta
