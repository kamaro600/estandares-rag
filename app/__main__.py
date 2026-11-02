"""python -m app  →  http://127.0.0.1:8000

Escucha solo en 127.0.0.1 (no expuesto a la red). Para que Prometheus en Docker lo lea, usa HOST=0.0.0.0.
"""
import logging
import os
import sys

import uvicorn

from app.config import ConfigError, Settings
from app.rag import IndiceError

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        Settings().validar()
    except ConfigError as e:
        sys.exit(f"Configuración: {e}")
    try:
        uvicorn.run("app.main:app", host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")))
    except IndiceError as e:
        sys.exit(f"Índice: {e}")
