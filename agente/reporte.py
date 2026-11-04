"""El reporte de la revisión: Markdown para leer y JSON para integrar (pipeline, API)."""
from __future__ import annotations

from collections import Counter

from agente.supervisor import Revision

ETIQUETA = {"NO_APTO": "NO APTO para pase a producción", "REVISAR": "REQUIERE REVISIÓN HUMANA", "APTO": "APTO"}


def a_dict(rev: Revision) -> dict:
    archivos = []
    for r in rev.resultados:
        archivos.append({
            "archivo": r.archivo.nombre, "lenguaje": r.archivo.lenguaje, "omitido": r.omitido,
            "evaluado_como": (r.ctx or rev.ctx).tipo_app,
            "hallazgos": [h.model_dump() for h in r.hallazgos],
            "semanticos": [h.model_dump() for h in r.semanticos],
            "parches": [p.model_dump() for p in r.parches],
            "rechazos_guarda": [{"hallazgo": h, "categoria": c, "motivo": m} for h, c, m in r.rechazos],
            "revision_manual": r.manuales,
            "resumen_especialista": r.resumen_agente,
            "hallazgos_despues": None if r.despues is None else len(r.despues),
        })
    todos = rev.todos()
    return {
        "contexto": {"tipo_app": rev.ctx.tipo_app, "modo_bd": rev.ctx.modo_bd},
        "veredicto_inicial": rev.veredicto(),
        "veredicto_final": rev.veredicto(final=True) if any(r.despues is not None for r in rev.resultados) else None,
        "totales": {
            "archivos": len(rev.resultados), "hallazgos": len(todos),
            "por_severidad": dict(Counter(h.severidad for h in todos)),
            "por_documento": dict(Counter(h.regla_id.split("-")[0] for h in todos)),
            "parches": len([p for r in rev.resultados for p in r.parches]),
            "llamadas_llm": rev.tracer.llamadas_llm,
            "tokens": {"entrada": rev.tracer.tokens_entrada, "salida": rev.tracer.tokens_salida},
            "segundos": rev.segundos,
        },
        "archivos": archivos,
    }


def a_markdown(rev: Revision) -> str:
    d = a_dict(rev)
    t = d["totales"]
    o = [f"# Revisión de estándares · {ETIQUETA[d['veredicto_inicial']]}", "",
         f"Aplicación **{rev.ctx.tipo_app}**, base de datos **{rev.ctx.modo_bd}**. "
         f"{t['archivos']} archivos, {t['hallazgos']} hallazgos, {t['parches']} parches propuestos, "
         f"{t['llamadas_llm']} llamadas al modelo.", ""]
    if d["veredicto_final"]:
        o += [f"**Tras aplicar lo aprobado: {ETIQUETA[d['veredicto_final']]}**", ""]
    for r in rev.resultados:
        o.append(f"## {r.archivo.nombre}")
        if r.omitido:
            o += [f"Omitido: {r.omitido}.", ""]
            continue
        if not r.hallazgos and not r.semanticos:
            o += ["Sin hallazgos.", ""]
            continue
        o += ["| Id | Línea | Regla | Severidad | Confianza | Qué pasa | Acción |", "|---|---|---|---|---|---|---|"]
        for h in r.hallazgos + r.semanticos:
            p = next((p for p in r.parches if p.hallazgo_id == h.id), None)
            accion = (f"parche {p.id} ({p.origen}, {p.estado})" if p else "")
            if h.id in r.manuales:
                accion = (accion + "; " if accion else "") + "revisión humana"
            if h.detector == "LLM-SEMANTICO":
                accion = "reportado por el especialista: confirmar"
            o.append(f"| {h.id} | {h.linea} | {h.regla_id} | {h.severidad} | {h.confianza} | "
                     f"{h.mensaje.replace('|', '/')} | {accion} |")
        o.append("")
        if r.rechazos:
            o.append("Parches rechazados por las guardas:")
            o += [f"- {hid} ({cat}): {m}" for hid, cat, m in r.rechazos]
            o.append("")
        notas = {k: v for k, v in r.manuales.items() if "Rotar" in v}
        if notas:
            o += [f"- **{k}**: {v}" for k, v in notas.items()] + [""]
        citas = sorted({h.cita for h in r.hallazgos + r.semanticos})
        o += ["Fuentes: " + "; ".join(citas), ""]
    return "\n".join(o)
