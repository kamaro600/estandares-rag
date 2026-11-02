"""EST-DSK-001 · Estándar de Desarrollo de Aplicaciones de Escritorio .NET (WPF / WinForms + SQL Server).

Es intencionalmente la versión MÁS ANTIGUA del conjunto (2023) y conserva convenciones heredadas que entran en
conflicto con EST-WEB-001 v3.0 (nomenclatura de BD, tipos de datos, versión de .NET). Sirve para probar que el chat
cita ambas fuentes y explica cuál prevalece.
"""
from fuentes.comun import R

DOC = {
    "codigo": "EST-DSK-001",
    "titulo": "Estándar de Desarrollo de Aplicaciones de Escritorio .NET",
    "subtitulo": "WPF, WinForms y SQL Server",
    "version": "1.4",
    "fecha": "2023-08-14",
    "categoria": "escritorio",
    "archivo": "EST-DSK-001_desarrollo_escritorio_net.pdf",
    "aprobado_por": "Comité de Arquitectura",
    "historial": [
        ("1.0", "2018-03-05", "Versión inicial para WinForms sobre .NET Framework 4.6."),
        ("1.3", "2021-11-22", "Se incorpora WPF con patrón MVVM y .NET 6."),
        ("1.4", "2023-08-14", "Distribución con MSIX firmado, Serilog y manejo global de excepciones. La "
                              "nomenclatura de base de datos está en revisión para alinearse con el estándar web."),
    ],
    "objetivo": "Definir la arquitectura, las convenciones de código y de base de datos, y la forma de "
                "distribución de las aplicaciones de escritorio Windows de la empresa.",
    "alcance": "Aplica a las aplicaciones de escritorio desarrolladas en WPF y WinForms que usan los colaboradores "
               "en agencias y oficinas, incluidas las bases de datos SQL Server que estas aplicaciones utilizan. "
               "Las reglas de seguridad están en EST-SEG-001, que prevalece sobre este documento.",
    "definiciones": [
        ("MVVM", "Model-View-ViewModel: patrón que separa la vista (XAML) de la lógica de presentación (ViewModel)."),
        ("MSIX", "Formato de empaquetado e instalación de aplicaciones Windows con soporte de firma y actualización."),
        ("DPAPI", "Data Protection API de Windows, cifra datos con una clave ligada al usuario o al equipo."),
    ],
    "capitulos": [
        {"titulo": "Plataforma y arquitectura", "reglas": [
            R("DSK-ARQ-001", "Tecnología de las aplicaciones de escritorio",
              "Los desarrollos nuevos se construyen en WPF sobre .NET 6 LTS. WinForms se permite solo para el "
              "mantenimiento de aplicaciones existentes. Está prohibido iniciar desarrollos nuevos en .NET "
              "Framework.",
              aplica="Escritorio"),
            R("DSK-ARQ-002", "Patrón MVVM",
              "Las aplicaciones WPF usan el patrón MVVM con CommunityToolkit.Mvvm. El code-behind de las vistas "
              "(`*.xaml.cs`) solo contiene lógica puramente visual; las acciones del usuario se enlazan a "
              "comandos (`ICommand` / `[RelayCommand]`) del ViewModel y los datos mediante bindings.",
              aplica="Escritorio",
              mal="""
// ClienteView.xaml.cs
private void btnGuardar_Click(object sender, RoutedEventArgs e)
{
    using var cn = new SqlConnection(cadena);
    // ... INSERT directo desde la vista
}
""",
              bien="""
// ClienteViewModel.cs
public partial class ClienteViewModel : ObservableObject
{
    [ObservableProperty] private string _nombre = "";

    [RelayCommand]
    private async Task GuardarAsync() => await _clienteService.GuardarAsync(new ClienteDto(Nombre));
}
// ClienteView.xaml: <Button Content="Guardar" Command="{Binding GuardarCommand}" />
"""),
            R("DSK-ARQ-003", "Capas de la aplicación",
              "La solución se organiza en `<Sistema>.Desktop` (vistas y ViewModels), `<Sistema>.Servicios` "
              "(lógica de aplicación) y `<Sistema>.Datos` (acceso a datos o clientes de API). Las vistas no "
              "acceden a datos directamente. Para aplicaciones nuevas el acceso a datos se hace preferentemente a "
              "través de las APIs corporativas (ver SEG-DSK-001).",
              aplica="Escritorio", refs="EST-SEG-001 SEG-DSK-001"),
            R("DSK-ARQ-004", "Configuración de la aplicación",
              "La configuración se lee de `appsettings.json` con `Microsoft.Extensions.Configuration` y se inyecta "
              "con `IOptions<T>`. Los valores sensibles que deban guardarse en el equipo se protegen con DPAPI "
              "(ver SEG-DSK-002). Está prohibido guardar contraseñas en `app.config` o en el registro de Windows.",
              aplica="Escritorio", refs="EST-SEG-001 SEG-DSK-002"),
        ]},
        {"titulo": "Convenciones de código", "reglas": [
            R("DSK-NET-001", "Nomenclatura de código y controles",
              "Las clases, métodos y propiedades siguen las convenciones de nombres de Microsoft para C# "
              "(PascalCase, camelCase para variables y parámetros, `_camelCase` para campos privados). Los "
              "controles con nombre en XAML o WinForms usan un prefijo de tres letras según su tipo: `txt` "
              "(TextBox), `btn` (Button), `cmb` (ComboBox), `dgv` (DataGrid), `lbl` (Label), `chk` (CheckBox).",
              aplica="Escritorio",
              bien="""
<TextBox x:Name="txtNombreCliente" Text="{Binding Nombre}" />
<Button  x:Name="btnGuardar" Command="{Binding GuardarCommand}" Content="Guardar" />
"""),
            R("DSK-NET-002", "Interfaz de usuario no bloqueante",
              "Las operaciones de base de datos, red o archivos se ejecutan de forma asíncrona (`async`/`await`) "
              "para no congelar la interfaz. Está prohibido usar `Thread.Sleep`, `.Result` o `.Wait()` en el hilo "
              "de la interfaz. Las actualizaciones de la UI desde otros hilos se hacen con el `Dispatcher` o "
              "mediante bindings a propiedades observables.",
              aplica="Escritorio",
              mal="""
private void btnBuscar_Click(object sender, EventArgs e)
{
    var clientes = _servicio.BuscarAsync(txtFiltro.Text).Result;   // congela la ventana
    dgvClientes.DataSource = clientes;
}
""",
              bien="""
private async void btnBuscar_Click(object sender, EventArgs e)   // async void solo en manejadores
{
    btnBuscar.Enabled = false;
    try { dgvClientes.DataSource = await _servicio.BuscarAsync(txtFiltro.Text); }
    finally { btnBuscar.Enabled = true; }
}
"""),
            R("DSK-NET-003", "Manejo global de excepciones",
              "La aplicación registra manejadores para `Application.DispatcherUnhandledException` (WPF) o "
              "`Application.ThreadException` (WinForms), `AppDomain.CurrentDomain.UnhandledException` y "
              "`TaskScheduler.UnobservedTaskException`. Cada error se registra en el log y se muestra al usuario un "
              "mensaje amigable con un código de seguimiento, nunca el detalle técnico de la excepción.",
              aplica="Escritorio", refs="EST-SEG-001 SEG-LOG-003"),
            R("DSK-NET-004", "Liberación de recursos",
              "Todo objeto `IDisposable` (`SqlConnection`, `SqlCommand`, `Stream`, `HttpResponseMessage`) se "
              "libera con `using`. Las suscripciones a eventos de objetos de larga vida se eliminan al cerrar la "
              "ventana para evitar fugas de memoria.",
              aplica="Escritorio"),
            R("DSK-NET-005", "Registro de eventos",
              "Se usa Serilog con salida a archivo en `%LOCALAPPDATA%\\<Aplicacion>\\logs`, rotación diaria y "
              "retención de 30 días. Los errores se envían además al servicio central de logs cuando hay "
              "conectividad. No se registran datos sensibles (ver SEG-LOG-001).",
              aplica="Escritorio", refs="EST-SEG-001 SEG-LOG-001"),
            R("DSK-NET-006", "Textos de la interfaz en recursos",
              "Los textos visibles para el usuario se definen en archivos de recursos (`.resx`) y no como literales "
              "en el XAML o en el código, para facilitar su mantenimiento y una eventual traducción.",
              nivel="Recomendado", aplica="Escritorio"),
        ]},
        {"titulo": "Base de datos SQL Server", "intro":
            "Nota: la nomenclatura de este capítulo es la vigente para las bases de datos de las aplicaciones de "
            "escritorio existentes. Se encuentra en revisión para alinearse con el estándar de desarrollo web.",
         "reglas": [
            R("DSK-BD-001", "Nombres de tablas",
              "Las tablas se nombran en MAYÚSCULAS, en plural, con palabras separadas por guion bajo y con el "
              "prefijo `TBL_`: `TBL_CLIENTES`, `TBL_DETALLE_PEDIDOS`. Las tablas se crean en el esquema `dbo`.",
              aplica="Escritorio",
              bien="""
CREATE TABLE dbo.TBL_CLIENTES (
    ID_CLIENTE   INT IDENTITY(1,1) NOT NULL,
    NOM_CLIENTE  VARCHAR(150) NOT NULL,
    NUM_DOCUMENTO VARCHAR(15) NOT NULL,
    FEC_REGISTRO DATETIME NOT NULL,
    CONSTRAINT PK_TBL_CLIENTES PRIMARY KEY (ID_CLIENTE)
);
"""),
            R("DSK-BD-002", "Nombres de columnas",
              "Las columnas se nombran en MAYÚSCULAS con guion bajo y un prefijo de tres letras que indica su "
              "naturaleza: `ID_` identificadores, `NOM_` nombres, `DES_` descripciones, `NUM_` números o códigos, "
              "`FEC_` fechas, `IMP_` importes, `FLG_` indicadores. La clave primaria se llama `ID_<ENTIDAD>` en "
              "singular (`ID_CLIENTE`).",
              aplica="Escritorio"),
            R("DSK-BD-003", "Nombres de procedimientos almacenados",
              "Los procedimientos almacenados se nombran `PA_<MODULO>_<ACCION>` en mayúsculas, donde el módulo es "
              "una abreviatura de tres letras: `PA_CLI_LISTAR`, `PA_PED_REGISTRAR`. Está prohibido el prefijo "
              "`sp_`.",
              aplica="Escritorio"),
            R("DSK-BD-004", "Nombres de restricciones e índices",
              "Restricciones con nombre explícito en mayúsculas: `PK_<TABLA>`, `FK_<TABLA_HIJA>_<TABLA_PADRE>`, "
              "`IX_<TABLA>_<COLUMNAS>`.",
              aplica="Escritorio"),
            R("DSK-BD-005", "Tipos de datos",
              "Texto: `VARCHAR(n)` con longitud definida. Importes: `DECIMAL(18,2)`. Fechas: `DATETIME` con hora "
              "local del servidor. Indicadores: `CHAR(1)` con valores 'S' / 'N'.",
              aplica="Escritorio"),
            R("DSK-BD-006", "Conexión a la base de datos",
              "Cuando la aplicación se conecta directamente a SQL Server (ver SEG-DSK-001): autenticación integrada "
              "de Windows (`Integrated Security=True`), `Encrypt=True`, tiempo de espera de 30 segundos y "
              "agrupación de conexiones habilitada. La conexión se abre lo más tarde posible y se cierra con "
              "`using`. Todas las consultas son parametrizadas o invocan procedimientos almacenados (ver "
              "SEG-INY-001).",
              aplica="Escritorio", refs="EST-SEG-001 SEG-INY-001; EST-SEG-001 SEG-DSK-001",
              mal="""
var cn = new SqlConnection("Server=sql01;Database=Ventas;User Id=sa;Password=Admin123");
cn.Open();
var cmd = new SqlCommand("PA_CLI_BUSCAR '" + txtDocumento.Text + "'", cn);
""",
              bien="""
await using var cn = new SqlConnection(_opciones.CadenaConexion);   // Integrated Security, Encrypt
await using var cmd = new SqlCommand("dbo.PA_CLI_BUSCAR", cn)
{
    CommandType = CommandType.StoredProcedure
};
cmd.Parameters.Add("@NUM_DOCUMENTO", SqlDbType.VarChar, 15).Value = txtDocumento.Text;
await cn.OpenAsync();
"""),
            R("DSK-BD-007", "Transacciones",
              "Las transacciones se controlan dentro de los procedimientos almacenados. Desde la aplicación se usa "
              "`SqlTransaction` o `TransactionScope` solo cuando una operación de negocio involucra varias llamadas "
              "y siempre con nivel de aislamiento READ COMMITTED. Las transacciones no deben quedar abiertas "
              "esperando una acción del usuario.",
              aplica="Escritorio"),
            R("DSK-BD-008", "Columnas de auditoría",
              "Las tablas transaccionales incluyen `USU_CREACION`, `FEC_CREACION`, `USU_MODIFICACION` y "
              "`FEC_MODIFICACION`. Los registros no se eliminan físicamente: se marcan con `FLG_ACTIVO = 'N'`.",
              aplica="Escritorio"),
        ]},
        {"titulo": "Distribución y actualización", "reglas": [
            R("DSK-DIS-001", "Empaquetado e instalación",
              "Las aplicaciones se distribuyen como paquetes MSIX firmados con el certificado corporativo (ver "
              "SEG-DSK-003) a través de Intune o del portal de software. Está prohibido distribuir copiando "
              "ejecutables desde carpetas compartidas.",
              aplica="Escritorio", refs="EST-SEG-001 SEG-DSK-003"),
            R("DSK-DIS-002", "Versionado de la aplicación",
              "Se usa versionado semántico (MAYOR.MENOR.PARCHE) en `AssemblyVersion` y `FileVersion`, generado por "
              "el pipeline. La versión se muestra en la ventana \"Acerca de\" y se registra en cada log.",
              aplica="Escritorio"),
            R("DSK-DIS-003", "Actualizaciones automáticas",
              "La aplicación verifica al iniciar si existe una versión nueva y, si es obligatoria, impide continuar "
              "hasta actualizar. El paquete descargado se valida por su firma antes de instalarse.",
              aplica="Escritorio", refs="EST-SEG-001 SEG-DSK-003"),
        ]},
        {"titulo": "Pruebas", "reglas": [
            R("DSK-QA-001", "Pruebas unitarias",
              "Los ViewModels y servicios tienen pruebas unitarias con xUnit y Moq, con una cobertura mínima de "
              "60%. Los ViewModels no deben depender de clases de WPF para poder probarse.",
              aplica="Escritorio"),
            R("DSK-QA-002", "Pruebas de interfaz",
              "Las pruebas funcionales de la interfaz se documentan como casos de prueba en Azure Test Plans. Se "
              "recomienda automatizar los flujos principales con FlaUI.",
              nivel="Recomendado", aplica="Escritorio"),
        ]},
    ],
    "cierre": [
        ("Relación con otros estándares", "EST-SEG-001 prevalece en temas de seguridad. La nomenclatura de base de "
         "datos de este documento se mantiene para las bases de datos existentes de aplicaciones de escritorio."),
    ],
}
