# Releasing

How a version gets cut. Written down so it doesn't depend on anyone remembering.

## Before you tag

```sh
# contract + round-trip tests, and the one-command self check
for t in tests/test_*.py; do python3 "$t"; done
python3 scripts/selfcheck.py
```

## 1. Bump the version — both places

| File | Field |
|---|---|
| `pyproject.toml` | `version = "x.y.z"` |
| `session_tape/__init__.py` | `__version__ = "x.y.z"` |

## 2. Build

```sh
rm -rf dist build
python3 -m venv /tmp/buildenv && /tmp/buildenv/bin/pip install -q build
/tmp/buildenv/bin/python -m build
```

Three things that will bite you if you skip them:

1. **A `build/` directory in the repo shadows the `build` module** — `python3 -m build` fails
   with `No module named build.__main__`. Always `rm -rf build dist` first.
2. **`uv build` resolves optional dependencies**, so it fails when one of them isn't on PyPI.
   Use a throwaway venv instead.
3. **Don't use deprecated metadata forms.** `license = { text = "MIT" }` and the
   `"License :: OSI Approved :: ..."` classifier both warn; use PEP 639:
   ```toml
   license = "MIT"
   license-files = ["LICENSE"]
   ```

## 3. Verify the artifacts, not the page

```sh
python3 -m venv /tmp/check && /tmp/check/bin/pip install dist/*.whl
/tmp/check/bin/session-tape --version
cd /tmp && /tmp/check/bin/session-tape demo
```

## 4. Tag and publish

```sh
git tag -a vx.y.z -m "x.y.z"
git push origin main && git push origin vx.y.z

python3 -m twine upload dist/*
```

Then check that it *installs*, not that it *uploaded*:

```sh
pip download session-tape==x.y.z -d /tmp/pypi-check --no-deps
```

The `https://pypi.org/pypi/<name>/json` "latest" endpoint is CDN-cached — if it still shows
the old version, query the version endpoint (`…/pypi/<name>/x.y.z/json`) before assuming the
upload failed.

## 5. What the PyPI page needs (it's the first impression)

- **`project_urls`** — without a repository link, people can't find the source at all;
- **`classifiers`** — an empty list means no license and no language shown;
- **image URLs in the long description must be absolute** — relative paths render as broken
  images on PyPI (they're fine on GitHub).

## 6. After publishing

- Confirm the About text and topics still describe what the project is;
- Version badges follow the tag automatically — nothing to edit;
- Release notes, if you write them, describe **what changed for users**, not how it was made.
