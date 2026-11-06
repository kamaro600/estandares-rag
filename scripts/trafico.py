"""python -m scripts.trafico [--url http://localhost:8000] [-n 20]  →  revisiones de prueba para Grafana."""
from __future__ import annotations

import argparse
import json
import random
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).parent.parent
CASOS = [("web", "nueva", "ejemplos/web"), ("escritorio", "legada", "ejemplos/escritorio"),
         ("web", "nueva", "ejemplos/bd/ventas_nueva.sql"), ("escritorio", "legada", "ejemplos/bd/escritorio_legada.sql")]


def archivos(ruta: str) -> list[dict]:
    p = RAIZ / ruta
    lista = sorted(x for x in p.rglob("*") if x.is_file()) if p.is_dir() else [p]
    return [{"nombre": x.relative_to(RAIZ).as_posix(), "contenido": x.read_text(encoding="utf-8")} for x in lista]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("-n", type=int, default=20)
    a = ap.parse_args()
    rng = random.Random(7)
    for i in range(a.n):
        tipo, bd, ruta = rng.choice(CASOS)
        cuerpo = json.dumps({"tipo_app": tipo, "modo_bd": bd, "archivos": archivos(ruta)}).encode("utf-8")
        req = urllib.request.Request(a.url + "/v1/revisiones", data=cuerpo, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.load(r)
        print(f"{i + 1:>3} {ruta:<38} {d['veredicto_inicial']:<8} hallazgos={d['totales']['hallazgos']}")


if __name__ == "__main__":
    main()
