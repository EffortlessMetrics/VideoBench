"""One-time VideoBench migration; executed only on its dedicated branch."""
from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import tomllib

ROOT = Path.cwd()
OUT = Path(os.environ['RUNNER_TEMP']) / 'astral-migration'
OUT.mkdir()
BASE = os.environ['GITHUB_SHA']
EXPECTED = {
    'pyproject.toml': 'f1faf9163f593f52858759eab3a577f94f1f0d03',
    'scripts/check.py': 'c17cde96314f3c56e5813b4b75b36d8e2541fae4',
    '.github/workflows/ci.yml': '29d7328955eb6a7438c95248795c6e259488bbba',
    '.pre-commit-config.yaml': '40d6c4fd1833a2fee9699d7f1d3205d3a4526d91',
    'AGENTS.md': 'e3a9ddb91b61967fd88aa04cb6e14c55ddbf5a09',
    'CONTRIBUTING.md': 'ddb21e65cb6b768d30349e767494d4b6dd9cbab9',
    'README.md': '4c475fdd8f619f9a640f71ffc168f80b6421ebe6',
}
for filename, expected in EXPECTED.items():
    data = Path(filename).read_bytes()
    digest = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
    if digest != expected:
        raise SystemExit(f'Source moved: {filename}; expected {expected}, observed {digest}')


def replace(filename: str, old: str, new: str, count: int = 1) -> None:
    path = Path(filename)
    text = path.read_text()
    if text.count(old) != count:
        raise SystemExit(f'Unexpected replacement count: {filename}: {old!r}')
    path.write_text(text.replace(old, new))


replace('pyproject.toml', 'requires = ["hatchling>=1.26"]\nbuild-backend = "hatchling.build"',
        'requires = ["uv_build==0.13.4"]\nbuild-backend = "uv_build"')
replace('pyproject.toml', '"ruff>=0.9",', '"ruff==0.17.1",\n  "ty==0.0.90",')
replace('pyproject.toml', '[tool.hatch.build.targets.wheel]\npackages = ["src/videobench"]',
        '[tool.uv]\nrequired-version = "==0.13.4"\n\n[tool.uv.build-backend]\nmodule-name = "videobench"\nsource-include = ["tests/**", "scripts/**", "contracts/**", "docs/**", "examples/**", "AGENTS.md", "ARCHITECTURE.md", "CONTRIBUTING.md", "CHANGELOG.md", "NOTICE", "CITATION.cff"]')
replace('scripts/check.py', '    run(sys.executable, "-m", "mypy", "src/videobench")',
        '    run(str(Path(sys.executable).with_name("ty.exe" if os.name == "nt" else "ty")),\n        "check", "--error-on-warning", "--python-version", "3.11", "src/videobench", "tests", "scripts")\n    # Retain strict mypy until its additional obligations have a proven replacement.\n    run(sys.executable, "-m", "mypy", "src/videobench")')
replace('.pre-commit-config.yaml',
        '  - repo: https://github.com/astral-sh/ruff-pre-commit\n    rev: v0.9.10\n    hooks:\n      - id: ruff\n        args: [--fix]\n      - id: ruff-format',
        '  - repo: local\n    hooks:\n      - id: ruff\n        name: Ruff (locked environment)\n        entry: uv run --locked --no-sync ruff check --fix\n        language: system\n        types_or: [python, pyi]\n      - id: ruff-format\n        name: Ruff format (locked environment)\n        entry: uv run --locked --no-sync ruff format\n        language: system\n        types_or: [python, pyi]')
replace('CONTRIBUTING.md', 'python -m venv .venv\n# activate the environment\npython -m pip install -e ".[dev]"\npython scripts/check.py',
        'uv sync --locked --extra dev\nuv run --locked --no-sync python scripts/check.py')
replace('CONTRIBUTING.md', '`python scripts/check.py` rejects schema drift.',
        '`uv run --locked --no-sync python scripts/check.py` rejects schema drift.\n\nThe manifest pins uv, Ruff, and ty; `uv.lock` owns resolved dependencies. Update the lock with `uv lock`, then verify `uv lock --check`. The strict mypy check remains a blocking companion until its additional obligations have a proven replacement; ty is required, not advisory.')
replace('README.md', 'python -m venv .venv\n# Windows PowerShell: .venv\\Scripts\\Activate.ps1\n# macOS/Linux: source .venv/bin/activate\npython -m pip install -e ".[dev]"\n\nvideobench demo --root . --out .videobench/demo',
        'uv sync --locked --extra dev\nuv run --locked --no-sync videobench demo --root . --out .videobench/demo')
replace('README.md', 'python scripts/check.py', 'uv run --locked --no-sync python scripts/check.py')
replace('AGENTS.md', 'python -m pytest tests/path_or_test.py\npython -m ruff check src tests\npython -m mypy src/videobench',
        'uv run --locked --no-sync pytest tests/path_or_test.py\nuv run --locked --no-sync ruff check src tests\nuv run --locked --no-sync ty check --error-on-warning src/videobench tests scripts\nuv run --locked --no-sync mypy src/videobench')
