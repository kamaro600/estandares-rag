"""C7: el tablero y las alertas solo usan métricas que la app expone (un panel con una métrica mal escrita muestra
"No data" para siempre y nadie se entera), y el tablero versionado es el que genera el script."""
import json
import re
from pathlib import Path

from agente import metricas

RAIZ = Path(__file__).parent.parent


def _expuestas() -> set[str]:
    return {m.nombre for m in metricas.REGISTRO}


def _usadas(texto: str) -> set[str]:
    return {re.sub(r"_(bucket|sum|count)$", "", m) for m in re.findall(r"\blab07_\w+", texto)}


def test_tablero_actualizado_y_con_metricas_existentes():
    from scripts.generar_tablero import PANELES
    tablero = json.loads((RAIZ / "grafana" / "dashboards" / "agente-estandares.json").read_text(encoding="utf-8"))
    assert len(tablero["panels"]) == len(PANELES), "Regenera el tablero: python -m scripts.generar_tablero"
    faltan = _usadas(json.dumps(tablero)) - _expuestas()
    assert not faltan, faltan


def test_alertas_usan_metricas_existentes_y_prometheus_las_carga():
    alertas = (RAIZ / "prometheus" / "alertas.yml").read_text(encoding="utf-8")
    usadas = _usadas(alertas)
    assert usadas and not usadas - _expuestas(), usadas - _expuestas()
    assert "/etc/prometheus/alertas.yml" in (RAIZ / "prometheus" / "prometheus.yml").read_text(encoding="utf-8")
    assert "./prometheus/alertas.yml:/etc/prometheus/alertas.yml" in (RAIZ / "docker-compose.yml").read_text(encoding="utf-8")


def test_la_imagen_incluye_lo_que_necesita_el_chat():
    dockerfile = (RAIZ / "Dockerfile").read_text(encoding="utf-8")
    assert "data/rutas.json" in dockerfile and "--si-falta" in dockerfile
