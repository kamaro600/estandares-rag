"""Evaluación medida, no supuesta (C7). Tres partes, cada una con su set de oro:

  1. Recuperación (RAG)  eval/gold.json         hit@1, hit@k, MRR, abstención y CALIBRACIÓN del umbral
  2. Router              eval/router_gold.json  exactitud por ruta y uso del respaldo
  3. Agente validador    eval/casos/            precisión, exhaustividad (recall) y F1 de las reglas reportadas

Uso:   python -m eval.evaluar               (usa el embedder de .env; el índice debe ser de ese embedder)
       python -m eval.evaluar --con-llm     la parte 3 corre el agente completo (gasta tokens si LLM_PROVIDER=openai)

Resultado en consola y en eval/resultados.json. El umbral se calibra sobre el MISMO set con que se mide: el número
es optimista (como advierte el informe del lab 04). Para una medición honesta, separar un set de validación.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from app import detector_codigo, verificadores
from app.config import Settings
from app.embeddings import crear_embedder
from app.rag import RAG
from app.router import crear_router

EVAL = Path(__file__).resolve().parent
UMBRALES = [round(0.05 * i, 2) for i in range(0, 15)]


def evaluar_rag(rag: RAG, k: int) -> dict:
    gold = json.loads((EVAL / "gold.json").read_text(encoding="utf-8"))
    respondibles = []
    for g in gold["respondibles"]:
        res = rag.buscar(g["q"], k=k, min_score=-1)                   # ranking completo; el umbral se aplica después
        pos = next((i for i, f in enumerate(res, 1) if f.id in g["esperados"]), None)
        respondibles.append({"q": g["q"], "pos": pos, "score_acierto": res[pos - 1].score if pos else None,
                             "score_top": res[0].score if res else 0.0, "top": [f.id for f in res[:3]]})
    no_resp = [{"q": g["q"], "score_top": (rag.buscar(g["q"], k=1, min_score=-1) or [None])[0].score}
               for g in gold["no_respondibles"]]

    def medir(u: float) -> dict:
        n = len(respondibles)
        hit1 = sum(1 for r in respondibles if r["pos"] == 1 and r["score_acierto"] >= u) / n
        hitk = sum(1 for r in respondibles if r["pos"] and r["score_acierto"] >= u) / n
        mrr = sum(1 / r["pos"] for r in respondibles if r["pos"] and r["score_acierto"] >= u) / n
        abst = sum(1 for r in no_resp if r["score_top"] < u) / len(no_resp)
        falsa = sum(1 for r in respondibles if r["score_top"] < u) / n          # se abstuvo teniendo respuesta
        # exactitud global: respondibles con la regla correcta sobre el umbral + no respondibles abstenidas, sobre
        # el total. A igual exactitud se prefiere el umbral MÁS ALTO (menos riesgo de responder sin evidencia).
        correctas = hitk * n + abst * len(no_resp)
        return {"umbral": u, "hit@1": round(hit1, 3), f"hit@{k}": round(hitk, 3), "mrr": round(mrr, 3),
                "abstencion": round(abst, 3), "abstencion_falsa": round(falsa, 3),
                "exactitud": round(correctas / (n + len(no_resp)), 3)}

    tabla = [medir(u) for u in UMBRALES]
    # Varios umbrales consecutivos suelen empatar en la mejor exactitud (una "meseta"). Se recomienda el CENTRO de la
    # meseta: deja margen hacia ambos lados (preguntas ajenas que suben un poco, respuestas válidas que bajan un poco).
    tope = max(t["exactitud"] for t in tabla)
    inicio = next(i for i, t in enumerate(tabla) if t["exactitud"] == tope)
    fin = inicio
    while fin + 1 < len(tabla) and tabla[fin + 1]["exactitud"] == tope:
        fin += 1
    mejor = medir(round((tabla[inicio]["umbral"] + tabla[fin]["umbral"]) / 2, 3))
    mejor["meseta"] = [tabla[inicio]["umbral"], tabla[fin]["umbral"]]
    actual = medir(rag.min_score)
    return {"k": k, "umbral_actual": actual, "recomendado": mejor, "tabla": tabla,
            "fallos": [r for r in respondibles if not r["pos"] or r["score_acierto"] < rag.min_score],
            "no_respondibles": no_resp}


def evaluar_router(router) -> dict:
    gold = json.loads((EVAL / "router_gold.json").read_text(encoding="utf-8"))
    filas = []
    for g in gold:
        r = router.enrutar(g["texto"])
        filas.append({"texto": g["texto"][:70], "esperada": g["ruta"], "elegida": r.ruta,
                      "confianza": r.confianza, "respaldo": r.respaldo})
    por_ruta = {}
    for ruta in sorted({f["esperada"] for f in filas}):
        sub = [f for f in filas if f["esperada"] == ruta]
        por_ruta[ruta] = round(sum(f["elegida"] == ruta for f in sub) / len(sub), 3)
    return {"exactitud": round(sum(f["esperada"] == f["elegida"] for f in filas) / len(filas), 3),
            "por_ruta": por_ruta, "uso_respaldo": round(sum(bool(f["respaldo"]) for f in filas) / len(filas), 3),
            "errores": [f for f in filas if f["esperada"] != f["elegida"]]}


def evaluar_agente(agente=None) -> dict:
    esperados = json.loads((EVAL / "casos" / "esperados.json").read_text(encoding="utf-8"))["casos"]
    vp = fp = fn = 0
    casos = []
    for archivo, ids in esperados.items():
        codigo = (EVAL / "casos" / archivo).read_text(encoding="utf-8")
        leng = detector_codigo.lenguaje(codigo)
        if agente:
            from app.modelos import SolicitudValidacion
            hallazgos = agente.validar(SolicitudValidacion(codigo=codigo, lenguaje=leng, trace_id=f"eval-{archivo}")).hallazgos
        else:
            hallazgos = verificadores.verificar(codigo, leng)
        obtenidos, esperado = {h.regla_id for h in hallazgos}, set(ids)
        vp += len(obtenidos & esperado)
        fp += len(obtenidos - esperado)
        fn += len(esperado - obtenidos)
        casos.append({"caso": archivo, "lenguaje": leng, "faltan": sorted(esperado - obtenidos),
                      "sobran": sorted(obtenidos - esperado)})
    precision = vp / (vp + fp) if vp + fp else 1.0
    recall = vp / (vp + fn) if vp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3),
            "verdaderos_positivos": vp, "falsos_positivos": fp, "falsos_negativos": fn, "casos": casos}


def main(argv: list[str]) -> None:
    s = Settings()
    embedder = crear_embedder(s)
    rag = RAG(s.indice_path, embedder, s.rag_min_score, s.rag_top_k)
    print(f"Embedder: {embedder.nombre} · umbral actual RAG_MIN_SCORE={s.rag_min_score} · top_k={s.rag_top_k}\n")

    r = evaluar_rag(rag, s.rag_top_k)
    k = r["k"]
    print("1) RECUPERACIÓN (eval/gold.json)")
    print(f"   {'umbral':>6} {'hit@1':>6} {'hit@' + str(k):>6} {'MRR':>6} {'abst.':>6} {'abst.falsa':>10} {'exactitud':>9}")
    lo, hi = r["recomendado"]["meseta"]
    for t in r["tabla"]:
        marca = " ← mejor exactitud" if lo <= t["umbral"] <= hi else ""
        print(f"   {t['umbral']:>6} {t['hit@1']:>6} {t[f'hit@{k}']:>6} {t['mrr']:>6} {t['abstencion']:>6} "
              f"{t['abstencion_falsa']:>10} {t['exactitud']:>9}{marca}")
    a = r["umbral_actual"]
    print(f"   Con el umbral actual ({s.rag_min_score}): hit@1 {a['hit@1']} · hit@{k} {a[f'hit@{k}']} · MRR {a['mrr']} · "
          f"abstención {a['abstencion']}")
    for f in r["fallos"][:8]:
        print(f"   ✗ {f['q'][:70]}  → top: {f['top']}")

    ro = evaluar_router(crear_router(s, embedder))
    print(f"\n2) ROUTER (eval/router_gold.json): exactitud {ro['exactitud']} · por ruta {ro['por_ruta']} · "
          f"uso del respaldo {ro['uso_respaldo']}")
    for e in ro["errores"]:
        print(f"   ✗ {e['texto']!r}: esperada {e['esperada']}, elegida {e['elegida']} ({e['confianza']}, {e['respaldo'] or '-'})")

    agente = None
    if "--con-llm" in argv:
        from app.agente import AgenteValidador
        from app.db import Repositorio
        from app.llm import crear_llm
        from app.traza import Trazador
        agente = AgenteValidador(rag, crear_llm(s), Trazador(Repositorio(":memory:")))
    ag = evaluar_agente(agente)
    print(f"\n3) AGENTE VALIDADOR (eval/casos, {'agente completo' if agente else 'verificadores deterministas'}): "
          f"precisión {ag['precision']} · recall {ag['recall']} · F1 {ag['f1']}")
    for c in ag["casos"]:
        if c["faltan"] or c["sobran"]:
            print(f"   ✗ {c['caso']}: faltan {c['faltan']} · sobran {c['sobran']}")

    salida = {"fecha": time.strftime("%Y-%m-%d %H:%M:%S"), "embedder": embedder.nombre, "rag": r, "router": ro,
              "agente": ag}
    (EVAL / "resultados.json").write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nDetalle: eval/resultados.json · umbral recomendado para {embedder.nombre}: "
          f"RAG_MIN_SCORE={r['recomendado']['umbral']} (centro de la meseta {lo}–{hi})")


if __name__ == "__main__":
    main(sys.argv[1:])
