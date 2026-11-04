"""python -m eval.eval_rag  →  hit@1, hit@4, MRR y la separación de scores para calibrar RAG_MIN_SCORE."""
from __future__ import annotations

import json
from pathlib import Path

from agente import config, rag

ORO = json.loads((Path(__file__).parent / "rag_oro.json").read_text(encoding="utf-8"))


def main() -> None:
    config.consola_segura()
    config.load_env()   # EMBEDDINGS_PROVIDER y la clave salen de .env, igual que en la ingesta
    hit1 = hit4 = mrr = 0.0
    mejores_buenas = []
    for caso in ORO["con_respuesta"]:
        res = rag.buscar(caso["pregunta"], k=4, min_score=0.0)
        ids = [r.regla.id for r in res]
        mejores_buenas.append(res[0].score)
        if caso["esperado"] in ids:
            pos = ids.index(caso["esperado"]) + 1
            hit4 += 1
            hit1 += pos == 1
            mrr += 1 / pos
        print(f"{'OK ' if caso['esperado'] in ids else 'NO '} {caso['esperado']:<12} -> {ids}")
    mejores_malas = [rag.buscar(q, k=1, min_score=0.0)[0].score for q in ORO["sin_respuesta"]]
    n = len(ORO["con_respuesta"])
    print(f"\nhit@1 = {hit1 / n:.2f}   hit@4 = {hit4 / n:.2f}   MRR = {mrr / n:.2f}")
    print(f"Mejor score, preguntas con respuesta: mín {min(mejores_buenas):.3f}")
    print(f"Mejor score, preguntas sin respuesta: máx {max(mejores_malas):.3f}")


if __name__ == "__main__":
    main()
