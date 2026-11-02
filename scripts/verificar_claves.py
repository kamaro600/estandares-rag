"""Prueba de humo contra los proveedores REALES configurados en .env (gasta unos centavos).
Las pruebas de pytest nunca llaman a un proveedor real.

Uso:   python -m scripts.verificar_claves

Verifica: las claves funcionan, el modelo de embeddings devuelve la dimensión esperada y el LLM responde JSON con el
esquema estricto. Muestra latencia y tokens para registrarlos en el análisis técnico.
"""
from __future__ import annotations

import sys
import time

from app.config import ConfigError, Settings
from app.embeddings import EmbeddingError, crear_embedder
from app.llm import ESQUEMA_RESPUESTA, LLMError, crear_llm


def main() -> None:
    s = Settings()
    s.validar()
    t0 = time.perf_counter()
    embedder = crear_embedder(s)
    m = embedder.embed(["¿Cómo se nombran los procedimientos almacenados?"])
    print(f"Embeddings OK: {embedder.nombre} · {m.shape[1]} dimensiones · {time.perf_counter() - t0:.2f} s")
    t0 = time.perf_counter()
    r = crear_llm(s).generar("Responde en español en una frase usando solo 'estandares'. Cita el id usado.",
                             {"estandares": [{"id": "WEB-BD-005",
                                              "texto": "Los procedimientos se nombran usp_<Entidad>_<Accion>."}],
                              "pregunta": "¿Cómo nombro un procedimiento?"}, ESQUEMA_RESPUESTA, "respuesta")
    print(f"LLM OK: {s.llm_provider} · {r.modelo} · {time.perf_counter() - t0:.2f} s · tokens {r.input_tokens} "
          f"entrada / {r.output_tokens} salida\n  → {r.datos}")


if __name__ == "__main__":
    try:
        main()
    except (ConfigError, EmbeddingError, LLMError) as e:
        sys.exit(f"Error: {e}")
