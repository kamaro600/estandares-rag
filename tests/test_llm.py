"""AnthropicLLM probado contra un cliente simulado con la forma de las respuestas del SDK."""
import json
from types import SimpleNamespace

import pytest

from agente.config import Settings
from agente.llm import BETA_RESPALDO, AnthropicLLM, LLMError, OpenAILLM, a_openai, crear_llm
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


# --- Claude real: razonamiento en el historial, rechazos, salida estructurada y errores -------------------------

class _ClienteBeta(_ClienteFalso):
    """Con respaldo activado el adaptador usa client.beta.messages (el servidor reintenta ante rechazos)."""
    def __init__(self, respuesta):
        super().__init__()
        self.respuesta = respuesta
        self.beta = SimpleNamespace(messages=self)

    def create(self, **kw):
        self.pedidos.append(kw)
        return self.respuesta


def _resp(contenido, stop="end_turn", **extra):
    return SimpleNamespace(content=contenido, stop_reason=stop, model="claude-opus-5-5",
                           usage=SimpleNamespace(input_tokens=50, output_tokens=10), **extra)


def test_los_bloques_de_razonamiento_vuelven_intactos_al_historial():
    """En Opus 5.5 el razonamiento siempre está activo: alterar sus bloques en el historial es un error."""
    cliente = _ClienteBeta(_resp([_Bloque(type="thinking", thinking="", signature="firma-123"),
                                  _Bloque(type="tool_use", id="t1", name="obtener_regla", input={"regla_id": "X"},
                                          caller=None)], "tool_use"))
    r = AnthropicLLM("claude-opus-5-5", "k", client=cliente, esfuerzo="medium", respaldo="default").responder(
        "s", [{"role": "user", "content": "hola"}], [{"name": "obtener_regla"}])
    assert r.contenido[0] == {"type": "thinking", "thinking": "", "signature": "firma-123"}
    pedido = cliente.pedidos[0]
    assert pedido["output_config"] == {"effort": "medium"} and pedido["max_tokens"] == 16000
    assert pedido["betas"] == [BETA_RESPALDO] and pedido["fallbacks"] == "default"


def test_el_historial_del_especialista_sale_enmascarado_pero_sus_bloques_intactos():
    """Un tool_result con líneas del archivo puede traer la contraseña de producción: no debe llegar al proveedor.
    Lo que produjo el modelo (razonamiento, tool_use) vuelve sin cambios, o la API rechaza el historial."""
    cliente = _ClienteBeta(_resp([_Bloque(type="text", text="listo")]))
    razonamiento = {"type": "thinking", "thinking": "", "signature": "firma-123"}
    historial = [{"role": "user", "content": "Revisa Data Source=x;Password=Clave2024!;"},
                 {"role": "assistant", "content": [razonamiento, {"type": "tool_use", "id": "t1", "name": "leer_lineas",
                                                                   "input": {"desde": 1}}]},
                 {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1",
                                               "content": '3: "Password=Clave2024!;" correo ana@empresa.pe'}]}]
    AnthropicLLM("m", "k", client=cliente, respaldo="default").responder("s", historial, [])
    enviado = json.dumps(cliente.pedidos[0]["messages"], ensure_ascii=False)
    assert "Clave2024!" not in enviado and "ana@empresa.pe" not in enviado
    assert cliente.pedidos[0]["messages"][1]["content"][0] == razonamiento


def test_un_rechazo_de_seguridad_termina_al_especialista_sin_romper():
    cliente = _ClienteBeta(_resp([], "refusal", stop_details=SimpleNamespace(category="cyber")))
    r = AnthropicLLM("m", "k", client=cliente, respaldo="default").responder("s", [{"role": "user", "content": "x"}], [])
    assert r.stop_reason == "refusal" and "cyber" in r.contenido[0]["text"]


def test_salida_estructurada_con_esquema_y_datos_enmascarados():
    texto = json.dumps({"respuesta": "ok", "citas": ["A"]})
    cliente = _ClienteBeta(_resp([SimpleNamespace(type="thinking"), SimpleNamespace(type="text", text=texto)]))
    esquema = {"type": "object", "properties": {"respuesta": {"type": "string"}}}
    r = AnthropicLLM("m", "k", client=cliente, respaldo="default").generar_json(
        "s", {"pregunta": 'cn="Password=Secreta99;" DNI 45678912'}, esquema, "respuesta")
    assert r.datos == {"respuesta": "ok", "citas": ["A"]}
    pedido = cliente.pedidos[0]
    assert pedido["output_config"]["format"] == {"type": "json_schema", "schema": esquema}
    assert "Secreta99" not in pedido["messages"][0]["content"] and "45678912" not in pedido["messages"][0]["content"]


@pytest.mark.parametrize("respuesta, mensaje", [
    (_resp([], "refusal"), "rechazó"),
    (_resp([SimpleNamespace(type="text", text='{"respuesta": "cort')], "max_tokens"), "max_tokens"),
    (_resp([SimpleNamespace(type="text", text="no es json")]), "JSON"),
])
def test_respuestas_no_utilizables_son_llmerror(respuesta, mensaje):
    with pytest.raises(LLMError, match=mensaje):
        AnthropicLLM("m", "k", client=_ClienteBeta(respuesta), respaldo="default").generar_json("s", {}, {}, "r")


def test_si_el_modelo_falla_el_especialista_deriva_a_humano():
    from agente.contexto import Contexto
    from agente.supervisor import Supervisor
    from agente.trace import Tracer

    class _Caido:
        proveedor, modelo = "anthropic", "m"

        def responder(self, *a):
            raise LLMError("sin conexión")
    rev = Supervisor(Contexto(), _Caido(), Tracer()).revisar([("A.cs", "var c = s.LeerAsync().Result;")])
    r = rev.resultados[0]
    assert r.hallazgos and all(h.id in r.manuales for h in r.hallazgos)   # nada se pierde: va a un humano
    assert "no respondió" in r.resumen_agente
