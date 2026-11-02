"""Las métricas que Prometheus lee en GET /metrics y que Grafana dibuja.

Convención: prefijo `est_`, `_total` para contadores, unidad al final (`_segundos`).
Cardinalidad: las etiquetas toman valores de listas cerradas (ruta, severidad, origen…). NUNCA el texto del usuario,
el id de una regla o el id de una conversación.
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

RUTAS = ["consulta_estandar", "validar_codigo", "fuera_de_alcance", "bloqueado"]
SEVERIDADES = ["critica", "alta", "media", "baja"]
ORIGENES = ["regla", "llm"]
PROVEEDORES_API = ["claude_llm", "openai_llm", "openai_emb"]
PROB = [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0]
LATENCIA = [0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8, 15, 30, 60]

CHAT_MENSAJES = Counter("est_chat_mensajes_total", "Mensajes del usuario por ruta elegida", ["ruta"])
CHAT_LATENCIA = Histogram("est_chat_latencia_segundos", "Desde que llega el mensaje hasta la respuesta", ["ruta"],
                          buckets=LATENCIA)
ROUTER_CONFIANZA = Histogram("est_router_confianza", "Similitud de la ruta elegida por el router semántico",
                             buckets=PROB)
ROUTER_RESPALDO = Counter("est_router_respaldo_total", "Decisiones tomadas por el router de respaldo", ["motivo"])
REFORMULACIONES = Counter("est_reformulaciones_total", "Preguntas de seguimiento reformuladas", ["resultado"])
RAG_SCORE = Histogram("est_rag_score", "Similitud del mejor fragmento recuperado", buckets=PROB)
RAG_SIN_CONTEXTO = Counter("est_rag_sin_contexto_total", "Consultas sin fragmentos sobre el umbral (abstención)")
RAG_CATEGORIA = Counter("est_rag_fragmentos_total", "Fragmentos entregados al LLM por categoría de estándar",
                        ["categoria"])
CITAS_INVALIDAS = Counter("est_citas_invalidas_total", "Citas del LLM a reglas que no estaban en su contexto")
INYECCION = Counter("est_inyeccion_total", "Intentos de prompt injection detectados", ["origen", "accion"])
PII = Counter("est_datos_enmascarados_total", "Datos personales o secretos enmascarados antes de salir hacia Claude u OpenAI", ["tipo"])
VALIDACIONES = Counter("est_validaciones_total", "Validaciones de código terminadas", ["resultado"])
HALLAZGOS = Counter("est_hallazgos_total", "Hallazgos de la validación de código", ["origen", "severidad"])
PISO = Counter("est_piso_agregado_total", "Hallazgos deterministas que el LLM omitió y la guarda restituyó")
REVISIONES = Counter("est_revisiones_total", "Decisiones humanas sobre hallazgos", ["decision", "origen"])
API_LATENCIA = Histogram("est_api_latencia_segundos", "Latencia de cada llamada al proveedor de IA", ["proveedor"],
                         buckets=LATENCIA)
API_ERRORES = Counter("est_api_errores_total", "Errores del proveedor de IA (Claude u OpenAI)", ["proveedor", "tipo"])
TOKENS = Counter("est_tokens_total", "Tokens consumidos", ["proveedor", "tipo"])
COSTO = Counter("est_costo_estimado_usd_total", "Costo estimado en USD (precios de .env)", ["proveedor"])
LIMITE_TASA = Counter("est_limite_tasa_total", "Peticiones rechazadas con 429 por límite de tasa")
INDICE_FRAGMENTOS = Gauge("est_indice_fragmentos", "Fragmentos en el índice vectorial", ["categoria"])
REPORTES_PENDIENTES = Gauge("est_reportes_pendientes", "Reportes de validación sin revisión humana")


def inicializar_series() -> None:
    """Crea en 0 las series con etiquetas conocidas: Grafana muestra 0 en lugar de "No data" al arrancar."""
    for r in RUTAS:
        CHAT_MENSAJES.labels(r)
    for o in ORIGENES:
        for s in SEVERIDADES:
            HALLAZGOS.labels(o, s)
        for d in ("confirmado", "descartado"):
            REVISIONES.labels(d, o)
    for p in PROVEEDORES_API:
        for t in ("input", "output"):
            TOKENS.labels(p, t)
        COSTO.labels(p)
    for res in ("cumple", "no_cumple", "error_llm"):
        VALIDACIONES.labels(res)
    for o in ("mensaje", "codigo", "documento"):
        INYECCION.labels(o, "detectado")
