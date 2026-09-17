"""Shared test fixtures.

The corpus lives in the reference clone, which is read-only and sits beside
this repo. Its location can be overridden with ARCHEAN_DATA_ROOT.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_DATA_ROOT = REPO_ROOT.parent / "engineering-challenges"
CHALLENGE_ROOT = Path(
    os.environ.get("ARCHEAN_CHALLENGE_ROOT", DEFAULT_DATA_ROOT)
).resolve()

SIREN = "480489707"


def _require(path: Path, what: str) -> Path:
    if not path.exists():
        pytest.skip(
            f"{what} not found at {path}. These tests read the challenge "
            f"corpus, which is not vendored into this repo. Clone "
            f"github.com/takeovers-ai/engineering-challenges beside this "
            f"repo, or set ARCHEAN_CHALLENGE_ROOT."
        )
    return path


@pytest.fixture(scope="session")
def challenge_root() -> Path:
    return _require(CHALLENGE_ROOT, "challenge repo")


@pytest.fixture(scope="session")
def actes_root(challenge_root: Path) -> Path:
    return _require(challenge_root / "data" / SIREN / "actes", "actes corpus")


@pytest.fixture(scope="session")
def bbox_viewer_path(challenge_root: Path) -> Path:
    return _require(
        challenge_root / "tools" / "bbox_viewer.py", "bbox_viewer.py"
    )


@pytest.fixture(scope="session")
def reference_polygon_to_norm(bbox_viewer_path: Path):
    """The challenge's own conversion, imported as the reference behaviour."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_bbox_viewer_reference", bbox_viewer_path
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.polygon_to_norm


def pdf_for(actes_root: Path, inpi_id: str) -> Path:
    hits = sorted(actes_root.glob(f"pdf/*{inpi_id}.pdf"))
    if not hits:
        raise FileNotFoundError(f"no PDF for {inpi_id} under {actes_root}")
    return hits[0]


def ocr_for(actes_root: Path, inpi_id: str) -> Path:
    return actes_root / "ocr" / inpi_id
