public class AutenticacionService
{
    private const string Cadena = "Server=sqlprod01;Database=Ventas;User Id=app_ventas;Password=Ventas2024!";

    public string HashClave(string clave)
    {
        using var md5 = MD5.Create();
        return Convert.ToHexString(md5.ComputeHash(Encoding.UTF8.GetBytes(clave)));
    }

    public string GenerarCodigo() => new Random().Next(100000, 999999).ToString();

    public void Registrar(string usuario, string clave)
    {
        _logger.LogInformation("Usuario {Usuario} con clave {Clave}", usuario, clave);
    }
}
