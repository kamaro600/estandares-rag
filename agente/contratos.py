"""Los contratos de datos: lo que entra a la API y lo que el chat le entrega al agente.

Si un dato no cumple su contrato, no se procesa: ni la revisión ni el agente reciben datos sin validar.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from agente import config


class ArchivoEntrada(BaseModel):
    nombre: str = Field(min_length=1, max_length=260)
    contenido: str = Field(max_length=config.MAX_BYTES_ARCHIVO)


class SolicitudRevision(BaseModel):
    """Contrato de ENTRADA del agente: lo usan la página de revisión y el chat (código pegado en un mensaje)."""
    tipo_app: str = Field(default="web", pattern="^(web|api|escritorio|movil)$")
    modo_bd: str = Field(default="nueva", pattern="^(nueva|legada)$")
    usar_llm: bool = True
    archivos: list[ArchivoEntrada] = Field(min_length=1, max_length=config.MAX_ARCHIVOS)


class Aprobado(BaseModel):
    archivo: str
    parche: str = Field(pattern=r"^P\d{3}$")


class SolicitudAprobacion(BaseModel):
    aprobados: list[Aprobado] = Field(default_factory=list, max_length=config.MAX_ARCHIVOS * 20)


class MensajeChat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversacion_id: int | None = None
    mensaje: str = Field(min_length=1, max_length=config.MAX_CARACTERES_MENSAJE)
    tipo_app: str = Field(default="web", pattern="^(web|api|escritorio|movil)$")
    modo_bd: str = Field(default="nueva", pattern="^(nueva|legada)$")
