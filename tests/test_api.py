"""La API: contratos, errores Problem Details, cabeceras de seguridad, límite de tasa y revisión humana."""
CODIGO = "Valida:\n```csharp\nvar sql = \"SELECT Nombre FROM ventas.Cliente WHERE Id = \" + id;\nvar x = s.Cargar().Result;\n```"


def test_health_y_metricas(cliente):
    h = cliente.get("/health").json()
    assert h["status"] == "ok" and h["embedder"] == "hash-1024" and h["fragmentos"] > 170
    m = cliente.get("/metrics").text
    assert "est_chat_mensajes_total" in m and "est_indice_fragmentos" in m


def test_cabeceras_de_seguridad(cliente):
    r = cliente.get("/")
    assert r.status_code == 200 and "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"


def test_chat_y_conversacion(cliente):
    d = cliente.post("/api/chat", json={"mensaje": "¿Cómo se versionan las APIs?"}).json()
    conv = d["conversacion_id"]
    assert len(cliente.get(f"/api/chat/{conv}").json()["mensajes"]) == 2
    assert cliente.get(f"/api/trazas/{d['trace_id']}").json()["pasos"][0]["paso"] == "router"


def test_errores_en_formato_problem_details(cliente):
    r = cliente.post("/api/chat", json={"mensaje": "hola", "conversacion_id": 999})
    assert r.status_code == 404 and r.headers["content-type"].startswith("application/problem+json")
    r = cliente.post("/api/chat", json={"mensaje": "hola", "campo_extra": 1})
    assert r.status_code == 400 and r.json()["errors"][0]["campo"] == "campo_extra"
    r = cliente.post("/api/chat", json={"mensaje": "x" * 20001})
    assert r.status_code == 400
    r = cliente.post("/api/chat", json={"mensaje": "hola", "categorias": ["inexistente"]})
    assert r.status_code == 400
    r = cliente.post("/api/chat", content=b"{no es json", headers={"Content-Type": "application/json"})
    assert r.status_code == 400 and r.headers["content-type"].startswith("application/problem+json")
    r = cliente.get("/no-existe")
    assert r.status_code == 404 and r.json()["title"] == "No encontrado"


def test_limite_de_tasa(cliente, servicios):
    cliente.app.state.limite.por_minuto = 2
    for _ in range(2):
        assert cliente.post("/api/chat", json={"mensaje": "¿Qué es OWASP?"}).status_code == 200
    r = cliente.post("/api/chat", json={"mensaje": "¿Qué es OWASP?"})
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0


def test_revision_humana_completa_y_unica(cliente):
    d = cliente.post("/api/chat", json={"mensaje": CODIGO}).json()
    rid = d["mensajes"][1]["meta"]["reporte_id"]
    rep = cliente.get(f"/api/reportes/{rid}").json()
    n = len(rep["resultado"]["hallazgos"])
    assert rep["estado"] == "PROPUESTO" and n >= 2

    incompleta = {"revisor": "Ana", "decisiones": [{"indice": 0, "decision": "confirmado"}]}
    assert cliente.post(f"/api/reportes/{rid}/revision", json=incompleta).status_code == 422
    sin_motivo = {"revisor": "Ana", "decisiones": [{"indice": i, "decision": "descartado"} for i in range(n)]}
    assert cliente.post(f"/api/reportes/{rid}/revision", json=sin_motivo).status_code == 400

    decisiones = [{"indice": 0, "decision": "confirmado"}] + [
        {"indice": i, "decision": "descartado", "comentario": "Falso positivo: es una propiedad"} for i in range(1, n)]
    r = cliente.post(f"/api/reportes/{rid}/revision", json={"revisor": "Ana", "decisiones": decisiones})
    assert r.status_code == 200 and r.json()["confirmados"] == 1 and r.json()["cumple"] is False
    assert cliente.post(f"/api/reportes/{rid}/revision",
                        json={"revisor": "Luis", "decisiones": decisiones}).status_code == 409

    mensajes = cliente.get(f"/api/chat/{d['conversacion_id']}").json()["mensajes"]
    assert mensajes[-1]["rol"] == "sistema" and "Ana" in mensajes[-1]["texto"]
    pasos = [p["paso"] for p in cliente.get(f"/api/trazas/{d['trace_id']}").json()["pasos"]]
    assert pasos[-1] == "revision_humana"
    assert "est_revisiones_total" in cliente.get("/metrics").text


def test_documentos(cliente):
    docs = {d["codigo"]: d for d in cliente.get("/api/documentos").json()}
    assert docs["EST-WEB-001"]["reglas"] == 34 and docs["EST-DSK-001"]["version"] == "1.4"


def test_reporte_inexistente(cliente):
    assert cliente.get("/api/reportes/999").status_code == 404
    assert cliente.get("/api/trazas/no-existe").status_code == 404
