import os
from pathlib import Path
import subprocess
import sys


def test_reranker_loads_dotenv_before_model_library(tmp_path):
    dotenv_package = tmp_path / "dotenv"
    dotenv_package.mkdir()
    (dotenv_package / "__init__.py").write_text(
        "import os\n"
        "def load_dotenv():\n"
        "    os.environ['HF_HOME'] = 'D:/expected-cache'\n",
        encoding="utf-8",
    )
    sentence_package = tmp_path / "sentence_transformers"
    sentence_package.mkdir()
    (sentence_package / "__init__.py").write_text(
        "import os\n"
        "print(os.environ.get('HF_HOME', 'MISSING'))\n"
        "class CrossEncoder:\n"
        "    pass\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.pop("HF_HOME", None)
    repo_root = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = os.pathsep.join([str(tmp_path), str(repo_root)])

    result = subprocess.run(
        [sys.executable, "-c", "import src.retriever.reranker"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "D:/expected-cache"


def test_embedder_loads_dotenv_before_model_library(tmp_path):
    dotenv_package = tmp_path / "dotenv"
    dotenv_package.mkdir()
    (dotenv_package / "__init__.py").write_text(
        "import os\n"
        "def load_dotenv():\n"
        "    os.environ['HF_HOME'] = 'D:/expected-cache'\n",
        encoding="utf-8",
    )
    sentence_package = tmp_path / "sentence_transformers"
    sentence_package.mkdir()
    (sentence_package / "__init__.py").write_text(
        "import os\n"
        "print(os.environ.get('HF_HOME', 'MISSING'))\n"
        "class SentenceTransformer:\n"
        "    pass\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.pop("HF_HOME", None)
    repo_root = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = os.pathsep.join([str(tmp_path), str(repo_root)])

    result = subprocess.run(
        [sys.executable, "-c", "import src.indexer.embedder"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "D:/expected-cache"
