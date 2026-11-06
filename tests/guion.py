"""Un LLM guionado para pruebas: devuelve respuestas fijas y registra lo que recibió."""
from agente.llm import Respuesta


class LLMGuionado:
    proveedor = "guion"

    def __init__(self, turnos: list[list[dict]]):
        self.turnos, self.recibidos = turnos, []

    def responder(self, system, mensajes, herramientas):
        self.recibidos.append([dict(m) for m in mensajes])
        bloques = self.turnos[min(len(self.recibidos) - 1, len(self.turnos) - 1)]
        usa = any(b["type"] == "tool_use" for b in bloques)
        return Respuesta(bloques, "tool_use" if usa else "end_turn", 100, 20)


def uso(i, nombre, **entrada):
    return {"type": "tool_use", "id": f"toolu_{i}", "name": nombre, "input": entrada}


def texto(t):
    return {"type": "text", "text": t}
