"""Simulador de LLM: un guion de reglas fijas, NO un modelo. Sirve para practicar sin clave y para
que las pruebas sean repetibles. Solo sabe corregir unos pocos casos; el resto lo deriva a un humano."""
from __future__ import annotations

import json
import re

from agente.llm import Respuesta


def _lineas_de(tarea: str) -> dict[int, str]:
    codigo = tarea.split('<datos_externos herramienta="archivo">', 1)[1].split("</datos_externos>", 1)[0]
    return {int(m.group(1)): m.group(2) for m in re.finditer(r"^\s*(\d+)\| (.*)$", codigo, re.M)}


def _pascal(nombre: str) -> str:
    return "".join(p[:1].upper() + p[1:] for p in re.split(r"[_\s]+", nombre) if p)


def _receta(h: dict, linea: str) -> tuple[str, str] | None:
    """(reemplazo, justificación) para los casos que el guion sabe corregir."""
    regla = h["regla_id"]
    m = re.search(r"=\s*(.+?)\.Result\b", linea)
    if regla in ("WEB-NET-002", "DSK-NET-002") and m:
        return (linea[:m.start()] + "= await " + m.group(1) + linea[m.end():],
                f"{regla}: se reemplaza .Result por await (la firma del método debe pasar a async Task).")
    if regla == "WEB-NET-004" and re.search(r"catch\s*\(\s*Exception\s*\)\s*\{\s*\}", linea):
        nuevo = re.sub(r"catch\s*\(\s*Exception\s*\)\s*\{\s*\}",
                       'catch (Exception ex) { _logger.LogError(ex, "Error no controlado"); throw; }', linea)
        return nuevo, "WEB-NET-004: la excepción se registra y se relanza en lugar de ignorarse."
    if regla == "WEB-ANG-003" and re.search(r":\s*any\b|<any>", linea):
        return (re.sub(r"<any>", "<unknown>", re.sub(r":\s*any\b", ": unknown", linea)),
                "WEB-ANG-003: any se reemplaza por unknown hasta modelar la interfaz en *.model.ts.")
    m = re.search(r"\b(class|record|struct)\s+([a-z_]\w*)", linea)
    if regla in ("WEB-NET-001", "DSK-NET-001") and m:
        return (linea[:m.start(2)] + _pascal(m.group(2)) + linea[m.end(2):],
                f"{regla}: el tipo pasa a PascalCase. Revisa las referencias en otros archivos.")
    return None


class MockLLM:
    proveedor = "mock"

    def responder(self, system: str, mensajes: list[dict], herramientas: list[dict]) -> Respuesta:
        tarea = mensajes[0]["content"]
        hallazgos = json.loads(tarea.split("<hallazgos>", 1)[1].split("</hallazgos>", 1)[0])
        lineas = _lineas_de(tarea)
        turno = sum(1 for m in mensajes if m["role"] == "assistant")
        usados = 0
        if not hallazgos:  # revisión semántica: el guion no sabe hacerla, lo dice y termina
            return Respuesta([{"type": "text", "text": "[simulado] Sin hallazgos de los detectores. El simulador no "
                                                       "hace revisión semántica: usa un modelo real para eso."}],
                             "end_turn", _tokens(tarea), 30)
        if turno == 0:  # primer turno: una acción por hallazgo, todas en paralelo
            bloques = [{"type": "text", "text": f"Reviso {len(hallazgos)} hallazgos."}]
            for h in hallazgos:
                receta = _receta(h, lineas.get(h["linea"], ""))
                usados += 1
                if receta:
                    bloques.append(_uso(usados, "proponer_parche", {
                        "hallazgo_id": h["id"], "linea_inicio": h["linea"], "linea_fin": h["linea"],
                        "reemplazo": receta[0], "justificacion": receta[1]}))
                else:
                    bloques.append(_uso(usados, "marcar_revision_manual", {
                        "hallazgo_id": h["id"],
                        "motivo": f"Corregir {h['regla_id']} exige cambios que el simulador no sabe hacer con seguridad."}))
            return Respuesta(bloques, "tool_use", _tokens(tarea), 40 * len(bloques))
        # turnos siguientes: lo que la guarda rechazó pasa a revisión manual
        ultimo = mensajes[-1]["content"]
        rechazados = [r for r in ultimo if isinstance(r, dict) and r.get("is_error") and "RECHAZADO" in r["content"]]
        if rechazados and turno == 1:
            pedidos = {b["id"]: b for b in mensajes[-2]["content"] if b["type"] == "tool_use"}
            bloques = [_uso(100 + i, "marcar_revision_manual", {
                "hallazgo_id": pedidos[r["tool_use_id"]]["input"]["hallazgo_id"],
                "motivo": "La guarda rechazó el parche automático: " + r["content"][:200]})
                for i, r in enumerate(rechazados)]
            return Respuesta(bloques, "tool_use", 200, 60)
        return Respuesta([{"type": "text", "text": "[simulado] Revisión terminada: parches propuestos y casos "
                                                   "derivados a revisión humana."}], "end_turn", 300, 30)


def _uso(n: int, nombre: str, entrada: dict) -> dict:
    return {"type": "tool_use", "id": f"toolu_mock_{n:03d}", "name": nombre, "input": entrada}


def _tokens(texto: str) -> int:
    return max(1, len(texto) // 4)  # aproximación: ~4 caracteres por token
