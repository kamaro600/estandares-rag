"""Detectores de Dockerfile: imagen base, usuario, secretos, contexto y limpieza."""
from __future__ import annotations

import re

from agente.detectores import Archivo, Patron, registrar, registrar_archivo

DK = ("dockerfile",)
I = re.IGNORECASE


def _tiene_instruccion(texto: str, instr: str) -> bool:
    return re.search(rf"^\s*{instr}\b", texto, re.I | re.M) is not None


registrar(
    Patron("DKR-FROM-LATEST", DK, ("SEG-CFG-001",),
           re.compile(r"^\s*FROM\s+\S+(?::latest)?\s*$", I | re.M),
           "Imagen base sin tag fijo ni digest: pinea la versión (y mejor el digest) para builds reproducibles.",
           verificar=lambda m, a: m.group(0).rstrip().lower().endswith(":latest")
                                 or ":" not in m.group(0).split()[-1]),
    Patron("DKR-SECRET-ENV", DK, ("SEG-CRI-003",),
           re.compile(r"^\s*ENV\s+\w*(PASSWORD|SECRET|TOKEN|API_?KEY|CLAVE)\w*\s*=", I | re.M),
           "Secreto en una variable ENV: queda en la imagen y en el historial; úsalo en tiempo de ejecución."),
    Patron("DKR-SECRET-ARG", DK, ("SEG-CRI-003",),
           re.compile(r"^\s*ARG\s+\w*(PASSWORD|SECRET|TOKEN|API_?KEY|CLAVE)\w*\s*=", I | re.M),
           "Secreto en un ARG: queda en el historial de la imagen; no lo pases en el build."),
    Patron("DKR-COPY-ALL", DK, ("SEG-CFG-001",),
           re.compile(r"^\s*(COPY|ADD)\s+\.\s+\.\s*$", I | re.M),
           "COPY . . trae todo el contexto (incluidos secretos): usa .dockerignore y copia solo lo necesario."),
    Patron("DKR-CURL-PIPE", DK, ("SEG-INY-004",),
           re.compile(r"(curl|wget)\b[^#\n]*\|\s*(sh|bash)\b", I),
           "Descarga y ejecución encadenadas en el build: descarga, verifica y ejecuta por separado."),
    Patron("DKR-APT-SIN-LIMPIEZA", DK, ("SEG-CFG-001",),
           re.compile(r"apt-get\s+install\b(?![^#\n]*--no-install-recommends)", I),
           "apt-get install sin --no-install-recommends ni limpieza: infla la imagen y arrastra paquetes."),
    Patron("DKR-USER-ROOT", DK, ("SEG-CFG-002",),
           re.compile(r"^\s*USER\s+root\s*$", I | re.M),
           "El contenedor corre como root: crea y usa un usuario no privilegiado."),
    Patron("DKR-ADD-REMOTO", DK, ("SEG-INY-004",),
           re.compile(r"^\s*ADD\s+https?://", I | re.M),
           "ADD con URL remota: usa RUN curl/wget con verificación y luego COPY."),
)


@registrar_archivo("dockerfile")
def _archivo_completo(a: Archivo, ctx) -> list[dict]:
    hallazgos = []
    texto = a.contenido
    if not _tiene_instruccion(texto, "HEALTHCHECK"):
        hallazgos.append(dict(codigo="DKR-SIN-HEALTHCHECK", linea=1, reglas=("SEG-CFG-001",),
                              mensaje="Sin HEALTHCHECK: el orquestador no puede saber si el contenedor está sano.",
                              confianza="media"))
    if not _tiene_instruccion(texto, "USER"):
        hallazgos.append(dict(codigo="DKR-SIN-USER", linea=1, reglas=("SEG-CFG-002",),
                              mensaje="No se declara USER: el proceso corre como root por defecto.",
                              confianza="alta"))
    return hallazgos