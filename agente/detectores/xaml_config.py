"""Detectores de XAML (EST-DSK-001) y de archivos de configuración (.json, .config, .csproj)."""
from __future__ import annotations

import re

from agente.detectores import Archivo, Patron, registrar, registrar_archivo

I = re.IGNORECASE
PREFIJOS = {"TextBox": "txt", "Button": "btn", "ComboBox": "cmb", "DataGrid": "dgv", "Label": "lbl", "CheckBox": "chk"}


def _prefijo_incorrecto(m: re.Match, a: Archivo) -> bool:
    return not m.group(2).startswith(PREFIJOS[m.group(1)])


registrar(
    Patron("XAML-NOMBRE-CONTROL", ("xaml",), ("DSK-NET-001",),
           re.compile(r"<(TextBox|Button|ComboBox|DataGrid|Label|CheckBox)\b[^>]*\bx:Name=\"(\w+)\""),
           "Control con nombre sin el prefijo de su tipo (txt, btn, cmb, dgv, lbl, chk).",
           verificar=_prefijo_incorrecto),
    Patron("XAML-CLICK", ("xaml",), ("DSK-ARQ-002",), re.compile(r"\bClick=\"\w+\""),
           "Evento Click en la vista: en MVVM la acción se enlaza a un comando del ViewModel.",
           confianza="media"),
    Patron("XAML-TEXTO-LITERAL", ("xaml",), ("DSK-NET-006",),
           re.compile(r"\b(Content|Text|Header|Title)=\"(?!\{)[^\"]*[A-Za-zÁÉÍÓÚáéíóú]{3,}[^\"]*\""),
           "Texto visible escrito en el XAML: defínelo en un .resx.", confianza="media"),
    # --- Configuración ---
    Patron("CFG-PASSWORD", ("config", "xml"), ("SEG-DSK-002", "SEG-CRI-003"),
           re.compile(r"\b(password|pwd)\s*=\s*[^;\"<\s]+", I),
           "Contraseña en un archivo de configuración: Key Vault/user-secrets (o DPAPI en escritorio).",
           relacionadas=("SEG-CRI-003", "DSK-ARQ-004", "WEB-ARQ-003")),
    Patron("CFG-SECRETO", ("config",), ("SEG-CRI-003",),
           re.compile(r"\"(api_?key|client_?secret|secret|password)\"\s*:\s*\"[^\"]{4,}\"", I),
           "Secreto en un archivo del repositorio: se considera comprometido y debe rotarse."),
    Patron("CFG-USUARIO-SA", ("config", "xml"), ("SEG-GEN-002",), re.compile(r"\buser\s*id\s*=\s*sa\b", I),
           "Conexión con sa: usuario propio con permisos mínimos.", relacionadas=("WEB-BD-012",)),
    Patron("CFG-SIN-CIFRADO", ("config", "xml"), ("SEG-CRI-004",),
           re.compile(r"\bEncrypt\s*=\s*(False|no)\b|TrustServerCertificate\s*=\s*True", I),
           "Conexión a SQL Server sin cifrado o sin validar el certificado."),
)


@registrar_archivo("config")
def _csproj(a: Archivo, ctx) -> list[dict]:
    if not a.nombre.lower().endswith(".csproj"):
        return []
    hallazgos = []
    for n, l in enumerate(a.lineas, 1):
        m = re.search(r"<TargetFrameworks?>([^<]+)<", l)
        if m:
            tfm = m.group(1)
            if re.search(r"\bnet4\d|\bv4\.", tfm):
                hallazgos.append(dict(codigo="CSPROJ-NETFRAMEWORK", linea=n,
                                      reglas=("DSK-ARQ-001", "WEB-ARQ-002"),
                                      mensaje=f"{tfm}: prohibido iniciar desarrollos nuevos en .NET Framework."))
            elif re.search(r"netcoreapp|\bnet[5-7]\.0", tfm) and ctx.tipo_app in ("web", "api"):
                hallazgos.append(dict(codigo="CSPROJ-VERSION", linea=n, reglas=("WEB-ARQ-002",),
                                      mensaje=f"{tfm}: el mínimo es .NET 8 LTS.", relacionadas=("SEG-CFG-003",)))
    texto = a.contenido
    if ctx.tipo_app in ("web", "api"):
        if not re.search(r"<Nullable>\s*enable\s*</Nullable>", texto, I):
            hallazgos.append(dict(codigo="CSPROJ-NULLABLE", linea=1, reglas=("WEB-NET-006",),
                                  mensaje="Falta <Nullable>enable</Nullable>."))
        if not re.search(r"<TreatWarningsAsErrors>\s*true", texto, I):
            hallazgos.append(dict(codigo="CSPROJ-WARNINGS", linea=1, reglas=("WEB-NET-006",), confianza="media",
                                  mensaje="Falta <TreatWarningsAsErrors>true</TreatWarningsAsErrors> en Release."))
    return hallazgos

