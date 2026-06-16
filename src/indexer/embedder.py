import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()


class Embedder:
    def __init__(self):
        self.client = OpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )
        self.model = os.environ.get("EMBED_MODEL", "text-embedding-3-small")

    def embed(self, text: str) -> list:
        response = self.client.embeddings.create(input=text, model=self.model)
        return response.data[0].embedding

    def embed_batch(self, texts: list) -> list:
        response = self.client.embeddings.create(input=texts, model=self.model)
        return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]
