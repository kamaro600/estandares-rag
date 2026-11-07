"""python -m scripts.verificar_claves  →  prueba de humo contra los proveedores REALES del .env (unos centavos).

Las pruebas de pytest nunca llaman a un proveedor real. Este script sí, y verifica lo que solo se ve con la API real:
  1. embeddings: la clave funciona y la dimensión es la esperada;
  2. chat: respuesta JSON con el esquema estricto (lo que usa el chat para responder citando reglas);
  3. agente: un ciclo de herramientas COMPLETO (pedir herramienta → resultado → respuesta final). Con Claude Opus 5.5
     el razonamiento siempre está activo y sus bloques deben volver intactos en el historial: si el adaptador los
     alterara, la segunda llamada fallaría.
Muestra latencia y tokens para registrarlos en el análisis.
"""
from __future__ import annotations

import sys
import time

from agente import config, embeddings
from agente.conversacion import ESQUEMA_RESPUESTA
from agente.llm import LLMError, crear_llm

HERRAMIENTA = [{"name": "obtener_regla", "description": "Texto exacto de una regla del catálogo, con su cita.",
                "input_schema": {"type": "object", "additionalProperties": False, "required": ["regla_id"],
                                 "properties": {"regla_id": {"type": "string"}}}}]


def main() -> None:
    config.consola_segura()
    config.load_env()
    s = config.Settings().validar()
    t0 = time.perf_counter()
    m = embeddings.vectorizar(["¿Cómo se nombran los procedimientos almacenados?"])
    print(f"1) Embeddings OK: {embeddings.descriptor()} · {m.shape[1]} dimensiones · {time.perf_counter() - t0:.1f} s")

    llm = crear_llm(s)
    t0 = time.perf_counter()
    r = llm.generar_json("Responde en español en una frase usando solo 'estandares'. Cita el id usado.",
                         {"estandares": [{"id": "WEB-BD-005", "texto": "Los procedimientos se nombran usp_<Entidad>_<Accion>."}],
                          "pregunta": "¿Cómo nombro un procedimiento?"}, ESQUEMA_RESPUESTA, "respuesta")
    print(f"2) Chat OK: {s.llm_provider} · {r.modelo} · {time.perf_counter() - t0:.1f} s · tokens {r.tokens_entrada}/"
          f"{r.tokens_salida}\n   → {r.datos}")

    t0 = time.perf_counter()
    mensajes = [{"role": "user", "content": "Usa la herramienta obtener_regla con WEB-BD-005 y luego resume la regla "
                                            "en una frase. No respondas sin usar la herramienta."}]
    primera = llm.responder("Eres un revisor de código. Usa herramientas cuando se te pida.", mensajes, HERRAMIENTA)
    usos = [b for b in primera.contenido if b["type"] == "tool_use"]
    if not usos:
        raise LLMError(f"el modelo no pidió la herramienta (stop_reason={primera.stop_reason})")
    tipos = [b["type"] for b in primera.contenido]
    mensajes += [{"role": "assistant", "content": primera.contenido},
                 {"role": "user", "content": [{"type": "tool_result", "tool_use_id": usos[0]["id"],
                                               "content": "WEB-BD-005 · Procedimientos: usp_<Entidad>_<Accion>; "
                                                          "prohibido el prefijo sp_."}]}]
    final = llm.responder("Eres un revisor de código. Usa herramientas cuando se te pida.", mensajes, HERRAMIENTA)
    texto = " ".join(b["text"] for b in final.contenido if b["type"] == "text")
    print(f"3) Agente OK: ciclo de herramientas completo · bloques del primer turno {tipos} · "
          f"{time.perf_counter() - t0:.1f} s\n   → {texto[:200]}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, LLMError, embeddings.EmbeddingError) as e:
        sys.exit(f"Error: {e}")
