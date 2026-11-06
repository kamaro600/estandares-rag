-- Base NUEVA: rige EST-WEB-001 cap. 7 y 8
CREATE TABLE dbo.TBL_PEDIDOS (
    PedidoId INT IDENTITY PRIMARY KEY,
    ClienteId INT REFERENCES ventas.Cliente(ClienteId),
    Total FLOAT NOT NULL,
    FechaPedido DATETIME NOT NULL,
    Observaciones NTEXT NULL
);
GO

CREATE PROCEDURE dbo.sp_ListarPedidos @filtro NVARCHAR(100)
AS
BEGIN
    DECLARE @sql NVARCHAR(MAX);
    SET @sql = N'SELECT * FROM dbo.TBL_PEDIDOS WHERE Observaciones LIKE ''%' + @filtro + '%''';
    EXEC(@sql);
END
GO

CREATE OR ALTER PROCEDURE ventas.usp_Pedido_Anular @PedidoId INT
AS
BEGIN
    UPDATE ventas.Pedido SET EsActivo = 0 WHERE PedidoId = @PedidoId;
END
GO

SELECT * FROM ventas.Pedido WHERE YEAR(FechaCreacion) = 2026;
