"""Enmascarar datos personales y secretos ANTES de que salgan hacia OpenAI (C6).

Un desarrollador pega código real del trabajo: puede traer la contraseña de producción en una cadena de conexión, o
datos de clientes en un ejemplo ("DNI 45678912"). El enmascarado vive en los ADAPTADORES de salida (app/llm.py y
app/embeddings.py): cualquier camino que llegue a un tercero pasa por aquí aunque quien llama se olvide.
En la base de datos interna se guarda el texto original (es el registro de la empresa).

Combina los patrones de secretos del lab 07 y los de datos personales del lab 06.
Límite honesto: son expresiones regulares. No detectan nombres propios ni direcciones (haría falta NER) ni un
secreto guardado en una variable con nombre neutro (`x = "Kj8#…"`).
"""
from __future__ import annotations

import re

from app import metricas

# valores que NO son secretos: vacíos, marcadores, lecturas de configuración
NO_SECRETO = re.compile(r"^(\*+|\[[A-Z_]+\]|<[^>]*>|\{[^}]*\}|\$\{[^}]*\}|x+|changeme|tu[-_ ]?clave.*|your[-_ ]?.*)$", re.I)

SECRETOS = [  # (tipo, regex con el grupo "v" = valor a ocultar)
    ("secreto", re.compile(r"(?:(?<=;)|(?<=\")|(?<=')|^)\s*(?:Password|Pwd)\s*=\s*(?P<v>[^;\"'\n]+)", re.I | re.M)),
    ("secreto", re.compile(r"\b\w*(?:password|passwd|pwd|secret|apikey|api_key|token|contrasena|contraseña|clave)\w*"
                           r"\s*[=:]\s*@?[\"'](?P<v>[^\"'\n]{4,})[\"']", re.I)),
    ("secreto", re.compile(r"(?P<v>sk-[A-Za-z0-9_-]{20,})")),
    ("secreto", re.compile(r"(?P<v>AKIA[0-9A-Z]{16})")),
    ("secreto", re.compile(r"(?P<v>gh[pousr]_[A-Za-z0-9]{36,})")),
    ("secreto", re.compile(r"(?P<v>eyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{10,})")),
    ("secreto", re.compile(r"(?P<v>-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)")),
]
# (?<![\d.]) y (?![\d.]) evitan enmascarar parte de un número más largo o de un decimal
PERSONALES = [
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("ruc", re.compile(r"(?<![\d.\w])(10|15|17|20)\d{9}(?![\d.])")),
    ("telefono", re.compile(r"(?<![\d.\w])(\+?51[\s-]?)?9\d{2}[\s-]?\d{3}[\s-]?\d{3}(?![\d.])")),
    ("dni", re.compile(r"(?<![\d.\w])\d{8}(?![\d.])")),
    ("tarjeta", re.compile(r"(?<![\d.\w])(?:\d{4}[\s-]?){3}\d{4}(?![\d.])")),
]


def _secretos(texto: str):
    for tipo, rx in SECRETOS:
        for m in rx.finditer(texto):
            valor = m.group("v").strip()
            if valor and not NO_SECRETO.match(valor):
                yield tipo, m.start("v"), m.start("v") + len(m.group("v").rstrip())


def hay_secretos(texto: str) -> list[int]:
    """Líneas (1-based) con un secreto escrito en el texto. Lo usa el validador de código."""
    return sorted({texto.count("\n", 0, inicio) + 1 for _t, inicio, _f in _secretos(texto)})


def enmascarar(texto: str, contar: bool = True) -> str:
    """Reemplaza secretos por [SECRETO] y datos personales por [EMAIL], [DNI]… `contar=False` para usos internos."""
    tramos: list[list] = []
    for _t, i, f in sorted(_secretos(texto), key=lambda x: x[1]):
        if tramos and i <= tramos[-1][1]:
            tramos[-1][1] = max(tramos[-1][1], f)
        else:
            tramos.append([i, f])
    for inicio, fin in reversed(tramos):            # de atrás hacia adelante: los índices previos no se mueven
        texto = texto[:inicio] + "[SECRETO]" + texto[fin:]
    if tramos and contar:
        metricas.PII.labels("secreto").inc(len(tramos))
    for tipo, rx in PERSONALES:
        texto, n = rx.subn(f"[{tipo.upper()}]", texto)
        if n and contar:
            metricas.PII.labels(tipo).inc(n)
    return texto
