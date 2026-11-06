namespace Ventas.Api.Controllers;

[ApiController]
[Route("api/ObtenerClientes")]
public class ClientesController : ControllerBase
{
    private readonly VentasContext _contexto;

    public ClientesController(VentasContext contexto) => _contexto = contexto;

    [HttpGet("{clienteId}")]
    public async Task<IActionResult> Obtener(int clienteId)
    {
        var cliente = await _contexto.Clientes.FindAsync(clienteId);
        if (cliente is null) return Ok(new { exito = false, mensaje = "Cliente no encontrado" });
        return Ok(cliente);
    }

    [HttpDelete("{clienteId}")]
    public async Task<IActionResult> Eliminar(int clienteId)
    {
        _contexto.Clientes.Remove(new Cliente { ClienteId = clienteId });
        await _contexto.SaveChangesAsync();
        return NoContent();
    }

    [HttpGet("tipo-cambio")]
    public async Task<IActionResult> TipoCambio()
    {
        using var http = new HttpClient();
        var r = await http.GetStringAsync("https://servicio-externo/tipo-cambio");
        return Ok(r);
    }
}
