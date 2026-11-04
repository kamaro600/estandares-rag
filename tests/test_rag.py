import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from agente import embeddings, rag

ORO = json.loads((Path(__file__).parent.parent / "eval" / "rag_oro.json").read_text(encoding="utf-8"))


def test_identificador_citado_se_trae_exacto():
    res = rag.buscar("¿qué exige SEG-CRI-002 y WEB-BD-005?")
    assert [r.regla.id for r in res[:2]] == ["SEG-CRI-002", "WEB-BD-005"]
    assert res[0].via == "id" and res[0].score == 1.0


def test_hit_at_4_sobre_el_conjunto_de_oro():
    aciertos = sum(c["esperado"] in [r.regla.id for r in rag.buscar(c["pregunta"], k=4, min_score=0)]
                   for c in ORO["con_respuesta"])
    assert aciertos / len(ORO["con_respuesta"]) >= 0.85


def test_filtro_por_tipo_de_aplicacion():
    for r in rag.buscar("almacenamiento seguro de tokens en el dispositivo", aplica_a="movil", min_score=0):
        assert "movil" in r.regla.aplica_a


def test_el_umbral_se_lee_del_entorno(monkeypatch):
    monkeypatch.setenv("RAG_MIN_SCORE", "0,99")
    assert rag.buscar("receta de ceviche") == []


def test_indice_y_consulta_con_embeddings_distintos_se_detiene(monkeypatch):
    monkeypatch.setenv("EMBEDDINGS_PROVIDER", "openai")     # el índice de las pruebas es hash
    monkeypatch.setenv("OPENAI_API_KEY", "clave-de-prueba")
    with pytest.raises(RuntimeError, match="agente.ingesta"):
        rag.buscar("validación de entradas")


def test_embeddings_openai_normalizados_y_en_orden(monkeypatch):
    class _Cliente:
        def __init__(self):
            self.embeddings = self

        def create(self, model, input):
            datos = [SimpleNamespace(index=i, embedding=[3.0 * (i + 1), 4.0 * (i + 1)]) for i in range(len(input))]
            return SimpleNamespace(data=list(reversed(datos)))     # la API no garantiza el orden
    monkeypatch.setenv("EMBEDDINGS_PROVIDER", "openai")
    monkeypatch.setattr(embeddings, "_cliente_openai", _Cliente)
    m = embeddings.vectorizar(["a", "b"])
    assert m.shape == (2, 2) and np.allclose(np.linalg.norm(m, axis=1), 1) and np.allclose(m[0], [0.6, 0.8])
