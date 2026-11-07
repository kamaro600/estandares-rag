"""python -m scripts.validar_api [--url http://127.0.0.1:8000] [--con-llm]

Valida la API en marcha de punta a punta: carga de archivos de cada lenguaje, análisis, aprobación,
descarga de lo corregido y respuestas de error. Solo usa la biblioteca estándar.

Por defecto revisa SIN el modelo (rápido, sin costo y repetible). --con-llm usa el proveedor del .env
del servidor: con OpenAI o Claude cuesta tokens y el número de correcciones puede variar.
Código de salida: 0 si todo pasó, 1 si algo falló.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from agente import catalogo, config

RAIZ = Path(__file__).resolve().parent.parent
# Un ejemplo por lenguaje: (archivo, lenguaje esperado, contexto con el que debe evaluarse)
EJEMPLOS = [
    ("ejemplos/web/api/ClienteService.cs", "csharp", "web"),
    ("ejemplos/web/angular/ClientesList.ts", "typescript", "web"),
    ("ejemplos/web/angular/clientes-list.html", "html", "web"),
    ("ejemplos/web/api/appsettings.json", "config", "web"),
    ("ejemplos/web/api/Ventas.Api.csproj", "config", "web"),
    ("ejemplos/bd/ventas_nueva.sql", "tsql", "web"),
    ("ejemplos/web/razor/Comentarios.cshtml", "razor", "web"),
    ("ejemplos/web/js/sesion.js", "javascript", "web"),
    ("ejemplos/api/openapi.yaml", "yaml", "web"),
    ("ejemplos/pipeline/azure-pipelines.yml", "yaml", "web"),
    ("ejemplos/movil/android/LoginActivity.kt", "kotlin", "movil"),
    ("ejemplos/movil/android/build.gradle.kts", "kotlin", "movil"),
    ("ejemplos/movil/android/AndroidManifest.xml", "xml", "movil"),
    ("ejemplos/movil/android/network_security_config.xml", "xml", "movil"),
    ("ejemplos/movil/ios/SesionManager.swift", "swift", "movil"),
    ("ejemplos/movil/ios/Info.plist", "xml", "movil"),
]
# Escritorio en una segunda revisión: las reglas de EST-DSK-001 (XAML, base legada) solo aplican a Escritorio.
ESCRITORIO = [
    ("ejemplos/escritorio/ClienteView.xaml", "xaml", "escritorio"),
    ("ejemplos/escritorio/ClienteView.xaml.cs", "csharp", "escritorio"),
    ("ejemplos/escritorio/App.config", "config", "escritorio"),
    ("ejemplos/escritorio/Textos.resx", "xml", "escritorio"),
    ("ejemplos/bd/escritorio_legada.sql", "tsql", "escritorio"),
]

resultados: list[tuple[bool, str, str]] = []


def comprobar(ok: bool, que: str, detalle: str = "") -> bool:
    resultados.append((bool(ok), que, detalle))
    print(f"  {'OK   ' if ok else 'FALLA'}  {que}" + (f"  ({detalle})" if detalle and not ok else ""))
    return bool(ok)


def pedir(url: str, cuerpo=None, crudo: bytes | None = None, timeout: int = 300):
    datos = crudo if crudo is not None else (None if cuerpo is None else json.dumps(cuerpo).encode("utf-8"))
    req = urllib.request.Request(url, data=datos, headers={"Content-Type": "application/json"} if datos else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--con-llm", action="store_true", help="usar el modelo configurado en el servidor (cuesta tokens)")
    a = ap.parse_args()
    base = a.url.rstrip("/")
    config.consola_segura()   # salida redirigida en Windows: UTF-8, como el resto del agente

    print(f"Validando {base}\n\n1. Servidor")
    try:
        status, _, cuerpo = pedir(base + "/health", timeout=5)
    except OSError as e:
        comprobar(False, "la API responde", f"{e}. ¿Está corriendo uvicorn en {base}?")
        return resumen()
    esperadas = len(catalogo.cargar())   # las del catálogo local: la API debe haber cargado el mismo
    comprobar(status == 200 and json.loads(cuerpo)["reglas"] == esperadas, f"GET /health: {esperadas} reglas cargadas")
    info = json.loads(pedir(base + "/v1/info")[2])
    comprobar(len(info["extensiones"]) == 24, f"GET /v1/info: {len(info['extensiones'])} extensiones aceptadas",
              "se esperaban 24")
    print(f"       modelo del servidor: {info['modelo']}")
    status, tipo, html = pedir(base + "/")
    comprobar(status == 200 and b"/app.js" in html, "GET /: la página web se sirve")
    for recurso in ("/app.js", "/app.css"):
        comprobar(pedir(base + recurso)[0] == 200, f"GET {recurso}")

    print("\n2. Carga de archivos (uno por lenguaje, más casos límite)")
    archivos = [{"nombre": n, "contenido": (RAIZ / n).read_text(encoding="utf-8")} for n, _, _ in EJEMPLOS]
    archivos.append({"nombre": "Pegado/ConTildes.cs",
                     "contenido": 'public class cliente_ñandú { var c = "Password=Clave123"; }'})
    archivos.append({"nombre": "script.py", "contenido": "print(1)"})        # fuera de los estándares
    print(f"       enviando {len(archivos)} archivos…")
    inicio = time.perf_counter()
    status, _, cuerpo = pedir(base + "/v1/revisiones", {"tipo_app": "web", "modo_bd": "nueva",
                                                         "usar_llm": a.con_llm, "archivos": archivos})
    segundos = time.perf_counter() - inicio
    if not comprobar(status == 200, f"POST /v1/revisiones responde 200 en {segundos:.1f} s",
                     cuerpo[:300].decode("utf-8", "replace")):
        return resumen()
    rev = json.loads(cuerpo)
    por_nombre = {x["archivo"]: x for x in rev["archivos"]}
    comprobar(len(rev["archivos"]) == len(archivos), "todos los archivos llegaron al análisis")

    print("\n3. Análisis por lenguaje (aplicación web; los móviles se evalúan como móvil)")
    for nombre, lenguaje, contexto in EJEMPLOS:
        r = por_nombre.get(nombre, {})
        hallazgos = r.get("hallazgos", []) + r.get("semanticos", [])
        comprobar(r.get("lenguaje") == lenguaje and not r.get("omitido") and hallazgos
                  and r.get("evaluado_como") == contexto,
                  f"{nombre.split('/')[-1]:<30} {lenguaje:<10} {len(hallazgos):>2} hallazgos, reglas de {contexto}",
                  f"lenguaje={r.get('lenguaje')} omitido={r.get('omitido')!r} evaluado_como={r.get('evaluado_como')}")
    pegado = por_nombre.get("Pegado/ConTildes.cs", {})
    comprobar({h["regla_id"] for h in pegado.get("hallazgos", [])} >= {"WEB-NET-001", "SEG-CRI-003"},
              "código pegado con tildes: nombre de clase y contraseña detectados")
    comprobar(por_nombre.get("script.py", {}).get("omitido") == "lenguaje sin especialista",
              "script.py se omite con su motivo (Python no está en los estándares)")
    comprobar(rev["veredicto_inicial"] == "NO_APTO", f"veredicto inicial NO_APTO ({rev['totales']['hallazgos']} hallazgos)")
    citas_ok = all(h["cita"].startswith("EST-") for x in rev["archivos"] for h in x["hallazgos"])
    comprobar(citas_ok, "cada hallazgo trae la cita del documento (EST-… §… pág.)")
    print("\n   Aplicación de escritorio con base legada")
    st, _, c = pedir(base + "/v1/revisiones", {"tipo_app": "escritorio", "modo_bd": "legada", "usar_llm": a.con_llm,
                                               "archivos": [{"nombre": n, "contenido": (RAIZ / n).read_text(encoding="utf-8")}
                                                            for n, _, _ in ESCRITORIO]})
    esc = {x["archivo"]: x for x in json.loads(c)["archivos"]} if st == 200 else {}
    for nombre, lenguaje, contexto in ESCRITORIO:
        r = esc.get(nombre, {})
        hallazgos = r.get("hallazgos", []) + r.get("semanticos", [])
        comprobar(r.get("lenguaje") == lenguaje and hallazgos and r.get("evaluado_como") == contexto,
                  f"{nombre.split('/')[-1]:<30} {lenguaje:<10} {len(hallazgos):>2} hallazgos, reglas de {contexto}",
                  f"status={st} lenguaje={r.get('lenguaje')} evaluado_como={r.get('evaluado_como')}")
    legada = {h["regla_id"].split("-")[1] for h in esc.get("ejemplos/bd/escritorio_legada.sql", {}).get("hallazgos", [])}
    comprobar("BD" in legada and not any(h["regla_id"].startswith("WEB-BD") for h in
                                         esc.get("ejemplos/bd/escritorio_legada.sql", {}).get("hallazgos", [])),
              "base legada: nomenclatura DSK-BD, sin exigir renombrar a WEB-BD")
    if a.con_llm:
        comprobar(rev["totales"]["llamadas_llm"] > 0, f"el modelo participó ({rev['totales']['llamadas_llm']} llamadas, "
                  f"{sum(rev['totales']['tokens'].values())} tokens)")

    print("\n4. Aprobación humana y descarga")
    parches = [(x["archivo"], p["id"]) for x in rev["archivos"] for p in x["parches"]]
    comprobar(parches, f"hay correcciones propuestas ({len(parches)})")
    url_aprob = f"{base}/v1/revisiones/{rev['revision_id']}/aprobacion"
    st, tipo, c = pedir(url_aprob, {"aprobados": [{"archivo": "no/existe.cs", "parche": "P001"}]})
    comprobar(st == 400 and "problem+json" in tipo, "aprobar un parche ajeno: 400 en Problem Details, nada aplicado")
    elegidos = parches[: max(1, len(parches) // 2)]
    st, _, c = pedir(url_aprob, {"aprobados": [{"archivo": f, "parche": p} for f, p in elegidos]})
    final = json.loads(c) if st == 200 else {}
    estados = {(x["archivo"], p["id"]): p["estado"] for x in final.get("archivos", []) for p in x["parches"]}
    comprobar(st == 200, f"POST …/aprobacion con {len(elegidos)} de {len(parches)} aprobados")
    comprobar(all(estados.get(k) in ("aplicado", "conflicto") for k in elegidos), "los aprobados quedaron aplicados")
    comprobar(all(estados.get(k) == "denegado" for k in parches if k not in elegidos), "los no aprobados quedaron denegados")
    corregidos = final.get("corregidos", [])
    comprobar(corregidos and all(c["diff"].startswith("--- a/") and c["contenido"] for c in corregidos),
              f"{len(corregidos)} archivos corregidos con contenido y diff para descargar")
    originales = {x["nombre"]: x["contenido"] for x in archivos}
    comprobar(all(c["contenido"] != originales[c["archivo"]] for c in corregidos), "el contenido corregido cambió")
    comprobar(final.get("veredicto_final") is not None, f"veredicto final: {final.get('veredicto_final')}")
    comprobar(pedir(url_aprob, {"aprobados": []})[0] == 409, "segunda aprobación de la misma revisión: 409")

    print("\n5. Errores y límites")
    st, tipo, _ = pedir(base + "/v1/revisiones", {"tipo_app": "mainframe", "archivos": []})
    comprobar(st == 400 and "problem+json" in tipo, "solicitud inválida: 400 en Problem Details")
    comprobar(pedir(base + "/v1/revisiones", crudo=b"{no es json")[0] == 400, "cuerpo que no es JSON: 400")
    grande = {"archivos": [{"nombre": "Grande.cs", "contenido": "x" * (info["max_bytes_archivo"] + 1)}]}
    comprobar(pedir(base + "/v1/revisiones", grande)[0] == 400, "archivo de más de 200 KB: 400")
    demasiados = {"archivos": [{"nombre": f"A{i}.cs", "contenido": "class A {}"} for i in range(info["max_archivos"] + 1)]}
    comprobar(pedir(base + "/v1/revisiones", demasiados)[0] == 400, f"más de {info['max_archivos']} archivos: 400")
    comprobar(pedir(f"{base}/v1/revisiones/no-existe/aprobacion", {"aprobados": []})[0] == 404, "revisión desconocida: 404")
    comprobar(pedir(base + "/v1/reglas/NO-EXI-STE")[0] == 404, "regla inexistente: 404")
    metricas = pedir(base + "/metrics")[2].decode("utf-8")
    comprobar("lab07_revisiones_total" in metricas and 'lenguaje="kotlin"' in metricas,
              "GET /metrics expone revisiones y los lenguajes nuevos")
    return resumen()


def resumen() -> int:
    fallas = [r for r in resultados if not r[0]]
    print(f"\n{len(resultados) - len(fallas)} de {len(resultados)} comprobaciones pasaron.")
    for _, que, detalle in fallas:
        print(f"  FALLA: {que}" + (f": {detalle}" if detalle else ""))
    return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main())
