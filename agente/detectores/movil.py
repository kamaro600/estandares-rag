"""Detectores móviles (EST-SEG-001 cap. 11): Android con Kotlin, iOS con Swift y sus manifiestos.

Estos archivos se evalúan siempre con las reglas de Móvil (ver es_movil y contexto_para).
"""
from __future__ import annotations

import re

from agente.detectores import Archivo, Patron, es_movil, registrar, registrar_archivo
from agente.detectores.web import SENSIBLE

I = re.IGNORECASE
KT, SW, XML = ("kotlin",), ("swift",), ("xml",)


def _sin(*textos: str):
    """El patrón solo cuenta si el archivo NO contiene ninguno de estos textos (el control ya existe)."""
    return lambda m, a: not any(t in a.contenido for t in textos)


def _con(texto: str):
    return lambda m, a: texto in a.contenido


# ---------------------------------------------------------------- Android (Kotlin y Gradle)
registrar(
    Patron("KT-PREFS-SENSIBLE", KT, ("SEG-MOV-001",),
           re.compile(r"\.put(String|StringSet)?\(\s*\"[^\"]*" + SENSIBLE, I),
           "Token o credencial en SharedPreferences: usa Android Keystore o EncryptedSharedPreferences.",
           verificar=_sin("EncryptedSharedPreferences")),
    Patron("KT-HOSTNAME-CUALQUIERA", KT, ("SEG-MOV-003",),
           re.compile(r"hostnameVerifier\s*\{\s*_\s*,\s*_\s*->\s*true\s*\}|HostnameVerifier\s*\{\s*_\s*,\s*_\s*->\s*true|"
                      r"ALLOW_ALL_HOSTNAME_VERIFIER|NoopHostnameVerifier", I),
           "Se acepta cualquier nombre de host: nunca se desactiva la validación TLS.",
           relacionadas=("SEG-CRI-004",)),
    Patron("KT-WEBVIEW-JS", KT, ("SEG-MOV-005",),
           re.compile(r"javaScriptEnabled\s*=\s*true|setJavaScriptEnabled\(\s*true\s*\)"),
           "WebView con JavaScript habilitado: solo con necesidad documentada y dominios de la empresa.",
           confianza="media"),
    Patron("KT-WEBVIEW-PUENTE", KT, ("SEG-MOV-005",),
           re.compile(r"addJavascriptInterface\s*\(|allowFileAccess\s*=\s*true|setAllowFileAccess\(\s*true|"
                      r"allowUniversalAccessFromFileURLs"),
           "Puente JavaScript-nativo o acceso a archivos en un WebView: no se expone a contenido no confiable.",
           confianza="media"),
    Patron("KT-BIOMETRIA-SIN-CLAVE", KT, ("SEG-MOV-004",), re.compile(r"\.authenticate\(\s*\w+\s*\)"),
           "BiometricPrompt sin CryptoObject: la biometría debe desbloquear una clave del Keystore.",
           confianza="media", verificar=_con("BiometricPrompt")),
    Patron("KT-RANDOM", KT, ("SEG-CRI-002",),
           re.compile(r"(?<!Secure)\bRandom\(\s*\)|\bRandom\.next(Int|Long|Bytes)\(|kotlin\.random\.Random"),
           "Random no sirve para tokens, códigos o claves: usa SecureRandom.", confianza="media"),
    Patron("GRADLE-SIN-OFUSCAR", KT, ("SEG-MOV-006",), re.compile(r"isMinifyEnabled\s*=\s*false|minifyEnabled\s+false"),
           "Compilación sin ofuscación (R8): las apps transaccionales ofuscan el código.", confianza="media"),
    Patron("GRADLE-DEPURABLE", KT, ("SEG-MOV-006",), re.compile(r"isDebuggable\s*=\s*true|debuggable\s+true"),
           "Compilación depurable: facilita la instrumentación de la app."),
)


@registrar_archivo("kotlin")
def _kotlin(a: Archivo, ctx) -> list[dict]:
    hallazgos = []
    for n, l in enumerate(a.lineas, 1):
        if re.search(r"override\s+fun\s+checkServerTrusted\s*\(", l):
            cuerpo = "".join(a.lineas[n - 1:n + 2])
            if re.search(r"checkServerTrusted\s*\([^)]*\)\s*(\{\s*\}|=\s*Unit|\{\s*(//[^\n]*)?\s*\})", cuerpo):
                hallazgos.append(dict(codigo="KT-TRUST-CUALQUIERA", linea=n, reglas=("SEG-MOV-003",),
                                      relacionadas=("SEG-CRI-004",),
                                      mensaje="TrustManager que acepta cualquier certificado: usa la validación "
                                              "del sistema y certificate pinning."))
        m = re.search(r"class\s+(\w+)\s*:\s*(AppCompatActivity|ComponentActivity|FragmentActivity|Activity)\s*\(", l)
        if m and "FLAG_SECURE" not in a.contenido:
            hallazgos.append(dict(codigo="KT-SIN-FLAG-SECURE", linea=n, reglas=("SEG-MOV-002",), confianza="media",
                                  mensaje=f"{m.group(1)} no usa FLAG_SECURE: si muestra datos sensibles, impide "
                                          "capturas de pantalla."))
    return hallazgos


