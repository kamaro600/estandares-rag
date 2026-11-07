"""La línea de comandos: código de salida útil como quality gate del pipeline, búsqueda y consulta de una regla."""
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).parent.parent


def _cli(*args):
    return subprocess.run([sys.executable, "-m", "agente", *args], cwd=RAIZ, capture_output=True, text=True,
                          encoding="utf-8")


def test_codigo_de_salida_para_el_pipeline():
    r = _cli("revisar", "ejemplos/bd/ventas_nueva.sql", "--bd", "nueva", "--sin-llm")
    assert r.returncode == 1 and "NO APTO" in r.stdout          # bloquea el pipeline
    limpio = RAIZ / "salida" / "limpio.sql"
    limpio.parent.mkdir(exist_ok=True)
    limpio.write_text("SELECT PedidoId, Total FROM ventas.Pedido WHERE PedidoId = @PedidoId;\n", encoding="utf-8")
    r = _cli("revisar", str(limpio), "--sin-llm")
    assert r.returncode == 0 and "Veredicto: APTO" in r.stdout


def test_buscar_y_regla():
    assert "[WEB-BD-005]" in _cli("buscar", "prefijo de procedimientos almacenados").stdout
    assert _cli("regla", "NO-EXI-STE").returncode == 2
