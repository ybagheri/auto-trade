from __future__ import annotations

import os
from pathlib import Path

import pytest

from auto_trade.infrastructure.configuration.env_file import (
    EnvFileError,
    load_env_file,
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name.startswith("AUTO_TRADE_"):
            monkeypatch.delenv(name, raising=False)


def read(path: Path) -> dict[str, str]:
    load_env_file(path)
    return {key: value for key, value in os.environ.items() if key.startswith("AUTO_TRADE_")}


def test_parses_simple_assignments(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("AUTO_TRADE_ONE=1\nAUTO_TRADE_TWO=two\n", encoding="utf-8")

    assert read(path) == {"AUTO_TRADE_ONE": "1", "AUTO_TRADE_TWO": "two"}


def test_ignores_comments_and_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("# a comment\n\nAUTO_TRADE_ONE=1\n   \n#another\n", encoding="utf-8")

    assert read(path) == {"AUTO_TRADE_ONE": "1"}


def test_supports_export_prefix(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("export AUTO_TRADE_ONE=1\n", encoding="utf-8")

    assert read(path) == {"AUTO_TRADE_ONE": "1"}


def test_unquoted_windows_paths_collapse_escaped_separators(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("AUTO_TRADE_PATH=C:\\\\Users\\\\demo\\\\Terminal\\\\ABC\n", encoding="utf-8")

    assert read(path)["AUTO_TRADE_PATH"] == r"C:\Users\demo\Terminal\ABC"


def test_double_quoted_value_is_taken_literally(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text('AUTO_TRADE_PATH="C:\\Users\\demo"\n', encoding="utf-8")

    assert read(path)["AUTO_TRADE_PATH"] == r"C:\Users\demo"


def test_single_quoted_value_is_taken_literally(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("AUTO_TRADE_ONE='1'\n", encoding="utf-8")

    assert read(path)["AUTO_TRADE_ONE"] == "1"


def test_value_may_contain_an_equals_sign(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("AUTO_TRADE_ONE=a=b=c\n", encoding="utf-8")

    assert read(path)["AUTO_TRADE_ONE"] == "a=b=c"


def test_existing_environment_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTO_TRADE_ONE", "from-environment")
    path = tmp_path / ".env"
    path.write_text("AUTO_TRADE_ONE=from-file\n", encoding="utf-8")

    assert read(path)["AUTO_TRADE_ONE"] == "from-environment"


def test_missing_file_is_not_an_error(tmp_path: Path) -> None:
    assert load_env_file(tmp_path / "absent.env") is None
    assert read(tmp_path / "absent.env") == {}


@pytest.mark.parametrize("line", ["NOEQUALS", "=novalue", "1BAD=x", "has space=x"])
def test_malformed_lines_are_rejected(tmp_path: Path, line: str) -> None:
    path = tmp_path / ".env"
    path.write_text(line + "\n", encoding="utf-8")

    with pytest.raises(EnvFileError):
        load_env_file(path)


def test_error_reports_the_line_number(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("AUTO_TRADE_ONE=1\nBROKEN\n", encoding="utf-8")

    with pytest.raises(EnvFileError, match=r":2"):
        load_env_file(path)


def test_explicit_env_file_override_is_honoured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "custom.env"
    path.write_text("AUTO_TRADE_ONE=from-override\n", encoding="utf-8")
    monkeypatch.setenv("AUTO_TRADE_ENV_FILE", str(path))

    assert load_env_file() == path
    assert read(path)["AUTO_TRADE_ONE"] == "from-override"
