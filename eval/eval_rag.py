"""python -m eval.eval_rag  →  hit@1, hit@k, MRR, abstención y el umbral RAG_MIN_SCORE recomendado.

Mide la búsqueda que usa el chat (reglas + secciones generales) con eval/rag_oro.json:
  con_respuesta  la regla esperada (o una alternativa válida) debe estar entre las k primeras y sobre el umbral
  sin_respuesta  ninguna regla debe superar el umbral (el chat responde "no está en los estándares" sin el modelo)

Recomendación: varios umbrales seguidos suelen empatar en la mejor exactitud (una "meseta"); se recomienda su
CENTRO, que deja margen hacia ambos lados. El resultado es optimista: se calibra sobre el mismo conjunto con que se
mide. Para una medición honesta, separar un conjunto de validación con preguntas reales.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from agente import config, embeddings, rag

ORO = json.loads((Path(__file__).parent / "rag_oro.json").read_text(encoding="utf-8"))
UMBRALES = [round(0.02 * i, 2) for i in range(0, 36)]   # 0.00 … 0.70


def medir(k: int = 5) -> dict:
    respondibles = []
    for caso in ORO["con_respuesta"]:
        validos = {caso["esperado"], *caso.get("alternativos", [])}
        res = [r for r in rag.buscar(caso["pregunta"], k=k, min_score=-1, incluir_secciones=True)   # ranking completo
               if r.via != "relacion"]   # se mide la similitud; los complementos por conflicto no cuentan como acierto
        pos = next((i for i, r in enumerate(res, 1) if r.regla.id in validos), None)
        respondibles.append({"pregunta": caso["pregunta"], "esperado": caso["esperado"], "pos": pos,
                             "score": res[pos - 1].score if pos else None, "top": [r.regla.id for r in res[:3]],
                             "mejor": res[0].score if res else 0.0})
    ajenas = [{"pregunta": q, "mejor": rag.buscar(q, k=1, min_score=-1, incluir_secciones=True)[0].score}
              for q in ORO["sin_respuesta"]]

    def con_umbral(u: float) -> dict:
        n = len(respondibles)
        acierto = [r for r in respondibles if r["pos"] and r["score"] >= u]
        abst = sum(a["mejor"] < u for a in ajenas) / len(ajenas)
        return {"umbral": u, "hit@1": round(sum(r["pos"] == 1 for r in acierto) / n, 3),
                f"hit@{k}": round(len(acierto) / n, 3), "mrr": round(sum(1 / r["pos"] for r in acierto) / n, 3),
                "abstencion": round(abst, 3),
                "abstencion_falsa": round(sum(r["mejor"] < u for r in respondibles) / n, 3),
                "exactitud": round((len(acierto) + abst * len(ajenas)) / (n + len(ajenas)), 3)}

    tabla = [con_umbral(u) for u in UMBRALES]
    tope = max(t["exactitud"] for t in tabla)
    inicio = next(i for i, t in enumerate(tabla) if t["exactitud"] == tope)
    fin = inicio
    while fin + 1 < len(tabla) and tabla[fin + 1]["exactitud"] == tope:
        fin += 1
    recomendado = round((tabla[inicio]["umbral"] + tabla[fin]["umbral"]) / 2, 3)
    actual = config.Settings().rag_min_score
    return {"embeddings": embeddings.descriptor(), "k": k, "umbral_actual": con_umbral(actual),
            "recomendado": con_umbral(recomendado) | {"meseta": [tabla[inicio]["umbral"], tabla[fin]["umbral"]]},
            "tabla": tabla, "fallos": [r for r in respondibles if not r["pos"] or r["score"] < actual],
            "ajenas": ajenas}


def main() -> None:
    config.consola_segura()
    config.load_env()   # EMBEDDINGS_PROVIDER y la clave salen de .env, igual que en la ingesta
    r = medir()
    k, a, rec = r["k"], r["umbral_actual"], r["recomendado"]
    print(f"Embeddings {r['embeddings']} · {len(ORO['con_respuesta'])} preguntas con respuesta, "
          f"{len(ORO['sin_respuesta'])} sin respuesta\n")
    print(f"{'umbral':>7} {'hit@1':>6} {'hit@' + str(k):>6} {'MRR':>6} {'abst.':>6} {'abst.falsa':>10} {'exactitud':>9}")
    for t in r["tabla"]:
        if t["exactitud"] < 0.5 and t["umbral"] > rec["meseta"][1]:
            break
        marca = "  ← mejor" if rec["meseta"][0] <= t["umbral"] <= rec["meseta"][1] else ""
        print(f"{t['umbral']:>7} {t['hit@1']:>6} {t[f'hit@{k}']:>6} {t['mrr']:>6} {t['abstencion']:>6} "
              f"{t['abstencion_falsa']:>10} {t['exactitud']:>9}{marca}")
    print(f"\nUmbral actual RAG_MIN_SCORE={a['umbral']}: hit@1 {a['hit@1']} · hit@{k} {a[f'hit@{k}']} · MRR {a['mrr']} · "
          f"abstención {a['abstencion']} · exactitud {a['exactitud']}")
    print(f"Recomendado RAG_MIN_SCORE={rec['umbral']} (centro de la meseta {rec['meseta'][0]}–{rec['meseta'][1]})")
    for f in r["fallos"][:10]:
        print(f"  ✗ {f['pregunta'][:70]}  esperado {f['esperado']} → top {f['top']}")
    destino = config.SALIDA_DIR / "eval_rag.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print(f"Detalle → {destino.name}")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, FileNotFoundError) as e:
        sys.exit(f"Error: {e}")
