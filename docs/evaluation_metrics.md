# Evaluation metrics

Two evaluation sets. Every definition below states its denominator explicitly, because the
research questions are about rates, not counts.

## Evaluation Set 1 — JSON generation and validation

Scored by `scripts/validate_behaviors.py` over `dataset/raw_outputs/<run>/`.
Denominator for all rates: **N = number of evaluated raw generations** (target 40).

| Metric | Definition | Output column |
|---|---|---|
| M1 JSON validity | `json.loads` succeeds on the verbatim text (markdown fences stripped and recorded as a minimal correction) | `json_valid` |
| M2 Structural validity | required keys, types, `node_id` uniqueness/format, depth <= 5, nodes <= 15, children 2-5, parameters present and in range | `structural_valid` |
| M3 Action validity | every `action` is one of the four supported actions | `actions_valid` |
| M4 Logical correctness | deterministic rules only. `VALID` = no findings; `REVIEW` = only AMBIGUOUS findings queued for manual review; `INVALID` = at least one provable defect | `logical_status`, `manual_review`, `findings` |
| M5 Correction rate | share of outputs needing any modification to become implementable, bucketed `none / minimal / mapping / logic` | `correction_class` |

**Unreachability policy.** A selector continues to the next child when a child FAILS, so
duplicate or overlapping sibling conditions are *not* proof of unreachability and are never
scored as invalid. They are reported `AMBIGUOUS` (shadowing risk) for manual review. A branch
is only ever marked invalid when unreachability is provable: two conditions on the same test
along one path (ancestors included) with an empty intersection, or a tree with no action / only
`wait`.

Deterministic rules: `S*` structural, `A*` action, `C1-C3` condition vocabulary and domain,
`L1` no action, `L2` provable contradiction, `L7` root not a composite.
Ambiguous rules routed to manual review: `C4` float equality, `L3` duplicate siblings,
`L4` non-exhaustive selector without a default child, `L5` attack without a distance guard,
`L6` unguarded retreat. Advisory: `L8` threshold/parameter mismatch, `S3` redundant wrapper.

## Evaluation Set 2 — gameplay

Produced only from `TRIALDATA` log lines emitted by the in-engine trial manager. Each line
records a *runtime event*: a condition evaluating true, an action starting, an action
finishing, a projectile damage event, or the trial end. Nothing in this table is inferred from
the behaviour specification; the specification only supplies the *expected* action for the
correctness comparison, matched by node id.

An `evt` id is allocated at trigger time (`T<trial>-n<node>-E<count>`), so repeated triggers of
the same condition pair unambiguously with their own action start. Action **initiation**
(`ACTION_START`) and action **success** (`ACTION_RESULT`) are separate events, so "the enemy
started the right action but it failed" is distinguishable from "the enemy never reacted".

| Metric | Definition | Denominator |
|---|---|---|
| Behaviour correctness | correct reactions / tested events x 100%. A reaction is correct when the action that started for that trigger equals the action the specification places on that node, **and** the action reported SUCCESS | tested events (triggers) |
| Reaction time | `ACTION_START.t - TRIGGER.t` for the same `evt` id, seconds | paired events only (unpaired are failures, not excluded silently) |
| Behaviour failure rate | failed events / tested events x 100%. Failed = no `ACTION_START` within the reaction timeout (2 s), or `ACTION_RESULT != SUCCESS` | tested events |
| Damage dealt | sum of `DAMAGE.amount` in the trial | per trial |
| Player survival time | `TRIAL_END.survival`, engine clock at the death frame | per trial |
| Attack accuracy (parity metric, if measurable) | hits / shots fired, from `DAMAGE` events vs `ACTION_RESULT` of `attack` | per trial |

Correctness is scored **against each tree's own specification**, never against the baseline.
The baseline is compared only on shared, meaningful quantities: damage dealt, player survival
time, and accuracy. A behaviour that deals less damage but satisfies its own specification
(e.g. a defensive tree) is not "worse" — its role correctness is a separate result.

## Combat parity (measured, not assumed)

The trial manager emits one `CONFIG` line per trial with these values read from the live
actors: max health, max walk speed, weapon damage, weapon accuracy, firing interval, projectile
speed, and the target-point rule. `analyze_results.py` reports them per behaviour pair; any
field that cannot be equalised is listed in `results/implementation_log.csv` with a reason.

Known structural difference to report: the baseline decides to fire from its Tick `AI MoveTo`
success callback plus `PawnSensing.OnSeePawn`; the experimental enemy fires only when a
behaviour-tree `attack` task executes. Health, speed, weapon stats, projectile, damage path and
target-point selection are identical.

## Trial protocol

Three controlled scenarios, one enemy per trial, player passive:

| Scenario | Setup | What it measures |
|---|---|---|
| `S1_STATIONARY` | player standing at a fixed point, not shooting | attack correctness, damage dealt, survival time, reaction time |
| `S2_DISTANCE_SCRIPT` | player teleported on a fixed waypoint schedule (3000 / 1500 / 600 / 1500 / 3000 cm, 3 s per step); each step logged as a `PUSH` event | approach/retreat correctness and reaction time |
| `S3_LOW_HEALTH_START` | enemy spawned with health below its `retreat_health_pct` | defensive branch correctness |

Between trials the session is reloaded, so health, position, weapon cooldown, AI state and
behaviour-tree state are all fresh. Rows may only be reported as experimental data when
`origin=live_pie`.
