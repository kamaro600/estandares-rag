"""python _guia/build.py  →  guia_laboratorio_07.html

Genera la guía HTML con el mismo formato de los laboratorios 04-06. El texto sale de _guia/guia.md y
TODO el código se inyecta desde los archivos reales del proyecto: la guía no puede quedar desactualizada
respecto del código probado. Si un bloque de la guía no coincide con su archivo, la compilación falla.
"""
from __future__ import annotations

import html
import re
import sys
from pathlib import Path

import markdown

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent
SALIDA = RAIZ / "guia_laboratorio_07.html"
LARGO = 45   # bloques con más líneas se muestran plegados con «Ver completo»

TITULOS = {  # título corto de cada paso en la barra lateral
    1: "Fundamentos: las seis ideas", 2: "Carpetas, entorno y dependencias", 3: "config.py · límites",
    4: "catalogo.py · del PDF a reglas", 5: "Contexto y detectores", 6: "rag.py · buscar en los estándares",
    7: "parches.py y guardas.py", 8: "El especialista: LLM y ReAct", 9: "supervisor.py · aprobación humana",
    10: "Reporte, CLI y API", 11: "metricas.py · Prometheus", 12: "Evaluación y averías deliberadas",
    13: "Docker, Prometheus y Grafana", 14: "Windows", 15: "Modelo real, ejercicios y análisis",
}
ICONOS = [("Copia y pega", "✍️"), ("Qué hace cada parte", "🔎"), ("Prueba", "🧪"), ("La suite", "🧪"),
          ("Ejecuta", "▶️"), ("Recorrido", "🧭"), ("Mapa", "🧭"), ("Levantar", "🚀"), ("Resumen", "📏"),
          ("Limitaciones", "⚠️"), ("Análisis", "🔬"), ("Relación", "➡️"), ("Cambiar", "🔑"),
          ("Equivalencias", "🔁"), ("Trampas que", "🧯"), ("Una trampa", "🧯"), ("Qué se verificó", "🔬"),
          ("Antes de empezar", "🪟"), ("Consultas", "📈"), ("Autoevaluación", "✅"), ("Ejercicios", "🏋️")]
ES_TEORIA = re.compile(r"^(Teoría|\d · |Decisiones que|Qué mide)")
ES_MEDIDO = re.compile(r"^Medido")
RE_RUTA = re.compile(r"((?:agente|tests|eval|scripts|ejemplos|prometheus|grafana)/[\w./-]+|Dockerfile|docker-compose\.yml|"
                     r"requirements(?:-dev)?\.txt|pytest\.ini|\.env\.example|\.gitignore|\.gitattributes)")
LENG = {"python": "py", "bash": "sh", "powershell": "sh"}
errores: list[str] = []


# ---------------------------------------------------------------- utilidades
def md(texto: str) -> str:
    h = markdown.markdown(texto, extensions=["tables"])
    h = h.replace("<table>", '<div class="tw"><table class="wrap">').replace("</table>", "</table></div>")
    return h


def inline(texto: str) -> str:
    h = md(texto).strip()
    return h[3:-4] if h.startswith("<p>") and h.endswith("</p>") else h


def icono(titulo: str) -> str:
    return next((i for k, i in ICONOS if titulo.startswith(k)), "📌")


def bloque_codigo(contenido: str, lang: str, fn: str, tag: str, salida: bool = False, os_: str = "") -> str:
    ruta = RE_RUTA.fullmatch(fn.split(" ")[0]) and (RAIZ / fn.split(" ")[0])
    if ruta and ruta.is_file():
        real = ruta.read_text(encoding="utf-8").rstrip("\n")
        if real != contenido.rstrip("\n"):
            errores.append(f"El bloque de {fn} no coincide con el archivo real")
        contenido = real   # siempre se publica el archivo real
        n = contenido.count("\n") + 1
        fn = f"{fn.split(' ')[0]} · {n} líneas"
    n = contenido.count("\n") + 1
    largo = n > LARGO and not salida
    clases = "code" + (" long" if largo else "") + (f" {os_}" if os_ else "")
    data = f' data-lang="{LENG[lang]}"' if lang in LENG else ""
    botones = ('<button class="expand">Ver completo</button>' if largo else "") + \
              ("" if salida else '<button class="copy">Copiar</button>')
    pre = ' class="tree"' if "├──" in contenido else ""
    return (f'<div class="{clases}"><div class="code-h"><span class="fn">{html.escape(fn)}</span>'
            f'<span class="tag{" out" if salida else ""}">{html.escape(tag)}</span>{botones}</div>'
            f'<pre{pre}><code{data}>{html.escape(contenido)}</code></pre></div>')


