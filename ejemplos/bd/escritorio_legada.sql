-- Base LEGADA de escritorio: rige EST-DSK-001 cap. 6 (no se renombra a la nomenclatura nueva)
CREATE TABLE dbo.Clientes (
    ID_CLIENTE INT IDENTITY(1,1) NOT NULL,
    NombreCliente VARCHAR(150) NOT NULL,
    IMP_LIMITE MONEY NOT NULL,
    FEC_REGISTRO DATETIME NOT NULL,
    CONSTRAINT PK_TBL_CLIENTES PRIMARY KEY (ID_CLIENTE)
);
GO

CREATE PROCEDURE dbo.sp_cli_listar
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    SELECT ID_CLIENTE, NombreCliente FROM dbo.Clientes;
END
