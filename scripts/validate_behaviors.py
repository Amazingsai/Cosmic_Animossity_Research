#!/usr/bin/env python3
"""
Evaluation Set 1 - JSON generation and validation.

Scores every behaviour document against dataset/schema/behavior_schema.json and
writes results/generation_validation.csv. This script NEVER modifies an input: it
scores the bytes it was given and records what a correct version would need.

Metrics
  M1 JSON validity       strict parse of the raw text
  M2 structural          required keys, types, node ids, depth/size limits
  M3 action validity     every action is one of the four supported actions
  M4 logical correctness deterministic rules only; genuinely ambiguous cases are
                         flagged for MANUAL REVIEW instead of being called wrong
  M5 correction rate     none / minimal / mapping / logic / impossible

Unreachability policy
  A BT selector runs child i and, if it FAILS, continues to child i+1. Therefore
  two siblings sharing a condition are NOT proof that the later one is
  unreachable - the earlier action can fail and execution falls through.
  Duplicate/overlapping sibling conditions are reported AMBIGUOUS (shadowing
  risk) for manual review.

  A branch is marked invalid ONLY when unreachability is provable, which happens
  in exactly two ways here:
    * two conditions on the same test along one path (ancestor chain included)
      whose value sets do not intersect, so the path can never run;
    * a tree that contains no action, or contains nothing but wait actions.

Usage
  python validate_behaviors.py --inputs dataset/raw_outputs --results results
  python validate_behaviors.py --legacy-fixtures
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime, timezone

ACTIONS = {"move_to_target", "move_away_from_target", "attack", "wait"}
STRUCT_TYPES = {"selector", "sequence"}
TESTS = {"distance_to_target", "health_percent", "can_attack"}
NUM_OPS = {"<", "<=", ">", ">=", "==", "!="}
BOOL_OPS = {"==", "!="}
STYLES = {"aggressive", "defensive", "tactical", "range_based", "retreating"}
MAX_DEPTH, MAX_NODES, MIN_CHILDREN, MAX_CHILDREN = 5, 15, 2, 5
DOMAIN = {"distance_to_target": (0.0, 10000.0), "health_percent": (0.0, 1.0)}
NODE_ID_RE = re.compile(r"^n[0-9]{1,2}$")
BEHAVIOR_ID_RE = re.compile(r"^[a-z0-9_]{3,32}$")
PROMPT_ID_RE = re.compile(r"^P[0-9]{2}$")

FAIL, AMBIGUOUS, WARN = "FAIL", "AMBIGUOUS", "WARN"
INF = float("inf")

LEGACY_ACTION_MAP = {
    "move_toward_player": "move_to_target",
    "chase_player": "move_to_target",
    "engage_player": "move_to_target",
    "retreat_from_player": "move_away_from_target",
    "attack_player": "attack",
    "ranged_attack": "attack",
    "aggressive_attack": "attack",
    "normal_attack": "attack",
}
LEGACY_AMBIGUOUS_ACTIONS = {
    "melee_attack", "reposition", "continue_combat", "defend", "guard_area",
    "strafe_around_player", "dodge", "patrol", "move_to_last_known_player_location",
    "return_to_spawn",
}
LEGACY_CONDITION_MAP = {
    "player_distance": "distance_to_target",
    "enemy_health_percent": "health_percent",
    "attack_ready": "can_attack",
}


class Finding:
    __slots__ = ("code", "severity", "where", "message")

    def __init__(self, code, severity, where, message):
        self.code, self.severity, self.where, self.message = code, severity, where, message


def strip_fences(text):
    """Return (clean_text, correction_name_or_None). Models often wrap JSON in fences."""
    s = text.strip()
    if not s.startswith("```"):
        return text, None
    lines = s.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines), "strip_markdown_fence"


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def numeric_set(test, op, value):
    """
    The set of values satisfying 'test op value' as a list of closed (lo, hi)
    intervals, clamped to the test's domain. '!=' yields two intervals.
    """
    lo_d, hi_d = DOMAIN[test]
    v = max(lo_d, min(hi_d, float(value)))
    if op == "<":
        return [(lo_d, v - 0.0)] if v > lo_d else []
    if op == "<=":
        return [(lo_d, v)]
    if op == ">":
        return [(v, hi_d)]
    if op == ">=":
        return [(v, hi_d)]
    if op == "==":
        return [(v, v)]
    if op == "!=":
        parts = []
        if v > lo_d:
            parts.append((lo_d, v))
        if v < hi_d:
            parts.append((v, hi_d))
        # '!=' excludes only the single point v; keep the two half-open sides
        return parts
    return [(lo_d, hi_d)]


def intersect(a, b):
    out = []
    for alo, ahi in a:
        for blo, bhi in b:
            lo, hi = max(alo, blo), min(ahi, bhi)
            if lo <= hi:
                out.append((lo, hi))
    return out


def set_is_empty(intervals):
    return not intervals


def covers_domain(intervals, test):
    """True when the union of intervals covers the whole domain of the test."""
    lo_d, hi_d = DOMAIN[test]
    ordered = sorted(intervals)
    cursor = lo_d
    for lo, hi in ordered:
        if lo > cursor:
            return False
        cursor = max(cursor, hi)
        if cursor >= hi_d:
            return True
    return cursor >= hi_d


def condition_set(cond):
    """Normalised value set of a validated condition, or None when not numerically comparable."""
    test = cond.get("test")
    if test in DOMAIN and is_number(cond.get("value")):
        return numeric_set(test, cond.get("op"), cond["value"])
    return None


def validate_condition(cond, where, findings):
    if not isinstance(cond, dict):
        findings.append(Finding("C0", FAIL, where, "condition must be an object"))
        return None
    extra = set(cond) - {"test", "op", "value"}
    if extra:
        findings.append(Finding("C0", FAIL, where, "unexpected condition keys: %s" % sorted(extra)))
    test, op, value = cond.get("test"), cond.get("op"), cond.get("value")
    if test not in TESTS:
        findings.append(Finding("C1", FAIL, where, "unsupported condition test %r" % (test,)))
        return None
    if test == "can_attack":
        if op not in BOOL_OPS:
            findings.append(Finding("C2", FAIL, where, "can_attack supports only == / !=, got %r" % (op,)))
        if not isinstance(value, bool):
            findings.append(Finding("C2", FAIL, where, "can_attack value must be boolean, got %r" % (value,)))
        return {"test": test, "op": op, "value": value}
    if op not in NUM_OPS:
        findings.append(Finding("C2", FAIL, where, "operator %r invalid for numeric test" % (op,)))
        return None
    if not is_number(value):
        findings.append(Finding("C3", FAIL, where, "value must be numeric, got %r" % (value,)))
        return None
    lo, hi = DOMAIN[test]
    if not (lo <= value <= hi):
        findings.append(Finding("C3", FAIL, where,
                                "value %s outside domain [%s, %s] for %s" % (value, lo, hi, test)))
        return None
    if op in ("==", "!=") and test in DOMAIN:
        findings.append(Finding("C4", AMBIGUOUS, where,
                                "exact %s %s %s on a continuous value; float equality is fragile"
                                % (test, op, value)))
    return {"test": test, "op": op, "value": value}


def path_is_unsatisfiable(path_conditions):
    """True when two conditions on the same numeric test along one path cannot both hold."""
    per_test = {}
    for c in path_conditions:
        if not c or c.get("test") not in DOMAIN:
            continue
        s = condition_set(c)
        if s is None:
            continue
        t = c["test"]
        per_test[t] = s if t not in per_test else intersect(per_test[t], s)
        if set_is_empty(per_test[t]):
            return t
    return None


def walk(node, depth, path, findings, state, inherited=()):
    if not isinstance(node, dict):
        findings.append(Finding("S0", FAIL, path, "node must be an object"))
        return
    state["count"] += 1
    if state["count"] > MAX_NODES:
        findings.append(Finding("S4", FAIL, path, "tree exceeds %d nodes" % MAX_NODES))
    if depth > MAX_DEPTH:
        findings.append(Finding("S4", FAIL, path, "depth %d exceeds %d" % (depth, MAX_DEPTH)))

    node_id = node.get("node_id")
    if not isinstance(node_id, str) or not NODE_ID_RE.match(node_id):
        findings.append(Finding("S2", FAIL, path, "node_id must look like n1 / n12, got %r" % (node_id,)))
    elif node_id in state["ids"]:
        findings.append(Finding("S2", FAIL, path, "duplicate node_id %r" % node_id))
    else:
        state["ids"].add(node_id)

    extra = set(node) - {"node_id", "type", "condition", "children", "action", "wait_seconds"}
    if extra:
        findings.append(Finding("S0", FAIL, path, "unexpected keys: %s" % sorted(extra)))

    cond_here = None
    if node.get("condition") is not None:
        if depth == 0:
            findings.append(Finding("S6", FAIL, path, "root must not carry a condition"))
        cond_here = validate_condition(node["condition"], path, findings)

    path_conditions = list(inherited) + ([cond_here] if cond_here else [])
    broken = path_is_unsatisfiable(path_conditions)
    if broken and cond_here is not None:
        findings.append(Finding("L2", FAIL, path,
                                "unsatisfiable %s conditions along this path (ancestors included), "
                                "so this branch can never run" % broken))

    ntype = node.get("type")

    if ntype in STRUCT_TYPES:
        children = node.get("children")
        if not isinstance(children, list):
            findings.append(Finding("S1", FAIL, path, "structure node requires a children array"))
            return
        if not (MIN_CHILDREN <= len(children) <= MAX_CHILDREN):
            findings.append(Finding("S1", FAIL, path, "%d children, must be %d-%d"
                                    % (len(children), MIN_CHILDREN, MAX_CHILDREN)))
        if len(children) == 1:
            findings.append(Finding("S3", WARN, path, "single-child composite is redundant"))

        sibling = [c.get("condition") for c in children
                   if isinstance(c, dict) and isinstance(c.get("condition"), dict)]
        keys = [(c.get("test"), c.get("op"), c.get("value")) for c in sibling]
        if len(keys) > 1 and len(keys) != len(set(keys)):
            findings.append(Finding("L3", AMBIGUOUS, path,
                                    "duplicate sibling conditions: shadowing risk only, NOT unreachable "
                                    "(a failing child falls through), manual review required"))

        if ntype == "selector" and len(sibling) == len(children) and children:
            tests = {c.get("test") for c in sibling}
            if len(tests) == 1:
                t = next(iter(tests))
                if t in DOMAIN:
                    intervals = []
                    for c in sibling:
                        intervals.extend(condition_set(c) or [])
                    if not covers_domain(intervals, t):
                        findings.append(Finding("L4", AMBIGUOUS, path,
                                                "selector has no unconditional child and its %s conditions do "
                                                "not cover the domain, so the tree can stall" % t))

        for i, child in enumerate(children):
            child_path = "%s/%s" % (path, (child or {}).get("node_id", i) if isinstance(child, dict) else i)
            walk(child, depth + 1, child_path, findings, state, path_conditions)
        return

    if ntype == "action":
        action = node.get("action")
        if action not in ACTIONS:
            findings.append(Finding("A1", FAIL, path, "unsupported action %r" % (action,)))
        else:
            state["actions"].append(action)
        if "children" in node:
            findings.append(Finding("S1", FAIL, path, "action node must not have children"))
        if "wait_seconds" in node:
            w = node["wait_seconds"]
            if not is_number(w) or not (0.1 <= w <= 3.0):
                findings.append(Finding("A2", FAIL, path, "wait_seconds must be 0.1-3.0"))
            elif action != "wait":
                findings.append(Finding("A2", WARN, path, "wait_seconds on a non-wait action is ignored"))

        guarded = [c for c in path_conditions if c and c.get("test") == "distance_to_target"]
        if action == "attack" and not guarded:
            findings.append(Finding("L5", AMBIGUOUS, path,
                                    "attack is not guarded by any distance_to_target condition on its path; "
                                    "weapon range is 5000 cm so it may fire far out of intended range"))
        if action == "move_away_from_target" and not path_conditions:
            findings.append(Finding("L6", AMBIGUOUS, path,
                                    "unbounded retreat: no condition anywhere on this path"))
        state["action_paths"].append((action, path, cond_here))
        return

    findings.append(Finding("S1", FAIL, path, "unknown node type %r" % (ntype,)))


def node_index(node, index=None):
    """node_id -> intended action, used to pair gameplay events against the spec."""
    index = {} if index is None else index
    if isinstance(node, dict):
        if node.get("type") == "action" and isinstance(node.get("action"), str):
            index[node.get("node_id")] = node["action"]
        for child in node.get("children") or []:
            node_index(child, index)
    return index


def validate_document(raw_text, identifiers):
    findings, corrections = [], []
    clean, fence_fix = strip_fences(raw_text)
    if fence_fix:
        corrections.append(fence_fix)

    try:
        doc = json.loads(clean)
    except Exception as exc:
        findings.append(Finding("M1", FAIL, "/", "invalid JSON: %s" % exc))
        return _result(identifiers, findings, corrections, None)

    if not isinstance(doc, dict):
        findings.append(Finding("M1", FAIL, "/", "top-level JSON must be an object"))
        return _result(identifiers, findings, corrections, doc)

    required = {"schema_version", "behavior_id", "behavior_style", "root", "parameters"}
    missing = required - set(doc)
    if missing:
        findings.append(Finding("S0", FAIL, "/", "missing required keys: %s" % sorted(missing)))
    extra = set(doc) - required - {"source_prompt_id", "description"}
    if extra:
        findings.append(Finding("S0", FAIL, "/", "unexpected top-level keys: %s" % sorted(extra)))

    if doc.get("schema_version") != "2.0":
        findings.append(Finding("S0", FAIL, "/", "schema_version must be '2.0', got %r"
                                % (doc.get("schema_version"),)))
    if not isinstance(doc.get("behavior_id"), str) or not BEHAVIOR_ID_RE.match(doc.get("behavior_id") or ""):
        findings.append(Finding("S0", FAIL, "/", "behavior_id must match ^[a-z0-9_]{3,32}$"))
    if doc.get("behavior_style") not in STYLES:
        findings.append(Finding("S0", FAIL, "/", "behavior_style must be one of %s" % sorted(STYLES)))
    if "source_prompt_id" in doc and not PROMPT_ID_RE.match(str(doc["source_prompt_id"])):
        findings.append(Finding("S0", WARN, "/", "source_prompt_id should look like 'P03'"))

    params = doc.get("parameters")
    if not isinstance(params, dict):
        findings.append(Finding("S5", FAIL, "/parameters", "parameters must be an object"))
    else:
        for key, lo, hi in (("attack_range_cm", 100, 4000), ("retreat_distance_cm", 100, 4000),
                            ("retreat_health_pct", 0.0, 1.0)):
            v = params.get(key)
            if not is_number(v):
                findings.append(Finding("S5", FAIL, "/parameters", "%s missing or not numeric" % key))
            elif not (lo <= v <= hi):
                findings.append(Finding("S5", FAIL, "/parameters", "%s=%s outside [%s, %s]" % (key, v, lo, hi)))
        a, r = params.get("attack_range_cm"), params.get("retreat_distance_cm")
        if is_number(a) and is_number(r) and r <= a:
            findings.append(Finding("S5", FAIL, "/parameters",
                                    "retreat_distance_cm (%s) must exceed attack_range_cm (%s)" % (r, a)))

    root = doc.get("root")
    if not isinstance(root, dict):
        findings.append(Finding("S1", FAIL, "/root", "root must be an object"))
    else:
        if root.get("type") not in STRUCT_TYPES:
            findings.append(Finding("L7", FAIL, "/root", "root must be a selector or sequence, not %r"
                                    % (root.get("type"),)))
        state = {"count": 0, "ids": set(), "actions": [], "action_paths": []}
        walk(root, 0, "/root", findings, state)
        if not state["actions"]:
            findings.append(Finding("L1", FAIL, "/root", "tree contains no action"))
        elif all(a == "wait" for a in state["actions"]):
            findings.append(Finding("L1", FAIL, "/root", "tree does nothing but wait"))

        if isinstance(params, dict) and is_number(params.get("attack_range_cm")):
            for action, path, cond in state["action_paths"]:
                if action == "attack" and cond and cond.get("test") == "distance_to_target" \
                        and is_number(cond.get("value")):
                    if abs(float(cond["value"]) - float(params["attack_range_cm"])) > 200:
                        findings.append(Finding("L8", WARN, path,
                                                "attack threshold %s differs from attack_range_cm %s by >200cm"
                                                % (cond["value"], params["attack_range_cm"])))

    return _result(identifiers, findings, corrections, doc)


def _result(identifiers, findings, corrections, doc):
    severities = [f.severity for f in findings]
    result = dict(identifiers)
    result.update({
        "json_valid": 0 if any(f.code == "M1" for f in findings) else 1,
        "structural_valid": 0 if any(f.code.startswith("S") for f in findings) else 1,
        "actions_valid": 0 if any(f.code.startswith("A") for f in findings) else 1,
        "logical_status": "INVALID" if FAIL in severities else ("REVIEW" if AMBIGUOUS in severities else "VALID"),
        "manual_review": 1 if AMBIGUOUS in severities else 0,
        "finding_codes": ";".join(sorted({f.code for f in findings})),
        "findings": " | ".join("%s:%s:%s" % (f.severity, f.code, f.message) for f in findings),
        "auto_corrections": ";".join(corrections),
        "behavior_id": (doc or {}).get("behavior_id", "") if isinstance(doc, dict) else "",
        "schema_version": (doc or {}).get("schema_version", "") if isinstance(doc, dict) else "",
    })
    return result


def correction_class(result):
    """M5 bucket, most severe first: impossible > logic > mapping > minimal > none."""
    codes = set((result.get("finding_codes") or "").split(";")) - {""}
    if not result["json_valid"]:
        return "logic"          # cannot be used without re-generating the structure
    if any(c.startswith("S") for c in codes) or {"L2", "L7", "L1"} & codes:
        return "logic"
    if "A1" in codes:
        return "mapping"        # out-of-vocabulary name bound to a supported action
    if result["manual_review"]:
        return "mapping"
    if result["auto_corrections"]:
        return "minimal"
    return "none"


RAW_SUFFIXES = (".json", ".txt")


def iter_json_files(path):
    """Yield candidate documents. Raw LLM outputs are written as verbatim .txt by
    generate_behaviors.py; hand-authored fixtures are .json. Both are scored the same way."""
    if os.path.isfile(path):
        yield path
        return
    for root, _dirs, files in os.walk(path):
        for name in sorted(files):
            if name.lower().endswith(RAW_SUFFIXES):
                yield os.path.join(root, name)


def run_specs(inputs, run_id):
    rows = []
    for path in iter_json_files(inputs):
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
        res = validate_document(raw, {"file": os.path.relpath(path).replace("\\", "/"),
                                      "origin": "llm", "run_id": run_id})
        res["correction_class"] = correction_class(res)
        rows.append(res)
    return rows


def write_csv(rows, path, fieldnames):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def summarize(rows, label):
    total = len(rows)
    if not total:
        return "%s: no documents evaluated" % label
    def pct(v):
        return "%.1f%%" % (100.0 * v / total)
    json_ok = sum(r["json_valid"] for r in rows)
    struct_ok = sum(r["structural_valid"] for r in rows)
    act_ok = sum(r["actions_valid"] for r in rows)
    valid = sum(1 for r in rows if r["logical_status"] == "VALID")
    review = sum(1 for r in rows if r["logical_status"] == "REVIEW")
    changed = sum(1 for r in rows if r["correction_class"] != "none")
    lines = [
        "%s: N=%d" % (label, total),
        "  M1 JSON valid .......... %d/%d (%s)" % (json_ok, total, pct(json_ok)),
        "  M2 structural valid .... %d/%d (%s)" % (struct_ok, total, pct(struct_ok)),
        "  M3 actions valid ....... %d/%d (%s)" % (act_ok, total, pct(act_ok)),
        "  M4 logically valid ..... %d/%d (%s)   manual review: %d" % (valid, total, pct(valid), review),
        "  M5 needs correction .... %d/%d (%s)" % (changed, total, pct(changed)),
    ]
    for cls in ("minimal", "mapping", "logic", "impossible"):
        count = sum(1 for r in rows if r["correction_class"] == cls)
        if count:
            lines.append("      %-10s %d" % (cls, count))
    return "\n".join(lines)


def legacy_fixture_rows(dataset_dir):
    """Convert the 12 hand-authored synthetic examples to schema shape in memory and score them."""
    rows = []
    legacy_dir = os.path.join(dataset_dir, "outputs")
    if not os.path.isdir(legacy_dir):
        return rows
    for name in sorted(os.listdir(legacy_dir)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(legacy_dir, name), encoding="utf-8") as fh:
            doc = json.load(fh)
        children, node_no, unsupported = [], 0, []
        for rule in doc.get("rules", []):
            cond = None
            for raw in [c.strip() for c in str(rule.get("condition", "")).split(" and ")]:
                key = raw.split()[0] if raw else ""
                mapped = LEGACY_CONDITION_MAP.get(key)
                if not mapped or cond is not None:
                    continue
                op = next((o for o in ("<=", ">=", "<", ">", "==") if o in raw), None)
                if not op:
                    continue
                try:
                    val = float(raw.split(op)[-1].strip())
                except Exception:
                    continue
                if mapped == "health_percent":
                    val /= 100.0
                if mapped == "can_attack":
                    continue
                cond = {"test": mapped, "op": op, "value": val}
            action = LEGACY_ACTION_MAP.get(rule.get("action"))
            if action is None:
                unsupported.append(rule.get("action"))
            node_no += 1
            child = {"node_id": "n%d" % node_no, "type": "action", "action": action or "wait"}
            if cond:
                child["condition"] = cond
            children.append(child)
        shaped = {
            "schema_version": "2.0",
            "behavior_id": doc.get("id", name).replace("behavior_", "legacy_"),
            "behavior_style": "aggressive",
            "source_prompt_id": "P00",
            "root": {"node_id": "n0", "type": "selector", "children": children or [
                {"node_id": "n1", "type": "action", "action": "move_to_target"},
                {"node_id": "n2", "type": "action", "action": "wait"}]},
            "parameters": {"attack_range_cm": 500, "retreat_distance_cm": 1500, "retreat_health_pct": 0.3},
        }
        res = validate_document(json.dumps(shaped),
                                {"file": name, "origin": "synthetic_demo", "run_id": "legacy_fixture"})
        res["correction_class"] = "mapping" if unsupported else correction_class(res)
        if unsupported:
            res["findings"] += " | legacy unsupported actions: %s" % ",".join(sorted(set(map(str, unsupported))))
        rows.append(res)
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate generated behaviour trees (Evaluation Set 1).")
    parser.add_argument("--inputs", default="dataset/raw_outputs")
    parser.add_argument("--results", default="results")
    parser.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    parser.add_argument("--legacy-fixtures", action="store_true",
                        help="score the 12 synthetic examples as schema fixtures (never counted as LLM data)")
    args = parser.parse_args(argv)

    if args.legacy_fixtures:
        rows = legacy_fixture_rows("dataset")
        out = os.path.join(args.results, "validator_fixtures_synthetic.csv")
        label = "Legacy synthetic fixtures (excluded from RQ1 denominators)"
        empty_cause = "dataset/outputs/ holds no *.json fixtures"
    else:
        rows = run_specs(args.inputs, args.run_id)
        out = os.path.join(args.results, "generation_validation.csv")
        label = "LLM generations (run %s)" % args.run_id
        if not os.path.exists(args.inputs):
            empty_cause = "the --inputs path %r does not exist" % args.inputs
        else:
            empty_cause = ("no files ending in %s were found under %r"
                           % (" / ".join(RAW_SUFFIXES), args.inputs))

    # A silent zero is indistinguishable from success: an empty directory, a mistyped path and a
    # wrong extension filter all produced "no documents evaluated" with exit code 0 in Phase 5D.
    # Fail loudly, return non-zero, and write nothing so an earlier run's results survive.
    if not rows:
        print("ERROR: no documents were evaluated, so there is nothing to score.", file=sys.stderr)
        print("       Cause: %s." % empty_cause, file=sys.stderr)
        print("       %s was not written; any existing copy is unchanged. Exit code 2." % out,
              file=sys.stderr)
        return 2

    fields = ["file", "origin", "run_id", "behavior_id", "schema_version", "json_valid",
              "structural_valid", "actions_valid", "logical_status", "manual_review",
              "correction_class", "finding_codes", "findings", "auto_corrections"]
    write_csv(rows, out, fields)
    print(summarize(rows, label))
    print("CSV: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
