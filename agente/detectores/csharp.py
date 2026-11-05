"""Detectores de C#: ASP.NET Core (EST-WEB/EST-API), WPF/WinForms (EST-DSK), MAUI y EST-SEG."""
from __future__ import annotations

import re

from agente.detectores import Archivo, Patron, registrar, registrar_archivo

CS = ("csharp",)
I = re.IGNORECASE


def _log_plantilla(linea: str, m: re.Match) -> str | None:
    """_logger.LogInformation($"Pedido {pedido.Id} por {usuario}")  →  plantilla + argumentos."""
    inicio = m.end() - 2  # posición de $"
    fin = linea.find('"', inicio + 2)
    if fin < 0 or linea[fin + 1:fin + 2] not in (")", ","):
        return None
    texto = linea[inicio + 2:fin]
    expresiones = re.findall(r"\{([^{}:]+)(?::[^{}]*)?\}", texto)
    if not expresiones:
        return None
    nombres = []
    for e in expresiones:
        partes = re.findall(r"[A-Za-z_]\w*", e)
        nombre = "".join(p[:1].upper() + p[1:] for p in partes[-2:]) if partes else "Valor"
        nombres.append(nombre)
    plantilla = texto
    for e, n in zip(expresiones, nombres):
        plantilla = re.sub(r"\{" + re.escape(e) + r"(?::[^{}]*)?\}", "{" + n + "}", plantilla, count=1)
    args = ", ".join(e.strip() for e in expresiones)
    return linea[:inicio] + f'"{plantilla}", {args}' + linea[fin + 1:]


def _random_seguro(linea: str, m: re.Match) -> str | None:
    nuevo = re.sub(r"new\s+Random\s*\(\s*\)\s*\.Next\s*\(", "RandomNumberGenerator.GetInt32(", linea)
    return nuevo if nuevo != linea else None


def _validacion_true(linea: str, m: re.Match) -> str:
    return re.sub(r"(\b(?:Validate\w+|Require\w+)\s*=\s*)false\b", r"\1true", linea)


def _cookie_segura(linea: str, m: re.Match) -> str | None:
    mm = re.search(r"Cookies\.Append\(\s*([^,()]+),\s*([^,()]+)\)", linea)
    if not mm:
        return None
    opciones = ("new CookieOptions { Secure = true, HttpOnly = true, SameSite = SameSiteMode.Strict }")
    return linea[:mm.start()] + f"Cookies.Append({mm.group(1).strip()}, {mm.group(2).strip()}, {opciones})" + linea[mm.end():]


def _no_es_manejador(m: re.Match, a: Archivo) -> bool:
    return "EventArgs" not in m.group(2)


class _Ruta:
    """Une los dos grupos posibles ([Route("…")] o .MapGet("…")) en group(2)."""
    def __init__(self, m: re.Match):
        self._ruta = m.group(2) if m.group(2) is not None else m.group(4)

    def group(self, i: int) -> str:
        return self._ruta


VERBOS_URL = re.compile(r"(^|/)(obtener|listar|eliminar|crear|actualizar|buscar|registrar|get|delete|update|create)", I)


def _ruta_no_estandar(m: re.Match, a: Archivo) -> bool:
    """API-DIS-001: /api/v{n}/recursos-en-plural, minúsculas, kebab-case, sin verbos ni extensiones."""
    ruta = m.group(2).strip("/")
    if not ruta.startswith("api"):
        ruta_rel = ruta  # [HttpGet("{clienteId}")] es relativa al [Route] del controlador
        return bool(re.search(r"[A-Z]", re.sub(r"\{[^}]*\}", "", ruta_rel)) or VERBOS_URL.search(ruta_rel)
                    or ruta_rel.endswith(".json"))
    sin_parametros = re.sub(r"\{[^}]*\}", "", ruta)
    return (not re.match(r"api/v\d+(/|$)", ruta) or bool(re.search(r"[A-Z_]", sin_parametros))
            or bool(VERBOS_URL.search(sin_parametros)) or ruta.endswith(".json"))


SENSIBLE = r"(clave|password|contrase\w*|token|pin|tarjeta|cvv|secret\w*|otp|codigo\w*)"

