"""El LLM con Claude (Anthropic). Misma interfaz que app/llm.py: `generar(instrucciones, contexto, esquema, nombre)`.

- SALIDA ESTRUCTURADA: `output_config.format` con JSON Schema (los esquemas de app/llm.py ya cumplen lo que exige:
  `additionalProperties: false` y `required`). El modelo no puede devolver texto libre ni inventar campos.
- Esfuerzo explícito (`output_config.effort`): en Claude Opus 5.5 el razonamiento siempre está activo y el esfuerzo
  es el único control de profundidad y costo. Su valor por defecto es `medium`; aquí se fija desde .env.
- Respaldo ante rechazos: si los clasificadores de seguridad rechazan una solicitud (p. ej. un código con un exploit
  real pegado para validarlo), `fallbacks: "default"` reintenta con otro modelo en la misma llamada. Si toda la cadena
  rechaza, `stop_reason == "refusal"` y se devuelve LLMError: el agente degrada a lo verificado por reglas.
- Privacidad: el contexto pasa por privacidad.enmascarar() antes de salir, igual que con OpenAI.

Anthropic no ofrece modelo de embeddings: los vectores siguen saliendo de OpenAI (como en el lab 01).
"""
from __future__ import annotations

import json
import time

from app import metricas
from app.llm import LLMError, RespuestaLLM
from app.privacidad import enmascarar

PROVEEDOR = "claude_llm"
BETA_RESPALDO = "server-side-fallback-2026-07-01"


class ClaudeLLM:
    nombre = "anthropic"

    def __init__(self, settings, client=None):
        import anthropic

        self.modelo = settings.anthropic_model
        self.esfuerzo = settings.anthropic_effort
        self.respaldo = settings.anthropic_fallback
        self.max_tokens = settings.anthropic_max_tokens
        self.precio_in, self.precio_out = settings.precio_anthropic_input, settings.precio_anthropic_output
        self.client = client or anthropic.Anthropic(api_key=settings.anthropic_api_key,
                                                    timeout=settings.anthropic_timeout_s, max_retries=2)

    def generar(self, instrucciones: str, contexto: dict, esquema: dict, nombre: str) -> RespuestaLLM:
        import anthropic

        output_config = {"format": {"type": "json_schema", "schema": esquema}}
        if self.esfuerzo:
            output_config["effort"] = self.esfuerzo
        kwargs = {"model": self.modelo, "max_tokens": self.max_tokens, "system": instrucciones,
                  "messages": [{"role": "user", "content": enmascarar(json.dumps(contexto, ensure_ascii=False, indent=1))}],
                  "output_config": output_config}
        if self.respaldo:
            kwargs.update(betas=[BETA_RESPALDO], fallbacks=self.respaldo)
        t0 = time.perf_counter()
        try:
            r = self.client.beta.messages.create(**kwargs)
        except anthropic.RateLimitError as e:              # 429: el SDK ya reintentó 2 veces
            metricas.API_ERRORES.labels(PROVEEDOR, "limite").inc()
            raise LLMError(f"Claude: límite de solicitudes ({e.status_code})") from e
        except anthropic.APIStatusError as e:              # 400 (esquema/parámetros), 401 (clave), 5xx…
            metricas.API_ERRORES.labels(PROVEEDOR, f"http_{e.status_code}").inc()
            raise LLMError(f"Claude falló: HTTP {e.status_code}: {e.message} (request-id {e.request_id})") from e
        except anthropic.APIConnectionError as e:          # red o timeout
            metricas.API_ERRORES.labels(PROVEEDOR, type(e).__name__).inc()
            raise LLMError(f"Claude: sin conexión ({type(e).__name__})") from e
        finally:
            metricas.API_LATENCIA.labels(PROVEEDOR).observe(time.perf_counter() - t0)

        uso_in = r.usage.input_tokens if r.usage else 0
        uso_out = r.usage.output_tokens if r.usage else 0
        metricas.TOKENS.labels(PROVEEDOR, "input").inc(uso_in)
        metricas.TOKENS.labels(PROVEEDOR, "output").inc(uso_out)
        metricas.COSTO.labels(PROVEEDOR).inc((uso_in * self.precio_in + uso_out * self.precio_out) / 1e6)

        if r.stop_reason == "refusal":
            categoria = getattr(r.stop_details, "category", None) if r.stop_details else None
            metricas.API_ERRORES.labels(PROVEEDOR, "rechazo").inc()
            raise LLMError(f"Claude rechazó la solicitud (categoría {categoria})")
        if r.stop_reason == "max_tokens":
            metricas.API_ERRORES.labels(PROVEEDOR, "incompleta").inc()
            raise LLMError(f"respuesta cortada en max_tokens={self.max_tokens}")
        texto = "".join(b.text for b in r.content if b.type == "text")   # los bloques de razonamiento se ignoran
        try:
            datos = json.loads(texto)
        except json.JSONDecodeError as e:
            metricas.API_ERRORES.labels(PROVEEDOR, "json_invalido").inc()
            raise LLMError(f"JSON inválido: {texto[:200]!r}") from e
        return RespuestaLLM(datos, r.model, uso_in, uso_out)
