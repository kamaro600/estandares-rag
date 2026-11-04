"""Detectores de Razor, JavaScript, YAML (contratos OpenAPI y pipelines) y XML/.resx.

También los patrones comunes a varios lenguajes nuevos (secretos, HTTP sin TLS, criptografía débil, logs).
"""
from __future__ import annotations

import re

from agente.detectores import Archivo, Patron, registrar, registrar_archivo

I = re.IGNORECASE
RZ, JS, YML, XML = ("razor",), ("javascript",), ("yaml",), ("xml",)
CODIGO = ("razor", "javascript", "kotlin", "swift")          # lenguajes con cadenas y llamadas
SENSIBLE = r"(clave|password|passwd|contrase\w*|token|jwt|pin|tarjeta|cvv|secret\w*|otp)"

# ---------------------------------------------------------------- comunes (EST-SEG-001)
registrar(
    Patron("GEN-SECRETO-LITERAL", CODIGO, ("SEG-CRI-003",),
           re.compile(r"\b(api_?key|client_?secret|secret|password|passwd|pwd)\w*\s*[:=]\s*[\"'][^\"'\s]{6,}[\"']", I),
           "Secreto escrito en el código: va en Key Vault, Keychain/Keystore o la configuración segura.",
           excluir=re.compile(r"[:=]\s*[\"'](\$\{|\{\{|%|<)")),
    Patron("GEN-HTTP-PLANO", CODIGO, ("SEG-MOV-003", "SEG-CRI-004"),
           re.compile(r"[\"']http://(?!localhost|127\.0\.0\.1|10\.0\.2\.2|schemas\.|www\.w3\.org)"),
           "URL con http://: toda comunicación usa TLS 1.2 o superior.", confianza="media"),
    Patron("GEN-CRIPTO-DEBIL", CODIGO, ("SEG-CRI-001",),
           re.compile(r"MessageDigest\.getInstance\(\s*\"(MD5|SHA-?1)\"|Cipher\.getInstance\(\s*\"(DES|DESede|RC4|AES/ECB)|"
                      r"\bInsecure\.(MD5|SHA1)\b|\bCC_(MD5|SHA1)\b|kCCAlgorithm(DES|3DES|RC4)|"
                      r"createHash\(\s*['\"](md5|sha1)['\"]|CryptoJS\.(MD5|SHA1|DES|TripleDES|RC4)\b"),
           "Algoritmo criptográfico prohibido (MD5, SHA-1, DES, 3DES, RC4 o modo ECB)."),
    Patron("GEN-LOG-SENSIBLE", CODIGO, ("SEG-LOG-001",),
           re.compile(r"(console\.(log|info|debug|warn|error)|\bLog\.[vdiwe]|\bprint|\bdebugPrint|\bNSLog|\bos_log|"
                      r"\b[lL]ogger\.\w+)\s*\(.*(\$\{?\s*|\\\(\s*|\+\s*|,\s*)[\w.]*" + SENSIBLE, I),
           "Dato sensible en el log (clave, token, PIN…): no se registra o se enmascara.",
           relacionadas=("SEG-MOV-002",)),
)

# ---------------------------------------------------------------- Razor (.cshtml, .razor)
registrar(
    Patron("RAZOR-HTML-RAW", RZ, ("SEG-INY-003",), re.compile(r"Html\.Raw\s*\("),
           "Html.Raw con datos no confiables permite XSS: deja que Razor codifique la salida.", confianza="media"),
    Patron("RAZOR-MARKUPSTRING", RZ, ("SEG-INY-003",), re.compile(r"\(MarkupString\)|new\s+MarkupString\s*\("),
           "MarkupString muestra HTML sin codificar: solo con contenido sanitizado.", confianza="media"),
    Patron("RAZOR-SCRIPT-EN-LINEA", RZ, ("SEG-CFG-001",), re.compile(r"<script(?![^>]*\bsrc\s*=)[^>]*>", I),
           "Script en línea: la CSP no admite unsafe-inline. Muévelo a un archivo .js.", confianza="media"),
    Patron("RAZOR-EVENTO-EN-LINEA", RZ, ("SEG-CFG-001",),
           re.compile(r"(?<![@\w])on(click|load|error|change|submit|input|mouseover|focus|blur)\s*=\s*\"", I),
           "Manejador de evento en línea: con CSP sin unsafe-inline no se ejecuta. Enlázalo desde un .js.",
           confianza="media"),
)

# ---------------------------------------------------------------- JavaScript (.js)
registrar(
    Patron("JS-TOKEN-STORAGE", JS, ("SEG-AUT-005",),
           re.compile(r"(localStorage|sessionStorage)\.setItem\(\s*['\"`][^'\"`]*(token|jwt|sesion|session|auth)", I),
           "Token en localStorage/sessionStorage: usa una cookie HttpOnly (BFF) o MSAL.",
           relacionadas=("WEB-ANG-005",)),
    Patron("JS-INNERHTML", JS, ("SEG-INY-003",),
           re.compile(r"\.(innerHTML|outerHTML)\s*=(?!=)|\bdocument\.write(ln)?\s*\(|insertAdjacentHTML\s*\("),
           "HTML insertado sin codificar: usa textContent o sanitiza el contenido.", confianza="media"),
    Patron("JS-EVAL", JS, ("SEG-CFG-001",), re.compile(r"\beval\s*\(|\bnew\s+Function\s*\("),
           "eval/new Function obligan a permitir unsafe-eval en la CSP, que está prohibido.",
           relacionadas=("SEG-INY-003",)),
    Patron("JS-MATH-RANDOM", JS, ("SEG-CRI-002",), re.compile(r"\bMath\.random\s*\(\s*\)"),
           "Math.random() no sirve para valores de seguridad: usa crypto.getRandomValues.", confianza="media"),
)

