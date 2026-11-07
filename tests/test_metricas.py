"""C7: formato de Prometheus, series en cero desde el arranque y etiquetas de baja cardinalidad."""
import re
from pathlib import Path

from agente import metricas
from agente.detectores import EXTENSIONES
from agente.guardas import CATEGORIAS
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
    permitidos |= set(EXTENSIONES.values())   # lenguajes soportados (crear_app inicia una serie por cada uno)
    permitidos |= set(CATEGORIAS)   # motivos de rechazo de la guarda
    # chat, router y seguridad: también listas cerradas (rutas, motivos del respaldo, origen y acción)
    permitidos |= {"consulta_estandar", "revisar_codigo", "fuera_de_alcance", "bloqueado", "bajo_umbral", "error",
                   "sin_codigo", "codigo_detectado", "mensaje", "codigo", "documento", "detectado",
                   "anthropic", "openai", "openai_embeddings", "secreto", "email", "ruc", "telefono", "dni", "tarjeta",
                   "ok", "igual", "limite", "conexion", "rechazo", "incompleta", "json_invalido"}
    permitidos |= {v for v in valores if re.fullmatch(r"http_\d{3}", v)}   # código HTTP del error: lista cerrada
    assert {v for v in valores if not re.fullmatch(r"[\d.]+|\+Inf", v)} <= permitidos
