"""C5: enrutamiento semántico con umbral y respaldo, y detección de código."""
import pytest

from app import detector_codigo
from app.embeddings import EmbeddingError, HashEmbedder
from app.router import Router, RouterSemantico, cargar_rutas, crear_router, respaldo


@pytest.fixture
def router(settings):
    return crear_router(settings, HashEmbedder())


@pytest.mark.parametrize("texto, ruta", [
    ("¿Qué prefijo usan los procedimientos almacenados?", "consulta_estandar"),
    ("¿Cuál es la capital de Francia?", "fuera_de_alcance"),
    ("Revisa este código:\n```sql\nSELECT * FROM dbo.Cliente\n```", "validar_codigo"),
])
def test_rutas_basicas(router, texto, ruta):
    assert router.enrutar(texto).ruta == ruta


def test_bajo_umbral_usa_respaldo(settings):
    r = Router(RouterSemantico(cargar_rutas(), HashEmbedder(), minimo=0.99)).enrutar("¿Qué versión de .NET uso?")
    assert r.bajo_umbral and r.proveedor == "respaldo" and r.respaldo == "bajo_umbral"
    assert r.ruta == "consulta_estandar"


def test_error_del_embedder_usa_respaldo():
    class Falla:
        def enrutar(self, *a, **k):
            raise EmbeddingError("sin red")
    r = Router(Falla()).enrutar("Hola, ¿qué tal?")
    assert r.respaldo == "error" and r.ruta == "fuera_de_alcance"


def test_codigo_detectado_fuerza_validacion(settings):
    class SiempreConsulta:
        def enrutar(self, *a, **k):
            from app.router import ResultadoRuta
            return ResultadoRuta("consulta_estandar", 0.9, "hash")
    r = Router(SiempreConsulta()).enrutar("¿por qué está mal?\nvar x = Servicio().Result;\nreturn x;")
    assert r.ruta == "validar_codigo" and r.respaldo == "codigo_detectado" and r.tiene_codigo


def test_validar_sin_codigo_ni_pedido_es_consulta():
    class SiempreValidar:
        def enrutar(self, *a, **k):
            from app.router import ResultadoRuta
            return ResultadoRuta("validar_codigo", 0.9, "embeddings")
    r = Router(SiempreValidar()).enrutar("¿Qué es OWASP A03?")
    assert r.ruta == "consulta_estandar" and r.respaldo == "sin_codigo"
    assert Router(SiempreValidar()).enrutar("Quiero que valides un controlador que hice").ruta == "validar_codigo"


def test_respaldo_determinista():
    assert respaldo("¿Cómo se nombran las tablas?") == "consulta_estandar"
    assert respaldo("¿Qué día es hoy?") == "fuera_de_alcance"
    assert respaldo("Valida este código C# por favor") == "validar_codigo"
    assert respaldo("¿y en Angular?", ["¿Dónde guardo el token?"]) == "consulta_estandar"


@pytest.mark.parametrize("texto, lenguaje", [
    ("```cs\nvar x = 1;\n```", "csharp"),
    ("```\nCREATE TABLE ventas.Cliente (ClienteId INT)\n```", "sql"),
    ("SELECT * FROM dbo.Cliente WHERE Id = 1", "sql"),
    ("Revisa:\nexport class A {\n  x: any;\n}", "typescript"),
    ('<Window x:Class="A">\n  <TextBox x:Name="txtNombre" />\n</Window>', "xaml"),
])
def test_detector_de_codigo(texto, lenguaje):
    assert detector_codigo.extraer(texto)[1] == lenguaje


def test_pregunta_que_menciona_codigo_no_es_codigo():
    assert detector_codigo.extraer("¿Puedo usar SELECT * en un procedimiento?") is None
    assert detector_codigo.extraer("¿Cómo se nombran las tablas?") is None


def test_exactitud_minima_del_router_con_embedder_hash(router):
    from eval.evaluar import evaluar_router
    assert evaluar_router(router)["exactitud"] >= 0.85
