import sys

import pytest

from agente.config import Settings, decode_env_bytes, importar_sdk


@pytest.mark.parametrize("raw", [
    "LLM_PROVIDER=mock\n".encode("utf-8"),
    "LLM_PROVIDER=mock\n".encode("utf-8-sig"),        # Bloc de notas
    "LLM_PROVIDER=mock\r\n".encode("utf-16"),          # echo > .env en PowerShell 5.1
])
def test_env_en_cualquier_codificacion(raw):
    assert decode_env_bytes(raw).strip() == "LLM_PROVIDER=mock"


def test_valida_proveedor_y_clave(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gpt")
    with pytest.raises(ValueError, match="LLM_PROVIDER"):
        Settings().validar()
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        Settings().validar()


def test_coma_decimal_se_acepta(monkeypatch):
    monkeypatch.setenv("RAG_MIN_SCORE", "0,12")   # configuración regional en español
    assert Settings().rag_min_score == pytest.approx(0.12)


def test_tipo_app_invalido(monkeypatch):
    monkeypatch.setenv("TIPO_APP", "mainframe")
    with pytest.raises(ValueError, match="TIPO_APP"):
        Settings().validar()


def test_openai_exige_clave_y_modelo(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        Settings().validar()
    monkeypatch.setenv("OPENAI_API_KEY", "clave-de-prueba")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    with pytest.raises(ValueError, match="OPENAI_MODEL"):
        Settings().validar()
    monkeypatch.setenv("OPENAI_MODEL", "modelo-x")
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "maximo")
    with pytest.raises(ValueError, match="OPENAI_REASONING_EFFORT"):
        Settings().validar()


def test_embeddings_openai_exigen_clave(monkeypatch):
    monkeypatch.setenv("EMBEDDINGS_PROVIDER", "openai")
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        Settings().validar()


def test_sdk_ausente_da_un_mensaje_que_dice_que_instalar(monkeypatch):
    monkeypatch.setitem(sys.modules, "openai", None)       # simula "pip install" olvidado
    with pytest.raises(RuntimeError, match="pip install -r requirements.txt"):
        importar_sdk("openai")
