"""python _guia/sincronizar.py  →  actualiza en _guia/guia.md los bloques de código que ya no coinciden con su archivo.

build.py falla si un bloque de la guía no es idéntico a su archivo real. Tras cambiar el código, este script reemplaza
el contenido de esos bloques por el del archivo (con la misma lógica de build.py para saber qué archivo es cada
bloque). El texto que rodea a cada bloque (teoría, salidas esperadas) se revisa a mano.
"""
from __future__ import annotations

import sys

import build

GUIA = build.AQUI / "guia.md"


def main() -> int:
    capturados: list[tuple[str, str]] = []
    original = build.bloque_codigo

    def espia(contenido, lang, fn, tag, salida=False, os_=""):
        ruta = build.RE_RUTA.fullmatch(fn.split(" ")[0])
        if ruta and (build.RAIZ / fn.split(" ")[0]).is_file():
            capturados.append((fn.split(" ")[0], contenido))
        return original(contenido, lang, fn, tag, salida, os_)

    build.bloque_codigo = espia
    fuente = build.preparar(GUIA.read_text(encoding="utf-8"))
    cuerpo = fuente[fuente.index("## Qué construirás"):]
    pasos = build.re.split(r"^## Paso (\d+) · (.+)$", cuerpo, flags=build.re.M)
    for n, t, c in zip(pasos[1::3], pasos[2::3], pasos[3::3]):
        build.paso(int(n), t, c)

    texto, cambiados, sin_ubicar = GUIA.read_text(encoding="utf-8"), [], []
    for ruta, viejo in capturados:
        real = (build.RAIZ / ruta).read_text(encoding="utf-8").rstrip("\n")
        if real == viejo.rstrip("\n"):
            continue
        bloque_viejo = "\n" + viejo.rstrip("\n") + "\n```"
        if texto.count(bloque_viejo) != 1:
            sin_ubicar.append(ruta)
            continue
        texto = texto.replace(bloque_viejo, "\n" + real + "\n```")
        cambiados.append(ruta)
    GUIA.write_text(texto, encoding="utf-8", newline="\n")
    print(f"Bloques actualizados: {len(cambiados)}")
    for r in cambiados:
        print(f"  ✓ {r}")
    for r in sin_ubicar:
        print(f"  ✗ no se pudo ubicar el bloque de {r}: actualízalo a mano")
    return 1 if sin_ubicar else 0


if __name__ == "__main__":
    sys.exit(main())
