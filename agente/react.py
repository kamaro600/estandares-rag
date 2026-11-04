"""El bucle ReAct de un especialista: razonar → pedir herramienta → observar, con límites."""
from __future__ import annotations

import json
from dataclasses import dataclass

from agente import config, metricas, tools
from agente.llm import LLM
from agente.trace import Tracer


@dataclass
class ResultadoAgente:
    texto_final: str
    iteraciones: int
    motivo_fin: str   # respuesta | max_iteraciones | bucle


def ejecutar_agente(llm: LLM, system: str, tarea: str, sesion: tools.Sesion,
                    permitidas: tuple[str, ...], tracer: Tracer, rol: str) -> ResultadoAgente:
    mensajes: list[dict] = [{"role": "user", "content": tarea}]
    esquemas = tools.esquemas(permitidas)
    vistas: dict[str, int] = {}
    for i in range(1, config.MAX_REACT_ITERS + 1):
        r = llm.responder(system, mensajes, esquemas)
        tracer.llm(rol, r.tokens_entrada, r.tokens_salida)
        metricas.LLM_LLAMADAS.inc(proveedor=llm.proveedor)
        metricas.LLM_TOKENS.inc(r.tokens_entrada, proveedor=llm.proveedor, tipo="entrada")
        metricas.LLM_TOKENS.inc(r.tokens_salida, proveedor=llm.proveedor, tipo="salida")
        mensajes.append({"role": "assistant", "content": r.contenido})
        pedidos = [b for b in r.contenido if b["type"] == "tool_use"]
        if not pedidos:
            texto = " ".join(b["text"] for b in r.contenido if b["type"] == "text").strip()
            return ResultadoAgente(texto, i, "respuesta")
        resultados = []
        for b in pedidos:
            firma = b["name"] + json.dumps(b["input"], sort_keys=True, ensure_ascii=False)
            vistas[firma] = vistas.get(firma, 0) + 1
            if vistas[firma] > config.MAX_REPEATED_CALLS:
                texto, error = "Llamada repetida con los mismos argumentos: cambia de estrategia.", True
            else:
                texto, error = tools.ejecutar(sesion, b["name"], b["input"], permitidas)
            tracer.evento("herramienta", rol=rol, nombre=b["name"], error=error, resultado=texto[:160])
            # Regla de oro: cada tool_use recibe su tool_result con el MISMO id, aunque haya fallado.
            resultados.append({"type": "tool_result", "tool_use_id": b["id"], "content": texto, "is_error": error})
        mensajes.append({"role": "user", "content": resultados})
        if all(vistas[b["name"] + json.dumps(b["input"], sort_keys=True, ensure_ascii=False)]
               > config.MAX_REPEATED_CALLS for b in pedidos):
            return ResultadoAgente("Detenido: el especialista repetía las mismas llamadas.", i, "bucle")
    return ResultadoAgente("Detenido: se alcanzó el máximo de iteraciones.", config.MAX_REACT_ITERS,
                           "max_iteraciones")
