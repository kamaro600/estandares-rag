"""AnthropicLLM probado contra un cliente simulado con la forma de las respuestas del SDK."""
from types import SimpleNamespace

from agente.config import Settings
from agente.llm import AnthropicLLM, OpenAILLM, a_openai, crear_llm
from agente.llm_mock import MockLLM


class _Bloque:
    def __init__(self, **d):
        self.d = d

    def model_dump(self):
        return dict(self.d)


class _ClienteFalso:
    def __init__(self):
        self.pedidos = []
        self.messages = self

    def create(self, **kw):
        self.pedidos.append(kw)
        return SimpleNamespace(
            content=[_Bloque(type="text", text="Corrijo H001.", citations=None),
                     _Bloque(type="tool_use", id="toolu_01A", name="obtener_regla",
                             input={"regla_id": "WEB-NET-002"}, caller=None)],
            stop_reason="tool_use", usage=SimpleNamespace(input_tokens=812, output_tokens=64))


def test_traduce_la_respuesta_del_sdk():
    cliente = _ClienteFalso()
    llm = AnthropicLLM("claude-sonnet-5-5", "sk-prueba", client=cliente)
    r = llm.responder("sistema", [{"role": "user", "content": "hola"}], [{"name": "obtener_regla"}])
    assert r.stop_reason == "tool_use" and (r.tokens_entrada, r.tokens_salida) == (812, 64)
    # solo los campos que la API acepta de vuelta en el historial (sin citations ni caller)
    assert r.contenido == [{"type": "text", "text": "Corrijo H001."},
                           {"type": "tool_use", "id": "toolu_01A", "name": "obtener_regla",
                            "input": {"regla_id": "WEB-NET-002"}}]
    pedido = cliente.pedidos[0]
    assert pedido["model"] == "claude-sonnet-5-5" and pedido["system"] == "sistema" and "tools" in pedido


def test_por_defecto_el_simulador():
    assert isinstance(crear_llm(Settings()), MockLLM)


# --- OpenAI: el mismo contrato, otro formato de mensajes ---------------------------------------------------------

class _ClienteOpenAIFalso:
    def __init__(self, argumentos='{"regla_id": "WEB-NET-002"}'):
        self.pedidos, self.argumentos = [], argumentos
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kw):
        self.pedidos.append(kw)
        llamada = SimpleNamespace(id="call_01A", function=SimpleNamespace(name="obtener_regla",
                                                                          arguments=self.argumentos))
        return SimpleNamespace(
            choices=[SimpleNamespace(finish_reason="tool_calls",
                                     message=SimpleNamespace(content="Corrijo H001.", tool_calls=[llamada]))],
            usage=SimpleNamespace(prompt_tokens=700, completion_tokens=40))


HERRAMIENTA = [{"name": "obtener_regla", "description": "Texto exacto de una regla",
                "input_schema": {"type": "object", "properties": {"regla_id": {"type": "string"}}}}]


def test_openai_traduce_la_respuesta_al_formato_comun():
    cliente = _ClienteOpenAIFalso()
    r = OpenAILLM("modelo-x", "clave-de-prueba", client=cliente).responder(
        "sistema", [{"role": "user", "content": "hola"}], HERRAMIENTA)
    assert r.stop_reason == "tool_use" and (r.tokens_entrada, r.tokens_salida) == (700, 40)
    assert r.contenido == [{"type": "text", "text": "Corrijo H001."},
                           {"type": "tool_use", "id": "call_01A", "name": "obtener_regla",
                            "input": {"regla_id": "WEB-NET-002"}}]
    pedido = cliente.pedidos[0]
    assert pedido["messages"][0] == {"role": "system", "content": "sistema"}
    assert pedido["tools"][0]["function"]["parameters"] == HERRAMIENTA[0]["input_schema"]
    assert "reasoning_effort" not in pedido          # vacío en .env = no se envía


def test_openai_envia_reasoning_effort_solo_si_se_configura():
    cliente = _ClienteOpenAIFalso()
    OpenAILLM("modelo-x", "clave-de-prueba", client=cliente, reasoning_effort="low").responder(
        "s", [{"role": "user", "content": "hola"}], HERRAMIENTA)
    assert cliente.pedidos[0]["reasoning_effort"] == "low"


def test_openai_json_roto_se_vuelve_error_legible():
    r = OpenAILLM("modelo-x", "clave-de-prueba", client=_ClienteOpenAIFalso("{regla_id: ")).responder(
        "s", [{"role": "user", "content": "hola"}], HERRAMIENTA)
    assert r.contenido[1]["input"] == {"_json_invalido": "{regla_id: "}


def test_historial_con_herramientas_se_traduce_a_openai():
    historial = [
        {"role": "user", "content": "revisa"},
        {"role": "assistant", "content": [{"type": "text", "text": "Busco."},
                                          {"type": "tool_use", "id": "c1", "name": "obtener_regla",
                                           "input": {"regla_id": "SEG-INY-001"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c1", "content": "no existe",
                                      "is_error": True}]},
    ]
    m = a_openai("sis", historial)
    assert [x["role"] for x in m] == ["system", "user", "assistant", "tool"]
    assert m[2]["tool_calls"][0]["function"]["arguments"] == '{"regla_id": "SEG-INY-001"}'
    assert m[3] == {"role": "tool", "tool_call_id": "c1", "content": "ERROR: no existe"}
