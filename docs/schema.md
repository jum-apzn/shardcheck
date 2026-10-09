# Version 1 schema reference

All documents use UTF-8 JSON. Duplicate object keys, NaN/Infinity, unknown fields, and documents larger than 1 MiB are rejected. Booleans and floating-point lexical forms such as `1.0` are not accepted as integers by the implementation. JSON Schema treats mathematically integral numbers such as `1.0` as integers, so structural schema validation alone is weaker here. JSON Schemas describe structural constraints; the implementation additionally enforces path safety, unique file paths, control-character/Unicode checks, filesystem type, identity, and integrity constraints.

## Expected manifest

```json
{"schema_version": 1, "shards": ["1", "2", "3", "4"]}
```

The shard list is nonempty and unique. Each ID is a nonempty string of at most 512 characters, with no C0/DEL control characters or lone Unicode surrogates. Case-sensitive IDs are sorted by Unicode code point for selection/output. Supply this manifest independently of downloaded artifacts.

## Sidecar (`*.shardcheck.json`)

```json
{
  "schema_version": 1,
  "run_id": "123456",
  "revision": "full-commit-sha",
  "shard_id": "2",
  "attempt": 3,
  "files": [
    {"path": "result.xml", "size": 0, "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}
  ]
}
```

`run_id`, `revision`, and `shard_id` follow the same string rules as expected IDs. `attempt` is a positive integer. `files` is a nonempty array of unique paths. `size` is a nonnegative byte count. `sha256` is exactly 64 lowercase hexadecimal characters. Paths are relative to the containing sidecar directory, at most 4096 characters, and use `/` as separator. Absolute paths, empty/`.`/`..` components, `\`, `:`, C0/DEL controls and lone surrogates are rejected. Final targets must be regular files reached through real directories.

## Check JSON output

Success (exit 0):

```json
{
  "schema_version": 1,
  "complete": true,
  "run_id": "123456",
  "revision": "full-commit-sha",
  "selected": [
    {"shard_id": "2", "attempt": 3, "sidecar": "shard-2-attempt-3/artifact.shardcheck.json", "paths": ["shard-2-attempt-3/result.xml"]}
  ]
}
```

Paths and sidecars are relative to `check --root`. `selected` is sorted by shard ID; `paths` is sorted by sidecar-relative file path. JSON keys are emitted in sorted order and non-ASCII characters are escaped. Stable output means repeated checks on identical inputs produce the same result independent of discovery order; diagnostic error messages and host-specific filesystem errors are not a stable interface.

Failure (exit 1):

```json
{"schema_version": 1, "complete": false, "error": "missing shards: 2"}
```

No partial selected list is emitted on failure. Argument parsing errors are exit 2 and use argparse's stderr output, even when `--format json` is supplied.
