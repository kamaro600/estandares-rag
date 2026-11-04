from agente.contexto import Contexto
from agente.detectores import Archivo, analizar
from agente.tools import Sesion, ejecutar
from agente.workers import PERMITIDAS

SRC = """[HttpGet("api/v1/cuentas/{cuentaId}")]
public async Task<ActionResult<CuentaDto>> Obtener(int cuentaId)
    => await _cuentas.ObtenerAsync(cuentaId);"""


def _s(tipo="web"):
    a = Archivo("CuentasController.cs", SRC)
    return Sesion(a, Contexto(tipo), analizar(a, Contexto(tipo)))


def test_el_llm_reporta_lo_que_el_detector_no_ve():
    s = _s()
    texto, error = ejecutar(s, "reportar_hallazgo", {"regla_id": "SEG-ACC-002", "linea": 3,
                            "mensaje": "No verifica que la cuenta pertenezca al usuario (IDOR)."}, PERMITIDAS)
    assert not error and s.semanticos[0].confianza == "media" and s.semanticos[0].id == "S001"


def test_no_puede_inventar_reglas_ni_reglas_que_no_aplican():
    s = _s(tipo="escritorio")
    texto, error = ejecutar(s, "reportar_hallazgo", {"regla_id": "SEG-XXX-999", "linea": 1,
                            "mensaje": "una regla que no existe en el catálogo"}, PERMITIDAS)
    assert error and "no inventes" in texto
    texto, error = ejecutar(s, "reportar_hallazgo", {"regla_id": "SEG-ACC-002", "linea": 1,
                            "mensaje": "aplica solo a web y api, no a escritorio"}, PERMITIDAS)
    assert error and "no aplica" in texto


def test_proponer_parche_rechazado_explica_el_motivo():
    a = Archivo("A.cs", "var c = s.LeerAsync().Result;")
    s = Sesion(a, Contexto(), analizar(a, Contexto()))
    texto, error = ejecutar(s, "proponer_parche", {"hallazgo_id": "H001", "linea_inicio": 1, "linea_fin": 1,
                            "reemplazo": "// var c = s.LeerAsync().Result;", "justificacion": "lo comento y listo"},
                            PERMITIDAS)
    assert error and texto.startswith("RECHAZADO por la guarda: Comentar") and s.parches == []
    assert s.rechazos[0][1] == "comentado"
