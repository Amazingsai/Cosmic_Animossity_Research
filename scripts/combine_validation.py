#!/usr/bin/env python3
"""
Combine the per-round validation CSVs into one auditable 40-sample table.

Reads   results/validation_round1.csv, results/validation_round2.csv   (never modified)
Checks  every row against the raw file on disk and its run manifest
Writes  results/validation_combined.csv                                (derived data)

Provenance is re-derived from disk rather than trusted: each scored row must have exactly
one manifest row for its sample_id, that row must record http_status 200, and its recorded
raw_sha256 must equal the sha256 of the file as it exists now.  The file inventory of both
run directories is also cross-checked against the scored set, so a sample cannot be silently
counted twice or missed.

Usage
  python scripts/combine_validation.py
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import sys

ROUND_CSVS = [("round1", os.path.join("results", "validation_round1.csv")),
              ("round2", os.path.join("results", "validation_round2.csv"))]
OUT_CSV = os.path.join("results", "validation_combined.csv")
RAW_ROOT = os.path.join("dataset", "raw_outputs")

FIELDS = ["sample_id", "file", "origin", "run_id", "behavior_id", "schema_version",
          "json_valid", "structural_valid", "actions_valid", "logical_status",
          "manual_review", "correction_class", "finding_codes", "findings",
          "auto_corrections"]


def sha256_file(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def load_rows():
    rows = []
    for label, path in ROUND_CSVS:
        if not os.path.exists(path):
            sys.exit("ERROR: missing %s" % path)
        with open(path, encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                row["_round"] = label
                row["sample_id"] = os.path.splitext(os.path.basename(row["file"]))[0]
                rows.append(row)
    return rows


def load_manifests(rows):
    manifests = {}
    for run_id in sorted({r["run_id"] for r in rows}):
        path = os.path.join(RAW_ROOT, run_id, "manifest.csv")
        if not os.path.exists(path):
            sys.exit("ERROR: missing manifest %s" % path)
        table = {}
        with open(path, encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                table.setdefault(row["sample_id"], []).append(row)
        manifests[run_id] = table
    return manifests


def verify(rows, manifests):
    problems = []
    seen = set()
    for r in rows:
        key = (r["run_id"], r["sample_id"])
        if key in seen:
            problems.append("duplicate scored row %s" % (key,))
        seen.add(key)
        if not os.path.exists(r["file"]):
            problems.append("missing raw file %s" % r["file"])
            continue
        entries = manifests.get(r["run_id"], {}).get(r["sample_id"], [])
        if len(entries) != 1:
            problems.append("%s/%s has %d manifest rows"
                            % (r["run_id"], r["sample_id"], len(entries)))
            continue
        entry = entries[0]
        if entry.get("http_status") != "200":
            problems.append("%s http_status %s" % (r["sample_id"], entry.get("http_status")))
        actual = sha256_file(r["file"])
        if entry.get("raw_sha256") != actual:
            problems.append("%s sha256 mismatch manifest=%s disk=%s"
                            % (r["sample_id"], (entry.get("raw_sha256") or "")[:12], actual[:12]))
    return problems


def verify_inventory(rows):
    problems = []
    on_disk = set()
    for run_id in sorted({r["run_id"] for r in rows}):
        directory = os.path.join(RAW_ROOT, run_id)
        for name in sorted(os.listdir(directory)):
            if name.lower().endswith(".txt"):
                on_disk.add((run_id, os.path.splitext(name)[0]))
    scored = {(r["run_id"], r["sample_id"]) for r in rows}
    for extra in sorted(on_disk - scored):
        problems.append("on disk but unscored %s" % (extra,))
    for missing in sorted(scored - on_disk):
        problems.append("scored but absent from disk %s" % (missing,))
    return problems


def structure(doc):
    """Node count, depth, actions and condition tests, read from the parsed document."""
    stats = {"nodes": 0, "depth": 0, "actions": set(), "tests": set()}

    def walk(node, depth):
        if not isinstance(node, dict):
            return
        stats["nodes"] += 1
        stats["depth"] = max(stats["depth"], depth)
        if node.get("type") == "action" and isinstance(node.get("action"), str):
            stats["actions"].add(node["action"])
        cond = node.get("condition")
        if isinstance(cond, dict) and isinstance(cond.get("test"), str):
            stats["tests"].add(cond["test"])
        for child in node.get("children") or []:
            walk(child, depth + 1)

    walk(doc.get("root"), 0)
    return stats


def severity_pairs(findings):
    """'FAIL:S1:x | WARN:L8:y' -> [('FAIL','S1'), ('WARN','L8')]."""
    pairs = []
    for chunk in (findings or "").split(" | "):
        parts = chunk.split(":", 2)
        if len(parts) >= 2 and parts[0] in ("FAIL", "AMBIGUOUS", "WARN"):
            pairs.append((parts[0], parts[1]))
    return pairs


def pct(n, total):
    return "%5.1f%%" % (100.0 * n / total) if total else "  n/a"


def main():
    rows = load_rows()
    manifests = load_manifests(rows)
    problems = verify(rows, manifests) + verify_inventory(rows)

    docs = {}
    for r in rows:
        try:
            with open(r["file"], encoding="utf-8", errors="replace") as fh:
                docs[r["sample_id"] + "@" + r["run_id"]] = json.load(fh)
        except Exception as exc:                     # M1 already recorded this
            docs[r["sample_id"] + "@" + r["run_id"]] = {"_parse_error": str(exc)}

    total = len(rows)
    run_counts = {}
    for r in rows:
        run_counts[r["run_id"]] = run_counts.get(r["run_id"], 0) + 1

    print("=== COMBINED DATASET ===")
    print("scored rows           %d" % total)
    for run_id, count in sorted(run_counts.items()):
        print("  %-28s %d" % (run_id, count))
    if problems:
        print("provenance            %d PROBLEM(S)" % len(problems))
        for p in problems:
            print("  ! %s" % p)
    else:
        print("provenance            verified %d/%d (1 manifest row each, http 200, sha256 "
              "recomputed from disk)" % (total, total))
        print("inventory             scored set == raw .txt inventory of both run dirs")

    print()
    print("=== M1-M5 (combined, N=%d) ===" % total)
    m1 = sum(1 for r in rows if r["json_valid"] == "1")
    m2 = sum(1 for r in rows if r["structural_valid"] == "1")
    m3 = sum(1 for r in rows if r["actions_valid"] == "1")
    valid = sum(1 for r in rows if r["logical_status"] == "VALID")
    review = sum(1 for r in rows if r["logical_status"] == "REVIEW")
    invalid = sum(1 for r in rows if r["logical_status"] == "INVALID")
    changed = sum(1 for r in rows if r["correction_class"] != "none")
    classes = {}
    for r in rows:
        classes[r["correction_class"]] = classes.get(r["correction_class"], 0) + 1
    print("M1 JSON valid         %2d/%d (%s)" % (m1, total, pct(m1, total)))
    print("M2 structural valid   %2d/%d (%s)" % (m2, total, pct(m2, total)))
    print("M3 actions valid      %2d/%d (%s)" % (m3, total, pct(m3, total)))
    print("M4 logically valid    %2d/%d (%s)   manual review %d"
          % (valid, total, pct(valid, total), review))
    print("M5 needs correction   %2d/%d (%s)   %s"
          % (changed, total, pct(changed, total),
             "  ".join("%s %d" % (k, classes[k]) for k in sorted(classes))))

    print()
    print("=== LOGICAL STATUS ===")
    print("VALID                 %2d (%s)" % (valid, pct(valid, total)))
    print("REVIEW                %2d (%s)" % (review, pct(review, total)))
    print("INVALID               %2d (%s)" % (invalid, pct(invalid, total)))
    flagged = sum(1 for r in rows if r["manual_review"] == "1")
    flagged_invalid = sum(1 for r in rows if r["manual_review"] == "1"
                          and r["logical_status"] == "INVALID")
    print("manual_review=1 flag  %2d  (= %d REVIEW + %d INVALID that also carry an "
          "AMBIGUOUS finding)" % (flagged, flagged - flagged_invalid, flagged_invalid))

    print()
    print("=== FINDING CODES (rows containing the code) ===")
    tally = {}
    for r in rows:
        for code in {c for _s, c in severity_pairs(r["findings"])}:
            sev = set()
            for s, c in severity_pairs(r["findings"]):
                if c == code:
                    sev.add(s)
            bucket = tally.setdefault(code, {"FAIL": 0, "AMBIGUOUS": 0, "WARN": 0})
            for s in sev:
                bucket[s] += 1
    print("%-6s %5s %5s %5s" % ("code", "FAIL", "AMBIG", "WARN"))
    for code in sorted(tally, key=lambda c: (-sum(tally[c].values()), c)):
        b = tally[code]
        print("%-6s %5d %5d %5d" % (code, b["FAIL"], b["AMBIGUOUS"], b["WARN"]))

    print()
    print("=== PER PROMPT ===")
    print("%-4s %5s %5s %5s %7s" % ("pid", "rows", "valid", "review", "invalid"))
    by_prompt = {}
    for r in rows:
        pid = r["sample_id"].split("-")[0]
        bucket = by_prompt.setdefault(pid, {"rows": 0, "VALID": 0, "REVIEW": 0, "INVALID": 0})
        bucket["rows"] += 1
        bucket[r["logical_status"]] += 1
    for pid in sorted(by_prompt):
        b = by_prompt[pid]
        print("%-4s %5d %5d %5d %7d" % (pid, b["rows"], b["VALID"], b["REVIEW"], b["INVALID"]))

    print()
    print("=== EVERY SAMPLE ===")
    print("%-8s %-8s %-11s %5s %5s  %s" % ("sample", "status", "style", "nodes", "depth", "codes"))
    for r in sorted(rows, key=lambda x: (x["run_id"], x["sample_id"])):
        doc = docs.get(r["sample_id"] + "@" + r["run_id"], {})
        s = structure(doc)
        codes = ";".join(sorted({c for _s, c in severity_pairs(r["findings"])})) or "-"
        print("%-8s %-8s %-11s %5d %5d  %s"
              % (r["sample_id"], r["logical_status"], str(doc.get("behavior_style", "?")),
                 s["nodes"], s["depth"], codes))

    print()
    print("=== VALID TREES (parameters read from the document) ===")
    print("%-8s %-11s %-4s %-3s %-9s %-9s %-6s %s"
          % ("sample", "behavior_id", "n", "d", "atk", "retreat", "hp", "actions"))
    for r in sorted(rows, key=lambda x: (x["run_id"], x["sample_id"])):
        if r["logical_status"] != "VALID":
            continue
        doc = docs.get(r["sample_id"] + "@" + r["run_id"], {})
        s = structure(doc)
        params = doc.get("parameters") or {}
        print("%-8s %-11s %-4d %-3d %-9s %-9s %-6s %s"
              % (r["sample_id"], str(doc.get("behavior_id", ""))[:11], s["nodes"], s["depth"],
                 params.get("attack_range_cm"), params.get("retreat_distance_cm"),
                 params.get("retreat_health_pct"), ",".join(sorted(a for a in s["actions"] if a))))

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        for r in sorted(rows, key=lambda x: (x["run_id"], x["sample_id"])):
            writer.writerow(r)
    print()
    print("wrote %s (%d rows)" % (OUT_CSV, total))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
