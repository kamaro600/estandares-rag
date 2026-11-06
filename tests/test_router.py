"""El router del chat (C5): semántico con umbral, respaldo determinista y guardas; y el nombre del código pegado."""
import pytest

from agente import codigo_chat, config, embeddings
from agente.router import ResultadoRuta, Router, respaldo


@pytest.fixture(scope="module")
def router():
    return Router(config.Settings().router_min_score)


@pytest.mark.parametrize("texto, ruta", [
    ("¿Qué prefijo usan los procedimientos almacenados?", "consulta_estandar"),
    ("¿Cuál es la capital de Francia?", "fuera_de_alcance"),
    ("Revisa esto:\n```sql\nSELECT * FROM dbo.Cliente\n```", "revisar_codigo"),
])
def test_rutas_basicas(router, texto, ruta):
    assert router.enrutar(texto).ruta == ruta


def test_bajo_umbral_decide_el_respaldo():
    r = Router(0.99).enrutar("¿Qué versión de .NET uso en un proyecto nuevo?")
    assert r.bajo_umbral and r.proveedor == "respaldo" and r.respaldo == "bajo_umbral"
    assert r.ruta == "consulta_estandar"


def test_si_fallan_los_embeddings_decide_el_respaldo(router, monkeypatch):
    def falla(*a, **k):
        raise embeddings.EmbeddingError("sin red")
    monkeypatch.setattr(router, "_semantico", falla)
    r = router.enrutar("Hola, ¿qué tal?")
    assert r.respaldo == "error" and r.ruta == "fuera_de_alcance"


def test_codigo_detectado_fuerza_la_revision(router, monkeypatch):
    monkeypatch.setattr(router, "_semantico", lambda *a: ResultadoRuta("consulta_estandar", 0.9, "embeddings"))
    r = router.enrutar("¿por qué está mal?\nvar x = Servicio().Result;\nreturn x;")
    assert r.ruta == "revisar_codigo" and r.respaldo == "codigo_detectado" and r.tiene_codigo


def test_sin_codigo_ni_pedido_no_se_invoca_al_agente(router, monkeypatch):
    monkeypatch.setattr(router, "_semantico", lambda *a: ResultadoRuta("revisar_codigo", 0.9, "embeddings"))
    r = router.enrutar("¿Qué es OWASP A03?")
    assert r.ruta == "consulta_estandar" and r.respaldo == "sin_codigo"
    assert router.enrutar("Quiero que revises un controlador que hice").ruta == "revisar_codigo"


def test_respaldo_determinista():
    assert respaldo("¿Cómo se nombran las tablas?") == "consulta_estandar"
    assert respaldo("¿Qué día es hoy?") == "fuera_de_alcance"
    assert respaldo("Revisa mi controlador, por favor") == "revisar_codigo"
    assert respaldo("¿y en Angular?", ["¿Dónde guardo el token?"]) == "consulta_estandar"


@pytest.mark.parametrize("texto, nombre", [
    ("```csharp\nvar x = 1;\n```", "codigo.cs"),
    ("```\n// archivo: Controllers/ClientesController.cs\npublic class A { }\n```", "Controllers/ClientesController.cs"),
    ("```\nCREATE TABLE ventas.Cliente (ClienteId INT)\n```", "script.sql"),
    ("SELECT * FROM dbo.Cliente WHERE Id = 1", "script.sql"),
    ("Revisa:\nexport class A {\n  x: any;\n}", "codigo.ts"),
    ('<Window x:Class="A">\n  <TextBox x:Name="txtNombre" />\n</Window>', "Vista.xaml"),
    ("```kotlin\nval token = prefs.getString(\"t\", null)\n```", "Codigo.kt"),
])
def test_nombre_del_codigo_pegado(texto, nombre):
    assert codigo_chat.extraer(texto)[1] == nombre


def test_una_pregunta_que_menciona_codigo_no_es_codigo():
    assert codigo_chat.extraer("¿Puedo usar SELECT * en un procedimiento?") is None
    assert codigo_chat.extraer("¿Cómo se nombran las tablas?") is None


def test_exactitud_minima_del_router_con_embeddings_hash():
    from eval.eval_router import medir
    assert medir()["exactitud"] >= 0.85
