"""python -m agente.ingesta  →  data/catalogo.json + data/indice.npz"""
from __future__ import annotations

from collections import Counter

import numpy as np

from agente import catalogo, config, embeddings


def texto_indexable(r: catalogo.Regla) -> str:
    return f"{r.id} {r.titulo}\n{r.texto}\n{' '.join(r.referencias)}"


def main() -> None:
    config.consola_segura()
    config.load_env()
    reglas = catalogo.construir_catalogo()
    catalogo.guardar(reglas)
    matriz = embeddings.vectorizar([texto_indexable(r) for r in reglas])
    np.savez(config.INDICE_PATH, ids=np.array([r.id for r in reglas]), vectores=matriz,
             descriptor=np.array(embeddings.descriptor()))
    print(f"Reglas extraídas: {len(reglas)}")
    for doc, n in sorted(Counter(r.documento for r in reglas).items()):
        print(f"  {doc}: {n}")
    print(f"Catálogo → {config.CATALOGO_PATH.relative_to(config.BASE_DIR).as_posix()}")
    print(f"Índice   → {config.INDICE_PATH.relative_to(config.BASE_DIR).as_posix()} {matriz.shape} "
          f"({embeddings.descriptor()})")


if __name__ == "__main__":
    main()
