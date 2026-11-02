"""Los datos que viajan entre las piezas (contratos). Sin lógica de negocio: solo estructuras y validación.

Fragmento            → una unidad del índice: una REGLA del estándar o una sección general (objetivo, alcance…).
MensajeChat          → lo que envía la página del chat.
SolicitudValidacion  → contrato de ENTRADA del agente validador (C5): si no valida, el agente no se invoca.
ResultadoValidacion  → contrato de SALIDA del agente: lo que vuelve al chat y se guarda como reporte.
Revision             → la decisión humana sobre los hallazgos (C6: humano en el circuito).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CATEGORIAS = ["seguridad", "web", "api", "escritorio", "referencia", "general"]
Categoria = Literal["seguridad", "web", "api", "escritorio", "referencia", "general"]
Severidad = Literal["critica", "alta", "media", "baja"]
Lenguaje = Literal["csharp", "typescript", "sql", "xaml", "otro"]


@dataclass
class Fragmento:
    id: str              # "WEB-BD-005" para una regla; "EST-WEB-001#2-alcance" para una sección general
    doc_codigo: str      # "EST-WEB-001"
    doc_titulo: str
    doc_version: str
    doc_fecha: str
    categoria: str       # seguridad | web | api | escritorio | referencia | general
    tipo: str            # regla | seccion | fragmento (corte genérico cuando el PDF no tiene reglas reconocibles)
    seccion: str         # "7.5"
    titulo: str
    pagina: int
    texto: str
    nivel: str = ""      # Obligatorio | Recomendado (solo reglas)
    aplica: str = ""
    referencias: str = ""
    score: float = 0.0

    def cita(self) -> str:
        """Lo que ve el usuario: "WEB-BD-005 · Nombres de procedimientos (EST-WEB-001 v3.0, pág. 8)"."""
        nombre = self.id if self.tipo == "regla" else f"{self.seccion}. {self.titulo}".strip(". ")
        if self.tipo == "regla":
            nombre += f" · {self.titulo}"
        return f"{nombre} ({self.doc_codigo} v{self.doc_version}, pág. {self.pagina})"

    def como_dict(self) -> dict:
        return asdict(self)


class MensajeChat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversacion_id: int | None = None
    mensaje: str = Field(min_length=1, max_length=20000)
    categorias: list[Categoria] | None = None          # filtro opcional elegido en la interfaz


class SolicitudValidacion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    codigo: str = Field(min_length=10, max_length=15000)
    lenguaje: Lenguaje
    instruccion: str = Field(default="", max_length=2000)   # lo que el usuario escribió además del código
    trace_id: str = Field(min_length=8, max_length=64)

    @field_validator("codigo")
    @classmethod
    def no_vacio(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("el código está vacío")
        return v


class Hallazgo(BaseModel):
    regla_id: str                          # regla del estándar incumplida ("" si el LLM no pudo asociarla)
    titulo: str
    severidad: Severidad
    origen: Literal["regla", "llm"]        # regla = verificador determinista (verificado); llm = opinión del modelo
    linea: int | None = None
    evidencia: str = ""                    # la línea de código que disparó el hallazgo
    explicacion: str = ""
    recomendacion: str = ""
    citas: list[str] = Field(default_factory=list)
    decision: Literal["pendiente", "confirmado", "descartado"] = "pendiente"
    comentario: str = ""


class ResultadoValidacion(BaseModel):
    trace_id: str
    lenguaje: Lenguaje
    hallazgos: list[Hallazgo]
    cumple: bool                           # lo decide el código (sin hallazgos obligatorios críticos/altos), no el LLM
    resumen: str
    reglas_consultadas: list[str]
    inyeccion_en_codigo: bool = False
    llm_error: str | None = None
    estado: Literal["PROPUESTO", "REVISADO"] = "PROPUESTO"


class DecisionHallazgo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    indice: int = Field(ge=0)
    decision: Literal["confirmado", "descartado"]
    comentario: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def justificar_descarte(self):
        if self.decision == "descartado" and len(self.comentario.strip()) < 5:
            raise ValueError("descartar un hallazgo exige un comentario que lo justifique")
        return self


class Revision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revisor: str = Field(min_length=2, max_length=80)
    decisiones: list[DecisionHallazgo] = Field(min_length=1)
    comentario: str = Field(default="", max_length=1000)
