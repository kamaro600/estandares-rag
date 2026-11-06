"""Detectores de Angular/TypeScript y plantillas HTML (EST-WEB-001 cap. 6 y EST-SEG-001)."""
from __future__ import annotations

import re
from pathlib import PurePath

from agente.detectores import Archivo, Patron, registrar, registrar_archivo

TS = ("typescript",)
I = re.IGNORECASE


def _es_environment(m: re.Match, a: Archivo) -> bool:
    return PurePath(a.nombre.replace("\\", "/")).name.startswith("environment")


def _no_es_environment(m: re.Match, a: Archivo) -> bool:
    return not _es_environment(m, a)


registrar(
    Patron("TS-ANY", TS, ("WEB-ANG-003",), re.compile(r":\s*any\b|<any>|\bas\s+any\b|<any\[\]>"),
           "Tipo any prohibido: modela el contrato con una interfaz (*.model.ts) o usa unknown."),
    Patron("TS-TOKEN-STORAGE", TS, ("SEG-AUT-005",),
           re.compile(r"(localStorage|sessionStorage)\.setItem\(\s*['\"`][^'\"`]*(token|jwt|sesion|session|auth)", I),
           "Token en localStorage/sessionStorage: usa MSAL o un BFF con cookie HttpOnly.",
           relacionadas=("WEB-ANG-005",)),
    Patron("TS-BYPASS-SANITIZER", TS, ("SEG-INY-003",),
           re.compile(r"bypassSecurityTrust(Html|Script|Url|ResourceUrl|Style)\s*\("),
           "bypassSecurityTrust* desactiva la protección XSS de Angular.", relacionadas=("WEB-ANG-006",)),
    Patron("TS-INNERHTML", TS, ("SEG-INY-003",), re.compile(r"nativeElement\.innerHTML\s*="),
           "Asignación directa de innerHTML: manipula el DOM con bindings.", relacionadas=("WEB-ANG-006",)),
    Patron("TS-MATH-RANDOM", TS, ("SEG-CRI-002",), re.compile(r"\bMath\.random\s*\(\s*\)"),
           "Math.random() no es seguro para valores de seguridad: usa crypto.getRandomValues.",
           confianza="media"),
    Patron("TS-SELECTOR", TS, ("WEB-ANG-002",), re.compile(r"selector:\s*['\"](?!emp-)([\w-]+)['\"]"),
           "Selector sin el prefijo corporativo emp- (o no está en kebab-case)."),
    Patron("TS-STANDALONE-FALSE", TS, ("WEB-ANG-001",), re.compile(r"standalone:\s*false"),
           "Los componentes nuevos son standalone."),
    Patron("TS-SECRETO-ENV", TS, ("SEG-CRI-003",),
           re.compile(r"\b(api_?key|client_?secret|secret|password)\s*:\s*['\"][^'\"]{6,}['\"]", I),
           "Secreto en environment.ts: el bundle de Angular es público.", relacionadas=("WEB-ARQ-003",)),
    Patron("TS-URL-FIJA", TS, ("WEB-ARQ-003",), re.compile(r"['\"`]https?://[^'\"`\s]+['\"`]"),
           "URL de API escrita en el código: léela de environment.ts.", confianza="media",
           verificar=_no_es_environment),
)


@registrar_archivo("typescript")
def _componentes(a: Archivo, ctx) -> list[dict]:
    hallazgos = []
    texto = a.contenido
    nombre = PurePath(a.nombre.replace("\\", "/")).name
    es_componente = "@Component" in texto or re.search(r"export\s+class\s+\w+Component\b", texto)
    if es_componente:
        if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*\.component\.ts", nombre):
            hallazgos.append(dict(codigo="TS-NOMBRE-ARCHIVO", linea=1, reglas=("WEB-ANG-002",),
                                  mensaje=f"Archivo '{nombre}': debe ser kebab-case con sufijo .component.ts."))
        for n, l in enumerate(a.lineas, 1):
            m = re.search(r"export\s+class\s+(\w+)", l)
            if m and not re.fullmatch(r"[A-Z]\w*Component", m.group(1)):
                hallazgos.append(dict(codigo="TS-NOMBRE-CLASE", linea=n, reglas=("WEB-ANG-002",),
                                      mensaje=f"Clase '{m.group(1)}': PascalCase con sufijo Component."))
            if re.search(r":\s*HttpClient\b|inject\(\s*HttpClient\s*\)", l):
                hallazgos.append(dict(codigo="TS-HTTP-EN-COMPONENTE", linea=n, reglas=("WEB-ANG-004",),
                                      mensaje="El componente usa HttpClient: encapsula las llamadas en un servicio."))
        if "takeUntilDestroyed" not in texto:
            for n, l in enumerate(a.lineas, 1):
                if ".subscribe(" in l:
                    hallazgos.append(dict(codigo="TS-SUSCRIPCION", linea=n, reglas=("WEB-ANG-004",),
                                          mensaje="Suscripción manual sin liberar: usa el pipe async o takeUntilDestroyed().",
                                          confianza="media"))
    elif "@Injectable" in texto and nombre.endswith(".ts") and not re.fullmatch(
            r"[a-z0-9]+(-[a-z0-9]+)*\.(service|guard|interceptor|resolver|store)\.ts", nombre):
        hallazgos.append(dict(codigo="TS-NOMBRE-ARCHIVO", linea=1, reglas=("WEB-ANG-002",),
                              mensaje=f"Archivo '{nombre}': kebab-case con sufijo de tipo (.service.ts…)."))
    return hallazgos


registrar(
    Patron("HTML-INNERHTML", ("html",), ("SEG-INY-003",), re.compile(r"\[innerHTML\]\s*="),
           "[innerHTML]: verifica que el contenido no venga de bypassSecurityTrust ni de datos sin sanitizar.",
           confianza="media", relacionadas=("WEB-ANG-006",)),
)
