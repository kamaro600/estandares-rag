"""Enmascarar secretos y datos personales ANTES de que salgan hacia Claude u OpenAI.

Quien revisa su código pega código real del trabajo: puede traer la contraseña de producción en una cadena de
conexión o datos de clientes en un ejemplo ("DNI 45678912"). El enmascarado vive en los ADAPTADORES de salida
(agente/llm.py y agente/embeddings.py): cualquier camino hacia un tercero pasa por aquí aunque quien llama se olvide.
Los detectores deterministas trabajan con el texto original (corren en el equipo, no salen).

Límite honesto: son expresiones regulares. No detectan nombres propios ni direcciones (haría falta reconocimiento
de entidades) ni un secreto guardado en una variable con nombre neutro (x = "Kj8#…").
"""
from __future__ import annotations

import re

from agente import metricas

# valores que NO son secretos: vacíos, marcadores, lecturas de configuración
NO_SECRETO = re.compile(r"^(\*+|\[[A-Z_]+\]|<[^>]*>|\{[^}]*\}|\$\{[^}]*\}|x+|changeme|tu[-_ ]?clave.*|your[-_ ]?.*)$", re.I)

SECRETOS = [  # regex con el grupo "v" = valor a ocultar
    re.compile(r"(?:(?<=;)|(?<=\")|(?<=')|^)\s*(?:Password|Pwd)\s*=\s*(?P<v>[^;\"'\n]+)", re.I | re.M),
    re.compile(r"\b\w*(?:password|passwd|pwd|secret|apikey|api_key|token|contrasena|contraseña|clave)\w*"
               r"\s*[=:]\s*@?[\"'](?P<v>[^\"'\n]{4,})[\"']", re.I),
    re.compile(r"(?P<v>sk-[A-Za-z0-9_-]{20,})"),                       # OpenAI y Anthropic (sk-ant-…)
    re.compile(r"(?P<v>AKIA[0-9A-Z]{16})"),                            # AWS
    re.compile(r"(?P<v>gh[pousr]_[A-Za-z0-9]{36,})"),                  # GitHub
    re.compile(r"(?P<v>eyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{10,})"),       # JWT
    re.compile(r"(?P<v>-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)"),
]
# (?<![\d.\w]) y (?![\d.]) evitan enmascarar parte de un número más largo, un decimal o un identificador
PERSONALES = [
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("ruc", re.compile(r"(?<![\d.\w])(10|15|17|20)\d{9}(?![\d.])")),
    ("telefono", re.compile(r"(?<![\d.\w])(\+?51[\s-]?)?9\d{2}[\s-]?\d{3}[\s-]?\d{3}(?![\d.])")),
    ("dni", re.compile(r"(?<![\d.\w])\d{8}(?![\d.])")),
    ("tarjeta", re.compile(r"(?<![\d.\w])(?:\d{4}[\s-]?){3}\d{4}(?![\d.])")),
]


def _tramos_secretos(texto: str) -> list[list[int]]:
    tramos: list[list[int]] = []
    hallados = []
    for rx in SECRETOS:
        for m in rx.finditer(texto):
            valor = m.group("v").strip()
            if valor and not NO_SECRETO.match(valor):
                hallados.append((m.start("v"), m.start("v") + len(m.group("v").rstrip())))
    for i, f in sorted(hallados):
        if tramos and i <= tramos[-1][1]:
            tramos[-1][1] = max(tramos[-1][1], f)
        else:
            tramos.append([i, f])
    return tramos


def enmascarar(texto: str, contar: bool = True) -> str:
    """Reemplaza secretos por [SECRETO] y datos personales por [EMAIL], [DNI]…"""
    if not texto:
        return texto
    tramos = _tramos_secretos(texto)
    for inicio, fin in reversed(tramos):            # de atrás hacia adelante: los índices previos no se mueven
        texto = texto[:inicio] + "[SECRETO]" + texto[fin:]
    if tramos and contar:
        metricas.ENMASCARADOS.inc(len(tramos), tipo="secreto")
    for tipo, rx in PERSONALES:
        texto, n = rx.subn(f"[{tipo.upper()}]", texto)
        if n and contar:
            metricas.ENMASCARADOS.inc(n, tipo=tipo)
    return texto


def enmascarar_mensajes(mensajes: list[dict]) -> list[dict]:
    """Copia del historial con el texto que sale hacia el proveedor enmascarado: mensajes del usuario, bloques de
    texto y resultados de herramientas (que traen líneas del archivo revisado). Los bloques que produjo el propio
    modelo (razonamiento, tool_use) se devuelven intactos: el proveedor exige recibirlos sin cambios."""
    salida = []
    for m in mensajes:
        c = m["content"]
        if isinstance(c, str):
            salida.append({**m, "content": enmascarar(c)})
            continue
        if m["role"] == "assistant":
            salida.append(m)
            continue
        bloques = []
        for b in c:
            if b.get("type") == "text":
                b = {**b, "text": enmascarar(b["text"])}
            elif b.get("type") == "tool_result" and isinstance(b.get("content"), str):
                b = {**b, "content": enmascarar(b["content"])}
            bloques.append(b)
        salida.append({**m, "content": bloques})
    return salida
