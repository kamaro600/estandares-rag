"""Detectores de archivos de prueba: calidad y robustez de los tests."""
from __future__ import annotations

import re

from agente.detectores import Archivo, Patron, registrar, registrar_archivo

TS = ("tests",)
I = re.IGNORECASE


registrar(
    Patron("TEST-ASSERT-TRUE", TS, ("WEB-NET-004",),
           re.compile(r"Assert\.(True|False)\s*\(\s*(true|false)\s*\)|"
                      r"expect\s*\(\s*(true|false)\s*\)\.toBe\(\s*(true|false)\s*\)|"
                      r"assert\s+(True|False)\s*$", I),
           "Aserción tautológica (Assert.True(true)): el test no verifica nada."),
    Patron("TEST-SLEEP", TS, ("WEB-NET-002",),
           re.compile(r"Thread\.Sleep\s*\(|Task\.Delay\s*\(|setTimeout\s*\(|time\.sleep\s*\(", I),
           "Espera fija en el test: genera tests lentos y frágiles; sincroniza con señales o await."),
    Patron("TEST-DATETIME-NOW", TS, ("WEB-NET-001",),
           re.compile(r"DateTime\.Now\b|new\s+Date\(\)|datetime\.now\(\)", I),
           "Uso de DateTime.Now/Date() en el test: inyecta un reloj (IClock/TimeProvider) para reproducibilidad."),
    Patron("TEST-REAL-DB", TS, ("SEG-CRI-003", "WEB-BD-012"),
           re.compile(r"new\s+Sql(Connection|Command)\b|Server\s*=\s*[^;]+;.*Database\s*=", I),
           "El test toca una base de datos real: usa una base en memoria o un contenedor efímero."),
    Patron("TEST-CONSOLE", TS, ("WEB-NET-005",),
           re.compile(r"\bConsole\.(Write|WriteLine)\s*\(|\bprint\s*\(", I),
           "Salida por consola en el test: usa el logger del framework de pruebas."),
    Patron("TEST-VACIO", TS, ("WEB-NET-004",),
           re.compile(r"\b(void|Task)\s+\w*Test\w*\s*\([^)]*\)\s*\{\s*\}", I),
           "Método de test vacío: implementa la verificación o elimínalo."),
    Patron("TEST-SECRETOS", TS, ("SEG-CRI-003",),
           re.compile(r"\"[^\"]*\b(password|pwd|secret|token)\s*=\s*[^;\"]+", I),
           "Secreto hardcodeado en el test: muévelo a configuración de prueba o user-secrets."),
)


@registrar_archivo("tests")
def _archivo_completo(a: Archivo, ctx) -> list[dict]:
    hallazgos = []
    texto = a.contenido
    if not re.search(r"\b(Assert|expect|assert)\b", texto, re.I):
        hallazgos.append(dict(codigo="TEST-SIN-ASERCION", linea=1, reglas=("WEB-NET-004",),
                              mensaje="El archivo de prueba no contiene aserciones: verifica el comportamiento.",
                              confianza="media"))
    return hallazgos