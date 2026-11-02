"""Enrutamiento semántico: decide QUÉ hacer con el mensaje antes de gastar en el LLM o en el agente (C5).

    consulta_estandar  → RAG conversacional sobre los estándares
    validar_codigo     → agente validador (verificadores deterministas + RAG por id + LLM)
    fuera_de_alcance   → derivación, sin LLM

RouterSemantico (principal)
    Compara el embedding del mensaje con los ejemplos de cada ruta (data/rutas.json) y elige la ruta del ejemplo más
    parecido. Si la similitud no llega a ROUTER_MIN_SCORE, la decisión NO se toma con esa confianza: va al respaldo.

Respaldo (determinista)
    Se usa cuando el principal queda bajo el umbral o falla (error de red con OpenAI). Reglas simples y explicables:
    ¿trae código? → validar_codigo; ¿menciona términos de los estándares? → consulta_estandar; si no → fuera.
    Cada uso queda contado en est_router_respaldo_total{motivo}.

Código detectado: si el mensaje TRAE código, la ruta es validar_codigo aunque el router semántico opine otra cosa
(el mensaje "¿por qué esto está mal? <código>" se parece a una consulta, pero lo útil es validar el código).
Seguimiento: "¿y en Angular?" no se entiende solo; si el mensaje es corto y hay uno anterior, se comparan juntos.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app import detector_codigo, metricas
from app.config import DATA_DIR
from app.embeddings import Embedder, EmbeddingError, sin_tildes
from app.rag import similitudes

RUTAS = ("consulta_estandar", "validar_codigo", "fuera_de_alcance")
PALABRAS_SEGUIMIENTO = 6
TERMINOS = re.compile(            # (?<!\w)…(?!\w) en lugar de \b: "c#" y ".net" empiezan o terminan sin letra
    r"(?<!\w)(estandar\w*|norma\w*|regla\w*|convenci\w*|nomenclatura|nombr\w*|prefijo|tabla\w*|column\w*|procedimiento\w*|"
    r"sql|base de datos|bd|t-?sql|api\w*|rest|endpoint\w*|http|json|angular|typescript|componente\w*|c#|\.net|dotnet|"
    r"asp\.net|wpf|winforms|escritorio|movil\w*|maui|segur\w*|owasp|asvs|masvs|cifrad\w*|contrasen\w*|token\w*|jwt|"
    r"cookie\w*|cors|xss|inyecci\w*|secreto\w*|log\w*|excepci\w*|async|prueba\w*|cobertura|version\w*|codigo|"
    r"clase\w*|metodo\w*|query|consulta sql|arquitectura|capa\w*|dto\w*|paginaci\w*|mfa|autentica\w*|autoriza\w*|"
    r"firma\w*|instalador\w*|controlador\w*)(?!\w)")
PIDE_VALIDAR = re.compile(r"\b(valid\w*|revis\w*|analiz\w*|verific\w*|evalu\w*|cumple\w*|audit\w*)\b")


@dataclass
class ResultadoRuta:
    ruta: str
    confianza: float
    proveedor: str                       # embeddings | hash | respaldo
    puntajes: dict = field(default_factory=dict)
    bajo_umbral: bool = False
    respaldo: str = ""                   # motivo: bajo_umbral | error | sin_codigo | codigo_detectado
    tiene_codigo: bool = False

    def como_dict(self) -> dict:
        return dict(vars(self))


def cargar_rutas(path: Path | None = None) -> dict:
    return json.loads((path or DATA_DIR / "rutas.json").read_text(encoding="utf-8"))


class RouterSemantico:
    def __init__(self, rutas: dict, embedder: Embedder, minimo: float):
        self.embedder, self.minimo = embedder, minimo
        self.proveedor = "hash" if embedder.nombre.startswith("hash") else "embeddings"
        self.etiquetas = np.array([n for n, r in rutas.items() for _ in r["ejemplos"]])
        self.vectores = embedder.embed([e for r in rutas.values() for e in r["ejemplos"]])
        self.nombres = list(rutas)

    def enrutar(self, texto: str, historial: list[str] | None = None) -> ResultadoRuta:
        if historial and len(texto.split()) < PALABRAS_SEGUIMIENTO:
            texto = f"{historial[-1]} {texto}"
        s = similitudes(self.vectores, self.embedder.embed([texto[:2000]])[0])
        mejor = {n: round(float(s[self.etiquetas == n].max()), 4) for n in self.nombres}
        ruta = max(mejor, key=mejor.get)
        metricas.ROUTER_CONFIANZA.observe(max(mejor[ruta], 0.0))
        return ResultadoRuta(ruta, mejor[ruta], self.proveedor, mejor, bajo_umbral=mejor[ruta] < self.minimo)


def respaldo(texto: str, historial: list[str] | None = None) -> str:
    if detector_codigo.extraer(texto):
        return "validar_codigo"
    t = sin_tildes(f"{(historial or [''])[-1]} {texto}" if len(texto.split()) < PALABRAS_SEGUIMIENTO else texto)
    if TERMINOS.search(t):
        return "validar_codigo" if PIDE_VALIDAR.search(sin_tildes(texto)) and "codigo" in t else "consulta_estandar"
    return "fuera_de_alcance"


class Router:
    def __init__(self, semantico: RouterSemantico):
        self.semantico = semantico

    def enrutar(self, texto: str, historial: list[str] | None = None) -> ResultadoRuta:
        tiene_codigo = detector_codigo.extraer(texto) is not None
        try:
            r = self.semantico.enrutar(texto, historial)
        except EmbeddingError:
            metricas.ROUTER_RESPALDO.labels("error").inc()
            r = ResultadoRuta(respaldo(texto, historial), 0.0, "respaldo", respaldo="error")
        if r.bajo_umbral:
            metricas.ROUTER_RESPALDO.labels("bajo_umbral").inc()
            r.ruta, r.proveedor, r.respaldo = respaldo(texto, historial), "respaldo", "bajo_umbral"
        if r.ruta == "validar_codigo" and not tiene_codigo and not PIDE_VALIDAR.search(sin_tildes(texto)):
            # "¿Qué es OWASP A03?" se parece a los ejemplos de validación (vocabulario de seguridad) pero no trae código
            # ni pide revisar nada: es una consulta. Sin esta guarda el usuario recibiría "pega tu código".
            metricas.ROUTER_RESPALDO.labels("sin_codigo").inc()
            r.ruta, r.proveedor, r.respaldo = respaldo(texto, historial), "respaldo", "sin_codigo"
        if tiene_codigo and r.ruta != "validar_codigo":
            metricas.ROUTER_RESPALDO.labels("codigo_detectado").inc()
            r.ruta, r.respaldo = "validar_codigo", "codigo_detectado"
        r.tiene_codigo = tiene_codigo
        return r


def crear_router(settings, embedder: Embedder, rutas: dict | None = None) -> Router:
    return Router(RouterSemantico(rutas or cargar_rutas(), embedder, settings.router_min_score))