registrar(
    # --- Asincronía (WEB-NET-002 / DSK-NET-002) ---
    Patron("CS-ASYNC-BLOQUEO", CS, ("WEB-NET-002", "DSK-NET-002"),
           re.compile(r"\.Result\b(?!\s*=)|\.Wait\(\s*\)|GetAwaiter\(\)\.GetResult\(\)"),
           "Bloqueo sincrónico sobre una tarea (.Result/.Wait()): usa await y propaga async."),
    Patron("CS-THREAD-SLEEP", CS, ("DSK-NET-002",), re.compile(r"\bThread\.Sleep\s*\("),
           "Thread.Sleep congela la interfaz: usa await Task.Delay(...)."),
    Patron("CS-ASYNC-VOID", CS, ("WEB-NET-002", "DSK-NET-002"),
           re.compile(r"\basync\s+void\s+(\w+)\s*\(([^)]*)\)"),
           "async void fuera de un manejador de eventos: devuelve Task.", verificar=_no_es_manejador),
    # --- Excepciones y logging (WEB-NET-004 / WEB-NET-005 / SEG-LOG-001) ---
    Patron("CS-CATCH-VACIO", CS, ("WEB-NET-004",),
           re.compile(r"\bcatch\s*(\(\s*(System\.)?Exception(\s+\w+)?\s*\))?\s*\{\s*\}"),
           "Bloque catch vacío: la excepción se pierde. Regístrala y relánzala o modela el error."),
    Patron("CS-LOG-INTERPOLADO", CS, ("WEB-NET-005",),
           re.compile(r"\.Log(?:Trace|Debug|Information|Warning|Error|Critical)\(\s*(?:\w+\s*,\s*)?\$\""),
           "Mensaje de log interpolado: usa plantilla con propiedades con nombre.",
           autofix=_log_plantilla),
    Patron("CS-CONSOLE", CS, ("WEB-NET-005",), re.compile(r"\bConsole\.Write(Line)?\s*\("),
           "Console.WriteLine no es logging: usa ILogger<T>.", confianza="media"),
    Patron("CS-LOG-SENSIBLE", CS, ("SEG-LOG-001",),
           re.compile(r"\.Log\w*\(.*\{\s*" + SENSIBLE + r"\s*\}", I),
           "Dato sensible en el log (clave, token, código…): no se registra o se enmascara.",
           relacionadas=("WEB-NET-005", "DSK-NET-005")),
    # --- Inyección SQL (SEG-INY-001, WEB-BD-010, DSK-BD-006) ---
    Patron("CS-SQL-CONCAT", CS, ("SEG-INY-001",),
           re.compile(r"\"[^\"]*\b(SELECT|INSERT|UPDATE|DELETE|EXEC|WHERE)\b[^\"]*\"\s*\+|"
                      r"new\s+SqlCommand\(\s*\"[^\"]*\"\s*\+|(FromSqlRaw|ExecuteSqlRaw)\s*\([^;]*(\+|\$\")", I),
           "SQL construido concatenando valores: usa parámetros (SqlParameter / FromSql interpolado).",
           relacionadas=("WEB-BD-010", "DSK-BD-006")),
    Patron("CS-SELECT-ASTERISCO", CS, ("WEB-BD-009",), re.compile(r"\"\s*SELECT\s+(TOP\s*\(?\d+\)?\s+)?\*", I),
           "SELECT * en el código de aplicación: lista las columnas."),
    Patron("CS-SQL-INTERPOLADO", CS, ("SEG-INY-001",),
           re.compile(r"\$\"[^\"]*\b(SELECT|INSERT|UPDATE|DELETE)\b[^\"]*\{", I),
           "SQL interpolado en una cadena: solo FromSql/FromSqlInterpolated lo parametrizan.",
           excluir=re.compile(r"\bFromSql(Interpolated)?\s*\(|\bSqlQuery\s*\(|ExecuteSql(Interpolated)?\s*\("),
           relacionadas=("WEB-BD-010",)),
    # --- Criptografía y aleatorios (SEG-CRI-001 / SEG-CRI-002 / SEG-AUT-002) ---
    Patron("CS-CRIPTO-DEBIL", CS, ("SEG-CRI-001",),
           re.compile(r"\b(MD5|SHA1|DES|TripleDES|RC2)\.Create\s*\(|\bnew\s+(MD5|SHA1)CryptoServiceProvider|"
                      r"CipherMode\.ECB|\bRC4\b"),
           "Algoritmo criptográfico prohibido (MD5, SHA-1, DES, 3DES, RC4 o modo ECB).",
           relacionadas=("SEG-AUT-002",)),
    Patron("CS-RANDOM", CS, ("SEG-CRI-002",), re.compile(r"\bnew\s+Random\s*\("),
           "System.Random no sirve para tokens, códigos o claves: usa RandomNumberGenerator.",
           confianza="media", autofix=_random_seguro),
    # --- Secretos y configuración (SEG-CRI-003 / SEG-GEN-002) ---
    Patron("CS-SECRETO-CADENA", CS, ("SEG-CRI-003",),
           re.compile(r"\"[^\"]*\b(password|pwd)\s*=\s*[^;\"]+", I),
           "Contraseña dentro del código: va en Key Vault (o user-secrets en desarrollo).",
           relacionadas=("DSK-ARQ-004", "SEG-DSK-002")),
    Patron("CS-SECRETO-LITERAL", CS, ("SEG-CRI-003",),
           re.compile(r"\b(api_?key|client_?secret|secret|password)\w*\s*=\s*\"[^\"]{6,}\"", I),
           "Secreto escrito en el código: léelo de la configuración segura."),
    Patron("CS-USUARIO-SA", CS, ("SEG-GEN-002",), re.compile(r"\buser\s*id\s*=\s*sa\b", I),
           "Conexión con el usuario sa: cada aplicación usa su propio usuario con mínimo privilegio.",
           relacionadas=("WEB-BD-012",)),
    # --- Deserialización y XML (SEG-INY-005 / SEG-INY-006) ---
    Patron("CS-DESERIALIZACION", CS, ("SEG-INY-005",),
           re.compile(r"\b(BinaryFormatter|SoapFormatter|NetDataContractSerializer|LosFormatter)\b|"
                      r"TypeNameHandling\.(All|Auto|Objects|Arrays)"),
           "Deserializador inseguro prohibido: usa System.Text.Json."),
    Patron("CS-XXE", CS, ("SEG-INY-006",),
           re.compile(r"DtdProcessing\s*=\s*DtdProcessing\.Parse|XmlResolver\s*=\s*new\s+XmlUrlResolver"),
           "Lector XML con DTD o entidades externas habilitadas (XXE)."),
    Patron("CS-COMANDO-SO", CS, ("SEG-INY-004",),
           re.compile(r"Process\.Start\([^;]*\+|\"(cmd|powershell)(\.exe)?\"", I),
           "Comando del sistema construido con datos: usa un ejecutable fijo y ArgumentList."),
    # --- Autenticación, sesión, CORS, TLS ---
    Patron("CS-JWT-SIN-VALIDAR", CS, ("SEG-AUT-006",),
           re.compile(r"\b(ValidateIssuer|ValidateAudience|ValidateLifetime|ValidateIssuerSigningKey|"
                      r"RequireSignedTokens|RequireExpirationTime)\s*=\s*false\b"),
           "Validación de JWT desactivada: firma, emisor, audiencia y vigencia se validan siempre.",
           relacionadas=("API-SEG-001",), autofix=_validacion_true),
    Patron("CS-COOKIE-INSEGURA", CS, ("SEG-AUT-005",),
           re.compile(r"Cookies\.Append\(\s*[^,()]+,\s*[^,()]+\)\s*;"),
           "Cookie sin Secure, HttpOnly ni SameSite.", autofix=_cookie_segura),
    Patron("CS-CORS-ABIERTO", CS, ("SEG-CFG-002",),
           re.compile(r"\.AllowAnyOrigin\(\)|SetIsOriginAllowed\(\s*\w*\s*=>\s*true\s*\)"),
           "CORS abierto o que refleja el origen: usa una lista blanca por entorno."),
    Patron("CS-CERT-CUALQUIERA", CS, ("SEG-MOV-003", "SEG-CRI-004"),
           re.compile(r"ServerCertificateCustomValidationCallback\s*=.*=>\s*true|"
                      r"DangerousAcceptAnyServerCertificateValidator"),
           "Se acepta cualquier certificado TLS: nunca se desactiva la validación.",
           relacionadas=("API-NET-002",)),
    Patron("CS-HTML-RAW", CS, ("SEG-INY-003",), re.compile(r"Html\.Raw\s*\("),
           "Html.Raw con datos no confiables permite XSS.", confianza="media"),
    Patron("CS-PREFERENCES-TOKEN", CS, ("SEG-MOV-001",),
           re.compile(r"Preferences(\.Default)?\.Set\(\s*\"[^\"]*" + SENSIBLE, I),
           "Token o credencial en Preferences: usa SecureStorage."),
    # --- APIs (EST-API-001) ---
    Patron("CS-NEW-HTTPCLIENT", CS, ("API-NET-002",), re.compile(r"\bnew\s+HttpClient\s*\("),
           "new HttpClient() por petición agota los sockets: usa IHttpClientFactory (cliente tipado)."),
    Patron("CS-RUTA-API", CS, ("API-DIS-001",),
           re.compile(r"\[(Route|HttpGet|HttpPost|HttpPut|HttpPatch|HttpDelete)\(\s*\"([^\"]*)\"|"
                      r"\.Map(Get|Post|Put|Patch|Delete)\(\s*\"([^\"]*)\""),
           "Ruta fuera del estándar: /api/v{n}/sustantivos-en-plural, minúsculas, kebab-case, sin verbos.",
           relacionadas=("API-VER-001",),
           verificar=lambda m, a: _ruta_no_estandar(_Ruta(m), a)),
    Patron("CS-OK-CON-ERROR", CS, ("API-RES-001",),
           re.compile(r"\bOk\(\s*new\s*\{[^}]*\b(exito|success|ok)\s*=\s*false", I),
           "200 con un error en el cuerpo: devuelve el código HTTP correcto (404, 422…)."),
    # --- Nomenclatura C# (WEB-NET-001 / DSK-NET-001) ---
    Patron("CS-NOMBRE-TIPO", CS, ("WEB-NET-001", "DSK-NET-001"),
           re.compile(r"\b(class|record|struct|enum)\s+([a-z_]\w*)"),
           "Tipo que no está en PascalCase."),
    Patron("CS-NOMBRE-INTERFAZ", CS, ("WEB-NET-001", "DSK-NET-001"),
           re.compile(r"\binterface\s+(?!I[A-Z])(\w+)"), "Interfaz sin el prefijo I."),
    Patron("CS-NOMBRE-METODO", CS, ("WEB-NET-001", "DSK-NET-001"),
           re.compile(r"^\s*(public|private|protected|internal)\s+(static\s+|virtual\s+|override\s+|async\s+)*"
                      r"[\w<>\[\]?,.]+\s+([a-z]\w*)\s*\("),
           "Método que no está en PascalCase.",
           excluir=re.compile(r"\(\s*object\s+\w+\s*,\s*\w*EventArgs")),  # btnGuardar_Click es el patrón del estándar
    Patron("CS-SUFIJO-ASYNC", CS, ("WEB-NET-001",),
           re.compile(r"^\s*(public|private|protected|internal)\s+(static\s+|virtual\s+|override\s+)*async\s+"
                      r"(Task|ValueTask)(<.+>)?\s+(?!\w*Async\b)(\w+)\s*\("),
           "Método asíncrono sin el sufijo Async.", confianza="media",
           excluir=re.compile(r"\bI?ActionResult\b|\bIResult\b")),  # acciones de controlador: los ejemplos de EST-API no lo usan
    Patron("CS-CAMPO-PRIVADO", CS, ("WEB-NET-001", "DSK-NET-001"),
           re.compile(r"^\s*private\s+(readonly\s+)?(?!const\b|static\b)[\w<>\[\]?,.]+\s+(?!_)([a-zA-Z]\w*)\s*(;|=)"),
           "Campo privado que no usa _camelCase.", confianza="media"),
    Patron("CS-HUNGARA", CS, ("WEB-NET-001",),
           re.compile(r"\b(string|int|bool|object|decimal)\s+(str|int|bln|bool|obj|dec)[A-Z]\w*"),
           "Notación húngara (strNombre): está prohibida."),
    # --- Entity Framework Core (EST-WEB/EST-API: acceso a datos) ---
    Patron("EF-SAVE-EN-BUCLE", CS, ("WEB-BD-012", "API-NET-001"),
           re.compile(r"\b(for|foreach|while)\b[^{]*\{[^}]*\bSaveChanges(Async)?\s*\("),
           "SaveChanges dentro de un bucle: acumula cambios y guarda una vez fuera del bucle.",
           confianza="media"),
    Patron("EF-ENSURE-CREATED", CS, ("WEB-BD-012",),
           re.compile(r"\bEnsureCreated(Async)?\s*\("),
           "EnsureCreated crea el esquema sin migraciones: usa Migrate() / migraciones versionadas."),
    Patron("EF-LAZY-LOADING", CS, ("WEB-BD-009", "API-NET-001"),
           re.compile(r"\.UseLazyLoadingProxies\s*\("),
           "Lazy loading activado: provoca N+1; proyecta con Select o usa Include explícito."),
    Patron("EF-RAW-SQL", CS, ("SEG-INY-001", "WEB-BD-010"),
           re.compile(r"\b(FromSqlRaw|ExecuteSqlRaw|ExecuteSqlRawAsync|SqlQueryRaw)\s*\([^;]*(\+|\$\")"),
           "SQL crudo con concatenación/interpolación en EF: usa FromSql/FromSqlInterpolated (parametrizado)."),
    Patron("EF-MIGRATION-DROP", CS, ("WEB-BD-003",),
           re.compile(r"\b(DropColumn|DropTable|DropIndex)\s*\("),
           "Migración que elimina columna/tabla/índice: revisa pérdida de datos y haz respaldo previo.",
           confianza="media"),
    Patron("EF-TRACKING-EN-LECTURA", CS, ("WEB-BD-009",),
           re.compile(r"\.ToList(Async)?\s*\(\s*\)\s*;"),
           "Consulta de lectura sin AsNoTracking(): añade AsNoTracking() si no vas a modificar las entidades.",
           confianza="baja"),
)


