builder.Services.AddCors(o => o.AddDefaultPolicy(p => p.AllowAnyOrigin().AllowAnyHeader()));
builder.Services.AddAuthentication().AddJwtBearer(o =>
{
    o.TokenValidationParameters = new TokenValidationParameters
    {
        ValidateIssuer = false,
        ValidateLifetime = false
    };
});

[HttpGet("{clienteId}")]
public async Task<IActionResult> Obtener(int clienteId)
{
    using var http = new HttpClient();
    var cliente = await _clientes.ObtenerAsync(clienteId);
    if (cliente is null) return Ok(new { exito = false, mensaje = "No encontrado" });
    var formatter = new BinaryFormatter();
    return Ok(cliente);
}
