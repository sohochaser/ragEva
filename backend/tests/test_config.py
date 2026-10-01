from pathlib import Path

import pytest

from backend.config import Settings


def test_defaults_are_local(tmp_path: Path) -> None:
    settings = Settings.from_env({"RAGEVA_DATA_DIR": str(tmp_path)})
    assert settings.api_host == "127.0.0.1"
    assert settings.api_port == 8000
    assert settings.data_dir == tmp_path


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("RAGEVA_API_HOST", " "),
        ("RAGEVA_API_PORT", "zero"),
        ("RAGEVA_API_PORT", "65536"),
        ("RAGEVA_HEARTBEAT_INTERVAL", "0"),
        ("RAGEVA_WORKER_STALE_AFTER", "-1"),
    ],
)
def test_invalid_configuration_is_rejected(name: str, value: str) -> None:
    with pytest.raises(ValueError, match=name):
        Settings.from_env({name: value})
