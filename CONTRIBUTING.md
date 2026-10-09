# Contributing

Human and AI-assisted or agent-authored contributions are welcome. The same review and quality requirements apply to everyone.

## Keep the scope small

shardcheck checks offline artifact completeness and byte integrity against sidecars, with explicit per-shard observed-attempt selection. It does not prove passing tests, authenticated provenance, or the existence of attempts whose sidecars were never downloaded. Preserve those boundaries and the standard-library-only runtime. Discuss substantial scope changes before implementing them.

## A useful change includes

- A clear description of the problem and intended behavior, with a minimal reproduction when reporting a bug.
- Regression tests for behavior changes, including relevant failure and security cases.
- Commands actually run and their results. Distinguish passed, failed, and untested checks; never fabricate execution, screenshots, benchmarks, or other evidence.
- Updated documentation when the CLI, schemas, or limitations change.

From a checkout:

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
python -m pip install .
shardcheck --version
```

Review generated code and documentation before submitting. Disclosing Codex or other tools is optional unless a maintainer asks for details needed to understand or reproduce the change. Tool use does not replace responsibility for correctness.

## Licensing and safety

Submit only code and material you have the right to contribute under this repository's MIT license. Attribute relevant sources and respect their licenses; do not copy incompatible code. Never include credentials, tokens, private artifacts, or personal data in issues, tests, logs, or pull requests. Use synthetic fixtures. Follow [SECURITY.md](SECURITY.md) for security concerns and avoid posting sensitive exploit details publicly.

Prefer focused pull requests with a short explanation of why the change helps. No contributor identity branding or special agent formatting is required.
