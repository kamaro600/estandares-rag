import re
from pathlib import Path

from agente import metricas
from agente.contexto import Contexto
from agente.llm_mock import MockLLM
from agente.supervisor import Supervisor
from agente.trace import Tracer


def test_formato_prometheus_y_series_en_cero():
    metricas.inicializar_series(("csharp",))
    texto = metricas.exponer()
    assert "# TYPE lab07_hallazgos_total counter" in texto
    assert 'lab07_revisiones_total{veredicto="APTO"}' in texto
    assert 'lab07_revision_segundos_bucket{le="+Inf"}' in texto


def test_etiquetas_de_baja_cardinalidad():
    """Ni nombres de archivo ni ids: solo valores de listas cerradas."""
    sup = Supervisor(Contexto(), MockLLM(), Tracer(destino=Path("no-usada.jsonl")))
    sup.revisar([("ruta/secreta/Servicio.cs", "var c = s.LeerAsync().Result;\nvar r = new Random();")])
    texto = metricas.exponer()
    assert "Servicio" not in texto and "secreta" not in texto and "H001" not in texto
    valores = set(re.findall(r'="([^"]*)"', texto))
    permitidos = {"APTO", "NO_APTO", "REVISAR", "bloqueante", "advertencia", "determinista", "llm", "aceptado",
                  "rechazado", "aprobado", "denegado", "mock", "guion", "entrada", "salida",
                  "csharp", "typescript", "html", "tsql", "xaml", "config"}
    permitidos |= {"no_existe", "regla", "rango", "tamano", "vacio", "supresion", "comentado", "identico",
                   "sigue_presente", "introduce_nuevos"}
    assert {v for v in valores if not re.fullmatch(r"[\d.]+|\+Inf", v)} <= permitidos