@registrar_archivo("csharp")
def _controladores(a: Archivo, ctx) -> list[dict]:
    """Reglas que miran el archivo entero: controladores de API y code-behind de WPF."""
    texto = a.contenido
    hallazgos = []
    es_controlador = ("[ApiController]" in texto or re.search(r":\s*(Controller|ControllerBase)\b", texto)
                      or re.search(r"\[Http(Get|Post|Put|Patch|Delete)\b", texto))
    if es_controlador:
        if "[Authorize" not in texto and "RequireAuthorization" not in texto:
            for n, l in enumerate(a.lineas, 1):
                if re.search(r"\[Http(Post|Put|Patch|Delete)\b", l):
                    hallazgos.append(dict(codigo="CS-API-SIN-AUTHORIZE", linea=n, reglas=("API-SEG-002",),
                                          mensaje="Operación de escritura sin [Authorize(Policy=...)] en la acción ni en el controlador.",
                                          confianza="media", relacionadas=("SEG-ACC-001",)))
        for n, l in enumerate(a.lineas, 1):
            if re.search(r"\b_?\w*[cC]onte(xt|xto)\.\w+\.(Add|Update|Remove|Find\w*|Where|ToList\w*)\b|"
                         r"\b_?\w*[cC]onte(xt|xto)\.(SaveChanges\w*|Update|Add|Remove)\(", l):
                hallazgos.append(dict(codigo="CS-API-DBCONTEXT", linea=n, reglas=("API-NET-001",),
                                      mensaje="El controlador accede al DbContext: delega en un caso de uso de Application.",
                                      confianza="media", relacionadas=("WEB-ARQ-001",)))
                break
    if a.nombre.lower().endswith(".xaml.cs"):
        for n, l in enumerate(a.lineas, 1):
            if re.search(r"\bnew\s+Sql(Connection|Command)\b", l):
                hallazgos.append(dict(codigo="CS-CODEBEHIND-DATOS", linea=n, reglas=("DSK-ARQ-002",),
                                      mensaje="Acceso a datos en el code-behind: va en el ViewModel/servicio (MVVM).",
                                      relacionadas=("DSK-ARQ-003",)))
    return hallazgos
