from pathlib import Path

import pytest

DATA = Path(__file__).parent / "data"


@pytest.fixture
def data_dir() -> Path:
    return DATA


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Nunca ler/gravar o "meu padrão" real do usuário durante os testes."""
    cfg = tmp_path / "config"
    monkeypatch.setenv("JABUTI_CONFIG_DIR", str(cfg))
    return cfg
