"""Kiểm tra vệ sinh repo: không có bí mật / file rác được theo dõi bởi git."""

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Mẫu key thật (Google API key, khối hex 32 ký tự của WeatherAPI gán cho *KEY*)
SECRET_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"(?i)(api[_-]?key|token|secret)\s*[:=]\s*[\"']?[0-9a-f]{32}[\"']?\b"),
]


def tracked_files():
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.splitlines()
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("không phải git checkout")
    return [ROOT / f for f in out if (ROOT / f).is_file()]


def test_no_env_files_or_os_artifacts_tracked():
    for f in tracked_files():
        is_env = f.name == ".env" or (f.name.startswith(".env.") and f.name != ".env.example")
        assert not is_env, f
        assert f.name != ".DS_Store", f


def test_no_secret_like_strings_in_tracked_text_files():
    for f in tracked_files():
        if f.suffix in {".lock", ".png", ".jpg", ".pdf"}:
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for pat in SECRET_PATTERNS:
            assert not pat.search(text), f"có vẻ chứa bí mật: {f.relative_to(ROOT)}"


def test_registry_json_parses():
    json.loads((ROOT / "03-production" / "registry.json").read_text(encoding="utf-8"))
