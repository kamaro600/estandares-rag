"""Reglas de higiene que evitan fallas silenciosas en Windows."""
import os
import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).parent.parent
FUENTES = sorted([*RAIZ.glob("agente/**/*.py"), *RAIZ.glob("eval/*.py"), *RAIZ.glob("scripts/*.py")])


def test_toda_lectura_y_escritura_declara_encoding():
    for f in FUENTES:
        for n, linea in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\.(read_text|write_text)\(|\bopen\(", linea) and "encoding=" not in linea \
                    and "read_bytes" not in linea and "np.load" not in linea:
                raise AssertionError(f"{f.name}:{n} sin encoding=: {linea.strip()}")


def test_salida_redirigida_en_utf8_aunque_windows_diga_cp1252():
    """Windows redirige en cp1252: sin consola_segura, '→' hace caer la ingesta y '·' rompe a quien lee UTF-8."""
    # Las variables de aislamiento de conftest (simulador, embeddings hash, rutas temporales) viajan al subproceso:
    # sin ellas leería el .env del desarrollador (que puede decir openai) y escribiría en data/.
    aislamiento = {k: os.environ[k] for k in ("EMBEDDINGS_PROVIDER", "RAG_MIN_SCORE", "CATALOGO_PATH", "SECCIONES_PATH",
                                               "INDICE_PATH", "SALIDA_DIR", "DB_PATH", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")}
    entorno = {"PYTHONIOENCODING": "cp1252", "PATH": "", "SYSTEMROOT": "", "LLM_PROVIDER": "mock", **aislamiento}
    salidas = []
    for comando in (["-m", "agente.ingesta"], ["-m", "agente", "regla", "SEG-AUT-002"],
                    ["-m", "agente", "revisar", "ejemplos/bd/ventas_nueva.sql", "--sin-llm"]):
        r = subprocess.run([sys.executable, *comando], cwd=RAIZ, capture_output=True, env=entorno)
        assert r.returncode in (0, 1), r.stderr.decode("utf-8", "replace")
        salidas.append(r.stdout.decode("utf-8"))   # falla con UnicodeDecodeError si salió en cp1252
    assert "→" in salidas[0] and "§5.2" in salidas[1] and " · " in salidas[2]


def test_archivos_para_docker_con_lf():
    for nombre in ("Dockerfile", "docker-compose.yml", "prometheus/prometheus.yml"):
        assert b"\r\n" not in (RAIZ / nombre).read_bytes(), nombre
