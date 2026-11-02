public class ClienteRepositorio
{
    public Cliente Buscar(string documento)
    {
        var sql = "SELECT ClienteId, Nombre FROM ventas.Cliente WHERE Documento = '" + documento + "'";
        using var cmd = new SqlCommand(sql, _conexion);
        var datos = _servicio.CargarAsync(documento).Result;
        try { cmd.ExecuteNonQuery(); }
        catch (Exception) { }
        return datos;
    }
}
