from agente import config
from agente.contexto import Contexto
from agente.detectores import Archivo, analizar
from agente.react import ejecutar_agente
from agente.tools import Sesion
from agente.trace import Tracer
from agente.workers import PERMITIDAS
from tests.guion import LLMGuionado, texto, uso

SRC = "public class A\n{\n    void F() { var c = s.LeerAsync().Result; }\n}"


def _sesion():
    a = Archivo("A.cs", SRC)
    return Sesion(a, Contexto(), analizar(a, Contexto()))


def test_cada_tool_use_recibe_su_tool_result_con_el_mismo_id():
    llm = LLMGuionado([[uso(1, "obtener_regla", regla_id="WEB-NET-002"), uso(2, "obtener_regla", regla_id="NO-EXI-STE")],
                       [texto("listo")]])
    res = ejecutar_agente(llm, "s", "tarea", _sesion(), PERMITIDAS, Tracer(), "t")
    assert res.motivo_fin == "respuesta" and res.texto_final == "listo"
    resultados = llm.recibidos[1][-1]["content"]
    assert [r["tool_use_id"] for r in resultados] == ["toolu_1", "toolu_2"]
    assert resultados[0]["is_error"] is False and resultados[1]["is_error"] is True   # el error también vuelve


def test_herramienta_no_permitida_y_argumentos_invalidos():
    llm = LLMGuionado([[uso(1, "aplicar_parche", x=1), uso(2, "leer_lineas", desde=0, hasta=2)], [texto("fin")]])
    ejecutar_agente(llm, "s", "tarea", _sesion(), PERMITIDAS, Tracer(), "t")
    r = llm.recibidos[1][-1]["content"]
    assert "no está permitida" in r[0]["content"]
    assert r[1]["content"].startswith("Argumentos inválidos: desde")


def test_bucle_detectado():
    llm = LLMGuionado([[uso(1, "leer_lineas", desde=1, hasta=2)]])
    tracer = Tracer()
    res = ejecutar_agente(llm, "s", "tarea", _sesion(), PERMITIDAS, tracer, "t")
    assert res.motivo_fin == "bucle" and res.iteraciones == config.MAX_REPEATED_CALLS + 1
    ultima = [e for e in tracer.eventos if e["tipo"] == "herramienta"][-1]
    assert ultima["error"] and ultima["resultado"].startswith("Llamada repetida")   # no se volvió a ejecutar


def test_maximo_de_iteraciones():
    turnos = [[uso(i, "leer_lineas", desde=1, hasta=i + 1)] for i in range(1, 20)]
    res = ejecutar_agente(LLMGuionado(turnos), "s", "tarea", _sesion(), PERMITIDAS, Tracer(), "t")
    assert res.motivo_fin == "max_iteraciones" and res.iteraciones == config.MAX_REACT_ITERS


def test_el_codigo_revisado_llega_como_dato():
    llm = LLMGuionado([[uso(1, "leer_lineas", desde=1, hasta=4)], [texto("fin")]])
    ejecutar_agente(llm, "s", "tarea", _sesion(), PERMITIDAS, Tracer(), "t")
    assert llm.recibidos[1][-1]["content"][0]["content"].startswith('<datos_externos herramienta="leer_lineas">')
