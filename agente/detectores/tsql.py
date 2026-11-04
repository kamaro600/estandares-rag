"""Detectores de T-SQL: WEB-BD-* (bases nuevas) o DSK-BD-* (bases legadas) y SEG-INY-001."""
from __future__ import annotations

import re

from agente.detectores import Archivo, Patron, registrar, registrar_archivo

SQL = ("tsql",)
I = re.IGNORECASE


def _datetime2(linea: str, m: re.Match) -> str:
    return re.sub(r"\bDATETIME\b(?!2)", "DATETIME2(3)", linea, flags=I)


def _nvarchar_max(linea: str, m: re.Match) -> str:
    return re.sub(r"\bN?TEXT\b", "NVARCHAR(MAX)", linea, flags=I)


registrar(
    # --- Válidas en cualquier base ---
    Patron("SQL-SELECT-ASTERISCO", SQL, ("WEB-BD-009",), re.compile(r"\bSELECT\s+(TOP\s*\(?\d+\)?\s+)?\*", I),
           "SELECT * prohibido: lista las columnas.", segun_bd=True),
    Patron("SQL-FUNCION-EN-WHERE", SQL, ("WEB-BD-009",),
           re.compile(r"\bWHERE\b.*\b(YEAR|MONTH|DAY|CONVERT|CAST|UPPER|LOWER|LTRIM|RTRIM|ISNULL)\s*\(\s*\w+", I),
           "Función sobre una columna en el WHERE: impide usar índices.", confianza="media", segun_bd=True),
    Patron("SQL-EXEC-DINAMICO", SQL, ("SEG-INY-001",), re.compile(r"\bEXEC(UTE)?\s*\(\s*@", I),
           "SQL dinámico con EXEC(@sql): usa sp_executesql con parámetros.", segun_bd=True),
    Patron("SQL-CONCATENA-PARAM", SQL, ("SEG-INY-001",),
           re.compile(r"\bSET\s+@\w+\s*=\s*N?'[^']*'+\s*\+\s*@", I),
           "Sentencia armada concatenando un parámetro: inyección SQL.", segun_bd=True),
    Patron("SQL-DB-OWNER", SQL, ("SEG-GEN-002",),
           re.compile(r"sp_addrolemember\s+N?'db_owner'|ALTER\s+ROLE\s+db_owner\s+ADD\s+MEMBER", I),
           "La aplicación no usa db_owner: EXECUTE y SELECT sobre sus esquemas.",
           relacionadas=("WEB-BD-012",), segun_bd=True),
    # --- Base NUEVA: EST-WEB-001 cap. 7 ---
    Patron("SQL-PREFIJO-SP", SQL, ("WEB-BD-005",),
           re.compile(r"CREATE\s+(OR\s+ALTER\s+)?PROC(EDURE)?\s+(\[?\w+\]?\.)?\[?sp_", I),
           "Prefijo sp_ prohibido: usa usp_<Entidad>_<Accion>.", modo_bd="nueva", segun_bd=True),
    Patron("SQL-ESQUEMA-DBO", SQL, ("WEB-BD-001",),
           re.compile(r"CREATE\s+(TABLE|VIEW|PROC(EDURE)?|FUNCTION)\s+(\[?dbo\]?\.)", I),
           "Objeto nuevo en dbo: usa un esquema por módulo (ventas, seguridad…).",
           modo_bd="nueva", segun_bd=True),
    Patron("SQL-TIPO-PROHIBIDO", SQL, ("WEB-BD-006",),
           re.compile(r"^\s*\[?\w+\]?\s+(FLOAT|REAL|MONEY|SMALLMONEY|IMAGE)\b", I),
           "Tipo prohibido (FLOAT/REAL/MONEY para montos, IMAGE): usa DECIMAL(18,2) o VARBINARY(MAX).",
           modo_bd="nueva", segun_bd=True),
    Patron("SQL-TIPO-TEXT", SQL, ("WEB-BD-006",), re.compile(r"^\s*\[?\w+\]?\s+N?TEXT\b", I),
           "TEXT/NTEXT son obsoletos: NVARCHAR(MAX).", modo_bd="nueva", segun_bd=True, autofix=_nvarchar_max),
    Patron("SQL-DATETIME", SQL, ("WEB-BD-006",), re.compile(r"^\s*\[?\w+\]?\s+DATETIME\b(?!2)", I),
           "DATETIME: en bases nuevas usa DATETIME2(3) en UTC.", modo_bd="nueva", segun_bd=True,
           autofix=_datetime2),
    Patron("SQL-VARCHAR", SQL, ("WEB-BD-006",), re.compile(r"^\s*\[?\w+\]?\s+VARCHAR\s*\(", I),
           "Texto en bases nuevas: NVARCHAR(n).", confianza="media", modo_bd="nueva", segun_bd=True),
    Patron("SQL-CONSTRAINT-ANONIMA", SQL, ("WEB-BD-004",),
           re.compile(r"^\s*\[?\w+\]?\s+\w+.*\b(PRIMARY\s+KEY|REFERENCES|UNIQUE|DEFAULT)\b", I),
           "Restricción sin nombre explícito: CONSTRAINT PK_/FK_/UQ_/DF_…",
           excluir=re.compile(r"\bCONSTRAINT\b", I), modo_bd="nueva", segun_bd=True),
    # --- Base LEGADA: EST-DSK-001 cap. 6 ---
    Patron("SQL-PREFIJO-SP-LEGADA", SQL, ("DSK-BD-003",),
           re.compile(r"CREATE\s+(OR\s+ALTER\s+)?PROC(EDURE)?\s+(\[?\w+\]?\.)?\[?sp_", I),
           "Prefijo sp_ prohibido: PA_<MOD>_<ACCION>.", modo_bd="legada", segun_bd=True),
    Patron("SQL-TIPO-PROHIBIDO-LEGADA", SQL, ("DSK-BD-005",),
           re.compile(r"^\s*\[?\w+\]?\s+(FLOAT|REAL|MONEY|SMALLMONEY)\b", I),
           "Importes en DECIMAL(18,2).", modo_bd="legada", segun_bd=True),
    Patron("SQL-CONSTRAINT-ANONIMA-LEGADA", SQL, ("DSK-BD-004",),
           re.compile(r"^\s*\[?\w+\]?\s+\w+.*\b(PRIMARY\s+KEY|REFERENCES)\b", I),
           "Restricción sin nombre explícito: PK_<TABLA>, FK_<HIJA>_<PADRE>.",
           excluir=re.compile(r"\bCONSTRAINT\b", I), modo_bd="legada", segun_bd=True),
)

