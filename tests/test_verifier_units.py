from __future__ import annotations

import json
from pathlib import Path

from videobench.contracts import ObjectiveCheckSpec
from videobench.types import CheckStatus
from videobench.verifier import evaluate_check


def test_verifier_json_membership_and_missing_path(tmp_path: Path) -> None:
    (tmp_path / "state.json").write_text(json.dumps({"value": 2}), encoding="utf-8")
    included = ObjectiveCheckSpec(
        check_id="in",
        check_type="json_path_in",
        description="membership",
        artifact_path="state.json",
        json_path="value",
        expected=[1, 2, 3],
        reason_code="not_in",
    )
    missing = ObjectiveCheckSpec(
        check_id="missing",
        check_type="json_path_equals",
        description="missing path",
        artifact_path="state.json",
        json_path="unknown",
        expected=1,
        reason_code="missing",
    )
    assert evaluate_check(included, tmp_path).status == CheckStatus.PASS
    assert evaluate_check(missing, tmp_path).status == CheckStatus.INSTRUMENT_FAILURE


def test_verifier_file_hash_and_missing_artifact(tmp_path: Path) -> None:
    check = ObjectiveCheckSpec(
        check_id="hash",
        check_type="file_sha256_equals",
        description="hash",
        artifact_path="missing.bin",
        expected="0" * 64,
        reason_code="hash",
    )
    assert evaluate_check(check, tmp_path).status == CheckStatus.NOT_OBSERVABLE
