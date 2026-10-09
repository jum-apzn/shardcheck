# shardcheck

An offline preflight for CI shard artifacts. Before merging reports, check that every expected shard has a recorded artifact, select the highest **observed** attempt per shard, and verify its file sizes and SHA-256 hashes.

Python 3.10+, standard-library runtime, MIT. Original implementation. No service, network access, report parser, or test runner.

> **Complete does not mean tests passed.** Hashes detect byte changes relative to the sidecar; they do not authenticate who produced it. Selection considers downloaded sidecars only. A newer attempt whose sidecar was never downloaded cannot be detected. See [security boundaries](SECURITY.md).

## Why this small tool?

Partial reruns can leave shard 1 at attempt 1 and shard 2 at attempt 3. Selecting the latest workflow attempt globally can drop shard 1; blindly merging everything can count shard 2 twice. shardcheck applies an explicit per-shard policy before your existing report merger.

This project was inspired by the [Langflow TypeScript CI aggregation workflow](https://github.com/langflow-ai/langflow/blob/main/.github/workflows/typescript_test.yml#L2384-L2517) and [Playwright's sharding documentation](https://playwright.dev/docs/test-sharding). It does not copy their code or claim that completeness checks are new.

Existing tools may fit better: Exevra already provides JUnit missing-shard gates; dorny/test-reporter and EnricoMi/publish-unit-test-result-action publish test results; junitparser reads and merges JUnit XML. shardcheck's narrower scope is an offline, format-agnostic sidecar preflight with explicit observed-attempt selection. It complements report tooling rather than replacing it.

## Install locally

From this repository (no PyPI release assumed):

```sh
python -m pip install .
shardcheck --version
```

Runtime needs no third-party dependencies. Installing from source uses setuptools. To run without installation:

```sh
PYTHONPATH=src python -m shardcheck --help
```

## A complete local example

```sh
mkdir -p demo/downloads/shard-1-attempt-1 demo/downloads/shard-2-attempt-1
printf '{"schema_version":1,"shards":["1","2"]}\n' > demo/expected.json
printf '<testsuite failures="0"/>\n' > demo/downloads/shard-1-attempt-1/result.xml
printf '<testsuite failures="1"/>\n' > demo/downloads/shard-2-attempt-1/result.xml

for shard in 1 2; do
  shardcheck record --root "demo/downloads/shard-$shard-attempt-1" \
    --output artifact.shardcheck.json --run-id run-42 --revision abc123 \
    --shard-id "$shard" --attempt 1 -- result.xml
done

shardcheck check --root demo/downloads --expected demo/expected.json \
  --run-id run-42 --revision abc123
```

Output is only selected paths, relative to `--root`, ordered by shard ID and then file path:

```text
shard-1-attempt-1/result.xml
shard-2-attempt-1/result.xml
```

The second report contains a test failure and still passes the completeness check, intentionally. Your report parser or test job must enforce test success separately.

Use `--format json` for a stable structured result containing `complete`, identity fields, and `selected` entries with `shard_id`, `attempt`, `sidecar`, and `paths`. Paths are data: never evaluate them as shell commands. Prefer JSON-aware consumers; text paths can contain spaces.

### Partial rerun

Create `shard-2-attempt-2/result.xml`, then record it with `--shard-id 2 --attempt 2`. Keep the old artifact directories separate. The check selects shard 1 attempt 1 and shard 2 attempt 2. If the attempt 2 sidecar exists but its file is missing or corrupt, the check fails; it does not fall back to attempt 1.

## Contract and failure policy

- Supply a trusted, explicit, nonempty expected-shard manifest, independent of downloaded artifacts. Do not generate the expected list from whatever happened to download.
- Every `*.shardcheck.json` in the artifact tree must match the exact requested run ID and revision. IDs are opaque, case-sensitive strings; revision should normally be the full commit SHA.
- A shard/attempt pair may occur once. Unexpected shards, missing shards, malformed sidecars, unknown schema fields, duplicate JSON keys, and duplicate paths fail closed.
- Highest observed positive integer attempt wins independently for each expected shard. All sidecars are schema/identity validated; only selected attempts' payloads are hashed. Older payloads can be absent.
- Each sidecar lists at least one regular file. File paths are canonical relative POSIX paths, relative to that sidecar's directory. No absolute paths, `.`/`..`, empty components, backslashes, colons, control characters, or invalid Unicode. Unicode and spaces are supported. Selected shards cannot share a payload path.
- Symlinks and special files anywhere in the downloaded tree are rejected. Unlisted ordinary files are ignored. Directories used in supplied roots/manifest paths cannot be symlinks.
- Sidecars and manifests must be UTF-8 JSON, at most 1 MiB each. Hashes are lowercase SHA-256 hex. Unknown schema versions fail.
- `record` creates a new sidecar exclusively and never overwrites one. It does not create parent directories. It hashes each explicitly named file, without glob expansion of its own.
- `check` only reads local files; it never extracts archives, downloads, deletes, executes, or modifies them. Supply an already-extracted, quiescent tree.
- Exit 0: the record/check succeeded. Exit 1: input or integrity failure. Exit 2: command-line usage error. Text check failure writes an error to stderr and no selected paths to stdout. JSON check failure writes `{"schema_version":1,"complete":false,"error":"..."}` to stdout. Error wording is diagnostic, not a stable API.

## GitHub Actions integration sketch

Assumptions: your repository vendors this source at `tools/shardcheck`, commits `ci/expected-shards.json` with `{"schema_version":1,"shards":["1","2","3","4"]}`, and has a test command writing `results/result.xml`. Adapt that command to your runner. This is illustrative and has not been executed against your repository.

```yaml
name: Sharded tests
on: [push, pull_request]
permissions:
  contents: read
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        shard: [1, 2, 3, 4]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: python -m pip install ./tools/shardcheck
      - name: Run your tests and write results/result.xml
        run: ./ci/test-shard.sh '${{ matrix.shard }}' 4
      - name: Record available report, even when tests fail
        if: always()
        run: >-
          shardcheck record --root results --output artifact.shardcheck.json
          --run-id '${{ github.run_id }}' --revision '${{ github.sha }}'
          --shard-id '${{ matrix.shard }}' --attempt '${{ github.run_attempt }}'
          -- result.xml
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: shard-${{ matrix.shard }}-attempt-${{ github.run_attempt }}
          path: results/
          if-no-files-found: error
  preflight:
    needs: test
    if: always()
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: python -m pip install ./tools/shardcheck
      - uses: actions/download-artifact@v4
        with:
          pattern: shard-*-attempt-*
          path: downloaded
          merge-multiple: false
      - name: Validate completeness before report aggregation
        run: >-
          shardcheck check --root downloaded --expected ci/expected-shards.json
          --run-id '${{ github.run_id }}' --revision '${{ github.sha }}'
          --format json > selected.json
      # Your next step consumes selected.json and separately checks test outcomes.
```

Preserve unique artifact directories across attempts. A downloaded sidecar must remain beside its listed files. Ensure the download covers the relevant attempts and that the report artifact is emitted only after the shard has finished. A missing newer sidecar is invisible to the selection algorithm, so the workflow must separately enforce runner/upload success and intended rerun coverage. Keep the test job as a required check: a successful preflight is not a replacement.

Action major-version tags above are examples, not immutable security pins. Review and pin third-party actions to verified commit SHAs for your supply-chain policy.

## Development

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
python -m pip install --no-build-isolation --no-deps .
shardcheck --version
```

The test suite covers four-shard completeness, partial reruns, duplicate attempts, corrupt/missing latest files, wrong identity, malformed/duplicate-key JSON, symlinks/special files, traversal, Unicode, deterministic ordering, read-only checks, and reports containing failing tests. CI also installs the package and exercises its console entry point.

See [schema reference](docs/schema.md), [JSON Schemas](docs/), and [security policy](SECURITY.md). Contributions should preserve the small offline contract and include regression tests.
