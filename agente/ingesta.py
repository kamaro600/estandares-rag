"""python -m agente.ingesta  →  data/catalogo.json + data/secciones.json + data/indice.npz

    python -m agente.ingesta              re-indexa siempre
    python -m agente.ingesta --si-falta   solo si no hay índice, cambió el proveedor de embeddings o cambió un PDF
                                          (lo usa el contenedor al arrancar: indexa con las claves del .env)

El índice guarda, junto a los vectores, QUÉ los produjo (descriptor y dimensión) y la huella SHA-256 de cada PDF:
así la API se niega a arrancar con un índice que no corresponde a los embeddings o a los PDF actuales.
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter

import numpy as np

from agente import catalogo, config, embeddings


def texto_indexable(r: catalogo.Regla) -> str:
    return f"{r.id} {r.titulo}\n{r.texto}\n{' '.join(r.referencias)}"


def huellas() -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in catalogo.pdfs()}


def vigente() -> tuple[bool, str]:
    """¿El índice actual sirve? (no hay que re-indexar) y, si no, por qué."""
    if not config.INDICE_PATH.exists() or not config.CATALOGO_PATH.exists():
        return False, "no existe el índice"
    with np.load(config.INDICE_PATH) as datos:
        if str(datos["descriptor"]) != embeddings.descriptor():
            return False, f"el índice es de {datos['descriptor']} y los embeddings actuales son {embeddings.descriptor()}"
        if "huellas" not in datos.files or json.loads(str(datos["huellas"])) != huellas():
            return False, "cambiaron los PDF de data/estandares"
    return True, "vigente"


def main(argv: list[str] | None = None) -> None:
    """PDF → catálogo, secciones e índice. Con --si-falta no hace nada si el índice coincide con el embedder y los PDF."""
    config.consola_segura()
    config.load_env()
    if "--si-falta" in (argv or []):
        ok, motivo = vigente()
        if ok:
            print(f"Índice vigente ({embeddings.descriptor()}): no se re-indexa.")
            return
        print(f"Re-indexando: {motivo}")
    reglas, secciones, descartados = catalogo.construir()
    catalogo.guardar(reglas)
    catalogo.guardar(secciones, config.SECCIONES_PATH)
    todo = reglas + secciones
    matriz = embeddings.vectorizar([texto_indexable(r) for r in todo])
    np.savez(config.INDICE_PATH, ids=np.array([r.id for r in todo]), vectores=matriz,
             descriptor=np.array(embeddings.descriptor()), dim=np.array(matriz.shape[1]),
             huellas=np.array(json.dumps(huellas())))
    print(f"Reglas extraídas: {len(reglas)} · secciones generales: {len(secciones)}")
    for doc, n in sorted(Counter(r.documento for r in reglas).items()):
        print(f"  {doc}: {n}")
    for d in descartados:
        print(f"  ✗ descartado por posible prompt injection: {d}")
    print(f"Catálogo → {config.CATALOGO_PATH.name} · secciones → {config.SECCIONES_PATH.name}")
    print(f"Índice   → {config.INDICE_PATH.name} {matriz.shape} ({embeddings.descriptor()})")


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except (ValueError, FileNotFoundError, RuntimeError) as e:   # mensaje claro, sin traza de Python
        sys.exit(f"Error: {e}")
