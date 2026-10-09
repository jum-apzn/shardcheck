# Security policy and boundaries

shardcheck 0.1 is an offline **completeness and integrity preflight**, not a trust verifier.

## What it checks

An explicitly supplied expected-shard list is compared with local sidecars. All sidecars must have valid schemas and matching caller-supplied run/revision identities. Duplicate shard/attempt pairs and unexpected shards fail. Each shard's highest observed attempt must have all listed regular files, matching recorded sizes and SHA-256 hashes. Invalid paths, symlinks, special files, duplicate JSON keys, and unsupported schemas are rejected.

## What it does not establish

- Hashes are not signatures. Someone able to change both payload and sidecar can forge a valid pair. Run IDs, revisions, and attempt values are caller assertions, not authenticated provenance.
- Completeness does not establish passing tests, correct assertions, actual execution, coverage, absence of skipped tests, or semantic validity of JUnit/other reports. Even an empty regular file can match its sidecar.
- Selection only knows downloaded sidecars. A newer run attempt whose sidecar is missing entirely is indistinguishable from an attempt that never occurred. A present newer sidecar with absent/corrupt payload fails without older fallback. Verify intended run coverage and download/upload/job status in your CI orchestration.
- Expected-shard manifests must come from a trusted independent source. Deriving expectations from downloaded files defeats missing-shard detection.
- Only selected payloads are hashed; older attempts' sidecars are schema/identity validated, but their payloads need not exist or match. Unlisted regular files are ignored.
- This is not an archive extractor, malware scanner, sandbox, signature verifier, or report merger. It does not inspect archive member paths or report contents.

## Filesystem threat model

Use an already-extracted, isolated, quiescent directory tree. Do not let untrusted concurrent processes modify the root, parent directories, sidecars, or payloads while recording/checking or consuming the selected files. Files are checked before use and opened with O_NOFOLLOW/O_NONBLOCK where supported, but these checks do **not** create an atomic filesystem snapshot or fully defend against time-of-check/time-of-use races. In particular, O_NOFOLLOW only protects the final path component; parent directories could change concurrently. A successful check does not protect files changed afterward.

Roots and their ancestors must be real directories; symlink roots are rejected. Symlinks and special files anywhere under the artifact root are rejected, even when not selected. Hard links are regular files, and are not specially rejected; isolate the tree from concurrent writers. Filesystem case sensitivity and Unicode normalization depend on the host; prefer unique ASCII artifact directory names for cross-platform CI portability.

JSON is capped at 1 MiB per document. There is no global payload-byte, file-count, sidecar-count, or elapsed-time quota. Run with ordinary CI resource limits. The program does not execute, extract, fetch, delete, or alter checked files. Access-time metadata may change as a normal consequence of reading.

## Reporting a concern

Do not post credentials, private artifacts, or exploit details affecting someone else's deployment. Contact the repository maintainers privately through a verified GitHub security advisory/reporting route if one is enabled. If no private route is available, open a minimal issue requesting a private reporting channel without disclosing sensitive details.
