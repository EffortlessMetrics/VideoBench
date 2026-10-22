"""Apply the source-reviewed repairs to the one-shot candidate generator."""
from pathlib import Path
p = Path('.github/maintenance/prepare_astral.py')
s = p.read_text()
def edit(old: str, new: str) -> None:
    global s
    assert s.count(old) == 1, old
    s = s.replace(old, new)
repairs = r'''
replace('src/videobench/runner.py', ') -> tuple[list[dict[str, float | int]], list[str]]:', ') -> tuple[list[dict[str, str | float | int]], list[str]]:')
replace('src/videobench/verifier.py', '    CheckResult,', '    CheckResult,\n    CheckType,')
replace('src/videobench/verifier.py', '            expected = str(check.expected)\n            return _result(\n                check,\n                CheckStatus.PASS if expected in text else CheckStatus.FAIL,\n                actual=expected in text,', '            expected_text = str(check.expected)\n            return _result(\n                check,\n                CheckStatus.PASS if expected_text in text else CheckStatus.FAIL,\n                actual=expected_text in text,')
replace('src/videobench/verifier.py', '            check_type="file_sha256_equals",', '            check_type=CheckType.FILE_SHA256_EQUALS,')
replace('tests/test_judge.py', 'from videobench.judge import qualify_judge, validate_judge_stack', 'from videobench.judge import qualify_judge, validate_judge_stack\nfrom videobench.types import JudgmentVerdict')
replace('tests/test_judge.py', '    run.observations[0].verdict = "reject"', '    run.observations[0].verdict = JudgmentVerdict.REJECT')
replace('src/videobench/runner.py', 'from pathlib import Path', 'from contextlib import suppress\nfrom pathlib import Path')
replace('src/videobench/runner.py', '        try:\n            excluded.append(usage_path.resolve().relative_to(output_dir.resolve()).as_posix())\n        except ValueError:\n            pass', '        with suppress(ValueError):\n            excluded.append(usage_path.resolve().relative_to(output_dir.resolve()).as_posix())')
with Path('pyproject.toml').open('a') as file:
    file.write('\n[tool.ruff.lint.per-file-ignores]\n# Preserve the existing str(Enum) API, pinned by test_enum_rendering.py.\n# Remove these two exceptions only with an intentional enum-rendering API migration.\n"src/videobench/contracts.py" = ["UP042"]\n"src/videobench/types.py" = ["UP042"]\n')
Path('tests/test_enum_rendering.py').write_text('from enum import Enum\nimport json\n\nfrom videobench import contracts, types\n\n\ndef test_existing_enum_string_and_json_contracts() -> None:\n    checked = 0\n    for module in (contracts, types):\n        for value in vars(module).values():\n            if isinstance(value, type) and issubclass(value, Enum) and value.__module__ == module.__name__:\n                for member in value:\n                    assert str(member) == f"{value.__name__}.{member.name}"\n                    assert json.dumps(member) == json.dumps(member.value)\n                    checked += 1\n    assert checked > 0\n')
'''
edit("tomllib.loads(Path('pyproject.toml').read_text())", repairs + "\ntomllib.loads(Path('pyproject.toml').read_text())")
edit("    'README.md': '4c475fdd8f619f9a640f71ffc168f80b6421ebe6',", "    'README.md': '4c475fdd8f619f9a640f71ffc168f80b6421ebe6',\n    'src/videobench/runner.py': 'bfc314c987e4cd83cbfd4a6cac2f309c7b9cb0d6',\n    'src/videobench/verifier.py': '5aac12eb63c7cd00f2c6a6f88684b87e890831d8',\n    'tests/test_judge.py': '64dc0e755f1f01b0cd26603e7ec3fba54072fd36',")
edit("Path('.github/maintenance/prepare_astral.py').unlink()", "Path('.github/maintenance/prepare_astral.py').unlink()\nPath('.github/maintenance/repair_astral.py').unlink()")
edit('    paths = [p for root', "    ok = run('reviewed-lint-repairs', ['uv', 'run', '--no-sync', 'ruff', 'check', '--select', 'I,SIM114', '--fix', '.']) and ok\n    paths = [p for root")
edit("['uv', 'build', '--locked', '--out-dir'", "['uv', 'build', '--out-dir'")
edit("    subprocess.run(['git', 'add', '--intent-to-add', 'uv.lock'], check=True)", "    subprocess.run(['git', 'add', '--intent-to-add', 'uv.lock', 'tests/test_enum_rendering.py'], check=True)")
compile(s, str(p), 'exec')
p.write_text(s)
