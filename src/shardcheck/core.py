"""Strict local sidecar recording and checking, using only the standard library."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat

SUFFIX = ".shardcheck.json"
MAX_JSON_BYTES = 1024 * 1024


class Invalid(ValueError):
    """Input failed the completeness or integrity contract."""


def identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise Invalid(f"{field} must be a nonempty string of at most 512 characters")
    if any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise Invalid(f"{field} contains a control character or invalid Unicode")
    return value


def relative(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise Invalid("file path must be a nonempty relative POSIX path")
    if any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise Invalid("file path contains a control character or invalid Unicode")
    if "\\" in value or ":" in value or any(p in ("", ".", "..") for p in value.split("/")):
        raise Invalid(f"unsafe relative path: {value!r}")
    return value


def root_directory(path: str | Path) -> Path:
    root = Path(os.path.abspath(path))
    # Do not resolve symlinks away before checking them.
    for item in (*reversed(root.parents), root):
        if not stat.S_ISDIR(item.lstat().st_mode):
            raise Invalid(f"not a real directory (symlinks forbidden): {item}")
    return root


def safe_path(root: Path, value: str, *, absent: bool = False) -> Path:
    parts = relative(value).split("/")
    current = root
    for part in parts[:-1]:
        current /= part
        if not stat.S_ISDIR(current.lstat().st_mode):
            raise Invalid(f"not a real directory: {current}")
    result = current / parts[-1]
    try:
        mode = result.lstat().st_mode
    except FileNotFoundError:
        if absent:
            return result
        raise
    if not stat.S_ISREG(mode):
        raise Invalid(f"not a regular file (symlinks forbidden): {result}")
    if absent:
        raise Invalid(f"output already exists: {result}")
    return result


def read_regular(path: Path, *, limit: int | None = None):
    # O_NONBLOCK prevents a substituted FIFO from blocking before fstat.
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise Invalid(f"not a regular file: {path}")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            if limit is not None:
                data = handle.read(limit + 1)
                if len(data) > limit:
                    raise Invalid(f"JSON exceeds {limit} bytes: {path}")
                return data
            digest = hashlib.sha256()
            size = 0
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
            return size, digest.hexdigest()
    finally:
        os.close(fd)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Invalid(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def load_json(path: Path):
    if not stat.S_ISREG(path.lstat().st_mode):
        raise Invalid(f"not a regular JSON file: {path}")
    try:
        return json.loads(read_regular(path, limit=MAX_JSON_BYTES).decode("utf-8"),
                          object_pairs_hook=_pairs,
                          parse_constant=lambda x: (_ for _ in ()).throw(Invalid(f"invalid JSON constant: {x}")))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise Invalid(f"malformed JSON: {path}: {exc}") from exc


def keys(obj, expected: set[str], label: str):
    if not isinstance(obj, dict) or set(obj) != expected:
        raise Invalid(f"{label} must contain exactly: {', '.join(sorted(expected))}")


def version(obj):
    if type(obj["schema_version"]) is not int or obj["schema_version"] != 1:
        raise Invalid("schema_version must be integer 1")


def manifest(path: str | Path) -> list[str]:
    path = Path(os.path.abspath(path))
    root_directory(path.parent)
    obj = load_json(path)
    keys(obj, {"schema_version", "shards"}, "expected manifest")
    version(obj)
    if not isinstance(obj["shards"], list) or not obj["shards"]:
        raise Invalid("expected shards must be a nonempty list")
    shards = [identifier(s, "shard") for s in obj["shards"]]
    if len(set(shards)) != len(shards):
        raise Invalid("duplicate expected shard")
    return sorted(shards)


def sidecar(obj):
    keys(obj, {"schema_version", "run_id", "revision", "shard_id", "attempt", "files"}, "sidecar")
    version(obj)
    for field in ("run_id", "revision", "shard_id"):
        identifier(obj[field], field)
    if type(obj["attempt"]) is not int or obj["attempt"] < 1:
        raise Invalid("attempt must be a positive integer")
    if not isinstance(obj["files"], list) or not obj["files"]:
        raise Invalid("files must be a nonempty list")
    seen = set()
    for entry in obj["files"]:
        keys(entry, {"path", "size", "sha256"}, "file entry")
        path = relative(entry["path"])
        if path in seen:
            raise Invalid(f"duplicate file path: {path}")
        seen.add(path)
        if type(entry["size"]) is not int or entry["size"] < 0:
            raise Invalid("size must be a nonnegative integer")
        if not isinstance(entry["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
            raise Invalid("sha256 must be 64 lowercase hexadecimal characters")
    return obj


def record(root, output, run_id, revision, shard_id, attempt, files):
    root = root_directory(root)
    if not output.endswith(SUFFIX):
        raise Invalid(f"output must end with {SUFFIX}")
    output_path = safe_path(root, output, absent=True)
    if not files or len(files) != len(set(files)):
        raise Invalid("provide at least one file, without duplicates")
    # Paths are relative to the sidecar's containing directory, not process cwd.
    entries = []
    for name in sorted(files):
        path = safe_path(output_path.parent, name)
        size, digest = read_regular(path)
        entries.append({"path": name, "size": size, "sha256": digest})
    obj = sidecar({"schema_version": 1, "run_id": run_id, "revision": revision,
                   "shard_id": shard_id, "attempt": attempt, "files": entries})
    data = (json.dumps(obj, ensure_ascii=True, sort_keys=True, indent=2) + "\n").encode("utf-8")
    if len(data) > MAX_JSON_BYTES:
        raise Invalid("sidecar exceeds maximum JSON size")
    # Exclusive creation prevents silent replacement of a previously recorded run.
    with output_path.open("xb") as handle:
        handle.write(data)
    return obj


def discover(root: Path) -> list[Path]:
    results = []
    def walk(directory):
        for path in sorted(directory.iterdir(), key=lambda p: p.name):
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                walk(path)
            elif stat.S_ISREG(mode):
                if path.name.endswith(SUFFIX):
                    results.append(path)
            else:
                raise Invalid(f"symlink or special file in artifact tree: {path}")
    try:
        walk(root)
    except RecursionError as exc:
        raise Invalid("artifact tree is too deeply nested") from exc
    return results


def check(root, expected, run_id, revision):
    root = root_directory(root)
    identifier(run_id, "run_id")
    identifier(revision, "revision")
    shards = manifest(expected)
    candidates = {shard: {} for shard in shards}
    for path in discover(root):
        obj = sidecar(load_json(path))
        if obj["run_id"] != run_id or obj["revision"] != revision:
            raise Invalid(f"run/revision mismatch: {path.relative_to(root)}")
        shard = obj["shard_id"]
        if shard not in candidates:
            raise Invalid(f"unexpected shard: {shard}")
        attempt = obj["attempt"]
        if attempt in candidates[shard]:
            raise Invalid(f"duplicate shard/attempt: {shard}/{attempt}")
        candidates[shard][attempt] = (path, obj)
    missing = [s for s in shards if not candidates[s]]
    if missing:
        raise Invalid(f"missing shards: {', '.join(missing)}")
    selected = []
    selected_paths = set()
    for shard in shards:
        attempt = max(candidates[shard])
        path, obj = candidates[shard][attempt]
        paths = []
        for entry in sorted(obj["files"], key=lambda f: f["path"]):
            file_path = safe_path(path.parent, entry["path"])
            relative_path = file_path.relative_to(root).as_posix()
            if relative_path in selected_paths:
                raise Invalid(f"file shared by selected shards: {relative_path}")
            selected_paths.add(relative_path)
            size, digest = read_regular(file_path)
            if (size, digest) != (entry["size"], entry["sha256"]):
                raise Invalid(f"integrity mismatch for shard {shard}, attempt {attempt}: {relative_path}")
            paths.append(relative_path)
        selected.append({"shard_id": shard, "attempt": attempt,
                         "sidecar": path.relative_to(root).as_posix(), "paths": paths})
    return {"schema_version": 1, "complete": True, "run_id": run_id,
            "revision": revision, "selected": selected}