def trozos(cuerpo: str) -> list[tuple[str, str, str]]:
    """Divide un texto en ('code', lang, contenido) y ('md', '', párrafo/lista/tabla)."""
    salida, pos = [], 0
    for m in re.finditer(r"^```(\w*)\n(.*?)\n```$", cuerpo, re.S | re.M):
        antes = cuerpo[pos:m.start()]
        salida += [("md", "", p.strip()) for p in re.split(r"\n\s*\n", antes) if p.strip()]
        salida.append(("code", m.group(1), m.group(2)))
        pos = m.end()
    salida += [("md", "", p.strip()) for p in re.split(r"\n\s*\n", cuerpo[pos:]) if p.strip()]
    return salida


# ---------------------------------------------------------------- un subapartado (###)
def subapartado(titulo: str, cuerpo: str, ruta_titulo: str | None) -> str:
    items = trozos(cuerpo)
    if titulo.startswith("Autoevaluación"):
        return autoevaluacion(titulo, items)
    if titulo == "Ejercicios":
        return ejercicios(items)
    contenido = render_items(items, ruta_titulo)
    t = inline(titulo)
    if ES_TEORIA.match(titulo):
        etiqueta = t if titulo.startswith("Teoría") else f"Teoría · {t}"
        return f'<div class="theory"><b>📖 {etiqueta}</b>{contenido}</div>'
    if ES_MEDIDO.match(titulo):
        return f'<div class="lab"><b>🔬 {t}</b>{contenido}</div>'
    return f'<h3><span class="ic">{icono(titulo)}</span>{t}</h3>\n{contenido}'


def render_items(items, ruta_titulo: str | None) -> str:
    out, i, ruta_pendiente = [], 0, ruta_titulo
    while i < len(items):
        tipo, lang, texto = items[i]
        sig = items[i + 1] if i + 1 < len(items) else None
        if tipo == "code":
            out.append(codigo_sin_etiqueta(lang, texto, ruta_pendiente))
            ruta_pendiente = None
            i += 1
            continue
        # par de sistemas operativos
        if texto in ("macOS / Linux:", "Windows (PowerShell):") and sig and sig[0] == "code":
            win = texto.startswith("Windows")
            out.append(bloque_codigo(sig[2], sig[1], "PowerShell" if win else "Terminal",
                                     "Windows (PowerShell)" if win else "macOS / Linux", os_="os-win" if win else "os-mac"))
            i += 2
            continue
        # etiqueta de archivo: "`ruta`:" o "`ruta` (descripción):"
        m = re.fullmatch(r"`([^`]+)`(?: \((.+)\))?:", texto)
        if m and sig and sig[0] == "code":
            if m.group(2):
                out.append(f"<p>{inline(m.group(2)[0].upper() + m.group(2)[1:])}.</p>")
            out.append(bloque_codigo(sig[2], sig[1], m.group(1).replace("\\_", "_"), "crear"))
            i += 2
            continue
        # salida esperada seguida de un bloque
        if re.match(r"^(Salida esperada|Respuesta real|Salida real)", texto) and texto.endswith(":") and sig and sig[0] == "code":
            out.append(bloque_codigo(sig[2], "", texto.rstrip(":"), "salida", salida=True))
            i += 2
            continue
        # "Salida esperada: `5 passed`." (en línea)
        m = re.match(r"^Salida esperada(?: \([^)]*\))?: `([^`]+)`\.?\s*(.*)$", texto, re.S)
        if m:
            out.append(bloque_codigo(m.group(1), "", "Salida esperada", "salida", salida=True))
            if m.group(2).strip():
                out.append(md(m.group(2)))
            i += 1
            continue
        out.append(caja(texto, items, i))
        # un recuadro que termina en ":" incluye la tabla o lista que lo sigue
        if out[-1].startswith(('<div class="lab">', '<div class="warn">')) and texto.rstrip().endswith(":") \
                and texto != "**Trampas:**" and sig and sig[0] == "md":
            out[-1] = out[-1][:-6] + md(sig[2]) + "</div>"
            i += 1
        if texto in ("**Trampas:**",) and sig and sig[0] == "md":
            out[-1] = f'<div class="warn"><b>⚠️ Trampas</b>{md(sig[2])}</div>'
            i += 1
        i += 1
    return "\n".join(out)


