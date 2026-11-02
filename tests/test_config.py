"""La plantilla de configuración está completa y alineada con el .env local (solo nombres, nunca valores)."""
import re

import pytest

from tests.conftest import RAIZ


def _variables(ruta) -> list[str]:
    return [l.split("=", 1)[0].strip() for l in ruta.read_text(encoding="utf-8-sig").splitlines()
            if "=" in l and not l.lstrip().startswith("#")]


def test_env_example_documenta_todas_las_variables_que_lee_la_app():
    codigo = (RAIZ / "app" / "config.py").read_text(encoding="utf-8") + \
             (RAIZ / "app" / "__main__.py").read_text(encoding="utf-8")
    leidas = set(re.findall(r'(?:_txt|_num|getenv)\("([A-Z_]+)"', codigo))
    plantilla = set(_variables(RAIZ / ".env.example"))
    assert leidas - plantilla == set(), f"Faltan en .env.example: {sorted(leidas - plantilla)}"
    assert plantilla - leidas == set(), f"Sobran en .env.example (la app no las lee): {sorted(plantilla - leidas)}"


def test_env_example_no_trae_claves():
    for linea in (RAIZ / ".env.example").read_text(encoding="utf-8").splitlines():
        if linea.startswith(("ANTHROPIC_API_KEY=", "OPENAI_API_KEY=")):
            assert linea.endswith("="), linea.split("=")[0]


def test_env_local_tiene_las_mismas_variables_que_la_plantilla():
    env = RAIZ / ".env"
    if not env.exists():
        pytest.skip("No hay .env local (normal en un servidor de integración continua)")
    assert _variables(env) == _variables(RAIZ / ".env.example"), \
        "Alinea .env con .env.example: mismas variables y mismo orden"
