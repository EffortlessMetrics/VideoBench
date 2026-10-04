from __future__ import annotations

from videobench.schemas import SCHEMA_MODELS, export_schemas


def test_all_public_schemas_export(tmp_path) -> None:
    paths = export_schemas(tmp_path)
    assert len(paths) == len(SCHEMA_MODELS)
    assert all(path.read_text(encoding="utf-8").startswith("{") for path in paths)
