"""python -m eval.eval_router  →  exactitud del router del chat con eval/router_oro.json (mensajes que NO están entre
los ejemplos de data/rutas.json: medir con los mismos ejemplos que usa el router daría 100 % sin significar nada)."""
from __future__ import annotations

import json
from pathlib import Path

from agente import config, embeddings
from agente.router import Router

ORO = json.loads((Path(__file__).parent / "router_oro.json").read_text(encoding="utf-8"))


def medir() -> dict:
    router = Router(config.Settings().router_min_score)
    filas = []
    for caso in ORO:
        r = router.enrutar(caso["texto"])
        filas.append({"texto": caso["texto"][:70], "esperada": caso["ruta"], "elegida": r.ruta,
                      "confianza": r.confianza, "respaldo": r.respaldo})
    por_ruta = {ruta: round(sum(f["elegida"] == ruta for f in filas if f["esperada"] == ruta)
                            / sum(f["esperada"] == ruta for f in filas), 3) for ruta in sorted({f["esperada"] for f in filas})}
    return {"embeddings": embeddings.descriptor(), "umbral": router.minimo,
            "exactitud": round(sum(f["esperada"] == f["elegida"] for f in filas) / len(filas), 3), "por_ruta": por_ruta,
            "uso_respaldo": round(sum(bool(f["respaldo"]) for f in filas) / len(filas), 3),
            "errores": [f for f in filas if f["esperada"] != f["elegida"]]}


def main() -> None:
    config.consola_segura()
    config.load_env()
    r = medir()
    print(f"Router ({r['embeddings']}, ROUTER_MIN_SCORE={r['umbral']}): exactitud {r['exactitud']} · por ruta "
          f"{r['por_ruta']} · uso del respaldo {r['uso_respaldo']}")
    for e in r["errores"]:
        print(f"  ✗ {e['texto']!r}: esperada {e['esperada']}, elegida {e['elegida']} ({e['confianza']}, {e['respaldo'] or '-'})")


if __name__ == "__main__":
    main()
