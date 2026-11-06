"""El supervisor: planifica por archivo, delega en el especialista de cada lenguaje, valida y pide permiso."""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from agente import config, metricas
from agente.contexto import Contexto, contexto_para
from agente.detectores import Archivo, Hallazgo, analizar
from agente.guardas import validar_parche
from agente.llm import LLM
from agente.parches import Parche, aplicar, diff
from agente.react import ejecutar_agente
from agente.tools import Sesion
from agente.trace import Tracer
from agente.workers import REVISION_SEMANTICA, especialista_para, tarea

REGLAS_SECRETO = {"SEG-CRI-003", "SEG-DSK-002"}


@dataclass
class ResultadoArchivo:
    """Todo lo que el supervisor sabe de un archivo: hallazgos, parches propuestos, rechazos de la guarda y derivaciones."""
    archivo: Archivo
    hallazgos: list[Hallazgo] = field(default_factory=list)
    semanticos: list[Hallazgo] = field(default_factory=list)
    parches: list[Parche] = field(default_factory=list)
    rechazos: list[tuple[str, str, str]] = field(default_factory=list)
    manuales: dict[str, str] = field(default_factory=dict)
    resumen_agente: str = ""
    omitido: str = ""
    despues: list[Hallazgo] | None = None   # hallazgos tras aplicar lo aprobado
    ctx: Contexto | None = None             # contexto efectivo del archivo (un .kt se evalúa como Móvil)


@dataclass
class Corregido:
    nombre: str
    contenido: str
    diff: str


@dataclass
class Revision:
    """Una revisión completa: el contexto, el resultado de cada archivo y su traza."""
    ctx: Contexto
    resultados: list[ResultadoArchivo]
    tracer: Tracer
    segundos: float = 0.0

    def todos(self) -> list[Hallazgo]:
        return [h for r in self.resultados for h in r.hallazgos + r.semanticos]

    def veredicto(self, final: bool = False) -> str:
        """NO_APTO: queda un incumplimiento obligatorio detectado con certeza (bloquea el pase).
        REVISAR: solo quedan casos de confianza media o derivados a humanos. APTO: nada pendiente."""
        hallazgos = ([h for r in self.resultados for h in (r.despues if r.despues is not None else r.hallazgos)]
                     if final else [h for r in self.resultados for h in r.hallazgos])
        hallazgos += [h for r in self.resultados for h in r.semanticos]
        if any(h.severidad == "bloqueante" and h.confianza == "alta" for h in hallazgos):
            return "NO_APTO"
        return "REVISAR" if hallazgos else "APTO"


