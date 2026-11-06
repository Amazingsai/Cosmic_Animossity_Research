#!/usr/bin/env python3
"""
Behaviour prompt set + authentic generation runner (Evaluation Set 1, data collection).

Two jobs:

1. `--export-prompts` writes dataset/prompts/P01..P10.json from the PROMPTS table
   below. The prompt set is frozen before any generation so the experiment is
   reproducible.

2. `--run` performs the real generation: one OpenAI chat-completions call per
   sample, raw response text preserved verbatim, metadata recorded per sample.
   Plain (unconstrained) generation only - no response_format / json_schema mode,
   because constrained decoding would defeat the JSON-validity measurement.

   Requires OPENAI_API_KEY in the environment. The key is never written to disk.
   If the key is missing the script exits non-zero and generates nothing.

   Nothing is ever repaired here. Invalid JSON stays invalid in raw_outputs/.

Usage
  python scripts/generate_behaviors.py --export-prompts
  python scripts/generate_behaviors.py --run --model gpt-4.1 --temperature 0.7 --n 4
  python scripts/generate_behaviors.py --run --prompt-id P01 --n 1   # one prompt only
  python scripts/generate_behaviors.py --run --dry-run          # shows what would be sent

A run id is single-use. If dataset/raw_outputs/<run_id>/ already holds raw responses or
manifest rows, the run is refused (exit 2) before the key is read, before any HTTP call and
before anything is written - reusing a run id would overwrite samples and register duplicate
sample ids. Use a fresh --run-id for every attempt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

API_URL = "https://api.openai.com/v1/chat/completions"
SCHEMA_PATH = os.path.join("dataset", "schema", "behavior_schema.json")
PROMPTS_DIR = os.path.join("dataset", "prompts")
RAW_DIR = os.path.join("dataset", "raw_outputs")

# Frozen prompt set: 5 behaviour styles + 3 scenario prompts + 2 prompts derived
# from the strongest legacy synthetic examples (approach_and_attack, keep_distance).
PROMPTS = {
    "P01": ("aggressive",
            "Write a behaviour tree for an enemy that closes on the player and attacks at close range."),
    "P02": ("defensive",
            "Write a behaviour tree for an enemy that retreats when its own health is low and otherwise attacks."),
    "P03": ("tactical",
            "Write a behaviour tree for an enemy that keeps a preferred distance from the player and attacks from it."),
    "P04": ("range_based",
            "Write a behaviour tree for an enemy that behaves differently at close, medium and long range from the player."),
    "P05": ("retreating",
            "Write a behaviour tree for an enemy that disengages and backs away under specific conditions, and re-engages otherwise."),
    "P06": ("aggressive",
            "An enemy should attack whenever its weapon is ready and the player is in range, and chase otherwise."),
    "P07": ("defensive",
            "An enemy should back away when the player gets too close, and attack from a safe distance."),
    "P08": ("range_based",
            "Make a ranged enemy back away if the player is closer than 300 units, shoot between 300 and 900 units, and approach if farther."),
    "P09": ("tactical",
            "An enemy should alternate between attacking and repositioning depending on whether its weapon is ready."),
    "P10": ("retreating",
            "An enemy should retreat when health is below 30 percent, and otherwise hold distance while attacking."),
}

SYSTEM_PROMPT = """You design enemy AI for a first-person arena shooter built in Unreal Engine 5.

Return ONE JSON object and nothing else. No prose, no markdown fences.

The object describes a behaviour tree with this exact structure:

{
  "schema_version": "2.0",
  "behavior_id": "<lowercase letters, digits, underscores; 3-32 chars>",
  "behavior_style": "<one of: aggressive, defensive, tactical, range_based, retreating>",
  "source_prompt_id": "<the prompt id given to you, e.g. P03>",
  "description": "<one sentence>",
  "root": <node>,
  "parameters": {
    "attack_range_cm": <number 100-4000>,
    "retreat_distance_cm": <number 100-4000, must be greater than attack_range_cm>,
    "retreat_health_pct": <number 0-1>
  }
}

