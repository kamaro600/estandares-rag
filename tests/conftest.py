"""Las pruebas nunca llaman a una API real: fuerzan el simulador antes de importar nada."""
import os

os.environ["LLM_PROVIDER"] = "mock"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("OPENAI_API_KEY", None)
os.environ["EMBEDDINGS_PROVIDER"] = "hash"
os.environ["RAG_MIN_SCORE"] = "0.08"
os.environ["TIPO_APP"] = "web"
os.environ["MODO_BD"] = "nueva"