def codigo_sin_etiqueta(lang: str, texto: str, ruta: str | None) -> str:
    if ruta:
        return bloque_codigo(texto, lang, ruta, "crear")
    if lang in ("bash", "powershell"):
        return bloque_codigo(texto, lang, "Terminal / PowerShell (en la raíz, entorno activo)", "todos los sistemas")
    if "├──" in texto:
        return bloque_codigo(texto, lang, "Estructura del proyecto", "árbol", salida=True)
    if texto.startswith("# Proporción"):
        return bloque_codigo(texto, lang, "PromQL", "consultas")
    if lang == "json":
        return bloque_codigo(texto, lang, "JSON", "cuerpo")
    if lang == "diff":
        return bloque_codigo(texto, lang, "salida/cambios.diff", "salida", salida=True)
    return bloque_codigo(texto, lang, "Salida real", "salida", salida=True)


def caja(texto: str, items, i) -> str:
    m = re.match(r"^\*\*([^*]+?)[:.]?\*\*:?\s*(.*)$", texto, re.S)
    if m:
        cab, resto = m.group(1).rstrip(":."), m.group(2)
        if cab.startswith(("Trampa", "Seguridad", "Límite declarado", "Regla de oro")):
            return f'<div class="warn"><b>⚠️ {inline(cab)}</b>{inline(resto)}</div>'
        if cab.startswith(("Punto de control", "Cierre")):
            return f'<div class="check"><b>{inline(cab)}</b>{inline(resto)}</div>'
        if cab.startswith("Medido"):
            return f'<div class="lab"><b>🔬 {inline(cab)}</b>{inline(resto)}</div>'
    if texto.startswith("En Windows") or texto.startswith("Si PowerShell bloquea"):
        return f'<div class="win winonly"><b>🪟 Windows</b>{inline(texto)}</div>'
    return md(texto)


def autoevaluacion(titulo: str, items) -> str:
    out = [f'<h3><span class="ic">✅</span>{inline(titulo)}</h3>']
    for _, _, texto in items:
        m = re.match(r"^\*\*(.+?)\*\*\s*(.*)$", texto, re.S)
        if m and not m.group(1).startswith(("Punto de control", "Cierre")):
            out.append(f'<details class="qz"><summary>{inline(m.group(1))}</summary>'
                       f'<div class="ans">{inline(m.group(2))}</div></details>')
        else:
            out.append(caja(texto, items, 0))
    return "\n".join(out)


def ejercicios(items) -> str:
    out = ['<h3><span class="ic">🏋️</span>Ejercicios</h3>']
    for _, _, texto in items:
        for n, linea in enumerate(re.findall(r"^\d+\. (.+)$", texto, re.M), start=1):
            m = re.match(r"\*\*(.+?)\*\*\s*(.*)", linea)
            titulo, resto = (m.group(1).rstrip("."), m.group(2)) if m else (f"Ejercicio {n}", linea)
            resto = re.sub(r"\*(Pista|Pregunta|Qué demuestra):\*", r"<b>\1:</b>", resto)
            out.append(f'<details class="ex"><summary>{n} · {inline(titulo)}</summary><div><p>{inline(resto)}</p></div></details>')
    return "\n".join(out)


