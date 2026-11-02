"""Datos comunes a todos los estándares de prueba.

Todo el contenido es FICTICIO: la empresa no existe y las reglas son un ejemplo verosímil para construir y probar el
chat RAG. Las referencias a OWASP (ASVS, MASVS, Top 10, API Security Top 10) son identificadores públicos; los
resúmenes son paráfrasis propias, no el texto oficial (la fuente autoritativa es owasp.org).
"""
from __future__ import annotations

EMPRESA = "Empresa Ejemplo S.A."
AREA = "Gerencia de Arquitectura y Desarrollo de Software"
AVISO = "Documento de prueba con contenido ficticio"

DEFINICIONES_COMUNES = [
    ("Obligatorio", "La regla debe cumplirse en todo desarrollo nuevo y en todo cambio sobre código existente. "
                    "Su incumplimiento bloquea el pase a producción salvo excepción aprobada."),
    ("Recomendado", "Buena práctica esperada. Su incumplimiento no bloquea el pase, pero debe justificarse en la "
                    "revisión de código."),
    ("Prohibido", "Práctica que no debe aparecer en el código. Equivale a una regla obligatoria en sentido negativo."),
    ("Excepción", "Autorización temporal (máximo 6 meses) para no cumplir una regla obligatoria. La aprueba el "
                  "Comité de Arquitectura y, si la regla es de seguridad, también Seguridad de la Información. "
                  "Se registra en el formulario FOR-ARQ-07."),
]


def R(id: str, titulo: str, texto: str, *, nivel: str = "Obligatorio", aplica: str = "", refs: str = "",
      mal: str | None = None, bien: str | None = None) -> dict:
    """Una regla del estándar. `texto` admite párrafos separados por línea en blanco y `código` entre comillas
    invertidas. `mal` y `bien` son ejemplos de código (incorrecto / correcto)."""
    return {"id": id, "titulo": titulo, "nivel": nivel, "aplica": aplica, "refs": refs,
            "texto": texto.strip(), "mal": mal.strip("\n") if mal else None, "bien": bien.strip("\n") if bien else None}
