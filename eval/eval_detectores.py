"""python -m eval.eval_detectores

Conjunto de oro sacado de los propios estándares: cada "Ejemplo incorrecto" debería disparar su
regla, y cada "Ejemplo correcto" no debería disparar nada con confianza alta.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from agente import catalogo
from agente.contexto import Contexto
from agente.detectores import Archivo, analizar

RE_BLOQUE = re.compile(r"^Ejemplo (incorrecto|correcto)\s*$", re.M)
NO_CODIGO = re.compile(r"^(GET|POST|PUT|DELETE|PATCH) /|^HTTP/1\.1|^\{ ?\"", re.M)


@dataclass
class Caso:
    regla: catalogo.Regla
    tipo: str          # incorrecto | correcto
    nombre: str
    codigo: str


def _nombre(codigo: str) -> str:
    """Un nombre de archivo verosímil: de él depende qué detectores se aplican."""
    primera = codigo.strip().splitlines()[0]
    m = re.match(r"//\s*(?:archivo:\s*)?([\w.\-]+\.(cs|ts|json))\b", primera)
    if m:
        return m.group(1)
    if primera.lstrip().startswith("<!--") and "config" in primera:
        return "app.config"
    if primera.lstrip().startswith("<"):
        return "Vista.xaml"
    if re.search(r"\b(CREATE\s+(TABLE|OR\s+ALTER|PROC)|^SELECT\b|SET\s+@\w+)", codigo, re.I | re.M):
        return "script.sql"
    if re.search(r"@Component|this\.\w+|: Observable|localStorage|=>\s*this\.", codigo):
        return "ejemplo.component.ts"
    return "Ejemplo.cs"


def _contexto(r: catalogo.Regla) -> Contexto:
    if r.documento == "EST-DSK-001":
        return Contexto("escritorio", "legada")
    for tipo in ("web", "api", "escritorio", "movil"):
        if tipo in r.aplica_a:
            return Contexto(tipo, "nueva")
    return Contexto()


def casos() -> list[Caso]:
    resultado = []
    for r in catalogo.cargar().values():
        partes = RE_BLOQUE.split(r.texto)
        for tipo, codigo in zip(partes[1::2], partes[2::2]):
            # El ejemplo de SEG-INY-001 trae C# y T-SQL juntos, separados por "-- T-SQL".
            for i, trozo in enumerate(re.split(r"^-- T-SQL\s*$", codigo, flags=re.M)):
                if not trozo.strip() or NO_CODIGO.search(trozo):
                    continue
                nombre = "script.sql" if i > 0 else _nombre(trozo)
                resultado.append(Caso(r, tipo, nombre, trozo.strip("\n")))
    return resultado


def evaluar() -> dict:
    detectados, no_detectados, falsos = [], [], []
    for c in casos():
        hs = analizar(Archivo(c.nombre, c.codigo), _contexto(c.regla))
        if c.tipo == "incorrecto":
            if any(h.regla_id == c.regla.id or c.regla.id in h.relacionadas for h in hs):
                detectados.append(c)
            else:
                no_detectados.append(c)
        else:
            altos = [h for h in hs if h.confianza == "alta"]
            if altos:
                falsos.append((c, altos))
    return {"detectados": detectados, "no_detectados": no_detectados, "falsos": falsos}


def main() -> None:
    res = evaluar()
    total_inc = len(res["detectados"]) + len(res["no_detectados"])
    total_cor = sum(1 for c in casos() if c.tipo == "correcto")
    print(f"Ejemplos incorrectos detectados: {len(res['detectados'])}/{total_inc} "
          f"(recall {len(res['detectados']) / total_inc:.2f})")
    for c in res["no_detectados"]:
        print(f"  sin detectar: {c.regla.id:<12} ({c.nombre})")
    print(f"Ejemplos correctos con falso positivo (confianza alta): {len(res['falsos'])}/{total_cor}")
    for c, hs in res["falsos"]:
        print(f"  {c.regla.id:<12} → " + ", ".join(f"{h.regla_id}@{h.linea}:{h.detector}" for h in hs))


if __name__ == "__main__":
    main()
