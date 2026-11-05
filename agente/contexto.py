"""Qué reglas aplican a este archivo y cuál prevalece cuando dos estándares chocan."""
from __future__ import annotations

from dataclasses import dataclass, replace

from agente import catalogo, config

# Orden de precedencia declarado en los propios estándares:
#  - EST-SEG-001 §2: "prevalece sobre cualquier otro estándar de desarrollo en materia de seguridad".
#  - EST-WEB-001 §10: en nomenclatura de BD prevalece WEB sobre DSK para bases NUEVAS.
#  - EST-WEB-001 §7: las bases existentes (TBL_, mayúsculas) no se renombran.
PRECEDENCIA = {"EST-SEG-001": 0, "EST-API-001": 1, "EST-WEB-001": 2, "EST-DSK-001": 3, "EST-REF-001": 4}


@dataclass(frozen=True)
class Contexto:
    """Lo que decide qué reglas aplican: el tipo de aplicación y si la base de datos es nueva o existente."""
    tipo_app: str = "web"      # web | api | escritorio | movil
    modo_bd: str = "nueva"     # nueva (WEB-BD-*) | legada (DSK-BD-*, prefijo TBL_)

    def __post_init__(self):
        if self.tipo_app not in config.TIPOS_APP:
            raise ValueError(f"tipo_app inválido: {self.tipo_app!r}")
        if self.modo_bd not in config.MODOS_BD:
            raise ValueError(f"modo_bd inválido: {self.modo_bd!r}")

    def tipos(self) -> tuple[str, ...]:
        """Una aplicación web incluye su API REST (EST-WEB-001 WEB-ARQ-001; EST-API-001 §2)."""
        return ("web", "api") if self.tipo_app == "web" else (self.tipo_app,)

    def regla_aplicable(self, candidatas: tuple[str, ...], segun_bd: bool = False) -> catalogo.Regla | None:
        """La primera regla candidata que aplica a este tipo de aplicación.

        segun_bd=True: la regla depende de la base (nueva o legada), no del tipo de aplicación;
        por ejemplo DSK-BD-001 "aplica a Escritorio" pero es la nomenclatura de toda base legada.
        """
        reglas = catalogo.cargar()
        for rid in candidatas:
            r = reglas.get(rid)
            if r is None:
                raise KeyError(f"El detector cita {rid}, que no existe en el catálogo")
            if segun_bd or any(t in r.aplica_a for t in self.tipos()):
                return r
        return None


def contexto_para(archivo, ctx: Contexto) -> Contexto:
    """Un .kt, un .swift o un AndroidManifest.xml solo existen en una app móvil: se evalúan como Móvil
    aunque la revisión sea de una solución web (si no, ninguna regla SEG-MOV aplicaría)."""
    from agente.detectores import es_movil  # noqa: PLC0415  (detectores importa este módulo)
    return replace(ctx, tipo_app="movil") if es_movil(archivo) and ctx.tipo_app != "movil" else ctx


def prioridad(regla_id: str) -> int:
    return PRECEDENCIA.get(catalogo.cargar()[regla_id].documento, 9)
