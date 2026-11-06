# Methodology — LLM-generated enemy behaviour in Cosmic Animosity

Module: DS 340W research project. Engine: Unreal Engine 5.7. Project: Cosmic Animosity
(Blueprint-only; no C++ module).

## Research questions

**RQ1 Generation reliability.** How reliably can an LLM produce behaviour specifications
that are syntactically valid, structurally valid, expressible in the project's action space,
and logically coherent?

**RQ2 Gameplay effectiveness.** When implemented in Unreal Engine, how do LLM-generated
behaviours perform on shared combat metrics compared with the existing hand-built baseline
enemy, and how well do they satisfy their *own* specification?

## Conditions and controls

| Element | Role | File |
|---|---|---|
| `BP_AICharacter` | Control group. Hand-built enemy, unmodified. | `Content/FirstPerson/Blueprints/AI/BP_AICharacter` |
| `BP_BasicEnemyAI` | Experimental enemy. One Blueprint, behaviour chosen by data. | `Content/FirstPerson/Blueprints/AI/BP_BasicEnemyAI` |
| `BP_WeaponBase` / `BP_Projectile` | Shared combat implementation. Unmodified; both enemies use it. | `Content/FirstPerson/Blueprints/Weapons/` |
| `DT_CharacterData` | Shared stat table (`Enemy` row: 500 HP, 500 cm/s). Unmodified. | `Content/FirstPerson/Blueprints/DT_CharacterData` |

The baseline is never edited. The experimental enemy reuses the same weapon and projectile
classes, so ballistics, damage application and the `IN_GenericActions.SendDamage` chain are
identical by construction; any remaining differences are measured and reported (see
`docs/evaluation_metrics.md`, "Combat parity").

## Action space (4) and condition space (3)

Actions: `move_to_target`, `move_away_from_target`, `attack`, `wait`.
Conditions: `distance_to_target` (cm), `health_percent` (0-1), `can_attack` (bool, weapon
cooldown).

The space is deliberately minimal. Behaviours such as "tactical kiting" are expressed as a
*composition* of move/retreat/attack under distance conditions, so the experiment measures
the model's behavioural logic rather than its ability to invent vocabulary. The legacy
synthetic examples in `dataset/inputs` and `dataset/outputs` are the evidence for this
choice: of 18 action names and 9 condition names used there, only 8 and 3 respectively map
onto engine-implementable primitives (see `dataset/PROVENANCE.md`).

## Data collection pipeline

```
dataset/prompts/P01..P10.json      frozen prompt set
        |  scripts/generate_behaviors.py --run --model gpt-4.1 --temperature 0.7 --n 4
        v
dataset/raw_outputs/<run>/G##.txt  verbatim responses + manifest.csv (model, settings, hashes)
        |  scripts/validate_behaviors.py
        v
results/generation_validation.csv  M1-M5 per output
        |  manual review queue for AMBIGUOUS findings
        v
dataset/validated_outputs/<run>/   corrected copies + corrections[] (originals untouched)
        |  manual implementation as Unreal Behaviour Tree (documented in implementation_log.csv)
        v
TRIALDATA log lines at runtime   ->  scripts/analyze_results.py  ->  results/gameplay_trials.csv
```

Generation is unconstrained: no `response_format`/JSON-schema decoding, because constrained
decoding would guarantee validity and invalidate RQ1. One model, one temperature, one prompt
set for the whole main experiment. Keys are read from the environment; `.env` is git-ignored.

## Provenance rules

1. A raw response is authentic only if a manifest row exists whose `raw_sha256` matches the
   preserved file.
2. Raw outputs are never edited; corrections create new files with a `corrections[]` record.
3. The 12 legacy examples are `synthetic_demo`, excluded from every denominator, and used
   only as validator fixtures and schema-design evidence.
4. No gameplay row is hand-written. Every row in `results/gameplay_trials.csv` is derived
   from `TRIALDATA` lines emitted by the engine at runtime, tagged `origin=live_pie` or
   `origin=synthetic_fixture`.

## Implementation fidelity

For every implemented behaviour the project records: original JSON, final tree, every
condition/action change, every technical adaptation, logic corrections, implementation and
debug time, and whether the original generated logic is preserved. Deviations are logged as
they happen; a behaviour that cannot be represented in the action space is reported as such
rather than silently redesigned.

## Threats to validity (acknowledged)

- One model, one temperature: reliability is specific to `gpt-4.1` at 0.7, not to LLMs generally.
- N=40 gives coarse confidence intervals; percentages are reported with denominators.
- The experimental enemy reacts on BT evaluation ticks (service interval 0.05 s), so reaction
  time includes engine evaluation latency, not human reaction.
- The baseline fires from its own Tick/AI-MoveTo-success path, so its firing cadence differs
  structurally from a BT-driven `attack` task. Shared metrics are therefore damage, survival
  time, and accuracy; "behaviour correctness" is only scored against each experimental
  behaviour's own specification and is never applied to the baseline.
