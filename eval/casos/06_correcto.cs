public class ClienteService : IClienteService
{
    private readonly IClienteRepository _clienteRepository;
    private readonly ILogger<ClienteService> _logger;

    public ClienteService(IClienteRepository clienteRepository, ILogger<ClienteService> logger)
    {
        _clienteRepository = clienteRepository;
        _logger = logger;
    }

    public async Task<ClienteDto?> ObtenerAsync(int clienteId, CancellationToken ct)
    {
        var cliente = await _clienteRepository.ObtenerAsync(clienteId, ct);
        _logger.LogInformation("Cliente {ClienteId} consultado", clienteId);
        return cliente is null ? null : new ClienteDto(cliente.ClienteId, cliente.Nombre);
    }
}