# ---------------------------------------------------------------- iOS (Swift)
registrar(
    Patron("SW-USERDEFAULTS-SENSIBLE", SW, ("SEG-MOV-001",),
           re.compile(r"UserDefaults(\.standard)?\.set\(.*forKey:\s*\"[^\"]*" + SENSIBLE + r"|@AppStorage\(\s*\"[^\"]*"
                      + SENSIBLE, I),
           "Token o credencial en UserDefaults: usa el Keychain."),
    Patron("SW-TRUST-CUALQUIERA", SW, ("SEG-MOV-003",),
           re.compile(r"completionHandler\(\s*\.useCredential\s*,\s*URLCredential\(\s*trust:"),
           "Se acepta el certificado del servidor sin evaluarlo ni comparar el pin.",
           relacionadas=("SEG-CRI-004",), verificar=_sin("SecTrustEvaluate", "pinn", "Pinn")),
    Patron("SW-TLS-DESACTIVADO", SW, ("SEG-MOV-003",),
           re.compile(r"DisabledEvaluator|DisabledTrustEvaluator|\.disableEvaluation|allowsInvalidSSLCertificate\s*=\s*true|"
                      r"validatesDomainName\s*=\s*false"),
           "Validación TLS desactivada.", relacionadas=("SEG-CRI-004",)),
    Patron("SW-WEBVIEW-JS", SW, ("SEG-MOV-005",),
           re.compile(r"javaScriptEnabled\s*=\s*true|allowsContentJavaScript\s*=\s*true"),
           "WKWebView con JavaScript habilitado: solo con necesidad documentada y dominios de la empresa.",
           confianza="media"),
    Patron("SW-WEBVIEW-PUENTE", SW, ("SEG-MOV-005",), re.compile(r"\.add\(\s*\w+\s*,\s*name:\s*\""),
           "Puente JavaScript-nativo (WKScriptMessageHandler): no se expone a contenido no confiable.",
           confianza="media"),
    Patron("SW-BIOMETRIA-BOOLEANA", SW, ("SEG-MOV-004",), re.compile(r"\.evaluatePolicy\s*\("),
           "LAContext.evaluatePolicy devuelve un booleano: la biometría debe proteger un ítem del Keychain "
           "(SecAccessControl con .biometryCurrentSet).", confianza="media",
           verificar=_sin("SecAccessControl", "biometryCurrentSet")),
)

# ---------------------------------------------------------------- Manifiestos (AndroidManifest, red, Info.plist)
PERMISOS_SENSIBLES = ("READ_CONTACTS|READ_SMS|RECEIVE_SMS|READ_CALL_LOG|ACCESS_FINE_LOCATION|ACCESS_BACKGROUND_LOCATION|"
                      "RECORD_AUDIO|READ_PHONE_STATE|READ_EXTERNAL_STORAGE|WRITE_EXTERNAL_STORAGE|MANAGE_EXTERNAL_STORAGE|"
                      "QUERY_ALL_PACKAGES|BODY_SENSORS|CAMERA|READ_MEDIA_IMAGES")
_movil = lambda m, a: es_movil(a)   # noqa: E731

registrar(
    Patron("AND-TRAFICO-CLARO", XML, ("SEG-MOV-003",),
           re.compile(r"usesCleartextTraffic=\"true\"|cleartextTrafficPermitted=\"true\""),
           "Tráfico HTTP sin cifrar permitido: la app usa solo HTTPS.", relacionadas=("SEG-CRI-004",),
           verificar=_movil),
    Patron("AND-CA-USUARIO", XML, ("SEG-MOV-003",), re.compile(r"<certificates\s+src=\"user\""),
           "Se confía en certificados instalados por el usuario: permite interceptar el tráfico.", verificar=_movil),
    Patron("AND-BACKUP", XML, ("SEG-MOV-002",), re.compile(r"android:allowBackup=\"true\""),
           "Copia de seguridad habilitada: los datos de la app salen del dispositivo.", confianza="media",
           verificar=_movil),
    Patron("AND-DEPURABLE", XML, ("SEG-MOV-006",), re.compile(r"android:debuggable=\"true\""),
           "App depurable: facilita la instrumentación.", verificar=_movil),
    Patron("AND-PERMISO", XML, ("SEG-MOV-008",),
           re.compile(r"<uses-permission[^>]*android\.permission\.(" + PERMISOS_SENSIBLES + r")\b"),
           "Permiso sensible: confirma que es imprescindible y que se pide en el momento en que se usa.",
           confianza="media", verificar=_movil),
)


@registrar_archivo("xml")
def _manifiestos(a: Archivo, ctx) -> list[dict]:
    if not es_movil(a):
        return []
    hallazgos, texto = [], a.contenido
    for n, l in enumerate(a.lineas, 1):
        if "NSAllowsArbitraryLoads" in l or "NSExceptionAllowsInsecureHTTPLoads" in l:
            if "<true/>" in "".join(a.lineas[n - 1:n + 1]):
                hallazgos.append(dict(codigo="IOS-ATS-DESACTIVADO", linea=n, reglas=("SEG-MOV-003",),
                                      relacionadas=("SEG-CRI-004",),
                                      mensaje="App Transport Security desactivado: la app usa solo HTTPS."))
    if "<domain-config" in texto and "<pin-set" not in texto:
        n = texto[:texto.index("<domain-config")].count("\n") + 1
        hallazgos.append(dict(codigo="AND-SIN-PINNING", linea=n, reglas=("SEG-MOV-003",), confianza="media",
                              mensaje="Configuración de red sin <pin-set>: las APIs de la empresa usan certificate "
                                      "pinning con un pin de respaldo."))
    return hallazgos
