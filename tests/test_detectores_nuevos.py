"""Lenguajes del alcance de EST-SEG-001 §2 que no son C#/TS/SQL: móvil, Razor, JavaScript, YAML y XML.

Cada ejemplo de ejemplos/ tiene incumplimientos deliberados; cada versión correcta no debe marcar nada.
"""
from pathlib import Path

import pytest

from agente.contexto import Contexto, contexto_para
from agente.detectores import Archivo, analizar

RAIZ = Path(__file__).parent.parent


def _detectores(nombre: str, contenido: str | None = None, tipo_app: str = "web") -> set[str]:
    a = Archivo(nombre, contenido if contenido is not None else (RAIZ / nombre).read_text(encoding="utf-8"))
    return {h.detector for h in analizar(a, contexto_para(a, Contexto(tipo_app, "nueva")))}


@pytest.mark.parametrize("nombre,esperados", [
    ("ejemplos/movil/android/LoginActivity.kt", {"GEN-SECRETO-LITERAL", "GEN-HTTP-PLANO", "KT-SIN-FLAG-SECURE",
     "KT-WEBVIEW-JS", "KT-WEBVIEW-PUENTE", "KT-PREFS-SENSIBLE", "GEN-LOG-SENSIBLE", "GEN-CRIPTO-DEBIL",
     "KT-TRUST-CUALQUIERA"}),
    ("ejemplos/movil/android/AndroidManifest.xml", {"AND-PERMISO", "AND-BACKUP", "AND-TRAFICO-CLARO", "AND-DEPURABLE"}),
    ("ejemplos/movil/android/network_security_config.xml", {"AND-SIN-PINNING", "AND-CA-USUARIO"}),
    ("ejemplos/movil/android/build.gradle.kts", {"GRADLE-SIN-OFUSCAR", "GRADLE-DEPURABLE"}),
    ("ejemplos/movil/ios/SesionManager.swift", {"GEN-HTTP-PLANO", "SW-USERDEFAULTS-SENSIBLE", "GEN-LOG-SENSIBLE",
     "SW-TRUST-CUALQUIERA", "SW-BIOMETRIA-BOOLEANA", "GEN-CRIPTO-DEBIL", "SW-WEBVIEW-JS"}),
    ("ejemplos/movil/ios/Info.plist", {"IOS-ATS-DESACTIVADO"}),
    ("ejemplos/web/razor/Comentarios.cshtml", {"RAZOR-HTML-RAW", "RAZOR-EVENTO-EN-LINEA", "RAZOR-SCRIPT-EN-LINEA"}),
    ("ejemplos/web/js/sesion.js", {"JS-TOKEN-STORAGE", "GEN-LOG-SENSIBLE", "JS-INNERHTML", "JS-MATH-RANDOM", "JS-EVAL"}),
    ("ejemplos/api/openapi.yaml", {"YAML-HTTP-PLANO", "OPENAPI-RUTA", "OPENAPI-OPERACION"}),
    ("ejemplos/pipeline/azure-pipelines.yml", {"PIPELINE-SAST", "YAML-SECRETO", "PIPELINE-DEPENDENCIAS"}),
    ("ejemplos/escritorio/Textos.resx", {"XML-SECRETO", "CFG-PASSWORD", "CFG-SIN-CIFRADO", "CFG-USUARIO-SA"}),
])
def test_ejemplos_incorrectos(nombre, esperados):
    assert _detectores(nombre) == esperados


@pytest.mark.parametrize("nombre,contenido", [
    ("Login.kt", 'val prefs = EncryptedSharedPreferences.create(ctx, "s", llave, a, b)\n'
                 'prefs.edit().putString("access_token", token).apply()\n'
                 'window.setFlags(WindowManager.LayoutParams.FLAG_SECURE, WindowManager.LayoutParams.FLAG_SECURE)\n'
                 'class LoginActivity : AppCompatActivity() {}\n'
                 'val url = "https://api.empresa.pe/v1"\nLog.d("Login", "Sesión iniciada")\n'
                 'val digest = MessageDigest.getInstance("SHA-256")\nval r = SecureRandom()'),
    ("Sesion.swift", 'let ok = SecItemAdd(consulta as CFDictionary, nil)\nlet url = "https://api.empresa.pe"\n'
                     'print("Sesión iniciada")\nlet h = SHA256.hash(data: datos)'),
    ("AndroidManifest.xml", '<manifest xmlns:android="http://schemas.android.com/apk/res/android">\n'
                            '<uses-permission android:name="android.permission.INTERNET" />\n'
                            '<application android:allowBackup="false" android:label="Banca" />'),
    ("network_security_config.xml", '<domain-config cleartextTrafficPermitted="false">\n<pin-set>\n'
                                    '<pin digest="SHA-256">abc=</pin>\n</pin-set>\n</domain-config>'),
    ("Info.plist", "<key>NSAppTransportSecurity</key>\n<dict>\n<key>NSAllowsArbitraryLoads</key>\n<false/>\n</dict>"),
    ("Index.cshtml", '<div>@c.Texto</div>\n<script src="~/js/sitio.js"></script>\n<button @onclick="Enviar">Ok</button>'),
    ("sesion.js", "contenedor.textContent = texto;\nconst v = crypto.getRandomValues(new Uint32Array(1));\n"
                  "console.log('Sesión iniciada');\nlocalStorage.setItem('tema', 'oscuro');"),
    ("openapi.yaml", "openapi: 3.0.3\nservers:\n  - url: https://api.empresa.pe/api/v1\npaths:\n  /clientes/{clienteId}:\n"
                     "    get:\n      summary: Un cliente\n      responses:\n        '200':\n          description: OK\n"
                     "        '404':\n          description: No existe"),
    ("azure-pipelines.yml", "trigger:\n  - main\nvariables:\n  sqlPassword: $(SqlPassword)\nsteps:\n"
                            "  - script: npm ci && npm audit --audit-level=high\n  - task: SonarQubeAnalyze@5"),
    ("Textos.resx", '<data name="TituloVentana" xml:space="preserve">\n<value>Clientes</value>\n</data>'),
])
def test_codigo_correcto_sin_hallazgos(nombre, contenido):
    assert _detectores(nombre, contenido) == set()


def test_archivos_moviles_se_evaluan_como_movil_aunque_la_revision_sea_web():
    for nombre in ("Login.kt", "Login.swift", "AndroidManifest.xml", "Info.plist", "build.gradle.kts"):
        assert contexto_para(Archivo(nombre, ""), Contexto("web", "nueva")).tipo_app == "movil"
    for nombre in ("Textos.resx", "openapi.yaml", "app.js"):
        assert contexto_para(Archivo(nombre, ""), Contexto("web", "nueva")).tipo_app == "web"


def test_los_lenguajes_nuevos_pasan_por_el_especialista_aunque_no_haya_hallazgos():
    from agente.llm_mock import MockLLM
    from agente.supervisor import Supervisor
    from agente.trace import Tracer
    rev = Supervisor(Contexto(), MockLLM(), Tracer(destino=Path("traza-no-usada.jsonl"))).revisar(
        [("Limpio.kt", 'val url = "https://api.empresa.pe"'), ("Limpio.cs", "public class Cliente { }")])
    kt, cs = rev.resultados
    assert kt.hallazgos == [] and "revisión semántica" in kt.resumen_agente     # el especialista sí corrió
    assert cs.resumen_agente == "" and rev.tracer.llamadas_llm == 1             # C# sin pendientes: no