A <node> is one of:

  { "node_id": "n0", "type": "selector", "children": [<node>, <node>] }
  { "node_id": "n1", "type": "sequence", "children": [<node>, <node>] }
  { "node_id": "n2", "type": "action", "action": "<action>" }

Any node except the root may also carry ONE condition:
  "condition": { "test": "<test>", "op": "<operator>", "value": <number or boolean> }

A selector runs its children in order and uses the first that succeeds.
A sequence runs its children in order and fails as soon as one fails.
A condition on a node gates that node: it only runs while the condition holds.

supported actions (use no others):
  move_to_target          walk toward the player
  move_away_from_target   walk away from the player
  attack                  fire the enemy's projectile weapon at the player
  wait                    stand still for a moment

supported tests (use no others):
  distance_to_target      distance to the player in centimetres, 0-10000
  health_percent          the enemy's own health as 0-1
  can_attack              true when the weapon cooldown has elapsed (boolean)

operators:  <  <=  >  >=  for distances and health;  ==  !=  for can_attack.

Rules:
- 2 to 5 children per selector or sequence. Maximum tree depth 5, maximum 15 nodes.
- node_id values must be unique and look like n0, n1, ... n14.
- The root must be a selector or a sequence, and must not carry a condition.
- Every number must respect the ranges above. Do not invent state the engine does not have
  (visibility, last known position, patrol routes, projectile dodging, player speed).
