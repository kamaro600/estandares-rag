"""C5: cada detector cita reglas que existen, y encuentra lo que los ejemplos de los estándares llaman incorrecto."""
from pathlib import Path

import pytest

from agente import catalogo
from agente.contexto import Contexto
from agente.detectores import PATRONES, Archivo, analizar, codigo_de, detectar_lenguaje
from eval.eval_detectores import evaluar

RAIZ = Path(__file__).parent.parent


def _reglas(ruta: str, tipo="web", bd="nueva") -> list[tuple[int, str]]:
    p = RAIZ / ruta
    return [(h.linea, h.regla_id) for h in analizar(Archivo(ruta, p.read_text(encoding="utf-8")), Contexto(tipo, bd))]


def test_cada_detector_cita_reglas_que_existen():
    reglas = catalogo.cargar()
    for p in PATRONES:
        for rid in p.reglas + p.relacionadas:
            assert rid in reglas, f"{p.codigo} cita {rid}"


@pytest.mark.parametrize("nombre,lenguaje", [
    ("A.cs", "csharp"), ("Vista.xaml.cs", "csharp"), ("Vista.xaml", "xaml"), ("x.component.ts", "typescript"),
    ("x.html", "html"), ("y.SQL", "tsql"), ("appsettings.json", "config"), ("A.csproj", "config"),
    ("C:\\src\\App.config", "config"), ("Index.cshtml", "razor"), ("Lista.razor", "razor"), ("app.js", "javascript"),
    ("openapi.yaml", "yaml"), ("azure-pipelines.yml", "yaml"), ("Textos.resx", "xml"), ("AndroidManifest.xml", "xml"),
    ("Info.plist", "xml"), ("Login.kt", "kotlin"), ("build.gradle.kts", "kotlin"), ("build.gradle", "kotlin"),
    ("Login.swift", "swift"), ("deploy.ps1", "powershell"), ("mod.psm1", "powershell"),
    ("Dockerfile", "dockerfile"), ("app.dockerfile", "dockerfile"),
    ("FooTests.cs", "tests"), ("foo.test.ts", "tests"),
    ("main.py", None), ("estilos.scss", None)])
def test_lenguaje_por_extension(nombre, lenguaje):
    assert detectar_lenguaje(nombre) == lenguaje


def test_servicio_csharp():
    encontrados = _reglas("ejemplos/web/api/ClienteService.cs")
    for esperado in [(12, "WEB-NET-002"), (13, "WEB-NET-005"), (19, "SEG-INY-001"), (19, "WEB-BD-009"),
                     (27, "WEB-NET-004"), (32, "SEG-CRI-002"), (33, "SEG-LOG-001"), (39, "SEG-CRI-001")]:
        assert esperado in encontrados


def test_web_incluye_las_reglas_de_su_api():
    """WEB-ARQ-001: la app web es Angular + su API REST, así que EST-API-001 también aplica."""
    assert {r for _, r in _reglas("ejemplos/web/api/ClientesController.cs")} >= {
        "API-DIS-001", "API-RES-001", "API-SEG-002", "API-NET-002"}
    assert _reglas("ejemplos/web/api/ClientesController.cs", tipo="escritorio") == []


def test_la_misma_tabla_segun_la_base():
    nueva = {r for _, r in _reglas("ejemplos/bd/escritorio_legada.sql", bd="nueva")}
    legada = {r for _, r in _reglas("ejemplos/bd/escritorio_legada.sql", tipo="escritorio", bd="legada")}
    assert "WEB-BD-002" in nueva and not any(r.startswith("DSK-BD") for r in nueva)
    assert "DSK-BD-001" in legada and not any(r.startswith("WEB-BD-00" + n) for r in legada for n in "1235")


def test_seguridad_prevalece_y_conserva_relacionadas():
    hs = analizar(Archivo("A.cs", 'var s = "SELECT Nombre FROM ventas.Cliente WHERE Id = " + id;'), Contexto())
    assert len(hs) == 1 and hs[0].regla_id == "SEG-INY-001" and "WEB-BD-010" in hs[0].relacionadas


def test_seguridad_prevalece_sobre_la_convencion():
    """Pasar a plantilla un log que incluye la clave sigue filtrando la clave: manda SEG-LOG-001,
    y por eso NO se ofrece el autofix de WEB-NET-005."""
    hs = analizar(Archivo("A.cs", '_logger.LogInformation($"Login de {usuario} con clave {clave}");'), Contexto())
    assert [(h.regla_id, h.autofix) for h in hs] == [("SEG-LOG-001", None)]
    assert "WEB-NET-005" in hs[0].relacionadas


def test_comentarios_y_urls_no_disparan():
    assert codigo_de("csharp", '// var x = tarea.Result;') == ""
    assert codigo_de("csharp", 'var u = "https://x.pe"; // .Result') == 'var u = "https://x.pe"; '
    assert analizar(Archivo("A.cs", "    // var c = new Random().Next();\n    /* MD5.Create() */"), Contexto()) == []


def test_manejador_de_eventos_no_es_falso_positivo():
    """El propio EST-DSK-001 usa btnGuardar_Click y async void en manejadores como ejemplo correcto."""
    src = "private async void btnBuscar_Click(object sender, EventArgs e)\n{\n}"
    assert analizar(Archivo("V.cs", src), Contexto("escritorio", "legada")) == []


def test_autofix_de_log_conserva_los_argumentos():
    h = analizar(Archivo("A.cs", '        _logger.LogWarning($"Pedido {pedido.Id} sin stock para {usuario}");'),
                 Contexto())[0]
    assert h.autofix == '        _logger.LogWarning("Pedido {PedidoId} sin stock para {Usuario}", pedido.Id, usuario);'


def test_ejemplos_de_los_propios_estandares():
    """Conjunto de oro: 'Ejemplo incorrecto' debe detectarse; 'Ejemplo correcto', no (confianza alta)."""
    res = evaluar()
    total = len(res["detectados"]) + len(res["no_detectados"])
    assert len(res["detectados"]) / total >= 0.90
    assert res["falsos"] == []
    # Lo que queda sin detectar es semántico: lo ve el especialista, no una expresión regular.
    assert {c.regla.id for c in res["no_detectados"]} <= {"API-RES-004", "SEG-GEN-003", "SEG-ACC-002"}