class Supervisor:
    """Orquesta la revisión sin LLM para decidir: plan por extensión, detectores, autofix con guarda,
    especialista ReAct para lo pendiente y, tras la aprobación humana, escritura en salida/corregido/.
    """
    def __init__(self, ctx: Contexto, llm: LLM | None, tracer: Tracer | None = None):
        self.ctx, self.llm = ctx, llm
        self.tracer = tracer or Tracer()

    # ---------- 1. Plan (determinista: no hace falta un LLM para decidir quién revisa un .cs) ----------
    def planificar(self, entradas: list[tuple[str, str]]) -> list[ResultadoArchivo]:
        """Asigna cada archivo a su especialista según la extensión, o lo omite (lenguaje desconocido o demasiado grande)."""
        plan = []
        for nombre, contenido in entradas[:config.MAX_ARCHIVOS]:
            a = Archivo(nombre, contenido)
            r = ResultadoArchivo(a, ctx=contexto_para(a, self.ctx))
            if not a.lenguaje:
                r.omitido = "lenguaje sin especialista"
            elif len(contenido.encode("utf-8")) > config.MAX_BYTES_ARCHIVO:
                r.omitido = f"supera {config.MAX_BYTES_ARCHIVO} bytes"
            plan.append(r)
        if len(entradas) > config.MAX_ARCHIVOS:
            self.tracer.evento("limite", motivo=f"solo se revisan {config.MAX_ARCHIVOS} archivos")
        self.tracer.evento("plan", archivos=len(plan), tipo_app=self.ctx.tipo_app, modo_bd=self.ctx.modo_bd,
                           pasos=[f"{r.archivo.nombre}→{r.omitido or especialista_para(r.archivo.lenguaje).nombre}"
                                  for r in plan])
        return plan

    # ---------- 2. Ejecutar cada paso ----------
    def revisar(self, entradas: list[tuple[str, str]], usar_llm: bool = True) -> Revision:
        """Analiza cada archivo del plan; con usar_llm=False solo hay detectores y correcciones mecánicas."""
        inicio = time.perf_counter()
        resultados = self.planificar(entradas)
        for r in resultados:
            if not r.omitido:
                self._revisar_archivo(r, usar_llm and self.llm is not None)
        rev = Revision(self.ctx, resultados, self.tracer, round(time.perf_counter() - inicio, 3))
        metricas.DURACION.observar(rev.segundos)
        self.tracer.evento("veredicto", inicial=rev.veredicto())
        return rev

    def _revisar_archivo(self, r: ResultadoArchivo, usar_llm: bool) -> None:
        a, ctx = r.archivo, r.ctx or self.ctx
        r.hallazgos = analizar(a, ctx)
        for h in r.hallazgos:
            metricas.HALLAZGOS.inc(lenguaje=a.lenguaje, severidad=h.severidad, origen="determinista")
        self.tracer.evento("analisis", archivo=a.nombre, hallazgos=len(r.hallazgos),
                           reglas=sorted({h.regla_id for h in r.hallazgos}))
        # 2a. Correcciones deterministas: también pasan por las guardas (el código también se equivoca).
        for h in r.hallazgos:
            if h.autofix is None:
                continue
            p = Parche(archivo=a.nombre, hallazgo_id=h.id, regla_id=h.regla_id, linea_inicio=h.linea,
                       linea_fin=h.linea, reemplazo=h.autofix, origen="determinista",
                       justificacion=f"Corrección mecánica de {h.regla_id}: {h.titulo_regla}.")
            rechazo = validar_parche(a, p, r.hallazgos, ctx)
            self._contar_parche(p, rechazo)
            if rechazo:
                r.rechazos.append((h.id, *rechazo))
            else:
                p.id = f"P{len(r.parches) + 1:03d}"
                r.parches.append(p)
        pendientes = [h for h in r.hallazgos if not any(p.hallazgo_id == h.id for p in r.parches)]
        # 2b. El especialista del lenguaje atiende lo que el código no sabe corregir. En los lenguajes con pocos
        #     detectores (Kotlin, Swift, Razor…) revisa además el archivo completo aunque no haya pendientes.
        if (pendientes or a.lenguaje in REVISION_SEMANTICA) and usar_llm:
            esp = especialista_para(a.lenguaje)
            sesion = Sesion(a, ctx, r.hallazgos, parches=r.parches, rechazos=r.rechazos)
            n_antes, rech_antes = len(r.parches), len(r.rechazos)
            res = ejecutar_agente(self.llm, esp.system, tarea(a, pendientes, ctx.tipo_app, ctx.modo_bd),
                                  sesion, esp.permitidas, self.tracer, esp.nombre)
            r.resumen_agente, r.manuales, r.semanticos = res.texto_final, sesion.manuales, sesion.semanticos
            for p in r.parches[n_antes:]:
                self._contar_parche(p, None)
            for _, cat, _m in r.rechazos[rech_antes:]:
                metricas.PARCHES.inc(origen="llm", resultado="rechazado")
                metricas.GUARDA_RECHAZOS.inc(motivo=cat)
            for h in r.semanticos:
                metricas.HALLAZGOS.inc(lenguaje=a.lenguaje, severidad=h.severidad, origen="llm")
            self.tracer.evento("especialista", archivo=a.nombre, rol=esp.nombre, fin=res.motivo_fin,
                               iteraciones=res.iteraciones)
        # 2c. Lo que nadie atendió va a un humano; un secreto expuesto SIEMPRE exige rotarlo.
        for h in r.hallazgos:
            atendido = any(p.hallazgo_id == h.id for p in r.parches) or h.id in r.manuales
            if not atendido:
                r.manuales[h.id] = "Sin corrección automática: requiere revisión humana."
            if h.regla_id in REGLAS_SECRETO or REGLAS_SECRETO & set(h.relacionadas):
                r.manuales[h.id] = (r.manuales.get(h.id, "") + " Rotar el secreto expuesto: quitarlo del "
                                    "archivo no lo invalida (SEG-CRI-003).").strip()
        for _ in r.manuales:
            metricas.REVISION_MANUAL.inc(lenguaje=a.lenguaje)

    def _contar_parche(self, p: Parche, rechazo: tuple[str, str] | None) -> None:
        if p.origen == "determinista":
            metricas.PARCHES.inc(origen="determinista", resultado="rechazado" if rechazo else "aceptado")
            if rechazo:
                metricas.GUARDA_RECHAZOS.inc(motivo=rechazo[0])
        else:
            metricas.PARCHES.inc(origen="llm", resultado="aceptado")

    # ---------- 3. Aprobación humana y escritura (fuera de los especialistas) ----------
    def corregir(self, rev: Revision, aprobar: Callable[[Parche, Hallazgo], bool]) -> list[Corregido]:
        """Pregunta por cada parche, aplica solo los aprobados EN MEMORIA y vuelve a analizar el resultado.
        No escribe nada: la CLI escribe en salida/corregido; la API devuelve el contenido."""
        cambios = []
        for r in rev.resultados:
            if r.omitido:
                continue
            for p in r.parches:
                h = next(x for x in r.hallazgos if x.id == p.hallazgo_id)
                ok = aprobar(p, h)
                p.estado = "aprobado" if ok else "denegado"
                metricas.APROBACIONES.inc(decision=p.estado)
                self.tracer.evento("aprobacion", archivo=r.archivo.nombre, parche=p.id, regla=p.regla_id,
                                   origen=p.origen, decision=p.estado)
            aprobados = [p for p in r.parches if p.estado == "aprobado"]
            nuevas, conflictos = aplicar(r.archivo.lineas, aprobados)
            for p in conflictos:
                p.estado, p.motivo = "conflicto", "Se superpone con otro parche aprobado: vuelve a revisar."
            for p in aprobados:
                if p.estado == "aprobado":
                    p.estado = "aplicado"
            corregido = Archivo(r.archivo.nombre, "\n".join(nuevas), r.archivo.lenguaje)
            r.despues = analizar(corregido, r.ctx or rev.ctx)
            if nuevas != r.archivo.lineas:
                cambios.append(Corregido(r.archivo.nombre, "\n".join(nuevas),
                                         diff(r.archivo.nombre, r.archivo.lineas, nuevas)))
        final = rev.veredicto(final=True)
        metricas.REVISIONES.inc(veredicto=final)
        self.tracer.evento("veredicto", final=final, archivos_corregidos=len(cambios))
        return cambios

    def aplicar_aprobados(self, rev: Revision, aprobar: Callable[[Parche, Hallazgo], bool],
                          destino: Path | None = None) -> list[Path]:
        """CLI: corrige y escribe SOLO dentro de salida/ (corregido/ y cambios.diff)."""
        destino = destino or config.SALIDA_DIR / "corregido"
        escritos = []
        cambios = self.corregir(rev, aprobar)
        for c in cambios:
            ruta = destino / ruta_segura(c.nombre)
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_text(c.contenido, encoding="utf-8", newline="\n")
            escritos.append(ruta)
        if cambios:
            ruta_diff = destino.parent / "cambios.diff"
            ruta_diff.write_text("".join(c.diff for c in cambios), encoding="utf-8", newline="\n")
            escritos.append(ruta_diff)
        return escritos


def ruta_segura(nombre: str) -> PurePosixPath:
    """Nunca escribir fuera de salida/: sin rutas absolutas, sin '..', sin unidades de Windows."""
    partes = [p for p in PurePosixPath(nombre.replace("\\", "/")).parts if p not in ("..", ".", "/") and ":" not in p]
    if not partes:
        raise ValueError(f"Nombre de archivo inválido: {nombre!r}")
    return PurePosixPath(*partes)
