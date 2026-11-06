"""python -m scripts.generar_tablero  →  grafana/dashboards/agente-estandares.json (tablero como código)."""
from __future__ import annotations

import json
from pathlib import Path

from agente import config

PANELES = [
    # (título, tipo, consulta PromQL, leyenda)
    ("Revisiones por veredicto (1 h)", "stat", "sum by (veredicto) (increase(lab07_revisiones_total[1h]))", "{{veredicto}}"),
    ("Hallazgos por severidad / min", "timeseries", "sum by (severidad) (rate(lab07_hallazgos_total[5m])) * 60", "{{severidad}}"),
    ("Hallazgos por lenguaje (1 h)", "barchart", "sum by (lenguaje) (increase(lab07_hallazgos_total[1h]))", "{{lenguaje}}"),
    ("Parches: aceptados vs. rechazados por las guardas", "timeseries",
     "sum by (origen, resultado) (rate(lab07_parches_total[5m])) * 60", "{{origen}} {{resultado}}"),
    ("Rechazos de la guarda por motivo (1 h)", "barchart", "sum by (motivo) (increase(lab07_guarda_rechazos_total[1h]))", "{{motivo}}"),
    ("Tasa de aprobación humana", "stat",
     'sum(increase(lab07_aprobaciones_total{decision="aprobado"}[1h])) / clamp_min(sum(increase(lab07_aprobaciones_total[1h])), 1)',
     "aprobados / decididos"),
    ("Hallazgos derivados a revisión humana (1 h)", "stat", "sum(increase(lab07_revision_manual_total[1h]))", "manual"),
    ("Tokens del modelo / min", "timeseries", "sum by (tipo) (rate(lab07_llm_tokens_total[5m])) * 60", "{{tipo}}"),
    ("Duración de la revisión p95 (s)", "timeseries",
     "histogram_quantile(0.95, sum by (le) (rate(lab07_revision_segundos_bucket[5m])))", "p95"),
    # ---- chat: preguntas con citas, router y comunicación con el agente ----
    ("Mensajes del chat por ruta / min", "timeseries", "sum by (ruta) (rate(lab07_chat_mensajes_total[5m])) * 60", "{{ruta}}"),
    ("Tasa de abstención (sin evidencia, sin modelo)", "stat",
     'sum(increase(lab07_rag_sin_contexto_total[1h])) / clamp_min(sum(increase(lab07_chat_mensajes_total{ruta="consulta_estandar"}[1h])), 1)',
     "abstención"),
    ("Router: decisiones del respaldo (1 h)", "barchart", "sum by (motivo) (increase(lab07_router_respaldo_total[1h]))", "{{motivo}}"),
    ("Citas inválidas del modelo (1 h)", "stat", "sum(increase(lab07_citas_invalidas_total[1h]))", "citas inválidas"),
    ("Secciones agregadas por conflicto entre estándares (1 h)", "stat",
     "sum(increase(lab07_rag_complementos_total[1h]))", "secciones"),
    ("Latencia del chat p95 (s)", "timeseries",
     "histogram_quantile(0.95, sum by (le) (rate(lab07_chat_segundos_bucket[5m])))", "p95"),
    ("Reformulaciones de seguimiento (1 h)", "barchart", "sum by (resultado) (increase(lab07_reformulaciones_total[1h]))", "{{resultado}}"),
    # ---- seguridad, privacidad y proveedor de IA ----
    ("Prompt injection detectado (1 h)", "barchart", "sum by (origen, accion) (increase(lab07_inyeccion_total[1h]))", "{{origen}} {{accion}}"),
    ("Datos enmascarados antes de salir (1 h)", "barchart", "sum by (tipo) (increase(lab07_datos_enmascarados_total[1h]))", "{{tipo}}"),
    ("Rechazos 429 por límite de tasa (1 h)", "stat", "sum(increase(lab07_limite_tasa_total[1h]))", "429"),
    ("Latencia del modelo p95 (s)", "timeseries",
     "histogram_quantile(0.95, sum by (le) (rate(lab07_llm_segundos_bucket[5m])))", "p95"),
    ("Errores y rechazos del proveedor (1 h)", "barchart", "sum by (proveedor, tipo) (increase(lab07_llm_errores_total[1h]))", "{{proveedor}} {{tipo}}"),
    ("Costo estimado USD (1 h)", "stat", "sum(increase(lab07_costo_usd_total[1h]))", "USD"),
]


def panel(i: int, titulo: str, tipo: str, expr: str, leyenda: str) -> dict:
    return {"id": i + 1, "title": titulo, "type": tipo,
            "datasource": {"type": "prometheus", "uid": "prometheus"},
            "gridPos": {"h": 8, "w": 8, "x": (i % 3) * 8, "y": (i // 3) * 8},
            "targets": [{"refId": "A", "expr": expr, "legendFormat": leyenda,
                         "datasource": {"type": "prometheus", "uid": "prometheus"}}],
            "fieldConfig": {"defaults": {"unit": "percentunit" if "Tasa" in titulo else "currencyUSD" if "USD" in titulo
                                         else "short"}, "overrides": []},
            "options": {}}


def main() -> None:
    config.consola_segura()
    tablero = {"uid": "lab07-agente", "title": "Lab 07 · Agente corrector de estándares", "schemaVersion": 39,
               "time": {"from": "now-1h", "to": "now"}, "refresh": "10s",
               "panels": [panel(i, *p) for i, p in enumerate(PANELES)]}
    destino = Path(__file__).parent.parent / "grafana" / "dashboards" / "agente-estandares.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(tablero, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print(f"{len(PANELES)} paneles → {destino.relative_to(destino.parent.parent.parent).as_posix()}")


if __name__ == "__main__":
    main()
