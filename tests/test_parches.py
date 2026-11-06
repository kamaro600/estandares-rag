"""Aplicación de parches: de abajo hacia arriba, sin superposiciones, y diff unificado para descargar."""
from agente.parches import Parche, aplicar, diff


def _p(i, f, r, pid):
    return Parche(id=pid, archivo="a", hallazgo_id="H001", regla_id="X", linea_inicio=i, linea_fin=f,
                  reemplazo=r, justificacion="j" * 10, origen="llm")


def test_aplica_de_abajo_hacia_arriba():
    lineas = ["a", "b", "c", "d"]
    nuevas, conflictos = aplicar(lineas, [_p(1, 1, "A1\nA2", "P1"), _p(3, 4, "CD", "P2")])
    assert nuevas == ["A1", "A2", "b", "CD"] and conflictos == []


def test_parches_superpuestos_no_se_aplican():
    nuevas, conflictos = aplicar(["a", "b", "c"], [_p(1, 2, "X", "P1"), _p(2, 3, "Y", "P2")])
    assert nuevas == ["X", "c"] and [p.id for p in conflictos] == ["P2"]


def test_diff_unificado():
    d = diff("x.cs", ["a", "b"], ["a", "B"])
    assert "--- a/x.cs" in d and "-b\n+B\n" in d
