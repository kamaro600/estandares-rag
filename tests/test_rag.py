"""C2 y C3: índice persistente con dimensión verificada, recuperación con umbral, filtros y recuperación exacta."""
import json

import numpy as np
import pytest

from app.embeddings import HashEmbedder
from app.rag import RAG, IndiceError


def test_dimension_y_embedder_se_verifican_al_iniciar(indice, tmp_path):
    class OtraDimension(HashEmbedder):
        def __init__(self):
            super().__init__(512)
            self.nombre = "hash-1024"                        # mismo nombre, otra dimensión
    with pytest.raises(IndiceError, match="dimensiones"):
        RAG(indice, OtraDimension(), 0.2, 5)
    with pytest.raises(IndiceError, match="no son comparables"):
        RAG(indice, HashEmbedder(dim=512), 0.2, 5)
    with pytest.raises(IndiceError, match="python -m app.ingesta"):
        RAG(tmp_path / "no-existe.npz", HashEmbedder(), 0.2, 5)


def test_indice_corrupto_se_detecta(indice, tmp_path):
    with np.load(indice) as z:
        datos = {k: z[k] for k in z.files}
    datos["vectores"] = datos["vectores"][:-1]
    np.savez(tmp_path / "roto.npz", **datos)
    with pytest.raises(IndiceError, match="corrupto"):
        RAG(tmp_path / "roto.npz", HashEmbedder(), 0.2, 5)


@pytest.mark.parametrize("pregunta, esperada", [
    ("¿Qué atributos deben tener las cookies de sesión?", "SEG-AUT-005"),
    ("¿Cómo se versionan las APIs?", "API-VER-001"),
    ("¿Qué prefijo usan los procedimientos almacenados?", "WEB-BD-005"),
    ("¿Está permitido usar BinaryFormatter?", "SEG-INY-005"),
])
def test_recupera_la_regla_correcta(rag, pregunta, esperada):
    assert esperada in [f.id for f in rag.buscar(pregunta)]


def test_umbral_produce_abstencion_fuera_del_corpus(rag):
    for pregunta in ("¿Cuál es la capital de Francia?", "Dame una receta de ceviche de pescado",
                     "¿Quién ganó el mundial de fútbol de 2018?"):
        assert rag.buscar(pregunta) == [], pregunta


def test_filtro_por_categoria(rag):
    res = rag.buscar("¿Cómo se nombran las tablas?", categorias=["escritorio"])
    assert res and {f.categoria for f in res} == {"escritorio"}


def test_id_mencionado_se_trae_exacto_y_primero(rag):
    res = rag.buscar("¿Qué dice la regla WEB-BD-005?")
    assert res[0].id == "WEB-BD-005" and res[0].score == 1.0


def test_por_id_y_relacionadas(rag):
    f = rag.por_id("WEB-BD-010")
    assert f.doc_codigo == "EST-WEB-001" and f.nivel == "Obligatorio" and "EST-WEB-001 v3.0" in f.cita()
    assert rag.por_id("NO-EXISTE-1") is None
    assert "SEG-INY-001" in [r.id for r in rag.relacionadas([f])]           # "ver SEG-INY-001" en su texto


def test_set_de_oro_referencia_reglas_existentes(rag):
    from eval.evaluar import EVAL
    gold = json.loads((EVAL / "gold.json").read_text(encoding="utf-8"))
    ids = {f.id for f in rag.fragmentos}
    faltan = [e for g in gold["respondibles"] for e in g["esperados"] if e not in ids]
    assert not faltan


def test_calidad_minima_de_recuperacion_con_embedder_hash(rag):
    """Piso de regresión con el embedder léxico (sin red). Con OpenAI se mide con: python -m eval.evaluar"""
    from eval.evaluar import evaluar_rag
    r = evaluar_rag(rag, 5)
    assert r["umbral_actual"]["hit@5"] >= 0.70
    assert r["umbral_actual"]["abstencion"] >= 0.5
