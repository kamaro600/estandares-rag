"""Genera grafana/dashboards/estandares.json (el tablero se escribe como código, no a mano en la interfaz).

Uso:   python -m grafana.generar_dashboard
"""
from __future__ import annotations

import json
from pathlib import Path

DS = {"type": "prometheus", "uid": "prom"}
DESTINO = Path(__file__).resolve().parent / "dashboards" / "estandares.json"
_id = 0


def _panel(tipo, titulo, descripcion, x, y, w, h, objetivos, unidad="short", extra=None):
    global _id
    _id += 1
    p = {"id": _id, "type": tipo, "title": titulo, "description": descripcion, "datasource": DS,
         "gridPos": {"x": x, "y": y, "w": w, "h": h},
         "targets": [{"refId": chr(65 + i), "datasource": DS, "expr": e, "legendFormat": l}
                     for i, (e, l) in enumerate(objetivos)],
         "fieldConfig": {"defaults": {"unit": unidad}, "overrides": []}}
    if tipo == "stat":
        p["options"] = {"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "value", "graphMode": "none"}
    if tipo == "timeseries":
        p["fieldConfig"]["defaults"]["custom"] = {"drawStyle": "line", "fillOpacity": 10, "lineWidth": 2}
    p.update(extra or {})
    return p


def fila(titulo, y):
    global _id
    _id += 1
    return {"id": _id, "type": "row", "title": titulo, "collapsed": False, "gridPos": {"x": 0, "y": y, "w": 24, "h": 1},
            "panels": []}


def p95(metrica, por=""):
    agrupar = f"le{', ' + por if por else ''}"
    return f"histogram_quantile(0.95, sum by ({agrupar}) (rate({metrica}_bucket[$__rate_interval])))"


def construir() -> dict:
    R = "[$__range]"
    paneles = [
        fila("Uso", 0),
        _panel("stat", "Mensajes", "Mensajes del usuario en el rango", 0, 1, 4, 4,
               [(f"sum(increase(est_chat_mensajes_total{R}))", "mensajes")]),
        _panel("stat", "Validaciones de código", "Reportes generados por el agente", 4, 1, 4, 4,
               [(f"sum(increase(est_validaciones_total{R}))", "validaciones")]),
        _panel("stat", "Reportes sin revisión humana", "Cola pendiente del revisor (alerta si crece)", 8, 1, 4, 4,
               [("est_reportes_pendientes", "pendientes")]),
        _panel("stat", "Abstención del RAG", "Consultas sin evidencia sobre el umbral / consultas", 12, 1, 4, 4,
               [(f"sum(increase(est_rag_sin_contexto_total{R})) / clamp_min(sum(increase(est_chat_mensajes_total"
                 f"{{ruta=\"consulta_estandar\"}}{R})), 1)", "abstención")], "percentunit"),
        _panel("stat", "Costo estimado", "USD según precios de .env", 16, 1, 4, 4,
               [(f"sum(increase(est_costo_estimado_usd_total{R}))", "USD")], "currencyUSD"),
        _panel("stat", "Precisión del LLM (revisión humana)", "Hallazgos propuestos por el LLM confirmados por el humano",
               20, 1, 4, 4,
               [(f"sum(increase(est_revisiones_total{{origen=\"llm\",decision=\"confirmado\"}}{R})) / "
                 f"clamp_min(sum(increase(est_revisiones_total{{origen=\"llm\"}}{R})), 1)", "precisión")],
               "percentunit"),
        _panel("timeseries", "Mensajes por ruta", "Decisión del router por minuto", 0, 5, 12, 7,
               [("sum by (ruta) (rate(est_chat_mensajes_total[$__rate_interval])) * 60", "{{ruta}}")], "short"),
        _panel("timeseries", "Latencia p95 por ruta", "Desde que llega el mensaje hasta la respuesta", 12, 5, 12, 7,
               [(p95("est_chat_latencia_segundos", "ruta"), "{{ruta}}")], "s"),

        fila("RAG y router", 12),
        _panel("timeseries", "Similitud del mejor fragmento (p50 / p95)", "Si baja, las preguntas se alejan del corpus",
               0, 13, 8, 7,
               [("histogram_quantile(0.5, sum by (le) (rate(est_rag_score_bucket[$__rate_interval])))", "p50"),
                (p95("est_rag_score"), "p95")], "short"),
        _panel("bargauge", "Fragmentos usados por categoría", "Qué estándares se consultan más", 8, 13, 8, 7,
               [(f"sum by (categoria) (increase(est_rag_fragmentos_total{R}))", "{{categoria}}")], "short",
               {"options": {"orientation": "horizontal", "displayMode": "basic",
                            "reduceOptions": {"calcs": ["lastNotNull"]}}}),
        _panel("timeseries", "Router: uso del respaldo", "bajo_umbral | error | codigo_detectado", 16, 13, 8, 7,
               [("sum by (motivo) (increase(est_router_respaldo_total[$__rate_interval]))", "{{motivo}}")], "short"),
        _panel("timeseries", "Citas inválidas y reformulaciones", "Citas a reglas fuera del contexto (alucinación)",
               0, 20, 12, 6,
               [("sum(increase(est_citas_invalidas_total[$__rate_interval]))", "citas inválidas"),
                ("sum by (resultado) (increase(est_reformulaciones_total[$__rate_interval]))", "reformulación {{resultado}}")],
               "short"),
        _panel("bargauge", "Índice vectorial", "Fragmentos por categoría", 12, 20, 12, 6,
               [("est_indice_fragmentos", "{{categoria}}")], "short",
               {"options": {"orientation": "horizontal", "displayMode": "basic",
                            "reduceOptions": {"calcs": ["lastNotNull"]}}}),

        fila("Agente validador y revisión humana", 26),
        _panel("bargauge", "Hallazgos por severidad y origen", "regla = verificado; llm = propuesto", 0, 27, 8, 7,
               [(f"sum by (origen, severidad) (increase(est_hallazgos_total{R}))", "{{origen}} · {{severidad}}")], "short",
               {"options": {"orientation": "horizontal", "displayMode": "basic",
                            "reduceOptions": {"calcs": ["lastNotNull"]}}}),
        _panel("timeseries", "Resultado de las validaciones", "cumple | no_cumple | error_llm", 8, 27, 8, 7,
               [("sum by (resultado) (increase(est_validaciones_total[$__rate_interval]))", "{{resultado}}")], "short"),
        _panel("bargauge", "Decisiones humanas", "Confirmados y descartados por origen", 16, 27, 8, 7,
               [(f"sum by (decision, origen) (increase(est_revisiones_total{R}))", "{{origen}} · {{decision}}")], "short",
               {"options": {"orientation": "horizontal", "displayMode": "basic",
                            "reduceOptions": {"calcs": ["lastNotNull"]}}}),

        fila("Seguridad y privacidad", 34),
        _panel("timeseries", "Prompt injection", "Detectados por origen y acción", 0, 35, 8, 7,
               [("sum by (origen, accion) (increase(est_inyeccion_total[$__rate_interval]))", "{{origen}} · {{accion}}")],
               "short"),
        _panel("bargauge", "Datos enmascarados antes de salir", "Secretos y datos personales que no llegaron a Claude ni a OpenAI",
               8, 35, 8, 7, [(f"sum by (tipo) (increase(est_datos_enmascarados_total{R}))", "{{tipo}}")], "short",
               {"options": {"orientation": "horizontal", "displayMode": "basic",
                            "reduceOptions": {"calcs": ["lastNotNull"]}}}),
        _panel("timeseries", "Rechazos por límite de tasa (429)", "Mensajes rechazados por IP", 16, 35, 8, 7,
               [("sum(increase(est_limite_tasa_total[$__rate_interval]))", "429")], "short"),

        fila("Proveedores de IA (Claude + embeddings de OpenAI)", 42),
        _panel("timeseries", "Latencia p95 de los proveedores", "claude_llm y openai_emb", 0, 43, 8, 7,
               [(p95("est_api_latencia_segundos", "proveedor"), "{{proveedor}}")], "s"),
        _panel("timeseries", "Tokens por minuto", "Entrada y salida", 8, 43, 8, 7,
               [("sum by (proveedor, tipo) (rate(est_tokens_total[$__rate_interval])) * 60", "{{proveedor}} {{tipo}}")],
               "short"),
        _panel("timeseries", "Errores de los proveedores", "Por tipo: limite, http_4xx/5xx, rechazo, json_invalido…", 16, 43, 8, 7,
               [("sum by (proveedor, tipo) (increase(est_api_errores_total[$__rate_interval]))", "{{proveedor}} {{tipo}}")],
               "short"),
    ]
    return {"uid": "estandares", "title": "Chat de estándares · RAG + agente validador", "tags": ["estandares", "rag"],
            "timezone": "browser", "schemaVersion": 41, "version": 1, "refresh": "10s",
            "time": {"from": "now-1h", "to": "now"}, "panels": paneles}


if __name__ == "__main__":
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    tablero = construir()
    DESTINO.write_text(json.dumps(tablero, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{DESTINO.name}: {sum(p['type'] != 'row' for p in tablero['panels'])} paneles")