RE_TABLA = re.compile(r"CREATE\s+TABLE\s+(?:\[?(\w+)\]?\.)?\[?(\w+)\]?\s*\(", I)
RE_FIN_TABLA = re.compile(r"\n\s*\)\s*;?\s*(?=\n|$)|\)\s*;\s*$", re.M)
RE_PROC = re.compile(r"CREATE\s+(?:OR\s+ALTER\s+)?PROC(?:EDURE)?\s+(?:\[?(\w+)\]?\.)?\[?(\w+)\]?(.*?)(?=\n\s*GO\b|\Z|CREATE\s+(?:OR\s+ALTER\s+)?PROC)", I | re.S)


def _linea(texto: str, pos: int) -> int:
    return texto.count("\n", 0, pos) + 1


@registrar_archivo("tsql")
def _objetos(a: Archivo, ctx) -> list[dict]:
    texto, hallazgos = a.contenido, []
    for m in RE_TABLA.finditer(texto):
        esquema, tabla = m.group(1), m.group(2)
        fin = RE_FIN_TABLA.search(texto, m.end())
        cuerpo = texto[m.end():fin.start() if fin else len(texto)]
        n = _linea(texto, m.start())
        if ctx.modo_bd == "nueva":
            if not esquema:
                hallazgos.append(dict(codigo="SQL-SIN-ESQUEMA", linea=n, reglas=("WEB-BD-001",), segun_bd=True,
                                      mensaje=f"Tabla '{tabla}' sin esquema: usa un esquema por módulo."))
            if re.match(r"(tbl|TBL_|T_)", tabla) or not re.fullmatch(r"[A-Z][a-z0-9]+([A-Z][a-z0-9]+)*", tabla):
                hallazgos.append(dict(codigo="SQL-NOMBRE-TABLA", linea=n, reglas=("WEB-BD-002",), segun_bd=True,
                                      mensaje=f"Tabla '{tabla}': PascalCase, singular y sin prefijos (ventas.Cliente)."))
            elif re.search(r"[^s]s$", tabla) and not tabla.endswith(("Estatus", "Mes", "Pais")):
                hallazgos.append(dict(codigo="SQL-TABLA-PLURAL", linea=n, reglas=("WEB-BD-002",), segun_bd=True,
                                      confianza="media", mensaje=f"Tabla '{tabla}' parece plural: las tablas van en singular."))
            for desp, col in enumerate(cuerpo.split("\n"), start=1):
                cm = re.match(r"\s*\[?([A-Z][A-Z0-9]*_[A-Z0-9_]+)\]?\s+\w+", col)
                if cm and not re.match(r"\s*CONSTRAINT", col, I):
                    hallazgos.append(dict(codigo="SQL-NOMBRE-COLUMNA", linea=n + desp, reglas=("WEB-BD-003",),
                                          segun_bd=True, mensaje=f"Columna '{cm.group(1)}': PascalCase (ClienteId, EsActivo)."))
            if "FechaCreacion" not in cuerpo or "UsuarioCreacion" not in cuerpo:
                hallazgos.append(dict(codigo="SQL-AUDITORIA", linea=n, reglas=("WEB-BD-007",), segun_bd=True,
                                      confianza="media", mensaje=f"Tabla '{tabla}' sin FechaCreacion/UsuarioCreacion (obligatorias si es transaccional)."))
        else:
            if not re.fullmatch(r"TBL_[A-Z0-9_]+", tabla):
                hallazgos.append(dict(codigo="SQL-NOMBRE-TABLA-LEGADA", linea=n, reglas=("DSK-BD-001",), segun_bd=True,
                                      mensaje=f"Tabla '{tabla}': en la base legada se usa TBL_ en MAYÚSCULAS y plural."))
            for desp, col in enumerate(cuerpo.split("\n"), start=1):
                cm = re.match(r"\s*\[?(\w+)\]?\s+[A-Za-z]+", col)
                if cm and not re.match(r"\s*CONSTRAINT", col, I) and not re.fullmatch(
                        r"(ID|NOM|DES|NUM|FEC|IMP|FLG|USU)_[A-Z0-9_]+", cm.group(1)):
                    hallazgos.append(dict(codigo="SQL-NOMBRE-COLUMNA-LEGADA", linea=n + desp, reglas=("DSK-BD-002",),
                                          segun_bd=True, mensaje=f"Columna '{cm.group(1)}': MAYÚSCULAS con prefijo ID_, NOM_, FEC_, IMP_…"))
            if "USU_CREACION" not in cuerpo or "FEC_CREACION" not in cuerpo:
                hallazgos.append(dict(codigo="SQL-AUDITORIA-LEGADA", linea=n, reglas=("DSK-BD-008",), segun_bd=True,
                                      confianza="media", mensaje=f"Tabla '{tabla}' sin USU_CREACION/FEC_CREACION (obligatorias si es transaccional)."))
    for m in RE_PROC.finditer(texto):
        nombre, cuerpo = m.group(2), m.group(3)
        n = _linea(texto, m.start())
        if ctx.modo_bd == "nueva" and not nombre.lower().startswith("sp_") and not re.fullmatch(r"usp_[A-Z][A-Za-z0-9]*_[A-Z][A-Za-z0-9]*", nombre):
            hallazgos.append(dict(codigo="SQL-NOMBRE-PROC", linea=n, reglas=("WEB-BD-005",), segun_bd=True,
                                  mensaje=f"Procedimiento '{nombre}': usp_<Entidad>_<Accion>."))
        if ctx.modo_bd == "legada" and not nombre.lower().startswith("sp_") and not re.fullmatch(r"PA_[A-Z]{3}_[A-Z_]+", nombre):
            hallazgos.append(dict(codigo="SQL-NOMBRE-PROC-LEGADA", linea=n, reglas=("DSK-BD-003",), segun_bd=True,
                                  mensaje=f"Procedimiento '{nombre}': PA_<MOD>_<ACCION> en mayúsculas."))
        faltan = [s for s in ("SET NOCOUNT ON", "SET XACT_ABORT ON") if not re.search(s.replace(" ", r"\s+"), cuerpo, I)]
        if faltan:
            hallazgos.append(dict(codigo="SQL-PROC-SET", linea=n, reglas=("WEB-BD-008",), segun_bd=True,
                                  mensaje=f"El procedimiento no inicia con {' ni '.join(faltan)}."))
        if re.search(r"\b(INSERT|UPDATE|DELETE|MERGE)\b", cuerpo, I) and not re.search(r"BEGIN\s+TRY", cuerpo, I):
            hallazgos.append(dict(codigo="SQL-PROC-SIN-TRY", linea=n, reglas=("WEB-BD-008",), segun_bd=True,
                                  mensaje="Procedimiento que modifica datos sin BEGIN TRY / transacción / THROW."))
    return hallazgos
