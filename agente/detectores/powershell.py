"""Detectores de PowerShell: secretos, Invoke-Expression, TLS desactivado, descargas sin verificar."""
from __future__ import annotations

import re

from agente.detectores import Archivo, Patron, registrar, registrar_archivo

PS = ("powershell",)
I = re.IGNORECASE


registrar(
    Patron("PS-SECRETO-LITERAL", PS, ("SEG-CRI-003",),
           re.compile(r"\$(password|pwd|secret|apikey|token|clave)\w*\s*=\s*\"[^\"]{4,}\"", I),
           "Secreto escrito en el script: léelo de la configuración segura o de un gestor de secretos."),
    Patron("PS-SECRETO-PARAMETRO", PS, ("SEG-CRI-003",),
           re.compile(r"-(Password|Secret|Token|ApiKey|Credential)\s+\"[^\"]+\"", I),
           "Credencial pasada en claro por parámetro: usa un SecureString o un gestor de secretos."),
    Patron("PS-CONVERTTO-PLAINTEXT", PS, ("SEG-CRI-003",),
           re.compile(r"ConvertTo-SecureString\b[^#\n]*-AsPlainText", I),
           "ConvertTo-SecureString con -AsPlainText deja la clave en memoria en texto plano."),
    Patron("PS-INVOKE-EXPRESSION", PS, ("SEG-INY-004",),
           re.compile(r"\bInvoke-Expression\b|\bIEX\b", I),
           "Invoke-Expression/IEX ejecuta texto arbitrario: evítalo o valida la entrada con una lista blanca."),
    Patron("PS-DOWNLOAD-EXEC", PS, ("SEG-INY-004",),
           re.compile(r"(Invoke-WebRequest|iwr|wget|curl)\b[^#\n]*\|\s*(Invoke-Expression|IEX)\b", I),
           "Descarga y ejecución encadenadas (iwr … | iex): descarga, verifica y ejecuta por separado."),
    Patron("PS-TLS-DISABLE", PS, ("SEG-CRI-004",),
           re.compile(r"\[Net\.ServicePointManager\]::SecurityProtocol\s*=\s*.*Tls1[01]\b|"
                     r"-SkipCertificateCheck\b|-SkipCertCheck\b", I),
           "TLS desactivado o degradado a TLS 1.0/1.1: usa TLS 1.2+ y valida el certificado."),
    Patron("PS-EXEC-SIN-VALIDAR", PS, ("SEG-INY-004",),
           re.compile(r"(Start-Process|&)\s+\$\w+", I),
           "Ejecución de una ruta construida con una variable: valida contra una lista blanca."),
    Patron("PS-ENCODED-COMMAND", PS, ("SEG-INY-004",),
           re.compile(r"-EncodedCommand\b|-enc\b", I),
           "Comando codificado en base64: revisa qué ejecuta; puede ocultar código malicioso."),
)