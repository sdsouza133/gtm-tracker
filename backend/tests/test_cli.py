import io
import json
from pathlib import Path

import pytest
from argon2 import PasswordHasher

from app import cli


def test_hash_password_reads_stdin(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("a long enough password\n"))
    assert cli.main(["cli", "hash-password"]) == 0
    assert PasswordHasher().verify(capsys.readouterr().out.strip(), "a long enough password")


def test_hash_password_refuses_short_ones(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("short\n"))
    assert cli.main(["cli", "hash-password"]) == 1


def test_openapi_writes_the_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert cli.main(["cli", "openapi"]) == 0
    schema = json.loads((tmp_path / "openapi.json").read_text())
    assert "/api/auth/login" in schema["paths"]


def test_unknown_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["cli"]) == 2
    assert "hash-password" in capsys.readouterr().out
