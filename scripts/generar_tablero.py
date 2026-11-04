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
]


def panel(i: int, titulo: str, tipo: str, expr: str, leyenda: str) -> dict:
    return {"id": i + 1, "title": titulo, "type": tipo,
            "datasource": {"type": "prometheus", "uid": "prometheus"},
            "gridPos": {"h": 8, "w": 8, "x": (i % 3) * 8, "y": (i // 3) * 8},
            "targets": [{"refId": "A", "expr": expr, "legendFormat": leyenda,
                         "datasource": {"type": "prometheus", "uid": "prometheus"}}],
            "fieldConfig": {"defaults": {"unit": "percentunit" if "Tasa" in titulo else "short"}, "overrides": []},
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