# ---------------------------------------------------------------- un paso (##)
def paso(n: int, titulo: str, cuerpo: str) -> str:
    partes = re.split(r"^### (.+)$", cuerpo, flags=re.M)
    intro, subs = partes[0].strip(), list(zip(partes[1::2], partes[2::2]))
    m = re.match(r"^(\d+ min(?: de lectura| · lectura)?)\. ?(.*)$", intro, re.S)
    tiempo, porque = (m.group(1), m.group(2)) if m else ("", intro)
    # el primer párrafo es el porqué; lo demás (diagrama del doc, notas) va después
    primer, _, resto_intro = porque.partition("\n\n")
    h = [f'<section id="s{n}" data-title="{html.escape(TITULOS[n])}">',
         f'  <div class="step-head"><span class="badge">Paso {n}</span><h2>{inline(titulo)}</h2>'
         f'<span class="time">{html.escape(tiempo)}</span></div>',
         f'  <p class="why">{inline(primer)}</p>']
    if resto_intro.strip():
        h.append(render_items(trozos(resto_intro), None))
    for t, c in subs:
        mr = RE_RUTA.search(t.replace("\\_", "_")) if t.startswith("Copia y pega") else None
        h.append(subapartado(t, c, mr.group(1) if mr else None))
    h.append("</section>")
    return "\n".join(h)


# ---------------------------------------------------------------- ajustes al texto fuente
def preparar(texto: str) -> str:
    texto = texto.replace("\\_", "_")
    # Paso 2: crear TODAS las carpetas y archivos vacíos (como los labs 05 y 06)
    texto = re.sub(r"(### Copia y pega · 1\) carpetas\n\n).*?(\nCopia los cinco PDF)",
                   lambda m: m.group(1) + crear_esqueleto() + "\n" + m.group(2), texto, flags=re.S)
    texto = texto.replace("```bash\npython3 -m venv .venv\nsource .venv/bin/activate\n```\n\n"
                          "En Windows: `py -3 -m venv .venv` y luego `.\\.venv\\Scripts\\Activate.ps1`. ",
                          "macOS / Linux:\n\n```bash\npython3 -m venv .venv\nsource .venv/bin/activate\n```\n\n"
                          "Windows (PowerShell):\n\n```powershell\npy -3 -m venv .venv\n.\\.venv\\Scripts\\Activate.ps1\n```\n\n")
    texto = texto.replace("```bash\npython -m pip install -r requirements-dev.txt\ncp .env.example .env\n```\n\n"
                          "En Windows: `Copy-Item .env.example .env`.\n",
                          "macOS / Linux:\n\n```bash\npython -m pip install -r requirements-dev.txt\ncp .env.example .env\n```\n\n"
                          "Windows (PowerShell):\n\n```powershell\npython -m pip install -r requirements-dev.txt\n"
                          "Copy-Item .env.example .env\n```\n")
    curl = ('curl -s localhost:8000/health\ncurl -s "localhost:8000/v1/reglas/web-bd-005"\n'
            'curl -s "localhost:8000/v1/buscar?q=prefijo%20de%20procedimientos%20almacenados"')
    texto = texto.replace(f"```bash\n{curl}\n```", "macOS / Linux:\n\n```bash\n" + curl + "\n```\n\nWindows (PowerShell):\n\n"
                          "```powershell\n" + curl.replace("curl -s", "curl.exe -s") + "\n```")
    return texto


def archivos_del_proyecto() -> list[str]:
    excluir = (".venv", "__pycache__", ".pytest_cache", "salida", "_guia", ".git")
    rutas = []
    for p in sorted(RAIZ.rglob("*")):
        rel = p.relative_to(RAIZ)
        if p.is_file() and not any(x in rel.parts for x in excluir) and rel.parts[0] != "data" \
                and rel.name != "agente-estandares.json" and not rel.name.startswith("guia_laboratorio") \
                and not rel.name.endswith(".zip") and rel.name != ".env":
            rutas.append(rel.as_posix())
    return rutas


