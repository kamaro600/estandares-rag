from collections import Counter

from agente import catalogo


def test_todas_las_reglas_de_los_cinco_documentos():
    reglas = catalogo.cargar()
    assert len(reglas) == 170
    assert Counter(r.documento for r in reglas.values()) == {
        "EST-SEG-001": 43, "EST-REF-001": 45, "EST-WEB-001": 34, "EST-API-001": 25, "EST-DSK-001": 23}


def test_cita_exacta_con_pagina():
    r = catalogo.cargar()["SEG-AUT-002"]
    assert r.cita() == "EST-SEG-001 v2.1 §5.2 SEG-AUT-002, pág. 4"
    # la línea de referencias venía partida en dos en el PDF
    assert r.referencias == ["ASVS V2.1.1", "ASVS V2.1.7", "ASVS V2.4.1", "OWASP A02:2021"]


def test_titulo_en_dos_lineas_y_niveles():
    reglas = catalogo.cargar()
    assert reglas["REF-MAS-RESILIENCE"].titulo.endswith("ingeniería inversa y manipulación")
    assert sorted(r.id for r in reglas.values() if r.nivel == "Recomendado") == [
        "DSK-NET-006", "DSK-QA-002", "REF-MAS-RESILIENCE", "SEG-MOV-006", "WEB-ANG-008", "WEB-NET-007"]
    assert reglas["WEB-NET-007"].severidad == "advertencia"
    assert reglas["SEG-INY-001"].severidad == "bloqueante"


def test_aplica_a_normalizado():
    for r in catalogo.cargar().values():
        assert set(r.aplica_a) <= {"web", "api", "escritorio", "movil"}, r.id
        assert len(r.texto) > 60, r.id


def test_el_cuerpo_no_arrastra_el_capitulo_siguiente():
    # "11. Aplicaciones móviles" introduce un capítulo: no es parte de SEG-CFG-004
    assert "Aplicaciones móviles" not in catalogo.cargar()["SEG-CFG-004"].texto
