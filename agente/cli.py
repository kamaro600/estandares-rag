"""Línea de comandos:  python -m agente revisar|regla|buscar …"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from agente import catalogo, config, rag
from agente.config import Settings
from agente.contexto import Contexto
from agente.detectores import detectar_lenguaje
from agente.llm import crear_llm
from agente.reporte import ETIQUETA, a_dict, a_markdown
from agente.supervisor import Supervisor
from agente.trace import Tracer


def recolectar(rutas: list[str]) -> list[tuple[str, str]]:
    archivos = []
    for r in rutas:
        p = Path(r)
        candidatos = sorted(x for x in p.rglob("*") if x.is_file()) if p.is_dir() else [p]
        for x in candidatos:
            if detectar_lenguaje(x.name) and not any(parte in (".venv", "node_modules", "bin", "obj", ".git")
                                                      for parte in x.parts):
                archivos.append((x.as_posix(), x.read_text(encoding="utf-8", errors="replace")))
    return archivos


def _preguntar(p, h) -> bool:
    print(f"\n  {p.id} · {p.archivo}:{p.linea_inicio}-{p.linea_fin} · {p.regla_id} ({p.origen})")
    print(f"    antes : {h.fragmento}")
    for l in p.reemplazo.split("\n"):
        print(f"    después: {l.strip()}")
    print(f"    motivo: {p.justificacion}")
    return input("    ¿Aplicar? [s/N] ").strip().lower() in ("s", "si", "sí", "y")


def cmd_revisar(a: argparse.Namespace) -> int:
    """Revisa archivos o carpetas desde la consola; devuelve 1 si el veredicto es NO_APTO (sirve como quality gate)."""
    settings = Settings().validar()
    ctx = Contexto(a.tipo or settings.tipo_app, a.bd or settings.modo_bd)
    entradas = recolectar(a.rutas)
    if not entradas:
        print("No encontré archivos de lenguajes soportados (.cs .xaml .ts .html .sql .json .config .csproj).")
        return 2
    tracer = Tracer(consola=a.traza)
    llm = None if a.sin_llm else crear_llm(settings)
    sup = Supervisor(ctx, llm, tracer)
    modelo = "ninguno" if llm is None else "mock" if llm.proveedor == "mock" else f"{llm.proveedor}:{llm.modelo}"
    print(f"Revisando {len(entradas)} archivos · app {ctx.tipo_app} · base {ctx.modo_bd} · modelo {modelo}")
    rev = sup.revisar(entradas, usar_llm=not a.sin_llm)
    if a.aprobar != "ninguno":
        politica = {"todo": lambda p, h: True,
                    "deterministas": lambda p, h: p.origen == "determinista",
                    "preguntar": _preguntar}[a.aprobar]
        escritos = sup.aplicar_aprobados(rev, politica)
        for e in escritos:
            print(f"  escrito: {e.relative_to(config.BASE_DIR).as_posix() if e.is_relative_to(config.BASE_DIR) else e}")
    config.SALIDA_DIR.mkdir(parents=True, exist_ok=True)
    (config.SALIDA_DIR / "reporte.md").write_text(a_markdown(rev), encoding="utf-8", newline="\n")
    reporte_json = json.dumps(a_dict(rev), ensure_ascii=False, indent=1)
    (config.SALIDA_DIR / "reporte.json").write_text(reporte_json, encoding="utf-8", newline="\n")
    traza = tracer.guardar()
    d = a_dict(rev)
    print("\nArchivo                                       Hallazgos  Parches  Manual")
    for r in rev.resultados:
        n = len(r.hallazgos) + len(r.semanticos)
        print(f"  {r.archivo.nombre[-44:]:<44} {n:>9} {len(r.parches):>8} {len(r.manuales):>7}"
              f"{'  (' + r.omitido + ')' if r.omitido else ''}")
    t = d["totales"]
    print(f"\nTotal: {t['hallazgos']} hallazgos {t['por_severidad']} · {t['parches']} parches · "
          f"{t['llamadas_llm']} llamadas al modelo · {t['segundos']} s")
    print(f"Veredicto: {ETIQUETA[d['veredicto_inicial']]}")
    if d["veredicto_final"]:
        print(f"Tras aplicar lo aprobado: {ETIQUETA[d['veredicto_final']]}")
    print(f"Reporte: salida/reporte.md · salida/reporte.json · traza: salida/trazas/{traza.name}")
    return 1 if d["veredicto_inicial"] == "NO_APTO" and a.aprobar == "ninguno" else 0


def cmd_regla(a: argparse.Namespace) -> int:
    r = catalogo.cargar().get(a.id.upper())
    if r is None:
        print(f"No existe {a.id}. Prueba: python -m agente buscar \"{a.id}\"")
        return 2
    print(f"{r.id} · {r.titulo}\n{r.nivel} · aplica a: {', '.join(r.aplica_a)} · {r.cita()}")
    if r.referencias:
        print("Referencias: " + "; ".join(r.referencias))
    print("\n" + r.texto)
    return 0


def cmd_buscar(a: argparse.Namespace) -> int:
    res = rag.buscar(a.consulta, k=a.k)
    if not res:
        print("Sin resultados por encima del umbral de relevancia.")
    for x in res:
        print(f"[{x.regla.id}] {x.regla.titulo} · score {x.score} ({x.via}) · {x.regla.cita()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    config.consola_segura()
    config.load_env()
    p = argparse.ArgumentParser(prog="python -m agente", description="Agente corrector de estándares")
    sub = p.add_subparsers(dest="comando", required=True)
    r = sub.add_parser("revisar", help="Revisa archivos o carpetas")
    r.add_argument("rutas", nargs="+")
    r.add_argument("--tipo", choices=config.TIPOS_APP, help="Tipo de aplicación (por defecto TIPO_APP)")
    r.add_argument("--bd", choices=config.MODOS_BD, help="Base nueva o legada (por defecto MODO_BD)")
    r.add_argument("--aprobar", choices=("preguntar", "deterministas", "todo", "ninguno"), default="ninguno",
                   help="Qué parches aplicar (siempre en salida/corregido, nunca sobre el original)")
    r.add_argument("--sin-llm", action="store_true", help="Solo análisis y correcciones deterministas")
    r.add_argument("--traza", action="store_true", help="Muestra los eventos en la consola")
    r.set_defaults(f=cmd_revisar)
    g = sub.add_parser("regla", help="Muestra una regla del catálogo")
    g.add_argument("id")
    g.set_defaults(f=cmd_regla)
    b = sub.add_parser("buscar", help="Busca en los estándares")
    b.add_argument("consulta")
    b.add_argument("-k", type=int, default=config.RAG_TOP_K)
    b.set_defaults(f=cmd_buscar)
    args = p.parse_args(argv)
    return args.f(args)