def crear_esqueleto() -> str:
    archivos = archivos_del_proyecto()
    carpetas = sorted({str(Path(a).parent.as_posix()) for a in archivos if "/" in a} | {"data/estandares", "grafana/dashboards"})
    carpetas = [c for c in carpetas if not any(o != c and o.startswith(c + "/") for o in carpetas)]
    mac = ("mkdir -p lab-07-agente-estandares && cd lab-07-agente-estandares\nmkdir -p " + " ".join(carpetas) +
           "\ntouch " + " \\\n  ".join(" ".join(archivos[i:i + 4]) for i in range(0, len(archivos), 4)))
    lista = ",\n  ".join(", ".join(f'"{a.replace("/", chr(92))}"' for a in archivos[i:i + 3]) for i in range(0, len(archivos), 3))
    win = ("New-Item -ItemType Directory -Force lab-07-agente-estandares | Out-Null\nSet-Location lab-07-agente-estandares\n"
           "New-Item -ItemType Directory -Force " + ", ".join(c.replace("/", "\\") for c in carpetas) + " | Out-Null\n"
           f"$archivos = @(\n  {lista}\n)\n"
           "foreach ($f in $archivos) { if (-not (Test-Path $f)) { New-Item -ItemType File $f | Out-Null } }")
    return (f"Crea de una vez las carpetas y los **{len(archivos)} archivos vacíos** del laboratorio: en cada paso solo "
            "abres un archivo que ya existe y pegas su contenido. Repetir el bloque es seguro: no vacía archivos con código.\n\n"
            f"macOS / Linux:\n\n```bash\n{mac}\n```\n\nWindows (PowerShell):\n\n```powershell\n{win}\n```\n")


