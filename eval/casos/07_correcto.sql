CREATE OR ALTER PROCEDURE ventas.usp_Pedido_Registrar
    @ClienteId INT, @Total DECIMAL(18,2), @Usuario NVARCHAR(100), @PedidoId INT OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    BEGIN TRY
        BEGIN TRANSACTION;
        INSERT INTO ventas.Pedido (ClienteId, Total, FechaCreacion, UsuarioCreacion)
        VALUES (@ClienteId, @Total, SYSUTCDATETIME(), @Usuario);
        SET @PedidoId = SCOPE_IDENTITY();
        COMMIT TRANSACTION;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
        THROW;
    END CATCH
END
