"""python -m scripts.averias  →  ¿las pruebas detectan fallos reales? Introduce una avería por vez.

Cada avería desactiva un control (una guarda, un límite, una regla de precedencia) y ejecuta la suite.
Si ninguna prueba falla, ese control no está protegido. El archivo original se restaura siempre.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from agente import config

RAIZ = Path(__file__).parent.parent
AVERIAS = [
    ("guarda: permitir comentar el código", "agente/guardas.py", 'if all(not l.strip() or es_comentario(archivo.lenguaje, l) for l in nuevas):', 'if False:'),
    ("guarda: no re-analizar si el hallazgo sigue", "agente/guardas.py", "    if sigue:\n", "    if False:\n"),
    ("guarda: no detectar incumplimientos nuevos", "agente/guardas.py", "    if nuevos:\n", "    if False:\n"),
    ("guarda: permitir supresiones", "agente/guardas.py", "    if SUPRESION.search(parche.reemplazo):", "    if False:"),
    ("supervisor: olvidar la rotación del secreto", "agente/supervisor.py", 'if h.regla_id in REGLAS_SECRETO or REGLAS_SECRETO & set(h.relacionadas):', 'if False:'),
    ("supervisor: aceptar autofix sin guarda", "agente/supervisor.py", "            rechazo = validar_parche(a, p, r.hallazgos, ctx)\n            self._contar_parche", "            rechazo = None\n            self._contar_parche"),
    ("supervisor: aplicar sin aprobación", "agente/supervisor.py", 'aprobados = [p for p in r.parches if p.estado == "aprobado"]', 'aprobados = list(r.parches)'),
    ("supervisor: escribir fuera de salida/", "agente/supervisor.py", 'if p not in ("..", ".", "/") and ":" not in p', 'if p != "/"'),
    ("react: tool_result con otro id", "agente/react.py", '"tool_use_id": b["id"]', '"tool_use_id": "x"'),
    ("react: sin límite de repeticiones", "agente/react.py", "if vistas[firma] > config.MAX_REPEATED_CALLS:", "if False:"),
    ("contexto: la web sin su API", "agente/contexto.py", 'return ("web", "api") if self.tipo_app == "web"', 'return ("web",) if self.tipo_app == "web"'),
    ("tools: el LLM reporta reglas que no aplican", "agente/tools.py", "    if s.ctx.regla_aplicable((regla.id,)) is None:", "    if False:"),
    ("detectores: analizar comentarios", "agente/detectores/__init__.py", "    if es_comentario(lenguaje, linea):\n        return \"\"", "    if False:\n        return \"\""),
    ("detectores: sin precedencia de SEG", "agente/detectores/__init__.py", "key=lambda h: (h.linea, prioridad(h.regla_id), h.detector)", "key=lambda h: (h.linea, -prioridad(h.regla_id), h.detector)"),
    ("catálogo: no unir referencias partidas", "agente/catalogo.py", "    while cuerpo and RE_CONTINUA_REF.match(cuerpo[0].strip()):", "    while False:"),
    ("config: .env UTF-16 ilegible", "agente/config.py", 'if raw[:2] in (b"\\xff\\xfe", b"\\xfe\\xff"):', 'if False:'),
    ("config: salida redirigida en cp1252", "agente/config.py", 'flujo.reconfigure(encoding="utf-8", errors="replace")', 'pass'),
    ("api: errores sin Problem Details", "agente/api.py", 'media_type="application/problem+json"', 'media_type="application/json"'),
    ("móvil: evaluar un .kt como web", "agente/contexto.py", 'return replace(ctx, tipo_app="movil") if es_movil(archivo)', 'return ctx if es_movil(archivo)'),
    ("supervisor: sin revisión semántica", "agente/supervisor.py", "if (pendientes or a.lenguaje in REVISION_SEMANTICA) and usar_llm:", "if pendientes and usar_llm:"),
    ("api: aprobar todo sin mirar al humano", "agente/api.py", "lambda p, h: (p.archivo, p.id) in pedidos", "lambda p, h: True"),
]


def main() -> None:
    config.consola_segura()
    detectadas = 0
    for nombre, archivo, viejo, nuevo in AVERIAS:
        p = RAIZ / archivo
        original = p.read_bytes()   # en bytes: la restauración es exacta (sin convertir LF a CRLF en Windows)
        texto = original.decode("utf-8")
        if viejo not in texto:
            raise SystemExit(f"La avería '{nombre}' ya no encuentra su texto en {archivo}: actualízala.")
        p.write_bytes(texto.replace(viejo, nuevo, 1).encode("utf-8"))
        try:
            if archivo.endswith("catalogo.py"):
                subprocess.run([sys.executable, "-m", "agente.ingesta"], cwd=RAIZ, capture_output=True)
            r = subprocess.run([sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider"],
                               cwd=RAIZ, capture_output=True, text=True, encoding="utf-8")
            ok = r.returncode != 0
            detectadas += ok
            prueba = next((l[7:].split(" - ")[0] for l in r.stdout.splitlines() if l.startswith("FAILED")), "")
            print(f"{'DETECTADA' if ok else 'NO DETECTADA':<13} {nombre:<45} {prueba[:70]}")
        finally:
            p.write_bytes(original)
            if archivo.endswith("catalogo.py"):
                subprocess.run([sys.executable, "-m", "agente.ingesta"], cwd=RAIZ, capture_output=True)
    print(f"{detectadas}/{len(AVERIAS)} averías detectadas")


if __name__ == "__main__":
    main()
