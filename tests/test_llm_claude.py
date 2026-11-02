"""El adaptador de Claude con un cliente falso (sin red): esquema estricto, enmascarado, esfuerzo, respaldo ante
rechazos y errores convertidos en LLMError (para que el agente degrade a lo verificado por reglas)."""
import json
from types import SimpleNamespace

import pytest

from app.llm import ESQUEMA_RESPUESTA, LLMError
from app.llm_claude import BETA_RESPALDO, ClaudeLLM


def _respuesta(texto, stop="end_turn", detalles=None):
    return SimpleNamespace(
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=texto)],
        stop_reason=stop, stop_details=detalles, model="claude-opus-5-5",
        usage=SimpleNamespace(input_tokens=20, output_tokens=7))


def _cliente(respuesta, enviado):
    def crear(**kw):
        enviado.update(kw)
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta
    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=crear)))


def test_solicitud_con_esquema_esfuerzo_respaldo_y_datos_enmascarados(settings):
    enviado = {}
    llm = ClaudeLLM(settings, client=_cliente(_respuesta(json.dumps({"respuesta": "ok", "citas": ["A"]})), enviado))
    r = llm.generar("instrucciones", {"pregunta": 'cn = "Password=Secreta99;" DNI 45678912'}, ESQUEMA_RESPUESTA,
                    "respuesta")
    assert r.datos == {"respuesta": "ok", "citas": ["A"]} and (r.input_tokens, r.output_tokens) == (20, 7)
    assert enviado["model"] == "claude-opus-5-5" and enviado["system"] == "instrucciones"
    assert enviado["output_config"] == {"format": {"type": "json_schema", "schema": ESQUEMA_RESPUESTA},
                                        "effort": "medium"}
    assert enviado["betas"] == [BETA_RESPALDO] and enviado["fallbacks"] == "default"
    contenido = enviado["messages"][0]["content"]
    assert "Secreta99" not in contenido and "45678912" not in contenido
    assert "thinking" not in enviado                                     # en Opus 5.5 siempre está activo


def test_respaldo_desactivable(settings, monkeypatch):
    from app.config import Settings
    monkeypatch.setenv("ANTHROPIC_FALLBACK", "")
    enviado = {}
    ClaudeLLM(Settings(), client=_cliente(_respuesta('{"respuesta":"","citas":[]}'), enviado)).generar(
        "i", {}, ESQUEMA_RESPUESTA, "respuesta")
    assert "fallbacks" not in enviado and "betas" not in enviado


@pytest.mark.parametrize("respuesta, mensaje", [
    (_respuesta("", stop="refusal", detalles=SimpleNamespace(category="cyber")), "rechazó"),
    (_respuesta('{"respuesta": "cort', stop="max_tokens"), "max_tokens"),
    (_respuesta("no es json"), "JSON"),
])
def test_respuestas_no_utilizables_son_llmerror(settings, respuesta, mensaje):
    with pytest.raises(LLMError, match=mensaje):
        ClaudeLLM(settings, client=_cliente(respuesta, {})).generar("i", {}, ESQUEMA_RESPUESTA, "respuesta")


def test_errores_del_sdk_son_llmerror(settings):
    import anthropic
    import httpx2
    error = anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
    with pytest.raises(LLMError, match="sin conexión"):
        ClaudeLLM(settings, client=_cliente(error, {})).generar("i", {}, ESQUEMA_RESPUESTA, "respuesta")


def test_config_exige_clave_de_anthropic(monkeypatch):
    from app.config import ConfigError, Settings
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        Settings().validar()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("ANTHROPIC_EFFORT", "altisimo")
    with pytest.raises(ConfigError, match="ANTHROPIC_EFFORT"):
        Settings().validar()


def test_crear_llm_elige_claude(monkeypatch):
    from app.config import Settings
    from app.llm import crear_llm
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "clave-de-prueba")
    assert isinstance(crear_llm(Settings()), ClaudeLLM)