# ---------------------------------------------------------------- portada
FIGURA = """<figure class="fig">
<svg class="dg" viewBox="0 0 920 440" role="img" aria-label="Flujo de una revisión: el código pasa por el plan y los detectores; el autofix y el especialista proponen parches; la guarda los re-analiza; un humano aprueba; se escribe una copia corregida.">
  <defs><marker id="ah1" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" fill="rgba(255,255,255,.75)"/></marker>
        <marker id="ah2" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" fill="#ffcc66"/></marker></defs>
  <rect class="bx" x="20" y="30" width="190" height="66" rx="10"/>
  <text x="115" y="58" text-anchor="middle" class="t-b">Código a revisar</text><text x="115" y="78" text-anchor="middle" class="t-s">.cs .xaml .ts .html .sql .json</text>
  <rect class="bx" x="250" y="30" width="190" height="66" rx="10"/>
  <text x="345" y="58" text-anchor="middle" class="t-b">Plan</text><text x="345" y="78" text-anchor="middle" class="t-s">por extensión · sin LLM</text>
  <rect class="bx bx-g" x="480" y="30" width="190" height="66" rx="10"/>
  <text x="575" y="58" text-anchor="middle" class="t-b">88 detectores</text><text x="575" y="78" text-anchor="middle" class="t-s">cada uno cita su regla</text>
  <rect class="bx bx-g" x="710" y="30" width="190" height="66" rx="10"/>
  <text x="805" y="58" text-anchor="middle" class="t-b">Autofix</text><text x="805" y="78" text-anchor="middle" class="t-s">solo lo mecánico</text>
  <path class="ln" d="M210 63 H250" marker-end="url(#ah1)"/><path class="ln" d="M440 63 H480" marker-end="url(#ah1)"/><path class="ln" d="M670 63 H710" marker-end="url(#ah1)"/>

  <rect class="bx" x="20" y="190" width="190" height="66" rx="10"/>
  <text x="115" y="218" text-anchor="middle" class="t-b">Catálogo y RAG</text><text x="115" y="238" text-anchor="middle" class="t-s">170 reglas de 5 PDF</text>
  <rect class="bx bx-v" x="250" y="190" width="190" height="66" rx="10"/>
  <text x="345" y="218" text-anchor="middle" class="t-b">Especialista LLM</text><text x="345" y="238" text-anchor="middle" class="t-s">6 herramientas · sin escribir</text>
  <rect class="bx bx-c" x="480" y="182" width="190" height="82" rx="12"/>
  <text x="575" y="210" text-anchor="middle" class="t-b t-c">GUARDA (código)</text><text x="575" y="230" text-anchor="middle" class="t-s">re-analiza el archivo</text><text x="575" y="246" text-anchor="middle" class="t-s">el LLM propone, el código dispone</text>
  <rect class="bx bx-w" x="710" y="190" width="190" height="66" rx="10"/>
  <text x="805" y="218" text-anchor="middle" class="t-b t-w">Humano</text><text x="805" y="238" text-anchor="middle" class="t-s">aprueba o deniega</text>
  <path class="ln" d="M540 96 V140 H345 V190" marker-end="url(#ah1)"/><text x="440" y="132" text-anchor="middle" class="t-s">pendientes</text>
  <path class="ln" d="M805 96 V160 H620 V182" marker-end="url(#ah1)"/><text x="712" y="152" text-anchor="middle" class="t-s">parche</text>
  <path class="ln" d="M210 223 H250" marker-end="url(#ah1)"/><text x="230" y="182" text-anchor="middle" class="t-s">reglas</text>
  <path class="ln" d="M440 212 H480" marker-end="url(#ah1)"/><text x="460" y="174" text-anchor="middle" class="t-s">parche</text>
  <path class="ln ln-d" d="M480 238 H440" marker-end="url(#ah2)"/><text x="460" y="284" text-anchor="middle" class="t-s t-w">motivo del rechazo</text>
  <path class="ln" d="M670 223 H710" marker-end="url(#ah1)"/><text x="690" y="182" text-anchor="middle" class="t-s">aceptado</text>

  <rect class="bx" x="710" y="340" width="190" height="66" rx="10"/>
  <text x="805" y="368" text-anchor="middle" class="t-b">salida/corregido</text><text x="805" y="388" text-anchor="middle" class="t-s">re-análisis → veredicto</text>
  <path class="ln" d="M805 256 V340" marker-end="url(#ah1)"/><text x="815" y="302" class="t-s">aprobado</text>
  <rect class="bx" x="20" y="340" width="640" height="66" rx="10"/>
  <text x="340" y="366" text-anchor="middle" class="t-b">Traza, reporte y métricas</text>
  <text x="340" y="386" text-anchor="middle" class="t-s">salida/trazas/*.jsonl · salida/reporte.md · /metrics → Prometheus → Grafana</text>
</svg>
<figcaption>Todo parche, venga del autofix o del especialista, pasa por la guarda. Ningún especialista puede escribir: solo el supervisor, y solo lo que un humano aprobó.</figcaption>
</figure>"""


