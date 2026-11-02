"""El LLM. Una interfaz (`generar`) y dos implementaciones.

- OpenAILLM: Responses API con SALIDA ESTRUCTURADA (JSON Schema estricto): el modelo no puede devolver texto libre
  ni inventar campos. `store=False`: la conversación no queda guardada en OpenAI. Antes de enviar, el contexto pasa
  por privacidad.enmascarar() (secretos y datos personales).
- ClaudeLLM (app/llm_claude.py): Claude de Anthropic, misma interfaz y las mismas garantías.
- MockLLM: reglas fijas, sin red. NO es inteligencia: arma la respuesta con el texto del mejor fragmento. Existe
  para que pytest y la demo corran sin clave ni costo.

Todas las instrucciones dicen lo mismo sobre seguridad: lo que escribe el usuario y el código son DATOS, no órdenes.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass

from app import metricas
from app.privacidad import enmascarar


class LLMError(RuntimeError):
    """Fallo del proveedor: red, clave, límite, respuesta incompleta o JSON inválido."""


@dataclass
class RespuestaLLM:
    datos: dict
    modelo: str
    input_tokens: int = 0
    output_tokens: int = 0


LISTA_TEXTO = {"type": "array", "items": {"type": "string"}}
ESQUEMA_RESPUESTA = {
    "type": "object", "additionalProperties": False, "required": ["respuesta", "citas"],
    "properties": {"respuesta": {"type": "string"}, "citas": LISTA_TEXTO},
}
ESQUEMA_REFORMULA = {
    "type": "object", "additionalProperties": False, "required": ["consulta"],
    "properties": {"consulta": {"type": "string"}},
}
ESQUEMA_VALIDACION = {
    "type": "object", "additionalProperties": False, "required": ["resumen", "explicaciones", "adicionales"],
    "properties": {
        "resumen": {"type": "string"},
        "explicaciones": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["indice", "explicacion", "recomendacion"],
            "properties": {"indice": {"type": "integer"}, "explicacion": {"type": "string"},
                           "recomendacion": {"type": "string"}}}},
        "adicionales": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["regla_id", "titulo", "severidad", "linea", "explicacion", "recomendacion"],
            "properties": {"regla_id": {"type": "string"}, "titulo": {"type": "string"},
                           "severidad": {"type": "string", "enum": ["critica", "alta", "media", "baja"]},
                           "linea": {"type": "integer"}, "explicacion": {"type": "string"},
                           "recomendacion": {"type": "string"}}}},
    },
}


class OpenAILLM:
    nombre = "openai"

    def __init__(self, settings, client=None):
        from openai import OpenAI

        self.modelo = settings.openai_model
        self.esfuerzo = settings.openai_reasoning_effort
        self.max_tokens = settings.openai_max_output_tokens
        self.precio_in, self.precio_out = settings.precio_openai_input, settings.precio_openai_output
        self.client = client or OpenAI(api_key=settings.openai_api_key, timeout=settings.openai_timeout_s, max_retries=2)

    def generar(self, instrucciones: str, contexto: dict, esquema: dict, nombre: str) -> RespuestaLLM:
        import openai

        kwargs = {"model": self.modelo, "instructions": instrucciones, "store": False,
                  "input": enmascarar(json.dumps(contexto, ensure_ascii=False, indent=1)),
                  "text": {"format": {"type": "json_schema", "name": nombre, "schema": esquema, "strict": True}},
                  "max_output_tokens": self.max_tokens}
        if self.esfuerzo:
            kwargs["reasoning"] = {"effort": self.esfuerzo}
        t0 = time.perf_counter()
        try:
            r = self.client.responses.create(**kwargs)
        except openai.APIError as e:
            metricas.API_ERRORES.labels("openai_llm", type(e).__name__).inc()
            raise LLMError(f"OpenAI falló: {type(e).__name__}: {e}") from e
        finally:
            metricas.API_LATENCIA.labels("openai_llm").observe(time.perf_counter() - t0)

        uso_in = r.usage.input_tokens if r.usage else 0
        uso_out = r.usage.output_tokens if r.usage else 0
        metricas.TOKENS.labels("openai_llm", "input").inc(uso_in)
        metricas.TOKENS.labels("openai_llm", "output").inc(uso_out)
        metricas.COSTO.labels("openai_llm").inc((uso_in * self.precio_in + uso_out * self.precio_out) / 1e6)
        if r.status != "completed":
            metricas.API_ERRORES.labels("openai_llm", "incompleta").inc()
            raise LLMError(f"respuesta {r.status}: {r.incomplete_details}")
        try:
            datos = json.loads(r.output_text)      # vacío si el modelo se negó (refusal)
        except json.JSONDecodeError as e:
            metricas.API_ERRORES.labels("openai_llm", "json_invalido").inc()
            raise LLMError(f"JSON inválido: {r.output_text[:200]!r}") from e
        return RespuestaLLM(datos, r.model, uso_in, uso_out)


class MockLLM:
    """Simulador determinista (ver docstring del módulo)."""
    nombre = "mock"
    modelo = "mock"

    def generar(self, instrucciones: str, contexto: dict, esquema: dict, nombre: str) -> RespuestaLLM:
        if nombre == "reformulacion":
            previas = [m["texto"] for m in contexto.get("conversacion_previa", []) if m["rol"] == "usuario"]
            return RespuestaLLM({"consulta": f"{previas[-1]} {contexto['mensaje']}" if previas else contexto["mensaje"]},
                                self.modelo)
        if nombre == "validacion":
            return RespuestaLLM({
                "resumen": f"[simulado] {len(contexto['hallazgos'])} hallazgo(s) detectado(s) por las reglas.",
                "explicaciones": [{"indice": i, "explicacion": f"[simulado] Incumple {h['regla_id']}: {h['titulo']}.",
                                   "recomendacion": "[simulado] Ver el ejemplo correcto de la regla citada."}
                                  for i, h in enumerate(contexto["hallazgos"])],
                "adicionales": []}, self.modelo)
        reglas = contexto.get("estandares", [])
        if not reglas:
            return RespuestaLLM({"respuesta": "[simulado] No hay información en los estándares.", "citas": []}, self.modelo)
        top = reglas[0]
        texto = " ".join(top["texto"].split())[:450]
        return RespuestaLLM({"respuesta": f"[simulado] Según {top['cita']}: {texto}", "citas": [top["id"]]}, self.modelo)


def crear_llm(settings):
    if settings.llm_provider == "anthropic":
        from app.llm_claude import ClaudeLLM
        return ClaudeLLM(settings)
    return OpenAILLM(settings) if settings.llm_provider == "openai" else MockLLM()
