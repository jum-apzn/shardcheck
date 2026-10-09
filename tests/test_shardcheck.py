import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from shardcheck.cli import main
from shardcheck.core import Invalid, check, record


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "artifacts"
        self.root.mkdir()
        self.expected = self.base / "expected.json"
        self.write_expected(["1", "2", "3", "4"])

    def write_expected(self, shards):
        self.expected.write_text(json.dumps({"schema_version": 1, "shards": shards}))

    def add(self, shard, attempt=1, body=b'<testsuite failures="0"/>', filename="result.xml"):
        directory = self.root / f"shard-{shard}-attempt-{attempt}"
        directory.mkdir(exist_ok=True)
        (directory / filename).write_bytes(body)
        sidecar = directory / "artifact.shardcheck.json"
        record(directory, sidecar.name, "run-42", "abc123", shard, attempt, [filename])
        return sidecar

    def all(self):
        return [self.add(str(i)) for i in range(1, 5)]

    def check(self):
        return check(self.root, self.expected, "run-42", "abc123")

    def mutate(self, path, operation):
        obj = json.loads(path.read_text())
        operation(obj)
        path.write_text(json.dumps(obj))

    def test_four_valid_shards(self):
        self.all()
        result = self.check()
        self.assertTrue(result["complete"])
        self.assertEqual([s["shard_id"] for s in result["selected"]], ["1", "2", "3", "4"])

    def test_missing_shard(self):
        self.add("1")
        with self.assertRaisesRegex(Invalid, "missing shards: 2, 3, 4"):
            self.check()

    def test_no_sidecars(self):
        with self.assertRaisesRegex(Invalid, "missing shards"):
            self.check()

    def test_unexpected_shard(self):
        self.all()
        self.add("5")
        with self.assertRaisesRegex(Invalid, "unexpected shard"):
            self.check()

    def test_duplicate_same_shard_attempt(self):
        sidecar = self.all()[0]
        (sidecar.parent / "duplicate.shardcheck.json").write_bytes(sidecar.read_bytes())
        with self.assertRaisesRegex(Invalid, "duplicate shard/attempt"):
            self.check()

    def test_partial_rerun_selects_each_latest(self):
        self.all()
        self.add("2", 3)
        self.add("4", 2)
        self.assertEqual([s["attempt"] for s in self.check()["selected"]], [1, 3, 1, 2])

    def test_latest_corrupt_never_falls_back(self):
        self.all()
        path = self.add("2", 2)
        (path.parent / "result.xml").write_bytes(b"corrupted")
        with self.assertRaisesRegex(Invalid, "integrity mismatch"):
            self.check()

    def test_latest_missing_never_falls_back(self):
        self.all()
        path = self.add("2", 2)
        (path.parent / "result.xml").unlink()
        with self.assertRaises(FileNotFoundError):
            self.check()

    def test_older_payload_may_be_missing(self):
        old = self.all()[0]
        self.add("1", 2)
        (old.parent / "result.xml").unlink()
        self.assertTrue(self.check()["complete"])

    def test_even_old_sidecar_must_match_identity(self):
        old = self.all()[0]
        self.add("1", 2)
        self.mutate(old, lambda o: o.update(run_id="different"))
        with self.assertRaisesRegex(Invalid, "run/revision mismatch"):
            self.check()

    def test_wrong_run_and_revision(self):
        sidecar = self.all()[0]
        for field in ("run_id", "revision"):
            original = sidecar.read_bytes()
            self.mutate(sidecar, lambda o: o.update({field: "wrong"}))
            with self.assertRaisesRegex(Invalid, "run/revision mismatch"):
                self.check()
            sidecar.write_bytes(original)

    def test_failing_tests_are_still_complete(self):
        self.write_expected(["1"])
        self.add("1", body=b'<testsuite failures="2"><testcase><failure/></testcase></testsuite>')
        self.assertTrue(self.check()["complete"])

    def test_unicode_paths_and_identifiers(self):
        self.write_expected(["한국어"])
        self.add("한국어", filename="résultat 결과.xml")
        self.assertIn("résultat 결과.xml", self.check()["selected"][0]["paths"][0])

    def test_order_independence(self):
        self.write_expected(["4", "2", "1", "3"])
        for shard in ("3", "1", "4", "2"):
            self.add(shard)
        first = self.check()
        self.write_expected(["1", "2", "3", "4"])
        self.assertEqual(first, self.check())

    def test_unsafe_artifact_paths(self):
        sidecar = self.all()[0]
        original = sidecar.read_bytes()
        for path in ("/etc/passwd", "../result.xml", "a/../../x", "./result.xml", "a//b", "C:/x", "a\\b", "", "a\nb", "\ud800"):
            with self.subTest(path=path):
                sidecar.write_bytes(original)
                self.mutate(sidecar, lambda o: o["files"][0].update(path=path))
                with self.assertRaises(Invalid):
                    self.check()

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink support required")
    def test_symlink_file_directory_and_root_rejected(self):
        self.all()
        link = self.root / "link"
        for target, is_dir in ((self.expected, False), (self.base, True)):
            link.symlink_to(target, target_is_directory=is_dir)
            with self.assertRaises(Invalid):
                self.check()
            link.unlink()
        link = self.base / "rootlink"
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(Invalid):
            check(link, self.expected, "run-42", "abc123")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO support required")
    def test_special_file_rejected_without_blocking(self):
        self.all()
        os.mkfifo(self.root / "pipe")
        with self.assertRaises(Invalid):
            self.check()

    def test_duplicate_json_keys_at_any_depth(self):
        sidecar = self.all()[0]
        original = sidecar.read_text()
        for text in (original.replace('"attempt": 1', '"attempt": 1, "attempt": 2'),
                     original.replace('"size":', '"size": 0, "size":')):
            sidecar.write_text(text)
            with self.assertRaisesRegex(Invalid, "duplicate JSON key"):
                self.check()

    def test_malformed_json(self):
        sidecar = self.all()[0]
        for bad in (b"{", b"\xff", b"[]", b"null", b'{"x":NaN}', b"[" * 2000):
            sidecar.write_bytes(bad)
            with self.assertRaises(Invalid):
                self.check()

    def test_schema_strictness(self):
        sidecar = self.all()[0]
        original = sidecar.read_bytes()
        mutations = [lambda o: o.update(extra=True), lambda o: o.update(schema_version=True),
                     lambda o: o.update(schema_version=2), lambda o: o.update(attempt=True),
                     lambda o: o.update(attempt=0), lambda o: o.update(attempt=1.5),
                     lambda o: o.update(shard_id=""), lambda o: o.update(files=[]),
                     lambda o: o["files"][0].update(size=True),
                     lambda o: o["files"][0].update(sha256="A" * 64),
                     lambda o: o["files"].append(o["files"][0].copy())]
        for mutation in mutations:
            sidecar.write_bytes(original)
            self.mutate(sidecar, mutation)
            with self.assertRaises(Invalid):
                self.check()

    def test_bad_manifest(self):
        self.all()
        for obj in ({"schema_version": 1, "shards": []}, {"schema_version": 1, "shards": ["1", "1"]},
                    {"schema_version": True, "shards": ["1"]}, {"schema_version": 1, "shards": [1]},
                    {"schema_version": 1, "shards": ["1"], "extra": 0}):
            self.expected.write_text(json.dumps(obj))
            with self.assertRaises(Invalid):
                self.check()
        self.expected.write_text('{"schema_version":1,"shards":["1"],"shards":["2"]}')
        with self.assertRaises(Invalid):
            self.check()

    def test_oversized_json(self):
        sidecar = self.all()[0]
        sidecar.write_text(" " * (1024 * 1024 + 1))
        with self.assertRaisesRegex(Invalid, "exceeds"):
            self.check()

    def test_record_does_not_overwrite(self):
        sidecar = self.add("1")
        before = sidecar.read_bytes()
        with self.assertRaises(Invalid):
            record(sidecar.parent, sidecar.name, "x", "y", "z", 1, ["result.xml"])
        self.assertEqual(before, sidecar.read_bytes())

    def test_record_rejects_bad_paths_and_duplicates(self):
        (self.root / "file").write_text("data")
        for output, files in (("../x.shardcheck.json", ["file"]), ("x.json", ["file"]),
                              ("x.shardcheck.json", ["../expected.json"]),
                              ("x.shardcheck.json", ["file", "file"])):
            with self.assertRaises(Invalid):
                record(self.root, output, "x", "y", "z", 1, files)
        self.assertFalse((self.root / "x.shardcheck.json").exists())

    def test_selected_shards_cannot_share_payload_path(self):
        self.write_expected(["1", "2"])
        (self.root / "result.xml").write_bytes(b"report")
        for shard in ("1", "2"):
            record(self.root, f"{shard}.shardcheck.json", "run-42", "abc123", shard, 1, ["result.xml"])
        with self.assertRaisesRegex(Invalid, "file shared by selected shards"):
            self.check()

    def test_nested_record_output_uses_sidecar_directory(self):
        (self.root / "nested").mkdir()
        (self.root / "nested" / "report").write_bytes(b"report")
        record(self.root, "nested/x.shardcheck.json", "run-42", "abc123", "1", 1, ["report"])
        self.write_expected(["1"])
        self.assertEqual(self.check()["selected"][0]["paths"], ["nested/report"])

    def test_missing_unobserved_retry_cannot_be_detected(self):
        # Explicit boundary: no newer sidecar means there is no retry evidence.
        self.all()
        (self.root / "shard-2-attempt-2").mkdir()
        self.assertEqual(self.check()["selected"][1]["attempt"], 1)

    def test_check_does_not_mutate_files(self):
        self.all()
        before = {str(p): p.read_bytes() for p in self.base.rglob("*") if p.is_file()}
        self.check()
        after = {str(p): p.read_bytes() for p in self.base.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_cli_text_and_json(self):
        self.all()
        args = ["check", "--root", str(self.root), "--expected", str(self.expected), "--run-id", "run-42", "--revision", "abc123"]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(args), 0)
        self.assertEqual(len(out.getvalue().splitlines()), 4)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(args + ["--format", "json"]), 0)
        self.assertEqual(json.loads(out.getvalue()), self.check())

    def test_cli_failure_outputs_no_selected_paths(self):
        self.add("1")
        args = ["check", "--root", str(self.root), "--expected", str(self.expected), "--run-id", "run-42", "--revision", "abc123"]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(main(args), 1)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("missing shards", err.getvalue())
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(args + ["--format", "json"]), 1)
        self.assertFalse(json.loads(output.getvalue())["complete"])

    def test_cli_module_smoke(self):
        result = subprocess.run([sys.executable, "-m", "shardcheck", "--version"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "shardcheck 0.1.0")


if __name__ == "__main__":
    unittest.main()
