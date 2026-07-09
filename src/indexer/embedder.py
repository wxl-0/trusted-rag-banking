import os
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = "BAAI/bge-large-zh-v1.5"
VECTOR_DIM = 1024


class Embedder:
    def __init__(self):
        model_name = os.environ.get("EMBED_MODEL", DEFAULT_MODEL)
        self.model = SentenceTransformer(model_name)
        self.dim = VECTOR_DIM

    def embed(self, text: str) -> list:
        return self.model.encode(text, normalize_embeddings=True).tolist()

    def embed_batch(self, texts: list) -> list:
        embeddings = self.model.encode(texts, normalize_embeddings=True, batch_size=64)
        return [e.tolist() for e in embeddings]
