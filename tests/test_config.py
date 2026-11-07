"""Configuración: .env en cualquier codificación, validación de proveedor y clave, umbrales y .env.example sin secretos."""
import re
import sys
from pathlib import Path

import pytest

from agente.config import Settings, decode_env_bytes, importar_sdk

RAIZ = Path(__file__).parent.parent


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


# --- La plantilla .env.example: completa, sin claves y alineada con el .env local --------------------------------

def _variables(ruta: Path) -> list[str]:
    return [l.split("=", 1)[0].strip() for l in ruta.read_text(encoding="utf-8-sig").splitlines()
            if "=" in l and not l.lstrip().startswith("#")]


def test_env_example_documenta_todas_las_variables_que_lee_la_app():
    codigo = (RAIZ / "agente" / "config.py").read_text(encoding="utf-8")
    leidas = set(re.findall(r'(?:_txt|_float|getenv)\("([A-Z_]+)"', codigo))
    plantilla = set(_variables(RAIZ / ".env.example"))
    assert leidas - plantilla == set(), f"Faltan en .env.example: {sorted(leidas - plantilla)}"
    assert plantilla - leidas == set(), f"Sobran en .env.example: {sorted(plantilla - leidas)}"


def test_env_example_no_trae_claves():
    """Condición mínima de la rúbrica: ninguna clave en el repositorio (.env.example sí se versiona)."""
    texto = (RAIZ / ".env.example").read_text(encoding="utf-8")
    assert not re.search(r"sk-(ant-|proj-)?[A-Za-z0-9_-]{20,}", texto)
    for linea in texto.splitlines():
        if linea.startswith(("ANTHROPIC_API_KEY=", "OPENAI_API_KEY=")):
            assert linea.endswith("="), linea.split("=")[0]


def test_env_local_tiene_las_mismas_variables_que_la_plantilla():
    env = RAIZ / ".env"
    if not env.exists():
        pytest.skip("No hay .env local (normal en integración continua)")
    assert _variables(env) == _variables(RAIZ / ".env.example"), "Alinea .env con .env.example"


def test_esfuerzo_de_claude_se_valida(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_EFFORT", "altisimo")
    with pytest.raises(ValueError, match="ANTHROPIC_EFFORT"):
        Settings().validar()


def test_umbral_por_defecto_segun_embedder(monkeypatch):
    from agente.config import RAG_MIN_SCORE_POR_EMBEDDER
    monkeypatch.setenv("RAG_MIN_SCORE", "")
    monkeypatch.setenv("EMBEDDINGS_PROVIDER", "openai")
    assert Settings().rag_min_score == RAG_MIN_SCORE_POR_EMBEDDER["openai"]
