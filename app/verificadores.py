"""Verificadores DETERMINISTAS: patrones de código que incumplen una regla concreta de los estándares (C5 y C6).

Son el "piso" del agente validador: lo que encuentran aquí es un hecho reproducible (misma entrada → mismo
resultado) y el LLM no puede borrarlo ni cambiar su severidad. El LLM explica y puede AGREGAR observaciones, que
quedan marcadas como no verificadas (origen "llm") hasta que un humano las confirme.

Cada verificador apunta a una regla que EXISTE en el índice (lo comprueba tests/test_agente.py). Si se cambia un
estándar, se ajusta aquí el patrón: la regla de negocio vive en el PDF, el patrón es su traducción ejecutable.

Límite honesto: son expresiones regulares, no un analizador sintáctico. Tienen falsos positivos (p. ej. `.Result`
de una propiedad propia) y falsos negativos (SQL concatenado en varias líneas). Por eso hay revisión humana.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app import inyeccion
from app.modelos import Hallazgo
from app.privacidad import hay_secretos

TODOS = ("csharp", "typescript", "sql", "xaml", "otro")


@dataclass(frozen=True)
class Verificador:
    regla_id: str
    titulo: str
    severidad: str
    lenguajes: tuple[str, ...]
    patron: re.Pattern
    recomendacion: str
    excluir: re.Pattern | None = None      # si la LÍNEA coincide con esto, no es hallazgo (p. ej. FromSql($"…"))


def V(regla_id, titulo, severidad, lenguajes, patron, recomendacion, excluir=None, flags=re.I) -> Verificador:
    return Verificador(regla_id, titulo, severidad, lenguajes, re.compile(patron, flags), recomendacion,
                       re.compile(excluir, re.I) if excluir else None)


CS, TS, SQL = ("csharp",), ("typescript",), ("sql",)
CS_SQL = ("csharp", "sql")

VERIFICADORES: list[Verificador] = [
    # ---------------------------------------------------------------------------------- seguridad (EST-SEG-001)
    V("SEG-INY-001", "SQL construido concatenando o interpolando valores", "critica", CS,
      r"\"\s*(SELECT|INSERT|UPDATE|DELETE)\b[^\"]*\"\s*\+|\$@?\"[^\"]*\b(SELECT|INSERT|UPDATE|DELETE)\b[^\"]*\{",
      "Usar parámetros (SqlParameter, Dapper o EF Core) en lugar de concatenar valores en la sentencia.",
      excluir=r"\b(FromSql|FromSqlInterpolated|ExecuteSql|ExecuteSqlInterpolated|SqlQuery)\s*\(\s*\$"),
    V("SEG-INY-001", "SQL dinámico ejecutado con EXEC(@variable)", "critica", SQL,
      r"\bEXEC(UTE)?\s*\(\s*@\w+",
      "Usar sp_executesql con parámetros; validar nombres de columnas contra una lista blanca."),
    V("WEB-BD-010", "FromSqlRaw/ExecuteSqlRaw con texto concatenado o interpolado", "critica", CS,
      r"\b(FromSqlRaw|ExecuteSqlRaw|ExecuteSqlRawAsync)\s*\(\s*(\$|\"[^\"]*\"\s*\+)",
      "Usar FromSql / FromSqlInterpolated con interpolación (EF Core la convierte en parámetros)."),
    V("SEG-INY-005", "Deserializador inseguro", "critica", CS,
      r"\b(BinaryFormatter|SoapFormatter|NetDataContractSerializer|LosFormatter)\b|TypeNameHandling\s*=\s*"
      r"TypeNameHandling\.(All|Auto|Objects|Arrays)",
      "Usar System.Text.Json con DTOs; nunca deserializar tipos arbitrarios."),
    V("SEG-INY-006", "Procesamiento de XML con DTD o resolución de entidades externas", "alta", CS,
      r"DtdProcessing\s*=\s*DtdProcessing\.Parse|XmlResolver\s*=\s*new\s+XmlUrlResolver",
      "DtdProcessing = DtdProcessing.Prohibit y XmlResolver = null."),
    V("SEG-INY-004", "Comando del sistema operativo construido con datos variables", "alta", CS,
      r"Process\.Start\s*\([^)]*(\+|\$\")|\bcmd(\.exe)?\s*/c\b",
      "Invocar un ejecutable fijo con ProcessStartInfo.ArgumentList y argumentos validados por lista blanca."),
    V("SEG-INY-003", "Contenido HTML sin codificar (Html.Raw)", "alta", CS, r"\bHtml\.Raw\s*\(",
      "Dejar que Razor codifique la salida; si es HTML confiable, sanitizarlo antes."),
    V("SEG-INY-003", "Se desactiva la sanitización de Angular (bypassSecurityTrust*)", "alta", TS,
      r"\bbypassSecurityTrust(Html|Script|Url|ResourceUrl|Style)\s*\(",
      "Mostrar el dato con interpolación {{ }}; Angular lo codifica automáticamente."),
    V("SEG-INY-003", "Asignación directa de innerHTML", "alta", TS,
      r"\.innerHTML\s*=|\[innerHTML\]\s*=",
      "Usar interpolación o enlaces de propiedad con datos sanitizados; no manipular el DOM directamente."),
    V("SEG-CRI-001", "Algoritmo criptográfico prohibido (MD5, SHA-1, DES, 3DES, RC2 o ECB)", "alta", CS,
      r"\b(MD5|SHA1|DES|TripleDES|RC2)(\.Create|CryptoServiceProvider|Managed)?\s*[.(]|\bCipherMode\.ECB\b|"
      r"\bnew\s+(MD5|SHA1)\w*\s*\(",
      "Contraseñas: PasswordHasher<T>. Hash: SHA-256 o superior. Cifrado: AES-256-GCM."),
    V("SEG-CRI-002", "System.Random en lugar de un generador criptográfico", "media", CS,
      r"\bnew\s+Random\s*\(",
      "Para tokens, códigos o claves: RandomNumberGenerator.GetInt32 / GetBytes."),
    V("SEG-CRI-002", "Math.random() en lugar de crypto.getRandomValues", "baja", TS,
      r"\bMath\.random\s*\(",
      "Para valores de seguridad: crypto.getRandomValues."),
    V("SEG-CRI-004", "Se acepta cualquier certificado TLS", "critica", CS,
      r"(ServerCertificateCustomValidationCallback|ServerCertificateValidationCallback|RemoteCertificateValidationCallback)"
      r"\s*[+]?=.*=>\s*true",
      "No desactivar la validación; en móviles usar certificate pinning (SEG-MOV-003)."),
    V("SEG-AUT-006", "Validación de JWT desactivada", "critica", CS,
      r"\b(ValidateIssuer|ValidateAudience|ValidateLifetime|ValidateIssuerSigningKey|RequireSignedTokens|"
      r"RequireExpirationTime)\s*=\s*false",
      "Validar emisor, audiencia, vigencia y firma; ClockSkew máximo de 2 minutos."),
    V("SEG-AUT-005", "Cookie creada sin opciones de seguridad (Secure, HttpOnly, SameSite)", "media", CS,
      r"Cookies\.Append\(\s*[^,]+,\s*[^,()]+\)\s*;",
      "Pasar CookieOptions con Secure = true, HttpOnly = true y SameSite = Strict."),
    V("SEG-AUT-005", "Token guardado en localStorage o sessionStorage", "alta", TS,
      r"(localStorage|sessionStorage)\.setItem\s*\([^)]*(token|jwt|sesion|session|auth)",
      "Usar cookie HttpOnly (BFF) o mantener el token solo en memoria con MSAL."),
    V("SEG-CFG-002", "CORS que admite cualquier origen", "alta", CS,
      r"\bAllowAnyOrigin\s*\(\s*\)|SetIsOriginAllowed\s*\(\s*_?\w*\s*=>\s*true",
      "WithOrigins con la lista blanca de orígenes por entorno leída de la configuración."),
    V("SEG-LOG-001", "Dato sensible escrito en el log", "alta", CS,
      r"\.Log(Information|Warning|Error|Debug|Critical|Trace)?\s*\([^;]*\b(password|clave|contrase\w*|token|pwd|tarjeta)\b",
      "No registrar credenciales, tokens ni datos de tarjeta; registrar solo un valor enmascarado si hace falta."),
    V("SEG-GEN-002", "Conexión con la cuenta sa (administrador de SQL Server)", "alta", CS_SQL + ("xaml",),
      r"\bUser\s*Id\s*=\s*sa\b|\bUID\s*=\s*sa\b",
      "Usar un usuario propio de la aplicación con permisos mínimos (o identidad administrada)."),
    V("SEG-MOV-001", "Token o credencial guardado en Preferences", "alta", CS,
      r"\bPreferences(\.Default)?\.Set\s*\([^)]*(token|clave|password|secret)",
      "Usar SecureStorage.Default.SetAsync."),
    # ---------------------------------------------------------------------------------- web y C# (EST-WEB-001)
    V("WEB-NET-002", "Bloqueo de código asíncrono (.Result, .Wait(), GetResult())", "media", CS,
      r"\.Result\b(?!s)|\.Wait\s*\(\s*\)|GetAwaiter\(\)\.GetResult\(\)",
      "Usar await de extremo a extremo y propagar CancellationToken."),
    V("WEB-NET-002", "Método async void fuera de un manejador de eventos", "baja", CS,
      r"\basync\s+void\s+\w+\s*\((?![^)]*\bsender\b)",
      "Devolver Task; async void solo en manejadores de eventos."),
    V("WEB-NET-004", "Bloque catch vacío", "media", CS,
      r"catch\s*(\(\s*\w*Exception(\s+\w+)?\s*\))?\s*\{\s*\}",
      "Registrar y relanzar, o manejar la excepción de dominio esperada; nunca ignorarla."),
    V("WEB-NET-005", "Log con interpolación de cadenas en lugar de plantilla", "baja", CS,
      r"\.Log(Information|Warning|Error|Debug|Critical|Trace)\s*\(\s*\$\"",
      "Plantilla con propiedades con nombre: LogInformation(\"Pedido {PedidoId}\", id)."),
    V("API-NET-002", "new HttpClient() en lugar de IHttpClientFactory", "media", CS,
      r"\bnew\s+HttpClient\s*\(",
      "Registrar un cliente tipado con AddHttpClient<TInterfaz, TImplementacion>()."),
    V("API-RES-001", "Respuesta 200 con un error en el cuerpo", "baja", CS,
      r"\bOk\s*\(\s*new\s*\{[^}]*\b(exito|success|ok|error)\s*=\s*(false|true)",
      "Devolver el código HTTP correcto (404, 422…) con Problem Details."),
    V("WEB-ANG-003", "Uso del tipo any en TypeScript", "baja", TS,
      r":\s*any\b|<any>|\bas\s+any\b",
      "Tipar con interfaces del modelo; si el tipo es desconocido, usar unknown con una verificación."),
    # ---------------------------------------------------------------------------------- SQL Server (EST-WEB-001)
    V("WEB-BD-009", "SELECT * (columnas no explícitas)", "media", CS_SQL + ("typescript",),
      r"\bSELECT\s+(TOP\s*\(?\d+\)?\s+)?\*",
      "Listar las columnas necesarias."),
    V("WEB-BD-009", "Función sobre una columna en el WHERE (impide usar índices)", "baja", SQL,
      r"\bWHERE\b.*\b(YEAR|MONTH|DAY|CONVERT|CAST|UPPER|LOWER|ISNULL)\s*\(\s*\w+",
      "Reescribir como rango sobre la columna (Fecha >= '2026-01-01' AND Fecha < '2027-01-01')."),
    V("WEB-BD-005", "Procedimiento almacenado con prefijo sp_", "media", SQL,
      r"CREATE\s+(OR\s+ALTER\s+)?PROC(EDURE)?\s+(\[?\w+\]?\.)?\[?sp_",
      "Nombrar usp_<Entidad>_<Accion> (sp_ está reservado para el sistema)."),
    V("WEB-BD-002", "Tabla con prefijo (TBL_, tbl) — nomenclatura anterior", "baja", SQL,
      r"CREATE\s+TABLE\s+(\[?\w+\]?\.)?\[?(tbl_?|T_)\w+",
      "Bases nuevas: PascalCase en singular sin prefijo (ventas.Cliente). En bases existentes con TBL_ se "
      "mantiene la nomenclatura de la base (EST-DSK-001)."),
    V("WEB-BD-001", "Objeto nuevo en el esquema dbo", "baja", SQL,
      r"CREATE\s+(TABLE|PROC|PROCEDURE|VIEW|FUNCTION)\s+(OR\s+ALTER\s+)?\[?dbo\]?\.",
      "Crear el objeto en el esquema del módulo (ventas, seguridad, maestro…)."),
    V("WEB-BD-006", "Tipo de dato no permitido (FLOAT/REAL/MONEY para montos, TEXT/NTEXT/IMAGE)", "media", SQL,
      r"^\s*\[?\w+\]?\s+(FLOAT|REAL|MONEY|SMALLMONEY|TEXT|NTEXT|IMAGE)\b",
      "Montos: DECIMAL(18,2). Texto largo: NVARCHAR(MAX). Binarios: VARBINARY(MAX).", flags=re.I | re.M),
    V("WEB-BD-004", "Restricción sin nombre explícito (PRIMARY KEY / REFERENCES en línea)", "baja", SQL,
      r"^(?!.*\bCONSTRAINT\b).*\b\w+\s+\w+.*\b(PRIMARY\s+KEY|REFERENCES)\b",
      "Declarar CONSTRAINT PK_<Tabla> / FK_<Hija>_<Padre> con nombre.", flags=re.I | re.M),
]


def _linea(codigo: str, pos: int) -> tuple[int, str]:
    n = codigo.count("\n", 0, pos) + 1
    return n, codigo.splitlines()[n - 1].strip()[:200] if codigo.splitlines() else ""


def verificar(codigo: str, lenguaje: str) -> list[Hallazgo]:
    hallazgos: list[Hallazgo] = []
    vistos: set[tuple[str, int]] = set()

    def agregar(regla_id, titulo, severidad, linea, evidencia, recomendacion):
        if (regla_id, linea) in vistos:
            return
        vistos.add((regla_id, linea))
        hallazgos.append(Hallazgo(regla_id=regla_id, titulo=titulo, severidad=severidad, origen="regla", linea=linea,
                                  evidencia=evidencia, explicacion=f"La línea {linea} incumple {regla_id}: {titulo}.",
                                  recomendacion=recomendacion, citas=[regla_id] if regla_id else []))

    for v in VERIFICADORES:
        if lenguaje not in v.lenguajes:
            continue
        for m in v.patron.finditer(codigo):
            n, texto = _linea(codigo, m.start())
            if v.excluir and v.excluir.search(texto):
                continue
            agregar(v.regla_id, v.titulo, v.severidad, n, texto, v.recomendacion)

    # Reglas que dependen del archivo completo, no de una línea
    if lenguaje == "sql":
        for m in re.finditer(r"CREATE\s+(OR\s+ALTER\s+)?PROC(EDURE)?\b", codigo, re.I):
            if not re.search(r"SET\s+NOCOUNT\s+ON", codigo[m.start():], re.I):
                n, texto = _linea(codigo, m.start())
                agregar("WEB-BD-008", "Procedimiento sin SET NOCOUNT ON / manejo de errores", "baja", n, texto,
                        "Iniciar con SET NOCOUNT ON; SET XACT_ABORT ON; y usar TRY/CATCH con THROW.")
    if lenguaje == "typescript" and "@Component" in codigo:
        m = re.search(r"(private|public|protected|readonly)\s+\w+\s*:\s*HttpClient\b|inject\(\s*HttpClient\s*\)", codigo)
        if m:
            n, texto = _linea(codigo, m.start())
            agregar("WEB-ANG-004", "El componente usa HttpClient directamente", "media", n, texto,
                    "Mover la llamada HTTP a un servicio de la funcionalidad y consumirlo con el pipe async.")
    for n in hay_secretos(codigo):
        agregar("SEG-CRI-003", "Secreto escrito en el código (contraseña, clave o token)", "critica", n,
                "[valor oculto]", "Leerlo de Azure Key Vault (producción) o dotnet user-secrets (desarrollo); "
                "rotar el secreto expuesto.")
    det = inyeccion.detectar(codigo)
    if det.sospechoso:
        for n in det.lineas[:3]:
            agregar("", "Comentario o texto que intenta manipular la revisión automática", "alta", n,
                    _linea(codigo, sum(len(l) + 1 for l in codigo.splitlines()[:n - 1]))[1],
                    "Eliminar el texto. Un revisor humano debe confirmar este reporte.")
    orden = {"critica": 0, "alta": 1, "media": 2, "baja": 3}
    return sorted(hallazgos, key=lambda h: (orden[h.severidad], h.linea or 0))