# ---------------------------------------------------------------- YAML: secretos (contratos y pipelines)
registrar(
    Patron("YAML-SECRETO", YML, ("SEG-CRI-003",),
           re.compile(r"^\s*-?\s*[\w.-]*(password|passwd|pwd|secret|api_?key|apikey|token|connectionstring)[\w.-]*"
                      r"\s*:\s*['\"]?(?!\$|\{\{|<|true\b|false\b)[^\s'\"#]{6,}", I),
           "Secreto escrito en el YAML: usa una variable secreta del pipeline o Key Vault."),
    Patron("YAML-HTTP-PLANO", YML, ("SEG-CRI-004",),
           re.compile(r"\burl\s*:\s*['\"]?http://(?!localhost|127\.0\.0\.1)", I),
           "Servidor con http://: toda comunicación usa TLS 1.2 o superior."),
)

METODOS = ("get", "post", "put", "patch", "delete")
VERBOS = re.compile(r"(^|/|-)(obtener|listar|eliminar|crear|actualizar|buscar|registrar|get|delete|update|create)", I)
HERRAMIENTAS_DEPENDENCIAS = {"npm": "npm audit", "dotnet": "dotnet list package --vulnerable"}
ANALISIS_SEGURIDAD = re.compile(r"credscan|gitleaks|trufflehog|detect-secrets|codeql|semgrep|sonar|snyk|"
                                r"advancedsecurity|secretscan", I)


@registrar_archivo("yaml")
def _openapi_y_pipeline(a: Archivo, ctx) -> list[dict]:
    texto, hallazgos = a.contenido, []
    if re.search(r"^(openapi|swagger)\s*:", texto, re.M):
        for n, l in enumerate(a.lineas, 1):
            if re.match(r"^(swagger\s*:|openapi\s*:\s*['\"]?2)", l):
                hallazgos.append(dict(codigo="OPENAPI-VERSION", linea=n, reglas=("API-DIS-005",),
                                      mensaje="El contrato debe ser OpenAPI 3 (no Swagger 2)."))
            m = re.match(r"^  (/[^:\s]*)\s*:\s*$", l)       # rutas: dos espacios bajo 'paths:'
            if m:
                fija = re.sub(r"\{[^}]*\}", "", m.group(1))
                if re.search(r"[A-Z_]", fija) or VERBOS.search(fija):
                    hallazgos.append(dict(codigo="OPENAPI-RUTA", linea=n, reglas=("API-DIS-001",),
                                          mensaje=f"Ruta '{m.group(1)}': sustantivos en plural, minúsculas, "
                                                  "kebab-case y sin verbos."))
        hallazgos += _operaciones_sin_documentar(a)
    elif re.search(r"^\s*(steps|stages|jobs|trigger|pool)\s*:", texto, re.M):
        bajo = texto.lower()
        for herramienta, requerido in HERRAMIENTAS_DEPENDENCIAS.items():
            usa = re.search(rf"\b{herramienta}\b|{'DotNetCoreCLI' if herramienta == 'dotnet' else 'Npm@'}", texto)
            if usa and requerido not in bajo:
                linea = texto[:usa.start()].count("\n") + 1
                hallazgos.append(dict(codigo="PIPELINE-DEPENDENCIAS", linea=linea, reglas=("SEG-CFG-003",),
                                      mensaje=f"El pipeline usa {herramienta} y no ejecuta '{requerido}'."))
        if not ANALISIS_SEGURIDAD.search(texto):
            hallazgos.append(dict(codigo="PIPELINE-SAST", linea=1, reglas=("SEG-CFG-004",), confianza="media",
                                  relacionadas=("WEB-QA-003",),
                                  mensaje="No se ve análisis estático ni detección de secretos (SonarQube, "
                                          "CodeQL, gitleaks…) en el pipeline."))
    return hallazgos


def _operaciones_sin_documentar(a: Archivo) -> list[dict]:
    """API-DIS-005: cada operación con descripción y con sus códigos de error."""
    hallazgos, lineas = [], a.lineas
    for n, l in enumerate(lineas, 1):
        m = re.match(r"^(\s+)(get|post|put|patch|delete)\s*:\s*$", l)
        if not m:
            continue
        sangria, cuerpo = len(m.group(1)), []
        for siguiente in lineas[n:]:
            if siguiente.strip() and len(siguiente) - len(siguiente.lstrip()) <= sangria:
                break
            cuerpo.append(siguiente)
        bloque = "\n".join(cuerpo)
        faltan = [x for x, rx in (("descripción", r"^\s+(description|summary)\s*:"),
                                  ("respuestas de error 4xx", r"^\s+['\"]?4\d\d['\"]?\s*:")) if not re.search(rx, bloque, re.M)]
        if faltan:
            hallazgos.append(dict(codigo="OPENAPI-OPERACION", linea=n, reglas=("API-DIS-005",), confianza="media",
                                  mensaje=f"Operación {m.group(2).upper()} sin {' ni '.join(faltan)}."))
    return hallazgos


# ---------------------------------------------------------------- XML y .resx
registrar(
    Patron("XML-SECRETO", XML, ("SEG-CRI-003",),
           re.compile(r"<(add|setting|data)\b[^>]*\b(key|name)=\"[^\"]*(password|secret|api_?key|clientsecret|token)"
                      r"[^\"]*\"[^>]*(\bvalue=\"[^\"]{4,}\"|>)", I),
           "Secreto en un archivo XML del repositorio: se considera comprometido y debe rotarse.",
           confianza="media", relacionadas=("SEG-DSK-002",)),
)
