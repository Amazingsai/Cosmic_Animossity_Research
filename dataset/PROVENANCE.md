# Dataset provenance

This file records where every behaviour example in `dataset/` came from. It exists so that
synthetic planning examples can never be mistaken for experimental results.

## 1. Legacy synthetic example set (NOT experimental data)

| Field | Value |
|---|---|
| Location | `dataset/inputs/behavior_001..012_input.json`, `dataset/outputs/behavior_001..012_output.json`, `dataset/manifest.csv`, `dataset/README.md` |
| Count | 12 input/output pairs |
| Origin | Hand-authored by the project author as illustrative placeholders |
| Evidence of origin | Every output contains `"dataset_type": "synthetic_demo"` and `"source": "hand-authored illustrative example; not a recorded LLM response"`; `manifest.csv` has `data_origin = synthetic_demo` on all 12 rows; `dataset/README.md` states "SYNTHETIC DEMONSTRATION DATA ONLY" |
| Model / generation settings | None — no model was invoked |
| Permitted use | Schema design reference, prompt wording reference, validator fixtures (`--fixtures` mode, results tagged `origin=synthetic_demo`) |
| Forbidden use | Counting toward the authentic-LLM denominator (RQs 1-2), reporting as LLM output, reporting as gameplay evidence |
| File handling | Left byte-for-byte unchanged. Nothing in `dataset/inputs/` or `dataset/outputs/` is renamed, moved, or overwritten. |

### Legacy -> supported-vocabulary compatibility (verified by inspection)

18 distinct action strings and 9 distinct condition names appear across the 12 outputs.
8 actions map onto the four supported actions; 10 are unsupported or ambiguous.
3 conditions map; 6 are unsupported.

| ID | Scenario | Verdict |
|---|---|---|
| 001 | approach_and_attack | Expressible |
| 002 | retreat_low_health | Expressible; logic gap (no attack branch) |
| 003 | keep_distance | Expressible |
| 009 | cooldown_attack | Expressible; `reposition` needs a documented manual mapping |
| 008 | circle_player | Partial; `strafe_around_player` has no analogue |
| 010 | defensive_low_health | Partial; `defend` is ambiguous |
| 004 | chase_visible_player | Not expressible (visibility state absent) |
| 005 | aggressive_when_damaged | Not expressible (`recently_damaged` absent) |
| 006 | patrol_until_detected | Not expressible (`patrol`, detection absent) |
| 007 | dodge_projectiles | Not expressible (projectile detection absent) |
| 011 | react_to_player_speed | Not expressible (`player_speed`, melee absent) |
| 012 | guard_spawn_area | Not expressible (spawn-distance state absent) |

## 2. Authentic LLM output set (experimental data)

| Field | Value |
|---|---|
| Location | `dataset/raw_outputs/<run_id>/` (verbatim text) and `dataset/validated_outputs/<run_id>/` (post-correction JSON) |
| Count | 0 as of this file's last edit — the generation run has not been executed |
| Planned configuration | OpenAI `gpt-4.1`, temperature 0.7, 10 prompts x 4 generations = 40 outputs, unconstrained JSON (no structured-output mode) |
| Provenance recorded per sample | `run_id`, `sample_id`, `prompt_id`, `prompt_sha256`, `model`, `temperature`, `top_p`, `max_tokens`, `seed` (if returned), `timestamp_utc`, `raw_sha256`, HTTP status |
| Rule | Raw text is written verbatim. Invalid JSON stays in `raw_outputs/` and is never edited. Corrections only ever produce a new file under `validated_outputs/` with a `corrections[]` record. |

A sample may only be counted as authentic if its manifest row exists and `raw_sha256`
matches the preserved raw file.

## 3. Gameplay results

`results/gameplay_trials.csv` is produced only from `TRIALDATA` log lines emitted by the
in-engine trial manager at runtime (see `docs/evaluation_metrics.md`). No row may be
hand-written. Rows are tagged with `origin` = `live_pie` or `synthetic_fixture`, so a
smoke-test run can never be reported as an experimental result.
