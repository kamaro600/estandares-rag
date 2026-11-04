import pytest

from agente.contexto import Contexto
from agente.detectores import Archivo, analizar
from agente.guardas import validar_parche
from agente.parches import Parche

SRC = """public class PedidoService
{
    public async Task RegistrarAsync(Pedido pedido, CancellationToken ct)
    {
        try { await _pedidos.RegistrarAsync(pedido, ct); }
        catch (Exception) { }
    }
}"""


@pytest.fixture
def caso():
    a = Archivo("PedidoService.cs", SRC)
    hs = analizar(a, Contexto())
    assert [(h.id, h.linea, h.regla_id) for h in hs] == [("H001", 6, "WEB-NET-004")]
    return a, hs


def _p(reemplazo, ini=6, fin=6, hid="H001", regla="WEB-NET-004"):
    return Parche(archivo="PedidoService.cs", hallazgo_id=hid, regla_id=regla, linea_inicio=ini, linea_fin=fin,
                  reemplazo=reemplazo, justificacion="prueba de la guarda", origen="llm")


BUENO = '        catch (Exception ex) { _logger.LogError(ex, "Error al registrar {PedidoId}", pedido.Id); throw; }'


def test_acepta_un_parche_correcto(caso):
    assert validar_parche(*caso[:1], _p(BUENO), caso[1], Contexto()) is None


@pytest.mark.parametrize("parche,categoria", [
    (_p(BUENO, hid="H009"), "no_existe"),
    (_p(BUENO, regla="SEG-INY-001"), "regla"),
    (_p(BUENO, ini=7, fin=99), "rango"),
    (_p(BUENO, ini=2, fin=3), "rango"),
    (_p(""), "vacio"),
    (_p("        // catch (Exception) { }"), "comentado"),
    (_p("#pragma warning disable CA1031\n        catch (Exception) { }"), "supresion"),
    (_p("        catch (Exception) { }"), "identico"),
    (_p("        catch (Exception ex) {  }"), "sigue_presente"),
    (_p("        catch (Exception ex) { Console.WriteLine(ex); throw; }"), "introduce_nuevos"),
    (_p("\n".join(["        //"] * 31) + "\n" + BUENO, ini=6, fin=6), "tamano"),
])
def test_rechazos_con_motivo_legible(caso, parche, categoria):
    rechazo = validar_parche(caso[0], parche, caso[1], Contexto())
    assert rechazo is not None and rechazo[0] == categoria
    assert len(rechazo[1]) > 15   # un motivo que el modelo puede leer y corregir


def test_no_se_puede_introducir_un_secreto(caso):
    p = _p(BUENO + '\n        var cn = "Server=x;User Id=app;Password=Clave123";')
    assert validar_parche(caso[0], p, caso[1], Contexto())[0] == "introduce_nuevos"
