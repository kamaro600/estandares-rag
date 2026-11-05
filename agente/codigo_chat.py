"""¿El mensaje del chat trae código? ¿Con qué nombre de archivo lo revisa el agente?

El agente decide qué detectores aplicar por la EXTENSIÓN del archivo. En el chat no hay archivo: el nombre sale de
  1. una primera línea "// archivo: Controllers/ClientesController.cs" (o "-- archivo:", "# archivo:", "<!-- archivo: -->"),
  2. el lenguaje del bloque ```csharp … ```, o
  3. una heurística sobre el propio código.
Una pregunta que MENCIONA código ("¿puedo usar SELECT * en un SP?") no es código: no empieza la línea.
"""
from __future__ import annotations

import re

from agente.detectores import detectar_lenguaje

RX_BLOQUE = re.compile(r"```[ \t]*([\w#+.-]*)[ \t]*\n(.*?)```", re.S)
RX_ARCHIVO = re.compile(r"^\s*(?://|--|#|<!--)\s*archivo:\s*([\w./\\-]+\.\w+)", re.I)
ALIAS = {"cs": "codigo.cs", "c#": "codigo.cs", "csharp": "codigo.cs", "ts": "codigo.ts", "typescript": "codigo.ts",
         "js": "codigo.js", "javascript": "codigo.js", "html": "plantilla.html", "sql": "script.sql",
         "tsql": "script.sql", "t-sql": "script.sql", "xaml": "Vista.xaml", "xml": "config.xml", "json": "appsettings.json",
         "yaml": "openapi.yaml", "yml": "pipeline.yml", "kotlin": "Codigo.kt", "kt": "Codigo.kt",
         "swift": "Codigo.swift", "razor": "Vista.cshtml", "cshtml": "Vista.cshtml"}
RX_LINEA_CODIGO = re.compile(
    r"([;{}]\s*$|^\s*[{}]|^\s*(public|private|protected|internal|using|namespace|var|const|let|import|export|return|"
    r"await|if|for|foreach|try|catch|class|fun|val|func|@Component|@Injectable|CREATE|ALTER|SELECT|INSERT|UPDATE|"
    r"DELETE|FROM|WHERE|BEGIN|END|EXEC|SET|DECLARE|GO)\b|=>|^\s*</?[A-Za-z][\w:.]*[\s>/]|^\s*//|^\s*--)", re.I)
RX_SQL_UNA_LINEA = re.compile(r"^\s*(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|EXEC)\b.*\b(FROM|TABLE|PROC|PROCEDURE|"
                              r"INTO|SET|VIEW)\b", re.I)


def nombre_por_contenido(codigo: str) -> str:
    """Un nombre de archivo verosímil para el código pegado (de él dependen los detectores que se aplican)."""
    if re.search(r"<(Window|UserControl|Grid|StackPanel|TextBox|Button|ContentPage)\b|x:Name=", codigo):
        return "Vista.xaml"
    if re.search(r"^\s*(CREATE|ALTER)\s+(TABLE|PROC|PROCEDURE|VIEW|FUNCTION|INDEX)\b|^\s*(SET NOCOUNT|DECLARE @|EXEC\s)|"
                 r"^\s*SELECT\b.+\bFROM\b", codigo, re.I | re.M) and not re.search(r"\b(class|namespace)\s+\w+", codigo):
        return "script.sql"
    if re.search(r"^\s*(fun|val|package)\s|import android\.", codigo, re.M):
        return "Codigo.kt"
    if re.search(r"^\s*import (UIKit|Foundation|SwiftUI)|\bfunc\s+\w+\(.*\)\s*(->|\{)", codigo, re.M):
        return "Codigo.swift"
    if re.search(r"@Component|@Injectable|\bimport\s+\{[^}]*\}\s+from\s+['\"]|:\s*(string|number|boolean|any)\b|"
                 r"localStorage|sessionStorage|this\.\w+\.subscribe", codigo):
        return "codigo.component.ts" if "@Component" in codigo else "codigo.ts"
    return "codigo.cs"


def extraer(texto: str) -> tuple[str, str, str] | None:
    """(código, nombre de archivo, texto sin el código) o None si el mensaje no trae código."""
    bloques = RX_BLOQUE.findall(texto)
    if bloques:
        alias, codigo = bloques[0][0].lower(), bloques[0][1].rstrip()
        resto = RX_BLOQUE.sub(" ", texto, count=1).strip()
    else:
        lineas = [l for l in texto.splitlines() if l.strip()]
        if len(lineas) == 1 and RX_SQL_UNA_LINEA.match(lineas[0]):
            alias, codigo, resto = "sql", texto.strip(), ""
        else:
            de_codigo = [bool(RX_LINEA_CODIGO.search(l)) for l in lineas]
            if len(lineas) < 2 or sum(de_codigo) < 2 or sum(de_codigo) / len(lineas) < 0.5:
                return None
            inicio = next(i for i, c in enumerate(de_codigo) if c)   # la prosa inicial es la instrucción
            alias, codigo, resto = "", "\n".join(lineas[inicio:]), "\n".join(lineas[:inicio])
    m = RX_ARCHIVO.match(codigo.splitlines()[0]) if codigo else None
    if m and detectar_lenguaje(m.group(1)):
        nombre = m.group(1).replace("\\", "/")
    elif alias in ALIAS:
        nombre = ALIAS[alias]
    else:
        nombre = nombre_por_contenido(codigo)
    return codigo, nombre, resto
