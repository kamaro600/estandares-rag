"""C2/C3: búsqueda exacta por id y por similitud, umbral, índice coherente con los embeddings, enmascarado y
secciones que resuelven conflictos entre estándares."""
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
    """Piso de regresión con embeddings hash (léxicos, sin red). La calidad real, con OpenAI: python -m eval.eval_rag"""
    aciertos = sum(bool({c["esperado"], *c.get("alternativos", [])} & {r.regla.id for r in rag.buscar(c["pregunta"], k=4, min_score=0)})
                   for c in ORO["con_respuesta"])
    assert aciertos / len(ORO["con_respuesta"]) >= 0.80


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
    monkeypatch.setenv("OPENAI_EMBEDDING_MODEL", "modelo-de-prueba")   # dimensión desconocida: no se verifica
    monkeypatch.setattr(embeddings, "_cliente_openai", _Cliente)
    m = embeddings.vectorizar(["a", "b"])
    assert m.shape == (2, 2) and np.allclose(np.linalg.norm(m, axis=1), 1) and np.allclose(m[0], [0.6, 0.8])


def test_embeddings_con_dimension_inesperada_se_detienen(monkeypatch):
    """text-embedding-3-small debe devolver 1536 dimensiones: otra cosa es un error, no un índice silenciosamente roto."""
    class _Cliente:
        def __init__(self):
            self.embeddings = self

        def create(self, model, input):
            return SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[1.0, 0.0])])
    monkeypatch.setenv("EMBEDDINGS_PROVIDER", "openai")
    monkeypatch.setattr(embeddings, "_cliente_openai", _Cliente)
    with pytest.raises(embeddings.EmbeddingError, match="1536"):
        embeddings.vectorizar(["a"])


def test_hacia_openai_sale_el_texto_enmascarado(monkeypatch):
    enviados = []

    class _Cliente:
        def __init__(self):
            self.embeddings = self

        def create(self, model, input):
            enviados.extend(input)
            return SimpleNamespace(data=[SimpleNamespace(index=i, embedding=[1.0] + [0.0] * 1535) for i in range(len(input))])
    monkeypatch.setenv("EMBEDDINGS_PROVIDER", "openai")
    monkeypatch.setattr(embeddings, "_cliente_openai", _Cliente)
    embeddings.vectorizar(['cadena "Server=x;Password=Clave123" del cliente con DNI 45678912'])
    assert "Clave123" not in enviados[0] and "45678912" not in enviados[0]


def test_el_chat_encuentra_secciones_generales():
    """La sección "Relación con otros estándares" dice qué prevalece: el chat la puede recuperar, el agente no."""
    ids = [r.regla.id for r in rag.buscar("relación con otros estándares: cuál prevalece en nomenclatura de base de datos",
                                          k=5, min_score=0, incluir_secciones=True)]
    assert any(i.startswith("EST-WEB-001-S") for i in ids)
    assert not any("-S" in r.regla.id for r in rag.buscar("relación con otros estándares", k=5, min_score=0))


def _res(*ids):
    from agente import catalogo
    reglas = catalogo.cargar()
    return [rag.Resultado(reglas[i], 0.6, "similitud") for i in ids]


def test_reglas_del_mismo_tema_en_dos_estandares_traen_lo_que_decide_cual_aplica():
    """WEB-BD-002 y DSK-BD-001 se contradicen: se agregan el capítulo y la relación con otros estándares de ambos."""
    from agente import catalogo
    extra = rag.complementos(_res("WEB-BD-002", "DSK-BD-001", "WEB-BD-003"), catalogo.secciones())
    ids = [r.regla.id for r in extra]
    assert {"EST-WEB-001-S10", "EST-WEB-001-S07", "EST-DSK-001-S09", "EST-DSK-001-S06"} == set(ids)
    assert all(r.via == "relacion" for r in extra) and len(ids) <= rag.MAX_COMPLEMENTOS


def test_sin_conflicto_no_se_agregan_secciones():
    from agente import catalogo
    generales = catalogo.secciones()
    assert rag.complementos(_res("WEB-ANG-005", "SEG-AUT-005"), generales) == []   # temas distintos
    assert rag.complementos(_res("WEB-BD-002", "WEB-BD-005"), generales) == []     # un solo estándar


def test_el_agente_no_recibe_complementos():
    ids = [r.regla.id for r in rag.buscar("WEB-BD-002 DSK-BD-001 nombre de tablas", k=5, min_score=0)]
    assert not any("-S" in i for i in ids)
