"""¿El mensaje trae código? ¿En qué lenguaje?  Heurísticas simples y explicables, sin LLM.

Lo usa el router (si hay código, la intención casi seguro es validarlo) y el agente (para elegir qué verificadores
aplicar). Reconoce: bloque ``` … ``` (con o sin lenguaje), o texto donde la mayoría de líneas "parecen código".
Una pregunta que MENCIONA código ("¿puedo usar SELECT * en un SP?") no se toma como código: no empieza la línea.
"""
from __future__ import annotations

import re

RX_BLOQUE = re.compile(r"```[ \t]*([\w#+-]*)[ \t]*\n(.*?)```", re.S)
ALIAS = {"cs": "csharp", "c#": "csharp", "csharp": "csharp", "ts": "typescript", "typescript": "typescript",
         "js": "typescript", "javascript": "typescript", "html": "typescript", "sql": "sql", "tsql": "sql",
         "t-sql": "sql", "xaml": "xaml", "xml": "xaml"}
RX_LINEA_CODIGO = re.compile(
    r"([;{}]\s*$|^\s*[{}]|^\s*(public|private|protected|internal|using|namespace|var|const|let|import|export|return|"
    r"await|if|for|foreach|try|catch|class|@Component|@Injectable|CREATE|ALTER|SELECT|INSERT|UPDATE|DELETE|FROM|WHERE|"
    r"BEGIN|END|EXEC|SET|DECLARE|GO)\b|=>|^\s*<\/?[A-Za-z][\w:.]*[\s>/]|^\s*//|^\s*--)", re.I)
RX_SQL_UNA_LINEA = re.compile(r"^\s*(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|EXEC)\b.*\b(FROM|TABLE|PROC|PROCEDURE|"
                              r"INTO|SET|VIEW)\b", re.I)


def lenguaje(codigo: str) -> str:
    if re.search(r"<(Window|UserControl|Grid|StackPanel|TextBox|Button)\b|x:Name=|xmlns(:x)?=", codigo):
        return "xaml"
    if re.search(r"^\s*(CREATE|ALTER)\s+(TABLE|PROC|PROCEDURE|VIEW|FUNCTION|INDEX)\b|^\s*(BEGIN TRAN|SET NOCOUNT|DECLARE @|"
                 r"EXEC\s|GO\s*$)", codigo, re.I | re.M) and not re.search(r"\b(class|namespace)\s+\w+", codigo):
        return "sql"
    if re.search(r"^\s*SELECT\b.+\bFROM\b", codigo, re.I | re.M) and not re.search(r"[;{}]\s*$", codigo, re.M):
        return "sql"
    if re.search(r"@Component|@Injectable|\bimport\s+\{[^}]*\}\s+from\s+['\"]|:\s*(string|number|boolean|any)\b|"
                 r"\b(let|const)\s+\w+\s*(:\s*\w+)?\s*=|localStorage|sessionStorage|this\.\w+\.subscribe", codigo):
        return "typescript"
    if re.search(r"\b(public|private|protected|internal)\b|\busing\s+[\w.]+;|\bvar\s+\w+\s*=|\bnamespace\b|"
                 r"\basync\s+Task\b|\bnew\s+\w+\(|\[Http(Get|Post|Put|Delete)", codigo):
        return "csharp"
    return "otro"


def extraer(texto: str) -> tuple[str, str, str] | None:
    """(código, lenguaje, texto_sin_código) o None si el mensaje no trae código."""
    bloques = RX_BLOQUE.findall(texto)
    if bloques:
        codigo = "\n\n".join(b[1].rstrip() for b in bloques)
        alias = ALIAS.get(bloques[0][0].lower(), "")
        resto = RX_BLOQUE.sub(" ", texto).strip()
        return codigo, alias or lenguaje(codigo), resto
    lineas = [l for l in texto.splitlines() if l.strip()]
    if len(lineas) == 1 and RX_SQL_UNA_LINEA.match(lineas[0]):
        return texto.strip(), "sql", ""
    if len(lineas) < 2:
        return None
    de_codigo = [bool(RX_LINEA_CODIGO.search(l)) for l in lineas]
    if sum(de_codigo) / len(lineas) < 0.5 or sum(de_codigo) < 2:
        return None
    # las líneas de prosa al inicio ("¿Esto cumple el estándar?") son la instrucción, no el código
    inicio = next(i for i, c in enumerate(de_codigo) if c)
    codigo = "\n".join(lineas[inicio:])
    return codigo, lenguaje(codigo), "\n".join(lineas[:inicio])