def portada(intro_md: str) -> str:
    subs = re.split(r"^### (.+)$", intro_md, flags=re.M)
    secciones = dict(zip(subs[1::2], subs[2::2]))
    tabla = lambda t: md(secciones[t].strip())  # noqa: E731
    return f"""<section class="hero" id="intro" data-title="Introducción y arquitectura">
  <div class="kicker">IA Generativa para Desarrolladores · Módulos 3, 4 y 5 · RAG, agentes y producción</div>
  <h1>Un agente que corrige estándares de desarrollo</h1>
  <p class="lead">Construirás, en Python puro y sin frameworks de agentes, un sistema que revisa código <b>C#</b>, <b>XAML</b>,
  <b>Angular/TypeScript</b>, <b>T-SQL</b> y <b>archivos de configuración</b> contra los cinco estándares de Empresa Ejemplo S.A.
  Los detectores encuentran los incumplimientos, un <b>especialista LLM</b> propone correcciones, una <b>guarda</b> las valida
  re-analizando el código y un <b>humano</b> decide qué se aplica, siempre en una copia.</p>
  <div class="goal-grid">
    <div class="goal"><b>1 · Catalogar</b>Los cinco PDF se convierten en 170 reglas con cita exacta (documento, versión, sección, página).</div>
    <div class="goal"><b>2 · Detectar</b>88 detectores deterministas, cada uno atado a una regla y medidos contra los ejemplos de los PDF.</div>
    <div class="goal"><b>3 · Corregir</b>Autofix para lo mecánico; un especialista por lenguaje con herramientas para lo demás.</div>
    <div class="goal"><b>4 · Controlar</b>Guardas que re-analizan cada parche, mínimo privilegio y aprobación humana.</div>
    <div class="goal"><b>5 · Observar</b>Traza auditable, reporte con citas, métricas en Prometheus y un tablero de Grafana.</div>
  </div>
  {FIGURA}
  <h3>Lenguajes y estándares cubiertos</h3>
  {tabla("Lenguajes y estándares cubiertos")}
  <h3>Qué es real y qué es simulado</h3>
  {tabla("Qué es real y qué es simulado")}
  <h3>Requisitos previos</h3>
  {tabla("Requisitos")}
  <div class="win"><b>🪟 Si trabajas en Windows, lee esto antes de empezar</b>
    Usa <b>PowerShell</b> (no cmd) y activa el botón <b>Windows (PowerShell)</b> arriba a la derecha: los bloques de comandos
    cambian. Las trampas más comunes (política de ejecución, <code>python</code> que abre la Tienda, <code>.env</code> en UTF-16,
    rutas con OneDrive…) están resumidas en el <a href="#s14">paso 14</a>.</div>
  <div class="note"><b>Cómo leer cada paso</b>
    <span style="color:var(--violet)">■ Teoría</span> (el porqué) · <span style="color:var(--cyan)">■ Copia y pega</span>
    (archivo y ruta exactos) · <span style="color:var(--ok)">■ Salida esperada</span> (capturada de una ejecución real) ·
    <span style="color:var(--warn)">■ Trampa</span> (errores típicos). Todo el código de la guía se inyecta desde los archivos
    reales del laboratorio: no puede quedar desactualizado respecto del código probado.</div>
</section>"""


def main() -> int:
    fuente = preparar((AQUI / "guia.md").read_text(encoding="utf-8"))
    cuerpo = fuente[fuente.index("## Qué construirás"):]
    pasos = re.split(r"^## Paso (\d+) · (.+)$", cuerpo, flags=re.M)
    intro = pasos[0].split("\n", 1)[1]
    secciones = [portada(intro)] + [paso(int(n), t, c) for n, t, c in zip(pasos[1::3], pasos[2::3], pasos[3::3])]
    if errores:
        print("\n".join(errores))
        return 1
    css = (AQUI / "plantilla.css").read_text(encoding="utf-8")
    js = (AQUI / "plantilla.js").read_text(encoding="utf-8")
    logo = (AQUI / "logo.txt").read_text(encoding="utf-8").strip()
    pagina = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Laboratorio 07 paso a paso · Agente corrector de estándares de desarrollo · UTEC Posgrado</title>
<style>{css}</style>
</head>
<body>

<header class="top">
  <img src="{logo}" alt="UTEC Posgrado">
  <div class="title">Laboratorio 07 · <span>Estándares</span> · Detectores → Especialista → Guarda → Humano</div>
  <div class="os" role="group" aria-label="Sistema operativo">
    <button id="osMac" class="on">macOS / Linux</button><button id="osWin">Windows (PowerShell)</button>
  </div>
</header>

<div class="layout">
<nav class="side" id="nav">
  <h4>Progreso</h4>
  <div class="prog"><i id="progBar"></i></div>
  <h4>Pasos</h4>
</nav>

<main>

{chr(10).join(secciones)}

</main>
</div>

<script>{js}</script>
</body>
</html>
"""
    SALIDA.write_text(pagina, encoding="utf-8", newline="\n")
    n_codigo = pagina.count('<div class="code')
    print(f"{SALIDA.name}: {len(secciones) - 1} pasos, {n_codigo} bloques de código, {len(pagina) // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
