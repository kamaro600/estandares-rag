"""C7: el tablero y las alertas solo usan métricas que la aplicación realmente expone (un panel con una métrica mal
escrita muestra "No data" para siempre y nadie se entera)."""
import json
import re

from tests.conftest import RAIZ


def _expuestas(cliente) -> set[str]:
    texto = cliente.get("/metrics").text
    return {m.group(1) for m in re.finditer(r"^# TYPE (est_\w+) ", texto, re.M)}


def _usadas(texto: str) -> set[str]:
    return {re.sub(r"_(bucket|sum|count)$", "", m) for m in re.findall(r"\best_\w+", texto)}


def test_tablero_actualizado_y_con_metricas_existentes(cliente):
    from grafana.generar_dashboard import DESTINO, construir
    assert json.loads(DESTINO.read_text(encoding="utf-8")) == json.loads(json.dumps(construir())), \
        "Regenera el tablero: python -m grafana.generar_dashboard"
    expuestas = _expuestas(cliente)
    usadas = _usadas(DESTINO.read_text(encoding="utf-8"))
    # prometheus_client expone un contador "x" como "x_total" y lo declara en # TYPE sin el sufijo
    faltan = {u for u in usadas if u not in expuestas and u.removesuffix("_total") not in expuestas}
    assert not faltan, faltan


def test_alertas_usan_metricas_existentes(cliente):
    expuestas = _expuestas(cliente)
    usadas = _usadas((RAIZ / "prometheus" / "alertas.yml").read_text(encoding="utf-8"))
    faltan = {u for u in usadas if u not in expuestas and u.removesuffix("_total") not in expuestas}
    assert usadas and not faltan, faltan
