"""El modelo, intercambiable: mismo contrato para Claude, OpenAI y el simulador."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Protocol

from agente.config import Settings, importar_sdk


@dataclass
class Respuesta:
    contenido: list[dict]             # bloques {"type":"text"} y {"type":"tool_use","id","name","input"}
    stop_reason: str                  # "tool_use" | "end_turn" | "max_tokens"
    tokens_entrada: int = 0
    tokens_salida: int = 0
    extra: dict = field(default_factory=dict)


class LLM(Protocol):
    proveedor: str

    def responder(self, system: str, mensajes: list[dict], herramientas: list[dict]) -> Respuesta: ...


class AnthropicLLM:
    """Messages API de Claude con tool use. El SDK se importa solo si se usa este proveedor."""
    proveedor = "anthropic"

    def __init__(self, modelo: str, api_key: str, client=None, max_tokens: int = 2048):
        if client is None:
            client = importar_sdk("anthropic").Anthropic(api_key=api_key, max_retries=2, timeout=60)
        self.client, self.modelo, self.max_tokens = client, modelo, max_tokens

    def responder(self, system: str, mensajes: list[dict], herramientas: list[dict]) -> Respuesta:
        r = self.client.messages.create(model=self.modelo, max_tokens=self.max_tokens, system=system,
                                        messages=mensajes, tools=herramientas)
        bloques = []
        for b in r.content:
            d = b.model_dump() if hasattr(b, "model_dump") else dict(b)
            if d.get("type") == "text":
                bloques.append({"type": "text", "text": d["text"]})
            elif d.get("type") == "tool_use":
                bloques.append({"type": "tool_use", "id": d["id"], "name": d["name"], "input": d["input"]})
        return Respuesta(bloques, r.stop_reason, r.usage.input_tokens, r.usage.output_tokens)


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

    def __init__(self, modelo: str, api_key: str, client=None, max_tokens: int = 2048, reasoning_effort: str = ""):
        if client is None:
            client = importar_sdk("openai").OpenAI(api_key=api_key, max_retries=2, timeout=60)
        self.client, self.modelo, self.max_tokens, self.reasoning_effort = client, modelo, max_tokens, reasoning_effort

    def responder(self, system: str, mensajes: list[dict], herramientas: list[dict]) -> Respuesta:
        pedido = {"model": self.modelo, "messages": a_openai(system, mensajes),
                  "max_completion_tokens": self.max_tokens,
                  "tools": [{"type": "function", "function": {"name": h["name"], "description": h["description"],
                                                              "parameters": h["input_schema"]}} for h in herramientas]}
        if self.reasoning_effort:   # solo modelos de razonamiento; vacío = no se envía
            pedido["reasoning_effort"] = self.reasoning_effort
        r = self.client.chat.completions.create(**pedido)
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


def crear_llm(settings: Settings) -> LLM:
    if settings.llm_provider == "anthropic":
        return AnthropicLLM(settings.llm_model, settings.anthropic_api_key)
    if settings.llm_provider == "openai":
        return OpenAILLM(settings.openai_model, settings.openai_api_key,
                         reasoning_effort=settings.openai_reasoning_effort)
    from agente.llm_mock import MockLLM  # noqa: PLC0415
    return MockLLM()