replace('AGENTS.md', 'python scripts/check.py', 'uv run --locked --no-sync python scripts/check.py')
ci = Path('.github/workflows/ci.yml')
text = ci.read_text()
text = text.replace('      - uses: actions/checkout@v4', '      - uses: actions/checkout@08eba0b27e820071cde6df949e0beb9ba4906955\n        with:\n          persist-credentials: false')
old = '      - uses: actions/setup-python@v5\n        with:\n          python-version: ${{ matrix.python-version }}\n          cache: pip\n      - name: Install\n        run: python -m pip install --upgrade pip && python -m pip install -e ".[dev]"\n      - name: Verify\n        run: python scripts/check.py'
new = '      - uses: astral-sh/setup-uv@d0cc045d04ccac9d8b7881df0226f9e82c39688e\n        with:\n          version: "0.13.4"\n          enable-cache: false\n      - name: Install locked environment\n        env:\n          UV_PYTHON: ${{ matrix.python-version }}\n        run: |\n          test -f uv.lock\n          uv lock --check\n          uv sync --locked --extra dev\n      - name: Verify\n        env:\n          UV_PYTHON: ${{ matrix.python-version }}\n        run: uv run --locked --no-sync python scripts/check.py'
if text.count(old) != 1:
    raise SystemExit('Unexpected CI source')
ci.write_text(text.replace(old, new))
tomllib.loads(Path('pyproject.toml').read_text())

# The one-shot generator and its trigger are not part of the resulting project.
Path('.github/workflows/prepare-astral-migration.yml').unlink()
Path('.github/maintenance/prepare_astral.py').unlink()
results: list[dict[str, object]] = []


def run(name: str, command: list[str], cwd: Path = ROOT) -> bool:
    with (OUT / f'{name}.log').open('w') as log:
        result = subprocess.run(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, check=False)
    results.append({'name': name, 'command': command, 'exit_code': result.returncode})
    print(f'{name}: {result.returncode}', flush=True)
    return result.returncode == 0


ok = run('uv-version', ['uv', '--version'])
ok = run('lock', ['uv', 'lock', '--python', '3.11.16']) and ok
ok = run('sync', ['uv', 'sync', '--locked', '--extra', 'dev', '--python', '3.11.16']) and ok
if ok:
    paths = [p for root in ('src', 'tests', 'scripts') for p in Path(root).rglob('*.py')]
    before = {str(p): ast.dump(ast.parse(p.read_text()), include_attributes=False) for p in paths}
    ok = run('format', ['uv', 'run', '--no-sync', 'ruff', 'format', '.']) and ok
    if any(ast.dump(ast.parse(p.read_text()), include_attributes=False) != before[str(p)] for p in paths):
        raise SystemExit('Formatter altered a Python AST')
    verified = run('verify', ['uv', 'run', '--no-sync', 'python', 'scripts/check.py'])
    ok = verified and ok
    if not verified:
        # Diagnostic only: failure remains failure; expose checks the aggregate did not reach.
        run('ty', ['uv', 'run', '--no-sync', 'ty', 'check', '--error-on-warning', '--python-version', '3.11', 'src/videobench', 'tests', 'scripts'])
        run('mypy', ['uv', 'run', '--no-sync', 'mypy', 'src/videobench'])
        run('pytest', ['uv', 'run', '--no-sync', 'pytest', '--cov=videobench', '--cov-branch', '--cov-report=term-missing', '-q'])
    ok = run('build', ['uv', 'build', '--locked', '--out-dir', str(OUT / 'dist')]) and ok
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        good = folder / 'good.py'
        bad = folder / 'bad.py'
        config = folder / 'ty.toml'
        config.write_text('[environment]\npython-version = "3.11"\n')
        good.write_text('value: int = 1\n')
        bad.write_text('value: int = "not an integer"\n')
        prefix = ['uv', 'run', '--no-sync', 'ty', 'check', '--error-on-warning', '--config-file', str(config)]
        good_ok = run('ty-positive', prefix + [str(good)])
        bad_ok = run('ty-negative', prefix + [str(bad)])
        negative = results[-1]
        diagnostic = (OUT / 'ty-negative.log').read_text()
        negative_proven = not bad_ok and negative['exit_code'] == 1 and 'invalid-assignment' in diagnostic
        results.append({'name': 'type-negative-control', 'passed': negative_proven})
        ok = good_ok and negative_proven and ok
    ok = run('lock-check', ['uv', 'lock', '--check']) and ok
    wheels = list((OUT / 'dist').glob('*.whl'))
    if len(wheels) != 1:
        ok = False
    else:
        with tempfile.TemporaryDirectory() as directory:
            consumer = Path(directory)
            environment = consumer / 'venv'
            created = run('consumer-venv', ['uv', 'venv', '--python', '3.11.16', str(environment)], cwd=consumer)
            if created:
                python = environment / 'bin' / 'python'
                installed = run('consumer-install', ['uv', 'pip', 'install', '--python', str(python), str(wheels[0])], cwd=consumer)
                ok = installed and ok
                if installed:
                    ok = run('consumer-cli', [str(python), '-m', 'videobench.cli', '--help'], cwd=consumer) and ok
            else:
                ok = False

# Artifacts survive failed qualification, but failure never authorizes a commit.
if Path('uv.lock').exists():
    subprocess.run(['git', 'add', '--intent-to-add', 'uv.lock'], check=True)
patch = subprocess.check_output(['git', 'diff', '--binary', 'HEAD'])
(OUT / 'candidate.patch').write_bytes(patch)
(OUT / 'receipt.json').write_text(json.dumps({'input_head': BASE, 'qualified': ok, 'results': results, 'patch_sha256': hashlib.sha256(patch).hexdigest()}, indent=2) + '\n')
raise SystemExit(0 if ok else 1)
