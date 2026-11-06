#!/usr/bin/env python3
"""
Regression tests for the two dataset-integrity defects found in Phase 5D.

Both CLIs are run as real subprocesses inside throwaway temporary directories, so nothing
under this repository's dataset/ or results/ is read, written or renamed.

  1. generate_behaviors.py must treat a run id as single-use. Reusing one must be refused
     (exit 2) before the key is read, before any HTTP call and before any write, because a
     reuse overwrites "<sample_id>.txt" and appends a duplicate sample id to the manifest.
  2. validate_behaviors.py must fail loudly (non-zero exit, no CSV written) when it evaluates
     zero documents, instead of printing "no documents evaluated" and exiting 0.

OPENAI_API_KEY is stripped from the child environment in every test, so a passing test that
reaches the key check proves the guard ran before it - and no test can ever reach the network.

Usage
  python -m unittest discover -s tests -v
  python tests/test_dataset_integrity.py
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GENERATOR = os.path.join(REPO, "scripts", "generate_behaviors.py")
VALIDATOR = os.path.join(REPO, "scripts", "validate_behaviors.py")

MANIFEST_HEADER = (
    "run_id,sample_id,prompt_id,behavior_style,model,temperature,max_tokens,seed,"
    "timestamp_utc,prompt_sha256,raw_sha256,response_model,system_fingerprint,"
    "prompt_tokens,completion_tokens,http_status\n"
)
MANIFEST_ROW = (
    "20261105_p01_success,P01-G01,P01,aggressive,gpt-4.1,0.7,900,,"
    "2026-11-06T03:45:08.969786+00:00,deadbeef,deadbeef,gpt-4.1-2025-04-14,fp_test,1538,326,200\n"
)

# Minimal document that must pass M1-M3 and be logically VALID: a selector whose two children
# are both distance-gated, so the union of their condition sets covers the domain and no
# L3/L4/L5/L8 rule can fire. Used to prove .txt discovery, not to exercise the rule set.
VALID_DOCUMENT = {
    "schema_version": "2.0",
    "behavior_id": "test_behavior",
    "behavior_style": "aggressive",
    "source_prompt_id": "P01",
    "description": "Fixture used only by the integrity tests.",
    "root": {
        "node_id": "n0",
        "type": "selector",
        "children": [
            {
                "node_id": "n1",
                "type": "action",
                "action": "attack",
                "condition": {"test": "distance_to_target", "op": "<=", "value": 300},
            },
            {
                "node_id": "n2",
                "type": "action",
                "action": "move_to_target",
                "condition": {"test": "distance_to_target", "op": ">", "value": 300},
            },
        ],
    },
    "parameters": {
        "attack_range_cm": 300,
        "retreat_distance_cm": 1200,
        "retreat_health_pct": 0.25,
    },
}


def run_script(script, args, cwd):
    """Run a CLI with OPENAI_API_KEY removed from the environment."""
    env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
    return subprocess.run([sys.executable, script] + args, cwd=cwd, env=env,
                          capture_output=True, text=True)


def snapshot(root):
    """path -> (size, sha256) for every file under root, so a no-write claim is provable."""
    state = {}
    for base, _dirs, files in os.walk(root):
        for name in sorted(files):
            path = os.path.join(base, name)
            with open(path, "rb") as fh:
                data = fh.read()
            state[os.path.relpath(path, root)] = (len(data), hashlib.sha256(data).hexdigest())
    return state


class GeneratorRunIdGuard(unittest.TestCase):
    """generate_behaviors.py must not reuse a run id that already holds generation data."""

    RUN_ID = "20261105_p01_success"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        self.run_dir = os.path.join(self.root, "dataset", "raw_outputs", self.RUN_ID)
        os.makedirs(self.run_dir)

    def _seed_raw_output(self, name="P01-G01.txt", body='{"behavior_id": "existing"}'):
        path = os.path.join(self.run_dir, name)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(body)
        return path

    def _seed_manifest(self, with_row=True):
        path = os.path.join(self.run_dir, "manifest.csv")
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(MANIFEST_HEADER)
            if with_row:
                fh.write(MANIFEST_ROW)
        return path

    def _generate(self, run_id=None, dry_run=False):
        args = ["--run", "--prompt-id", "P01", "--n", "1", "--run-id", run_id or self.RUN_ID]
        if dry_run:
            args.append("--dry-run")
        return run_script(GENERATOR, args, self.root)

    def _assert_refused(self, proc):
        out = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 2, out)
        self.assertIn("REFUSED", out)
        self.assertIn(self.RUN_ID, out)
        self.assertIn("No API calls were made", out)

    def test_refuses_when_run_dir_holds_raw_outputs(self):
        self._seed_raw_output()
        self._assert_refused(self._generate())

    def test_refusal_wins_over_the_key_check(self):
        # OPENAI_API_KEY is absent from the child env. Getting the refusal instead of the key
        # error proves the guard runs before the key is read, and therefore before any HTTP call.
        self._seed_raw_output()
        proc = self._generate()
        self._assert_refused(proc)
        self.assertNotIn("OPENAI_API_KEY is not set", proc.stdout + proc.stderr)

    def test_refuses_when_manifest_has_data_rows_but_no_raw_outputs(self):
        self._seed_manifest(with_row=True)
        self._assert_refused(self._generate())

    def test_rejected_run_does_not_modify_or_add_any_file(self):
        self._seed_raw_output()
        manifest = self._seed_manifest(with_row=True)
        before = snapshot(self.root)
        proc = self._generate()
        self._assert_refused(proc)
        self.assertEqual(snapshot(self.root), before,
                         "a refused run changed, created or deleted files on disk")
        with open(manifest, encoding="utf-8", newline="") as fh:
            rows = [line for line in fh.read().splitlines() if line.strip()]
        self.assertEqual(len(rows), 2, "a refused run appended a duplicate manifest row")

    def test_rejected_run_creates_no_new_directory(self):
        # A refusal must precede os.makedirs, so the tree below dataset/raw_outputs is untouched.
        self._seed_raw_output()
        before = sorted(os.listdir(os.path.join(self.root, "dataset", "raw_outputs")))
        self._assert_refused(self._generate())
        after = sorted(os.listdir(os.path.join(self.root, "dataset", "raw_outputs")))
        self.assertEqual(before, after)

    def test_dry_run_is_refused_too(self):
        # --dry-run writes nothing, but it cannot preview a run id that a real run would refuse.
        self._seed_raw_output()
        self._assert_refused(self._generate(dry_run=True))

    def test_header_only_manifest_is_not_generation_data(self):
        # A manifest with just the header records no sample, so continuing into it loses nothing
        # and cannot duplicate a sample id. The run must reach the key check instead of refusing.
        manifest = self._seed_manifest(with_row=False)
        proc = self._generate()
        out = proc.stdout + proc.stderr
        self.assertNotIn("REFUSED", out)
        self.assertIn("OPENAI_API_KEY is not set", out)
        with open(manifest, encoding="utf-8", newline="") as fh:
            self.assertEqual(fh.read(), MANIFEST_HEADER,
                             "the existing header was rewritten or duplicated")

    def test_fresh_run_id_is_not_refused(self):
        proc = self._generate(run_id="20261106_fresh")
        out = proc.stdout + proc.stderr
        self.assertNotIn("REFUSED", out)
        self.assertIn("OPENAI_API_KEY is not set", out)
        fresh = os.path.join(self.root, "dataset", "raw_outputs", "20261106_fresh")
        self.assertFalse(os.path.exists(fresh),
                         "the run stopped at the key check, so no directory may be created")


class ValidatorZeroDocumentGuard(unittest.TestCase):
    """validate_behaviors.py must fail loudly rather than report a silent zero."""

    RUN_ID = "20261105_p01_success"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        self.inputs = os.path.join(self.root, "in")
        self.results = os.path.join(self.root, "out")
        os.makedirs(self.inputs)

    def _validate(self, inputs=None):
        return run_script(VALIDATOR, ["--inputs", inputs or self.inputs,
                                      "--results", self.results,
                                      "--run-id", self.RUN_ID], self.root)

    def _write_document(self, name, document=None, raw=None):
        path = os.path.join(self.inputs, name)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            if raw is not None:
                fh.write(raw)
            else:
                json.dump(document if document is not None else VALID_DOCUMENT, fh, indent=2)
        return path

    def _rows(self):
        with open(os.path.join(self.results, "generation_validation.csv"),
                  encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))

    def test_empty_input_directory_exits_nonzero_and_writes_no_csv(self):
        proc = self._validate()
        out = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 2, out)
        self.assertIn("no documents were evaluated", out)
        self.assertIn("Exit code 2", out)
        self.assertFalse(os.path.exists(os.path.join(self.results, "generation_validation.csv")),
                         "a failed validation must not write a CSV")

    def test_missing_input_path_exits_nonzero(self):
        proc = self._validate(inputs=os.path.join(self.root, "does_not_exist"))
        out = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 2, out)
        self.assertIn("does not exist", out)

    def test_zero_documents_does_not_clobber_existing_results(self):
        os.makedirs(self.results)
        csv_path = os.path.join(self.results, "generation_validation.csv")
        sentinel = "file,origin,run_id\nprevious,P01,20261105_p01_success\n"
        with open(csv_path, "w", encoding="utf-8", newline="") as fh:
            fh.write(sentinel)
        before = snapshot(self.root)
        proc = self._validate()
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertEqual(snapshot(self.root), before,
                         "a failed validation wrote over existing results")
        with open(csv_path, encoding="utf-8", newline="") as fh:
            self.assertEqual(fh.read(), sentinel)

    def test_success_path_still_exits_zero(self):
        self._write_document("P01-G01.txt")
        proc = self._validate()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("N=1", proc.stdout)

    def test_txt_raw_output_is_scored(self):
        # Phase 5D regression: raw generations are written as .txt and were filtered out by an
        # extension test, which is what made the validator report a silent zero.
        self._write_document("P01-G01.txt")
        proc = self._validate()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["file"], os.path.join("in", "P01-G01.txt").replace("\\", "/"))
        self.assertEqual(rows[0]["json_valid"], "1")
        self.assertEqual(rows[0]["structural_valid"], "1")
        self.assertEqual(rows[0]["actions_valid"], "1")
        self.assertEqual(rows[0]["logical_status"], "VALID")
        self.assertEqual(rows[0]["correction_class"], "none")

    def test_json_fixture_is_still_scored(self):
        # The .txt fix must not have replaced the .json path.
        self._write_document("fixture.json")
        proc = self._validate()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("N=1", proc.stdout)
        self.assertEqual(self._rows()[0]["json_valid"], "1")

    def test_invalid_json_is_still_a_finding_not_a_crash(self):
        self._write_document("P01-G01.txt", raw="this is not json")
        proc = self._validate()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        row = self._rows()[0]
        self.assertEqual(row["json_valid"], "0")
        self.assertIn("M1", row["finding_codes"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
