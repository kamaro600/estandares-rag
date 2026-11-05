"""Enrutamiento semántico del chat: decide QUÉ hacer con cada mensaje antes de gastar en el modelo o en el agente.

    consulta_estandar  → pregunta: buscar reglas y responder citándolas (o "no está en los estándares")
    revisar_codigo     → el código pasa, con su contrato, al Supervisor y a los especialistas
    fuera_de_alcance   → derivación, sin modelo

Principal: compara el embedding del mensaje con los ejemplos de cada ruta (data/rutas.json) y elige la del ejemplo
más parecido. Si la similitud no llega a ROUTER_MIN_SCORE, la decisión NO se toma con esa confianza: va al respaldo.
Respaldo (determinista): ¿trae código? → revisar; ¿menciona términos de los estándares? → consulta; si no → fuera.
Guardas: si el mensaje TRAE código, se revisa aunque el router opine otra cosa; si pide revisar pero no trae
código, no se invoca al agente con datos vacíos. Cada uso del respaldo cuenta en lab07_router_respaldo_total{motivo}.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field

import numpy as np

from agente import codigo_chat, config, embeddings, metricas

RUTAS_PATH = config.DATA_DIR / "rutas.json"
PALABRAS_SEGUIMIENTO = 6
TERMINOS = re.compile(            # (?<!\w)…(?!\w) en lugar de \b: "c#" y ".net" empiezan o terminan sin letra
    r"(?<!\w)(estandar\w*|norma\w*|regla\w*|convenci\w*|nomenclatura|nombr\w*|prefijo|tabla\w*|column\w*|"
    r"procedimiento\w*|sql|base de datos|bd|t-?sql|api\w*|rest|endpoint\w*|http|json|angular|typescript|componente\w*|"
    r"c#|\.net|dotnet|asp\.net|wpf|winforms|escritorio|movil\w*|maui|android|ios|kotlin|swift|segur\w*|owasp|asvs|"
    r"masvs|cifrad\w*|contrasen\w*|token\w*|jwt|cookie\w*|cors|xss|inyecci\w*|secreto\w*|log\w*|excepci\w*|async|"
    r"prueba\w*|cobertura|version\w*|codigo|clase\w*|metodo\w*|query|arquitectura|capa\w*|dto\w*|paginaci\w*|mfa|"
    r"autentica\w*|autoriza\w*|firma\w*|instalador\w*|controlador\w*)(?!\w)")
PIDE_REVISAR = re.compile(r"\b(valid\w*|revis\w*|analiz\w*|verific\w*|evalu\w*|cumple\w*|audit\w*|corrig\w*|corrij\w*)\b")
ARTEFACTO = re.compile(r"\b(codigo|controlador\w*|clase\w*|metodo\w*|componente\w*|procedimiento\w*|servicio\w*|script\w*|"
                       r"query|consulta sql|archivo\w*|vista\w*|funcion\w*|endpoint\w*|pipeline\w*)\b")


def sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")


@dataclass
class ResultadoRuta:
    """La ruta elegida, con su confianza, quién decidió (embeddings o respaldo) y por qué."""
    ruta: str
    confianza: float
    proveedor: str                       # embeddings | respaldo
    puntajes: dict = field(default_factory=dict)
    bajo_umbral: bool = False
    respaldo: str = ""                   # motivo: bajo_umbral | error | sin_codigo | codigo_detectado
    tiene_codigo: bool = False

    def como_dict(self) -> dict:
        return dict(vars(self))


def respaldo(texto: str, historial: list[str] | None = None) -> str:
    """Decisión determinista cuando el router semántico no está seguro: ¿trae código? ¿pide una revisión?
    ¿usa términos de los estándares? Sin nada de eso, el mensaje queda fuera de alcance.
    """
    if codigo_chat.extraer(texto):
        return "revisar_codigo"
    corto = len(texto.split()) < PALABRAS_SEGUIMIENTO and historial
    t = sin_tildes(f"{historial[-1]} {texto}" if corto else texto)
    pide = PIDE_REVISAR.search(sin_tildes(texto))
    if pide and ARTEFACTO.search(t):      # "revisa mi controlador": quiere una revisión (y le pediremos el código)
        return "revisar_codigo"
    return "consulta_estandar" if TERMINOS.search(t) else "fuera_de_alcance"


class Router:
    """Router semántico: compara el mensaje con los ejemplos de data/rutas.json usando los mismos embeddings
    del buscador. Bajo ROUTER_MIN_SCORE, o si los embeddings fallan, decide respaldo().
    """
    def __init__(self, minimo: float, rutas: dict | None = None):
        rutas = rutas or json.loads(RUTAS_PATH.read_text(encoding="utf-8"))
        self.minimo = minimo
        self.etiquetas = np.array([n for n, r in rutas.items() for _ in r["ejemplos"]])
        self.vectores = embeddings.vectorizar([e for r in rutas.values() for e in r["ejemplos"]])
        self.nombres = list(rutas)

    def _semantico(self, texto: str, historial: list[str] | None) -> ResultadoRuta:
        if historial and len(texto.split()) < PALABRAS_SEGUIMIENTO:   # "¿y en Angular?" no se entiende solo
            texto = f"{historial[-1]} {texto}"
        s = self.vectores @ embeddings.vectorizar([texto[:2000]])[0]
        mejor = {n: round(float(s[self.etiquetas == n].max()), 4) for n in self.nombres}
        ruta = max(mejor, key=mejor.get)
        return ResultadoRuta(ruta, mejor[ruta], "embeddings", mejor, bajo_umbral=mejor[ruta] < self.minimo)

    def enrutar(self, texto: str, historial: list[str] | None = None) -> ResultadoRuta:
        """Ruta del mensaje, con dos guardas: sin código no hay revisión (salvo pedido explícito), y con código siempre."""
        tiene_codigo = codigo_chat.extraer(texto) is not None
        try:
            r = self._semantico(texto, historial)
        except embeddings.EmbeddingError:
            r = ResultadoRuta(respaldo(texto, historial), 0.0, "respaldo", respaldo="error")
        if r.bajo_umbral:
            r.ruta, r.proveedor, r.respaldo = respaldo(texto, historial), "respaldo", "bajo_umbral"
        if r.ruta == "revisar_codigo" and not tiene_codigo and not PIDE_REVISAR.search(sin_tildes(texto)):
            # "¿Qué es OWASP A03?" se parece a los ejemplos de revisión (vocabulario de seguridad) pero no trae código
            r.ruta, r.proveedor, r.respaldo = respaldo(texto, historial), "respaldo", "sin_codigo"
        if tiene_codigo and r.ruta != "revisar_codigo":
            r.ruta, r.respaldo = "revisar_codigo", "codigo_detectado"
        if r.respaldo:
            metricas.ROUTER_RESPALDO.inc(motivo=r.respaldo)
        r.tiene_codigo = tiene_codigo
        return r
