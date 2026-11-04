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
    assert json.load(urllib.request.urlopen(base + "/health")) == {"estado": "ok", "reglas": 170}
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
    assert info["modelo"] == "mock" and info["reglas"] == 170
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


def test_el_script_de_validacion_pasa_contra_la_api(base):
    """scripts/validar_api.py es lo que corre el estudiante contra su servidor: debe pasar completo."""
    r = subprocess.run([sys.executable, "-m", "scripts.validar_api", "--url", base], cwd=RAIZ,
                       capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stdout[-2000:]
    assert "FALLA" not in r.stdout