"""


def load_schema_text():
    with open(SCHEMA_PATH, encoding="utf-8") as fh:
        return fh.read()


def user_message(prompt_id, prompt_text):
    return ("Prompt id: %s\n\n%s\n\nJSON schema (for reference only; do not echo it back):\n%s"
            % (prompt_id, prompt_text, load_schema_text()))


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def export_prompts():
    os.makedirs(PROMPTS_DIR, exist_ok=True)
    for pid, (style, text) in PROMPTS.items():
        payload = {
            "prompt_id": pid,
            "behavior_style": style,
            "prompt": text,
            "system_prompt_sha256": sha256(SYSTEM_PROMPT),
            "schema_sha256": sha256(load_schema_text()),
            "prompt_sha256": sha256(text),
        }
        path = os.path.join(PROMPTS_DIR, "%s.json" % pid)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
            fh.write("\n")
        print("wrote %s" % path)


def call_openai(api_key, model, temperature, messages, max_tokens, seed=None, timeout=120):
    body = {"model": model, "temperature": temperature, "max_tokens": max_tokens, "messages": messages}
    if seed is not None:
        body["seed"] = seed
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer %s" % api_key},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    text = payload["choices"][0]["message"]["content"]
    usage = payload.get("usage", {})
    return text, usage, payload.get("model", model), payload.get("system_fingerprint")


def run_dir_conflicts(out_dir):
    """Paths that make this run id unusable, because writing would destroy or duplicate data.

    A directory is a conflict when it holds raw responses (a new sample would reopen
    "<sample_id>.txt" with mode "w") or a manifest that already has data rows (the new sample
    would be appended under a sample_id that is already recorded). A manifest holding only the
    header row is not generation data, so a run may legitimately continue into it.
    """
    if not os.path.isdir(out_dir):
        return []
    conflicts = []
    for base, _dirs, files in os.walk(out_dir):
        for name in sorted(files):
            if name.lower().endswith(".txt"):
                conflicts.append(os.path.join(base, name))
    manifest_path = os.path.join(out_dir, "manifest.csv")
    if os.path.exists(manifest_path):
        with open(manifest_path, encoding="utf-8", errors="replace", newline="") as fh:
            rows = [line for line in fh.read().splitlines() if line.strip()]
        if len(rows) > 1:                           # header only == nothing recorded yet
            conflicts.append(manifest_path)
    return conflicts


def run(args):
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = os.path.join(RAW_DIR, run_id)

    # Integrity guard: a run id is single-use. Refuse before the key is read, before any HTTP
    # call and before os.makedirs, so a rejected run touches neither the network nor the disk.
    conflicts = run_dir_conflicts(out_dir)
    if conflicts:
        print("REFUSED: run id %r already contains generation data. No API calls were made "
              "and nothing was written." % run_id, file=sys.stderr)
        for path in conflicts:
            print("    %s" % path, file=sys.stderr)
        print("Choose a new --run-id, or move the existing run directory aside first.",
              file=sys.stderr)
        sys.exit(2)

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        sys.exit("ERROR: OPENAI_API_KEY is not set. Nothing was generated. "
                 "Export the key in this shell, then re-run. Never commit the key.")

    os.makedirs(out_dir, exist_ok=True)
    manifest_path = os.path.join(out_dir, "manifest.csv")
    new_manifest = not os.path.exists(manifest_path)

    sample_no = 0
    with open(manifest_path, "a", newline="", encoding="utf-8") as manifest:
        if new_manifest:
            manifest.write("run_id,sample_id,prompt_id,behavior_style,model,temperature,max_tokens,"
                           "seed,timestamp_utc,prompt_sha256,raw_sha256,response_model,system_fingerprint,"
                           "prompt_tokens,completion_tokens,http_status\n")
        for pid, (style, text) in PROMPTS.items():
            if args.prompt_id and pid != args.prompt_id:
                continue
            for generation in range(args.n):
                sample_no += 1
                sample_id = "%s-G%02d" % (pid, generation + 1)
                messages = [{"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_message(pid, text)}]
                if args.dry_run:
                    print("[dry-run] %s model=%s temperature=%s" % (sample_id, args.model, args.temperature))
                    continue
                seed = args.seed + sample_no if args.seed is not None else None
                started = datetime.now(timezone.utc).isoformat()
                try:
                    raw, usage, response_model, fingerprint = call_openai(
                        api_key, args.model, args.temperature, messages, args.max_tokens, seed)
                    status = 200
                except urllib.error.HTTPError as exc:
                    raw = "HTTP_ERROR %s\n%s" % (exc.code, exc.read().decode("utf-8", "replace"))
                    usage, response_model, fingerprint, status = {}, args.model, "", exc.code
                except Exception as exc:                    # network / timeout
                    raw = "TRANSPORT_ERROR %s" % exc
                    usage, response_model, fingerprint, status = {}, args.model, "", 0

                raw_path = os.path.join(out_dir, "%s.txt" % sample_id)
                with open(raw_path, "w", encoding="utf-8", newline="") as fh:
                    fh.write(raw)                            # verbatim, never edited
                manifest.write(",".join(str(v) for v in [
                    run_id, sample_id, pid, style, args.model, args.temperature, args.max_tokens,
                    "" if seed is None else seed, started, sha256(text), sha256(raw),
                    response_model, fingerprint, usage.get("prompt_tokens", ""),
                    usage.get("completion_tokens", ""), status]) + "\n")
                manifest.flush()
                print("%s -> %s (%d chars, status %s)" % (sample_id, raw_path, len(raw), status))
                if args.sleep:
                    time.sleep(args.sleep)

    if not args.dry_run:
        print("Raw outputs: %s" % out_dir)
        print("Manifest:    %s" % manifest_path)
        print("Next: python scripts/validate_behaviors.py --inputs %s --run-id %s" % (out_dir, run_id))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Prompt set + OpenAI generation runner.")
    parser.add_argument("--export-prompts", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--model", default="gpt-4.1")
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--max-tokens", type=int, default=900)
    parser.add_argument("--n", type=int, default=4, help="generations per prompt")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--prompt-id", default=None,
                        help="generate only this prompt id (e.g. P01); omit to generate all ten")
    parser.add_argument("--sleep", type=float, default=0.0, help="seconds between calls")
    args = parser.parse_args(argv)

    if args.export_prompts:
        export_prompts()
        return 0
    if args.run:
        if args.prompt_id and args.prompt_id not in PROMPTS:
            parser.error("--prompt-id %s is not in the frozen prompt set (%s)"
                         % (args.prompt_id, ", ".join(sorted(PROMPTS))))
        run(args)
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
