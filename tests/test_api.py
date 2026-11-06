"""La API se prueba de verdad: uvicorn en un puerto libre y peticiones HTTP reales."""
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

RAIZ = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def base():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "agente.api:crear_app", "--factory",
                             "--port", str(puerto), "--log-level", "warning"], cwd=RAIZ)
    url = f"http://127.0.0.1:{puerto}"
    for _ in range(50):
        try:
            urllib.request.urlopen(url + "/health", timeout=1)
            break
        except OSError:
            time.sleep(0.2)
    yield url
    proc.terminate()
    proc.wait(timeout=10)


def _post(url, cuerpo):
    req = urllib.request.Request(url, data=json.dumps(cuerpo).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.headers["Content-Type"], json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, e.headers["Content-Type"], json.loads(e.read())


def test_salud_y_regla(base):
    salud = json.load(urllib.request.urlopen(base + "/health"))
    assert salud["estado"] == "ok" and salud["reglas"] == 200 and salud["secciones"] > 20
    assert salud["embeddings"] == "hash:2048" and salud["modelo"] == "mock"
    r = json.load(urllib.request.urlopen(base + "/v1/reglas/web-bd-005"))
    assert r["id"] == "WEB-BD-005" and r["cita"].startswith("EST-WEB-001 v3.0 §7.5")


def test_revision_por_http(base):
    codigo = (RAIZ / "ejemplos/bd/ventas_nueva.sql").read_text(encoding="utf-8")
    status, _, d = _post(base + "/v1/revisiones", {"archivos": [{"nombre": "db/ventas.sql", "contenido": codigo}]})
    assert status == 200 and d["veredicto_inicial"] == "NO_APTO" and d["modelo"] == "mock"
    assert d["totales"]["hallazgos"] == 15


def test_errores_en_problem_details(base):
    status, tipo, d = _post(base + "/v1/revisiones", {"tipo_app": "pc", "archivos": []})
    assert status == 400 and tipo == "application/problem+json"
    assert set(d["errors"]) == {"tipo_app", "archivos"}
    status, _, _ = _post(base + "/v1/revisiones", {"archivos": [{"nombre": "a.cs", "contenido": "x" * 200_001}]})
    assert status == 400


def test_metricas_expuestas(base):
    texto = urllib.request.urlopen(base + "/metrics").read().decode("utf-8")
    assert "lab07_hallazgos_total" in texto and "lab07_llm_llamadas_total" in texto


def test_no_arranca_con_un_indice_de_otros_embeddings(monkeypatch):
    from agente.api import crear_app
    monkeypatch.setenv("EMBEDDINGS_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "clave-de-prueba")
    with pytest.raises(RuntimeError, match="agente.ingesta"):
        crear_app()


def test_pagina_web_con_cabeceras_de_seguridad(base):
    with urllib.request.urlopen(base + "/") as r:
        assert "text/html" in r.headers["Content-Type"] and b"/app.js" in r.read()
        assert "default-src 'self'" in r.headers["Content-Security-Policy"]
    info = json.load(urllib.request.urlopen(base + "/v1/info"))
    assert info["modelo"] == "mock" and info["reglas"] == 200
    assert {d["codigo"]: d["reglas"] for d in info["documentos"]} == {"EST-API-001": 25, "EST-DSK-001": 23, "EST-REF-001": 45,
                                                                    "EST-SEG-001": 43, "EST-WEB-001": 34,
                                                                    "EST-BPA-001": 30}
    archivos = {d["codigo"]: d["archivo"] for d in info["documentos"]}
    assert archivos["EST-BPA-001"].startswith("EST_BP_") and archivos["EST-API-001"].startswith("EST-API-001_")
    assert {".kt", ".swift", ".cshtml", ".yaml", ".resx"} <= set(info["extensiones"])
    # cada extensión aceptada aparece en alguna familia de la página, y ninguna familia ofrece una que no se acepte
    assert {e for f in info["familias"] for e in f["extensiones"]} == set(info["extensiones"])
    assert all(l["patrones"] > 0 for l in info["lenguajes"])


def test_aprobar_por_http_devuelve_lo_corregido_sin_escribir(base):
    codigo = (RAIZ / "ejemplos/bd/ventas_nueva.sql").read_text(encoding="utf-8")
    _, _, rev = _post(base + "/v1/revisiones", {"archivos": [{"nombre": "db/ventas.sql", "contenido": codigo}]})
    parches = rev["archivos"][0]["parches"]
    assert len(parches) >= 2
    url = f"{base}/v1/revisiones/{rev['revision_id']}/aprobacion"
    # aprobar un parche que no es de esta revisión no aplica nada
    status, tipo, d = _post(url, {"aprobados": [{"archivo": "db/ventas.sql", "parche": "P999"}]})
    assert status == 400 and tipo == "application/problem+json" and d["desconocidos"] == ["db/ventas.sql P999"]
    # se aprueba solo el primero: el resto queda denegado
    status, _, d = _post(url, {"aprobados": [{"archivo": "db/ventas.sql", "parche": parches[0]["id"]}]})
    estados = {p["id"]: p["estado"] for p in d["archivos"][0]["parches"]}
    assert status == 200 and estados[parches[0]["id"]] == "aplicado"
    assert all(e == "denegado" for i, e in estados.items() if i != parches[0]["id"])
    corregido = d["corregidos"][0]
    assert corregido["archivo"] == "db/ventas.sql" and corregido["contenido"] != codigo
    assert corregido["diff"].startswith("--- a/db/ventas.sql")
    assert not (RAIZ / "salida" / "corregido" / "db").exists()     # la API no escribe en disco
    # cada revisión se decide una sola vez; una desconocida da 404
    assert _post(url, {"aprobados": []})[0] == 409
    assert _post(f"{base}/v1/revisiones/no-existe/aprobacion", {"aprobados": []})[0] == 404


def test_chat_pregunta_con_citas_y_conversacion_persistida(base):
    status, _, d = _post(base + "/v1/chat", {"mensaje": "¿Qué atributos deben tener las cookies de sesión?"})
    assert status == 200 and d["mensajes"][1]["meta"]["ruta"] == "consulta_estandar"
    assert d["mensajes"][1]["meta"]["citas"]
    conv = json.load(urllib.request.urlopen(f"{base}/v1/chat/{d['conversacion_id']}"))
    assert [m["rol"] for m in conv["mensajes"]] == ["usuario", "asistente"]
    traza = json.load(urllib.request.urlopen(f"{base}/v1/trazas/{d['trace_id']}"))
    # primer mensaje: sin historial no hay nada que reformular (y no se gasta una llamada)
    assert [e["tipo"] for e in traza["eventos"]][:3] == ["router", "rag", "llm"]


def test_chat_invoca_al_agente_y_la_aprobacion_vuelve_al_chat(base):
    codigo = ("```csharp\n// archivo: ClienteService.cs\npublic Cliente Obtener(int id)\n{\n"
              "    var cliente = _repo.ObtenerAsync(id).Result;\n    return cliente;\n}\n```")
    _, _, d = _post(base + "/v1/chat", {"mensaje": codigo, "tipo_app": "api"})
    rev = d["mensajes"][1]["meta"]["revision"]
    assert rev["archivo"] == "ClienteService.cs" and rev["evaluado_como"] == "api" and rev["parches"]
    url = f"{base}/v1/revisiones/{rev['revision_id']}/aprobacion"
    status, _, a = _post(url, {"aprobados": [{"archivo": rev["archivo"], "parche": rev["parches"][0]["id"]}]})
    assert status == 200 and a["mensaje_chat"]["rol"] == "sistema" and a["corregidos"]
    conv = json.load(urllib.request.urlopen(f"{base}/v1/chat/{d['conversacion_id']}"))
    assert conv["mensajes"][-1]["meta"]["tipo"] == "aprobacion"
    assert _post(url, {"aprobados": []})[0] == 409                    # decisión única


def test_chat_errores_en_problem_details(base):
    status, tipo, d = _post(base + "/v1/chat", {"mensaje": "hola", "campo_extra": 1})
    assert status == 400 and tipo == "application/problem+json" and "campo_extra" in d["errors"]
    assert _post(base + "/v1/chat", {"mensaje": "hola", "conversacion_id": 999999})[0] == 404
    assert _post(base + "/v1/chat", {"mensaje": "x" * 20_001})[0] == 400
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(base + "/v1/trazas/no-existe")
    assert e.value.code == 404


def test_limite_de_tasa_por_equipo():
    from agente.api import LimiteTasa
    limite = LimiteTasa(2)
    assert limite.esperar("10.0.0.1") == 0 and limite.esperar("10.0.0.1") == 0
    assert 0 < limite.esperar("10.0.0.1") <= 61          # el tercero espera (429 con Retry-After)
    assert limite.esperar("10.0.0.2") == 0               # otro equipo no se ve afectado


def test_la_api_aplica_el_limite_antes_de_procesar(monkeypatch):
    """Revisar y chatear gastan modelo: superado el límite se responde 429 sin validar ni ejecutar nada."""
    from starlette.testclient import TestClient

    from agente.api import crear_app
    monkeypatch.setenv("LIMITE_POR_MINUTO", "2")
    cliente = TestClient(crear_app())
    for ruta in ("/v1/chat", "/v1/revisiones"):
        assert cliente.post(ruta, json={}).status_code != 429
    r = cliente.post("/v1/chat", json={"mensaje": "hola"})
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0
    assert r.headers["Content-Type"].startswith("application/problem+json")


def test_el_script_de_validacion_pasa_contra_la_api(base):
    """scripts/validar_api.py es lo que corre el estudiante contra su servidor: debe pasar completo."""
    r = subprocess.run([sys.executable, "-m", "scripts.validar_api", "--url", base], cwd=RAIZ,
                       capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stdout[-2000:]
    assert "FALLA" not in r.stdout
