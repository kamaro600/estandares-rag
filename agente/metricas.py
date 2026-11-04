"""Métricas en el formato de texto de Prometheus, escritas a mano para ver qué hay debajo.

Etiquetas SOLO de listas cerradas (lenguaje, severidad, origen…): nunca el nombre de un archivo,
un usuario o un id de revisión, que harían crecer las series sin límite.
"""
from __future__ import annotations

import threading
from collections import defaultdict

_lock = threading.Lock()


class Contador:
    def __init__(self, nombre: str, ayuda: str, etiquetas: tuple[str, ...] = ()):
        self.nombre, self.ayuda, self.etiquetas = nombre, ayuda, etiquetas
        self.valores: dict[tuple, float] = defaultdict(float)
        REGISTRO.append(self)

    def inc(self, valor: float = 1.0, **etq) -> None:
        clave = tuple(str(etq[e]) for e in self.etiquetas)
        with _lock:
            self.valores[clave] += valor

    def exponer(self) -> list[str]:
        salida = [f"# HELP {self.nombre} {self.ayuda}", f"# TYPE {self.nombre} counter"]
        for clave, v in sorted(self.valores.items()):
            salida.append(f"{self.nombre}{_etq(self.etiquetas, clave)} {v}")
        return salida


class Histograma:
    def __init__(self, nombre: str, ayuda: str, cubetas: tuple[float, ...]):
        self.nombre, self.ayuda, self.cubetas = nombre, ayuda, cubetas
        self.cuentas = [0] * len(cubetas)
        self.suma, self.total = 0.0, 0
        REGISTRO.append(self)

    def observar(self, valor: float) -> None:
        with _lock:
            for i, limite in enumerate(self.cubetas):
                if valor <= limite:
                    self.cuentas[i] += 1
            self.suma += valor
            self.total += 1

    def exponer(self) -> list[str]:
        salida = [f"# HELP {self.nombre} {self.ayuda}", f"# TYPE {self.nombre} histogram"]
        for limite, n in zip(self.cubetas, self.cuentas):
            salida.append(f'{self.nombre}_bucket{{le="{limite}"}} {n}')
        salida += [f'{self.nombre}_bucket{{le="+Inf"}} {self.total}',
                   f"{self.nombre}_sum {self.suma}", f"{self.nombre}_count {self.total}"]
        return salida


def _etq(nombres: tuple[str, ...], valores: tuple) -> str:
    if not nombres:
        return ""
    return "{" + ",".join(f'{n}="{v}"' for n, v in zip(nombres, valores)) + "}"


REGISTRO: list = []

REVISIONES = Contador("lab07_revisiones_total", "Revisiones terminadas por veredicto", ("veredicto",))
HALLAZGOS = Contador("lab07_hallazgos_total", "Hallazgos por lenguaje, severidad y origen",
                     ("lenguaje", "severidad", "origen"))
PARCHES = Contador("lab07_parches_total", "Parches propuestos por origen y resultado de la guarda",
                   ("origen", "resultado"))
GUARDA_RECHAZOS = Contador("lab07_guarda_rechazos_total", "Parches rechazados por las guardas, por motivo",
                           ("motivo",))
REVISION_MANUAL = Contador("lab07_revision_manual_total", "Hallazgos derivados a revisión humana", ("lenguaje",))
APROBACIONES = Contador("lab07_aprobaciones_total", "Decisiones humanas sobre parches", ("decision",))
LLM_LLAMADAS = Contador("lab07_llm_llamadas_total", "Llamadas al modelo", ("proveedor",))
LLM_TOKENS = Contador("lab07_llm_tokens_total", "Tokens consumidos", ("proveedor", "tipo"))
DURACION = Histograma("lab07_revision_segundos", "Duración de una revisión completa",
                      (0.1, 0.5, 1, 2, 5, 10, 30, 60, 120))


def inicializar_series(lenguajes: tuple[str, ...]) -> None:
    """Crea en 0 las combinaciones conocidas: sin esto Grafana muestra 'No data' hasta el primer evento."""
    for v in ("APTO", "NO_APTO", "REVISAR"):
        REVISIONES.inc(0, veredicto=v)
    for l in lenguajes:
        for s in ("bloqueante", "advertencia"):
            for o in ("determinista", "llm"):
                HALLAZGOS.inc(0, lenguaje=l, severidad=s, origen=o)
    for o in ("determinista", "llm"):
        for r in ("aceptado", "rechazado"):
            PARCHES.inc(0, origen=o, resultado=r)
    for d in ("aprobado", "denegado"):
        APROBACIONES.inc(0, decision=d)


def exponer() -> str:
    lineas = []
    for m in REGISTRO:
        lineas.extend(m.exponer())
    return "\n".join(lineas) + "\n"
