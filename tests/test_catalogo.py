"""C1: el catálogo es fiel a los PDF (200 reglas: 170 de los cinco estándares y 30 del manual de buenas prácticas de
APIs), con conteo por documento, cita con página, títulos partidos y niveles."""
from collections import Counter

from agente import catalogo


def test_todas_las_reglas_de_los_seis_documentos():
    reglas = catalogo.cargar()
    assert len(reglas) == 200
    assert Counter(r.documento for r in reglas.values()) == {
        "EST-SEG-001": 43, "EST-REF-001": 45, "EST-WEB-001": 34, "EST-API-001": 25, "EST-DSK-001": 23,
        "EST-BPA-001": 30}


def test_cita_exacta_con_pagina():
    r = catalogo.cargar()["SEG-AUT-002"]
    assert r.cita() == "EST-SEG-001 v2.1 §5.2 SEG-AUT-002, pág. 4"
    # la línea de referencias venía partida en dos en el PDF
    assert r.referencias == ["ASVS V2.1.1", "ASVS V2.1.7", "ASVS V2.4.1", "OWASP A02:2021"]


def test_titulo_en_dos_lineas_y_niveles():
    reglas = catalogo.cargar()
    assert reglas["REF-MAS-RESILIENCE"].titulo.endswith("ingeniería inversa y manipulación")
    assert sorted(r.id for r in reglas.values() if r.nivel == "Recomendado" and r.documento != "EST-BPA-001") == [
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


# ---- el manual de buenas prácticas de APIs: sin ids ni niveles, la estructura la dan los números ----
def test_manual_sin_ids_genera_reglas_citables():
    reglas = catalogo.cargar()
    r = reglas["BPA-305-01"]
    assert r.titulo == "Autorización de nivel de objeto roto" and r.referencias == ["API1:2019"]
    assert r.cita() == "EST-BPA-001 v1 §3.5.1 BPA-305-01, pág. 7" and r.fecha == "2026-11-04"
    assert r.nivel == "Recomendado" and r.severidad == "advertencia"   # el manual no declara niveles
    assert reglas["BPA-201-00"].seccion == "2.1"                         # sección final de segundo nivel
    assert "•" in reglas["BPA-305-04"].texto and "\uf0b7" not in reglas["BPA-305-04"].texto   # viñetas de Word


def test_manual_consumidor_aplica_a_toda_aplicacion_y_el_resto_a_apis():
    reglas = catalogo.cargar()
    assert reglas["BPA-402-02"].aplica_a == catalogo.TODOS_LOS_TIPOS   # "Para consumo de APIs"
    assert reglas["BPA-401-02"].aplica_a == ["api"]


def test_manual_titulos_partidos_y_secciones_generales():
    secciones = catalogo.secciones()
    assert secciones["EST-BPA-001-S0304"].titulo.endswith("de las API's")   # título partido en dos líneas
    assert "1.2 ALCANCE" in secciones["EST-BPA-001-S01"].texto              # el capítulo completo en una sección
    assert {"EST-BPA-001-S0203", "EST-BPA-001-S0301", "EST-BPA-001-S05"} <= set(secciones)
    assert not {"BPA-304-00", "BPA-305-00", "BPA-101-00"} & set(catalogo.cargar())   # contexto o agrupadores


def test_los_pdf_que_se_indexan():
    nombres = [p.name for p in catalogo.pdfs()]
    assert len(nombres) == 6 and "EST_BP_BUENAS PRACTICAS DE DESARROLLO DE API.pdf" in nombres
