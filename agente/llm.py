"""El modelo, intercambiable: mismo contrato para Claude, OpenAI y el simulador.

Dos formas de usarlo:
  responder(system, mensajes, herramientas)  → el bucle ReAct del especialista (tool use)
  generar_json(system, contexto, esquema)    → el chat (respuesta con citas, reformulación): salida JSON con esquema
                                               estricto, el modelo no puede devolver texto libre ni inventar campos

Todo lo que sale hacia el proveedor pasa por privacidad.enmascarar (secretos y datos personales), aquí y no en
quien llama: así nadie puede olvidarlo.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Protocol

from agente import metricas
from agente.config import Settings, importar_sdk
from agente.privacidad import enmascarar, enmascarar_mensajes

BETA_RESPALDO = "server-side-fallback-2026-07-01"


class LLMError(RuntimeError):
    """El proveedor falló, cortó la respuesta, la rechazó por seguridad o devolvió JSON inválido."""


@dataclass
class Respuesta:
    contenido: list[dict]             # bloques {"type":"text"}, {"type":"tool_use","id","name","input"} y, en Claude,
                                      # {"type":"thinking"…}: se devuelven tal cual en el historial
    stop_reason: str                  # "tool_use" | "end_turn" | "max_tokens" | "refusal"
    tokens_entrada: int = 0
    tokens_salida: int = 0
    extra: dict = field(default_factory=dict)


@dataclass
class RespuestaJSON:
    datos: dict
    modelo: str
    tokens_entrada: int = 0
    tokens_salida: int = 0


class LLM(Protocol):
    proveedor: str

    def responder(self, system: str, mensajes: list[dict], herramientas: list[dict]) -> Respuesta: ...

    def generar_json(self, system: str, contexto: dict, esquema: dict, nombre: str) -> RespuestaJSON: ...


def _medir(proveedor: str, inicio: float, entrada: int, salida: int, precio_in: float, precio_out: float) -> None:
    metricas.LLM_SEGUNDOS.observar(time.perf_counter() - inicio)
    metricas.COSTO.inc((entrada * precio_in + salida * precio_out) / 1e6, proveedor=proveedor)


def _json(texto: str, proveedor: str) -> dict:
    try:
        return json.loads(texto)
    except json.JSONDecodeError as e:
        metricas.LLM_ERRORES.inc(proveedor=proveedor, tipo="json_invalido")
        raise LLMError(f"JSON inválido: {texto[:200]!r}") from e


# Campos que la API de Claude acepta de vuelta en el historial, por tipo de bloque. Los bloques de razonamiento
# (thinking) DEBEN volver sin cambios: en Opus 5.5 el razonamiento siempre está activo y alterar el historial es un
# error. Cualquier otro tipo (p. ej. el bloque que marca un respaldo de modelo) se devuelve completo.
CAMPOS = {"text": ("type", "text"), "tool_use": ("type", "id", "name", "input"),
          "thinking": ("type", "thinking", "signature"), "redacted_thinking": ("type", "data")}


def _bloque(b) -> dict:
    d = b.model_dump() if hasattr(b, "model_dump") else dict(b)
    campos = CAMPOS.get(d.get("type"))
    return {k: d[k] for k in campos if k in d} if campos else {k: v for k, v in d.items() if v is not None}


class AnthropicLLM:
    """Messages API de Claude con tool use y salida estructurada. El SDK se importa solo si se usa."""
    proveedor = "anthropic"

    def __init__(self, modelo: str, api_key: str, client=None, max_tokens: int = 16000, esfuerzo: str = "",
                 respaldo: str = "", timeout: float = 120, precios: tuple[float, float] = (0, 0)):
        if client is None:
            client = importar_sdk("anthropic").Anthropic(api_key=api_key, max_retries=2, timeout=timeout)
        self.client, self.modelo, self.max_tokens = client, modelo, max_tokens
        self.esfuerzo, self.respaldo, self.precios = esfuerzo, respaldo, precios

    def _crear(self, **kwargs):
        """Una llamada con esfuerzo y respaldo ante rechazos; los errores del SDK se vuelven LLMError legibles."""
        anthropic = importar_sdk("anthropic")
        if self.esfuerzo:
            kwargs.setdefault("output_config", {})["effort"] = self.esfuerzo
        inicio = time.perf_counter()
        try:
            if self.respaldo:   # si los clasificadores rechazan, el servidor reintenta con otro modelo en la misma llamada
                r = self.client.beta.messages.create(**kwargs, betas=[BETA_RESPALDO], fallbacks=self.respaldo)
            else:
                r = self.client.messages.create(**kwargs)
        except anthropic.RateLimitError as e:
            metricas.LLM_ERRORES.inc(proveedor=self.proveedor, tipo="limite")
            raise LLMError(f"Claude: límite de solicitudes ({e.status_code})") from e
        except anthropic.APIStatusError as e:
            metricas.LLM_ERRORES.inc(proveedor=self.proveedor, tipo=f"http_{e.status_code}")
            raise LLMError(f"Claude falló: HTTP {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            metricas.LLM_ERRORES.inc(proveedor=self.proveedor, tipo="conexion")
            raise LLMError(f"Claude: sin conexión ({type(e).__name__})") from e
        _medir(self.proveedor, inicio, r.usage.input_tokens, r.usage.output_tokens, *self.precios)
        if r.stop_reason == "refusal":
            metricas.LLM_ERRORES.inc(proveedor=self.proveedor, tipo="rechazo")
        return r

    def responder(self, system: str, mensajes: list[dict], herramientas: list[dict]) -> Respuesta:
        r = self._crear(model=self.modelo, max_tokens=self.max_tokens, system=system,
                        messages=enmascarar_mensajes(mensajes), tools=herramientas)
        if r.stop_reason == "refusal":   # el especialista termina; sus hallazgos pasan a revisión humana
            categoria = getattr(r.stop_details, "category", None) if getattr(r, "stop_details", None) else None
            return Respuesta([{"type": "text", "text": f"El modelo rechazó la solicitud (categoría {categoria}): "
                                                       "los hallazgos pendientes pasan a revisión humana."}],
                             "refusal", r.usage.input_tokens, r.usage.output_tokens)
        return Respuesta([_bloque(b) for b in r.content], r.stop_reason, r.usage.input_tokens, r.usage.output_tokens)

    def generar_json(self, system: str, contexto: dict, esquema: dict, nombre: str) -> RespuestaJSON:
        r = self._crear(model=self.modelo, max_tokens=self.max_tokens, system=system,
                        messages=[{"role": "user", "content": enmascarar(json.dumps(contexto, ensure_ascii=False, indent=1))}],
                        output_config={"format": {"type": "json_schema", "schema": esquema}})
        if r.stop_reason == "refusal":
            raise LLMError("Claude rechazó la solicitud por seguridad")
        if r.stop_reason == "max_tokens":
            metricas.LLM_ERRORES.inc(proveedor=self.proveedor, tipo="incompleta")
            raise LLMError(f"respuesta cortada en max_tokens={self.max_tokens}")
        texto = "".join(b.text for b in r.content if b.type == "text")   # los bloques de razonamiento se ignoran
        return RespuestaJSON(_json(texto, self.proveedor), r.model, r.usage.input_tokens, r.usage.output_tokens)


def a_openai(system: str, mensajes: list[dict]) -> list[dict]:
    """Traduce el historial (formato de bloques de Claude) al de Chat Completions de OpenAI."""
    salida = [{"role": "system", "content": system}]
    for m in mensajes:
        c = m["content"]
        if isinstance(c, str):
            salida.append({"role": m["role"], "content": c})
        elif m["role"] == "assistant":
            texto = " ".join(b["text"] for b in c if b["type"] == "text").strip()
            llamadas = [{"id": b["id"], "type": "function",
                         "function": {"name": b["name"], "arguments": json.dumps(b["input"], ensure_ascii=False)}}
                        for b in c if b["type"] == "tool_use"]
            d = {"role": "assistant", "content": texto or None}
            if llamadas:
                d["tool_calls"] = llamadas
            salida.append(d)
        else:  # cada tool_result es un mensaje role="tool" con el MISMO id de la llamada
            for b in c:
                if b["type"] == "tool_result":
                    contenido = ("ERROR: " if b.get("is_error") else "") + b["content"]
                    salida.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": contenido})
                elif b["type"] == "text":
                    salida.append({"role": "user", "content": b["text"]})
    return salida


class OpenAILLM:
    """Chat Completions de OpenAI con tool calling, traducido al mismo contrato que Claude."""
    proveedor = "openai"

    def __init__(self, modelo: str, api_key: str, client=None, max_tokens: int = 4096, reasoning_effort: str = "",
                 timeout: float = 120, precios: tuple[float, float] = (0, 0)):
        if client is None:
            client = importar_sdk("openai").OpenAI(api_key=api_key, max_retries=2, timeout=timeout)
        self.client, self.modelo, self.max_tokens, self.reasoning_effort = client, modelo, max_tokens, reasoning_effort
        self.precios = precios

    def _crear(self, **pedido):
        openai = importar_sdk("openai")
        if self.reasoning_effort:   # solo modelos de razonamiento; vacío = no se envía
            pedido["reasoning_effort"] = self.reasoning_effort
        inicio = time.perf_counter()
        try:
            r = self.client.chat.completions.create(**pedido)
        except openai.APIError as e:
            metricas.LLM_ERRORES.inc(proveedor=self.proveedor, tipo=type(e).__name__)
            raise LLMError(f"OpenAI falló: {type(e).__name__}: {e}") from e
        uso = r.usage
        _medir(self.proveedor, inicio, getattr(uso, "prompt_tokens", 0) or 0, getattr(uso, "completion_tokens", 0) or 0,
               *self.precios)
        return r

    def responder(self, system: str, mensajes: list[dict], herramientas: list[dict]) -> Respuesta:
        r = self._crear(model=self.modelo, messages=a_openai(system, enmascarar_mensajes(mensajes)),
                        max_completion_tokens=self.max_tokens,
                        tools=[{"type": "function", "function": {"name": h["name"], "description": h["description"],
                                                                 "parameters": h["input_schema"]}} for h in herramientas])
        eleccion = r.choices[0]
        msg = eleccion.message
        bloques = [{"type": "text", "text": msg.content}] if msg.content else []
        for tc in msg.tool_calls or []:
            try:
                entrada = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:   # JSON roto: la validación lo devuelve como error legible
                entrada = {"_json_invalido": tc.function.arguments}
            bloques.append({"type": "tool_use", "id": tc.id, "name": tc.function.name, "input": entrada})
        parada = "tool_use" if msg.tool_calls else ("max_tokens" if eleccion.finish_reason == "length" else "end_turn")
        uso = r.usage
        return Respuesta(bloques, parada, getattr(uso, "prompt_tokens", 0) or 0, getattr(uso, "completion_tokens", 0) or 0)

    def generar_json(self, system: str, contexto: dict, esquema: dict, nombre: str) -> RespuestaJSON:
        r = self._crear(model=self.modelo, max_completion_tokens=self.max_tokens,
                        messages=[{"role": "system", "content": system},
                                  {"role": "user", "content": enmascarar(json.dumps(contexto, ensure_ascii=False, indent=1))}],
                        response_format={"type": "json_schema",
                                         "json_schema": {"name": nombre, "schema": esquema, "strict": True}})
        eleccion = r.choices[0]
        if eleccion.finish_reason == "length":
            metricas.LLM_ERRORES.inc(proveedor=self.proveedor, tipo="incompleta")
            raise LLMError(f"respuesta cortada en max_completion_tokens={self.max_tokens}")
        uso = r.usage
        return RespuestaJSON(_json(eleccion.message.content or "", self.proveedor), r.model,
                             getattr(uso, "prompt_tokens", 0) or 0, getattr(uso, "completion_tokens", 0) or 0)


def crear_llm(settings: Settings) -> LLM:
    """El adaptador del proveedor configurado en LLM_PROVIDER (mock, anthropic u openai)."""
    precios = (settings.precio_llm_entrada, settings.precio_llm_salida)
    if settings.llm_provider == "anthropic":
        return AnthropicLLM(settings.llm_model, settings.anthropic_api_key, max_tokens=settings.llm_max_tokens,
                            esfuerzo=settings.anthropic_effort, respaldo=settings.anthropic_fallback,
                            timeout=settings.llm_timeout_s, precios=precios)
    if settings.llm_provider == "openai":
        return OpenAILLM(settings.openai_model, settings.openai_api_key, max_tokens=min(settings.llm_max_tokens, 8000),
                         reasoning_effort=settings.openai_reasoning_effort, timeout=settings.llm_timeout_s, precios=precios)
    from agente.llm_mock import MockLLM  # noqa: PLC0415
    return MockLLM()
