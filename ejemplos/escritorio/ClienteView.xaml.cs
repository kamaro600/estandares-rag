namespace Ventas.Desktop.Vistas;

public partial class ClienteView : UserControl
{
    private void btnGuardar_Click(object sender, RoutedEventArgs e)
    {
        var cn = new SqlConnection("Server=sql01;Database=Ventas;User Id=sa;Password=Admin123");
        cn.Open();
        var cmd = new SqlCommand("PA_CLI_BUSCAR '" + txtDocumento.Text + "'", cn);
        var clientes = _servicio.BuscarAsync(txtDocumento.Text).Result;
        Thread.Sleep(500);
    }
}
