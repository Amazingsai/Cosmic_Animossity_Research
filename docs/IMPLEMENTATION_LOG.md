# Implementation log — gameplay candidates from the generated dataset

This file records what was actually built in Unreal Engine for each selected candidate, what was
assumed or deviated from the generated JSON, what was verified by running the game, and what could
not be verified. It is deliberately kept **separate from the generated JSON**: the 40 raw outputs,
their manifests and the Round 1 / Round 2 validation CSVs remain the untouched input record. Nothing
here is a correction to a generated output; anything that differs is an implementation decision and
is labelled as one.

Engine: Unreal Engine 5.7.4, Blueprint-only project (no `*.Build.cs`).

---

## Candidate #1 — `round2/P01-G01`

### Identity

| Field | Value |
|---|---|
| Source file | `dataset/raw_outputs/20261105_round2/P01-G01.txt` (unmodified) |
| `behavior_id` | `close_range_rusher` |
| `behavior_style` | `aggressive` |
| `source_prompt_id` | `P01` |
| Validation status | `VALID` (`results/validation_combined.csv` row 12; `manual_review=0`, `correction_class=none`, no finding codes) |
| Structural repairs needed | none (no `S1` single-child composite, no `S3`; attack threshold equals `attack_range_cm` so no `L8`) |

> `behavior_id` is **not** a unique key across samples. The pilot generation
> `20261105_p01_success/P01-G01` carries the same `behavior_id` but a different tree and different
> numbers. Always identify a candidate by run + sample id.

### Generated specification (verbatim structure)

```
root: n0 selector
  n1 sequence
    n2 action "attack"         condition  distance_to_target <= 300
    n3 action "wait"           condition  can_attack != true
  n4 action "move_to_target"   condition  distance_to_target > 300

parameters:
  attack_range_cm     = 300
  retreat_distance_cm = 600
  retreat_health_pct  = 0.10
```

Note: candidate #1 contains **no retreat node**, so `retreat_distance_cm` and `retreat_health_pct`
are unused by this tree. They are carried for completeness only and must not be presented as
implemented.

### Translation to Unreal assets

Asset created: `/Game/Research/AI/BT_Behavior_P01_G01`
Blackboard: `/Game/Research/AI/BB_EnemyBehavior` (keys `TargetActor`, `DistanceToTarget`,
`HealthPercent`, `CanAttack`, `SelfActor` — unchanged)
Controller: `/Game/Research/AI/AIController_ResearchEnemy`, default `BehaviorTreeAsset` repointed
from `BT_Behavior_AttackAlways` to `BT_Behavior_P01_G01`.

| JSON node | Unreal node | Task | Task properties | Decorator | Decorator configuration |
|---|---|---|---|---|---|
| `n0` selector | `n0_Selector` | `BTComposite_Selector` | — | — | — |
| `n1` sequence | `n1_Sequence` | `BTComposite_Sequence` | — | — | — |
| `n2` action attack | `n2_Attack` | `BTTask_EnemyAttack_C` | `AttackRange = 300.0` | `Attack_DistanceLE300` | key `DistanceToTarget`, operation `LessOrEqual`, `FloatValue = 300.0` |
| `n3` action wait | `n3_Wait` | `BTTask_Wait` | `WaitTime = 0.1`, `RandomDeviation = 0.0` | `Wait_CanAttackFalse` | key `CanAttack`, `BasicOperation = NotSet` |
| `n4` action move_to_target | `n4_MoveToTarget` | `BTTask_EnemyMoveToTarget_C` | `AcceptanceRadius = 150.0` | `Move_DistanceGT300` | key `DistanceToTarget`, operation `Greater`, `FloatValue = 300.0` |

All three decorators: `NotifyObserver = ResultChange`, `FlowAbortMode = Self`,
`bInverseCondition = False`.

`FlowAbortMode` is clamped by the engine to `Self` on a decorator parented to a leaf task; only
composite-parented decorators accept `Both`. `Self` is therefore the correct maximum here, not a
downgrade.

### Decoration decisions (not translations — recorded as assumptions)

1. **`n3_Wait`'s `WaitTime = 0.1 s` is an implementation choice.** None of the 40 generated
   documents supply a `wait_seconds` parameter, so the generated `wait` action carries no duration.
   `0.1 s` was chosen so the sequence re-evaluates about ten times per second instead of depending on
   the task's default. `RandomDeviation = 0.0` keeps that cadence deterministic and measurable.
2. **`n4_MoveToTarget`'s `AcceptanceRadius = 150.0`** follows the Phase 5C mapping
   `attack_range_cm − 150`. With `BTTask_EnemyMoveToTarget`'s literal 150 cm arrival band, the move
   task reports success at ≤ 300 cm — exactly the attack decorator's boundary — so the handoff from
   "approach" to "attack" is coherent by construction rather than by luck.
3. **`n2_Attack`'s `AttackRange` was temporarily set to `10000.0` as an experimental control**, then
   restored to the faithful `300.0`. `BTTask_EnemyAttack` contains a hard-coded internal gate
   `DistanceToTarget <= AttackRange`. Requirement #7 forbids counting that in-task safety check as
   evidence that a behaviour-tree condition executed. With `AttackRange = 10000` (larger than any test
   distance and above the weapon's own 5000 cm range) the internal gate cannot refuse anything, so
   any refusal to fire had to come from the decorator. The final shipped state is `300.0`, matching
   `attack_range_cm`.

No generated logical errors were repaired. Candidate #1 has none: it is `VALID` and its attack
threshold already equals `attack_range_cm`.

---

## Defect found and fixed during implementation: decorators absent from the *compiled* tree

This was the single most important finding of the phase and it would have invalidated any behavioural
conclusion had it gone unnoticed.

### Symptom

The tree was built, saved five times with clean asset validation, and reported by tooling as having
all three decorators with correct values. Yet PIE showed the enemy firing at **1500 cm and 600 cm**
while remaining **completely stationary** in every phase — the exact signature of `n1_Sequence`
always succeeding, which means `n4_MoveToTarget` was never reached. There was **no compile error and
no log line about decorators at all**.

### Root cause

The decorators were correctly registered in the asset, but the asset's **compiled `BehaviourTree`
data was stale** and `save_asset` had not rebuilt it. PIE executed the previously compiled,
decorator-free tree.

The engine mechanism is why this fails silently. The compiler collects decorators in
`CollectDecorators()` (`Engine/Source/Editor/BehaviorTreeEditor/Private/BehaviorTreeGraph.cpp`,
lines 329–365), which reads **only** the parent graph node's `Decorators` array and skips anything
that is not a `UBehaviorTreeGraphNode_Decorator` / `UBehaviorTreeGraphNode_CompositeDecorator`
carrying a valid `NodeInstance`:

```cpp
for (int32 i = 0; i < GraphNode->Decorators.Num(); i++)
{
    UBehaviorTreeGraphNode* MyNode = GraphNode->Decorators[i];
    if (MyNode == NULL || MyNode->bInjectedNode) { continue; }
    UBehaviorTreeGraphNode_Decorator* MyDecoratorNode = Cast<UBehaviorTreeGraphNode_Decorator>(MyNode);
    if (MyDecoratorNode) { MyDecoratorNode->CollectDecoratorData(...); NumNodes++; }
}
```

`Decorators` is a plain public `UPROPERTY` (`BehaviorTreeGraphNode.h:32-33`), populated by
`UBehaviorTreeGraphNode::OnSubNodeAdded`. An unregistered decorator, or a graph whose compiled data
was never regenerated, therefore compiles to **nothing and logs nothing**.

### Fix and lesson

Re-registering the decorators and, critically, forcing an additional property-set + save cycle so the
compile actually landed restored them. **Acceptance test: `get_asset_meta` must list the decorators in
its `BehaviorTree Structure` block.** That tool renders decorators from compiled data, so it is the
valid structural probe — e.g. the same tool on the dev tree `BT_Behavior_AttackAlways` prints
`( aborts self ) Blackboard: DistanceToTarget Is Less Than 1000.000000`.

**Rule for every future candidate: a clean save does not imply a rebuilt compile. After any edit to a
behaviour tree, confirm with `get_asset_meta` that the decorators are still listed — do not trust a
graph-level read-back, and do not trust a successful save.**

---

## Verification in Unreal Engine (requirement #9)

### Procedure

Level `/Game/Research/Maps/Lvl_Research_Trial`. Enemy `SM_ExperimentalEnemy`
(`BP_BasicEnemyAI_C`) at world `(0, 600, 120)`; `PlayerStart` at `(0, -200, 120)`; spawn-to-spawn
distance 800 cm. The player's `CurrentHealth` is raised to `100000` at session start so a player death
cannot end the session mid-run (Phase 4B harness rule). Each phase resets the enemy to its captured
spawn transform and teleports the player to a fixed distance from it, so geometry at phase start does
not depend on where earlier movement left the actors.

Harnesses (project files, `Content/Python/`): `aura_bt_probe.py` (four-phase probe) and
`aura_bt_diag.py` (single-phase movement diagnostic with velocities). Both write to `Saved/`.

Phases: `A_far_1500` 8 s, `B_mid_600` 5 s, `C_close_200` 6 s, `D_far_again_1500` 6 s.
Decision ceiling 350 cm = threshold 300 + 50 cm sampling tolerance.

The probe also reports which tree the live controller believes it is running; it read back
`ctrl.BehaviorTreeAsset = /Game/Research/AI/BT_Behavior_P01_G01`, confirming the right tree executed.

### Run A — before the repair (decorators absent from compiled tree)

| Phase | Requested | Enemy displacement | Damage events | Damage at distance |
|---|---|---|---|---|
| A_far_1500 | 1500 cm | 0 cm | 5 | 1500.0 cm |
| B_mid_600 | 600 cm | 0 cm | 4 | 600.1 cm |
| C_close_200 | 200 cm | 0 cm | 6 | 200.2 cm |
| D_far_again_1500 | 1500 cm | 0 cm | 4 | 1500.0 cm |

19 damage events, **13 beyond the ceiling**, max distance at damage **1500.0 cm**. Firing at 1500 cm
while never moving is impossible for `BT_Behavior_AttackAlways` (which moves at that range) and
impossible for this tree with live decorators (which would refuse and run `n4`). The tree was running
**minus its decorators**.

### Run B — after the repair, `AttackRange` still 10000 (isolation run)

15 damage events, max **blackboard** distance at damage **289.3 cm**, all ≤ 300 cm. The single
apparent violation in that report (geo 600.1 cm) was a phase-teleport artefact: the player was moved
to the next phase distance on the same tick the damage was detected, so the geometric reading was
post-teleport while the blackboard value was pre-teleport (218.6 cm). The probe now discards damage
bookkeeping on a teleport tick.

Because `AttackRange` was 10000, the in-task gate could not have refused any shot. **Every refusal to
fire at long range in Run B was therefore produced by the tree's own decorator.**

### Run B2 — who actually moves

A dedicated diagnostic resolved an ambiguity in Run B, where sparse location reads suggested the enemy
had not moved even though distance closed from 1500 cm to 218 cm:

| Measurement | Value |
|---|---|
| `enemy_moved` | **1284.5 cm** (y: 600 → −684) |
| `player_moved` | **0.0 cm** (stationary at y = −900) |
| Enemy velocity while closing | `(-13.1, -499.8)` ≈ 500 cm/s |
| Distance at which it stopped | **218.6 cm** (= `AcceptanceRadius` 150 + both capsule radii) |
| After stopping | fires, 5 damage per hit, ≈ 1.1 s cadence |

So `n4_MoveToTarget` does execute at 1500 cm and the enemy closes before firing.

### Run C — faithful configuration (`AttackRange = 300`), final state

```
damage_events_total=10  within_ceiling=10  BEYOND_ceiling=0
max_distance_at_damage=218.6 cm   min_distance_at_damage=152.1 cm
no damage was recorded beyond the ceiling in any phase
```

Per phase: A 3 events (all at 218.4 cm), B 2 events (152.1 cm), C 4 events (200.2 cm), D 1 event
(218.6 cm). Damage per hit 5.0 throughout. First damage arrived 0.67 s (phase C, already in range) to
4.69 s (phase D, after closing) after each phase reset — i.e. firing begins only after the enemy has
closed to contact range.

---

## Requirement #7 — which generated conditions were shown to control their actions

Judged strictly: a condition counts only if its action's behaviour changed when the condition's truth
value changed, and never by citing a safety check inside an action task.

| JSON condition | Controls | Verdict | Evidence |
|---|---|---|---|
| `distance_to_target <= 300` on `attack` | whether the enemy fires | **Verified** | Run B: `AttackRange` 10000 made the in-task gate inert, yet no shot landed beyond 300 cm (max 289.3). Run A, with the same task property, fired at 1500 cm — the only difference was the decorator. |
| `distance_to_target > 300` on `move_to_target` | whether the enemy approaches | **Partially verified** | Run A: 0 cm displacement at 1500 cm. Run B/B2: 1284.5 cm closing at 1500 cm. The decorator therefore permits movement beyond 300. It is **not** independently proven to *block* movement below 300, because `BTTask_EnemyMoveToTarget`'s own `AcceptanceRadius` (≈219 cm centre-to-centre) stops the pawn for reasons unrelated to the tree. |
| `can_attack != true` on `wait` | the gating of the attack branch behind the weapon cooldown | **NOT verified** | The observed ≈1.05–1.1 s cadence matches the weapon's 1.0 s cooldown quantised by the 0.1 s wait, but an *undecorated* sequence produces the same cadence. At the achieved sampling resolution the two are indistinguishable. Recorded as unverified, not as passing. |

The one reserved judgement above (`n3_Wait`) is a genuine gap, not a rounding of the result.

### What the gameplay run does and does not establish

Established: the enemy closes to contact range before firing, never damages the player from beyond
218.6 cm, and fires on roughly the weapon's cooldown. Its observable behaviour is consistent with the
generated tree, and it is materially different from its own behaviour before the decorator repair.

Not established: that every condition node executed as authored (see `n3_Wait`), absolute timing
precision (see throttling below), or anything about the other five candidates, which are not
implemented.

---

## Candidate #2 — `round2/P02-G01`

### Identity

| Field | Value |
|---|---|
| Source file | `dataset/raw_outputs/20261105_round2/P02-G01.txt` (unmodified) |
| `behavior_id` | `retreat_when_low_hp` |
| `behavior_style` | `retreating` |
| `source_prompt_id` | `P02` |
| Validation status | `VALID` (`results/validation_round2.csv` row 5; `manual_review=0`, `correction_class=none`, no finding codes) |
| Structural repairs needed | none — no `S1` single-child composite, no `S3`, `retreat_distance_cm` 1200 > `attack_range_cm` 800 so no `S5`, and the attack threshold equals `attack_range_cm` so no `L8` |

Selected by §10 of `docs/RESEARCH_PROGRESS.md` as **the only health-gated family** and as the sample whose
oscillation was a *prediction* (Phase 5C's hold-branch rule) rather than a measurement. It is also the
largest of the early candidates at 7 nodes and the only one of the six that exercises all four actions.

### Generated specification (verbatim structure)

```
root: n0 selector
  n1 sequence
    n2 action "move_away_from_target"   condition  health_percent      <= 0.25
    n3 action "wait"
  n4 sequence
    n5 action "move_to_target"          condition  distance_to_target >  800
    n6 action "attack"                  condition  distance_to_target <= 800

parameters:
  attack_range_cm     = 800
  retreat_distance_cm = 1200
  retreat_health_pct  = 0.25
```

Two structural features of this tree drive everything measured below, and neither is a validator
finding:

1. **`n1`'s `wait` child has no condition at all.** `wait` is unconditional inside the low-health
   branch, so it is the branch's only fallback when retreat refuses.
2. **`n5` and `n6` are opposite comparisons inside one sequence.** A sequence runs its children in
   order and stops at the first failure, so `n6` is only ever reached on a pass where `n5` returned
   SUCCESS. See the reachability section.

### Translation to Unreal assets

Asset created: `/Game/Research/AI/BT_Behavior_P02_G01`
Blackboard: `/Game/Research/AI/BB_EnemyBehavior` (keys `TargetActor`, `DistanceToTarget`,
`HealthPercent`, `CanAttack`, `SelfActor` — unchanged)
Controller: `/Game/Research/AI/AIController_ResearchEnemy`, default `BehaviorTreeAsset` repointed
from `BT_Behavior_P01_G01` to `BT_Behavior_P02_G01` (compiled and saved).
`BT_Behavior_P01_G01` is **left in place and unmodified**, so candidate #1 remains reproducible by
repointing `BehaviorTreeAsset` back at it.

| JSON node | Unreal node | Task | Task properties | Decorator | Decorator configuration |
|---|---|---|---|---|---|
| `n0` selector | `n0_Selector` | `BTComposite_Selector` | — | — | — |
| `n1` sequence | `n1_Sequence` | `BTComposite_Sequence` | — | — | — |
| `n2` action move_away | `n2_MoveAway` | `BTTask_EnemyMoveAwayFromTarget_C` | `RetreatDistance = 1200.0` | `MoveAway_HealthLE025` | key `HealthPercent`, operation `LessOrEqual`, `FloatValue = 0.25` |
| `n3` action wait | `n3_Wait` | `BTTask_Wait` | `WaitTime = 0.1`, `RandomDeviation = 0.0` | **none** | faithful — the JSON gives `n3` no condition |
| `n4` sequence | `n4_Sequence` | `BTComposite_Sequence` | — | — | — |
| `n5` action move_to | `n5_MoveToTarget` | `BTTask_EnemyMoveToTarget_C` | `AcceptanceRadius = 650.0` | `MoveTo_DistanceGT800` | key `DistanceToTarget`, operation `Greater`, `FloatValue = 800.0` |
| `n6` action attack | `n6_Attack` | `BTTask_EnemyAttack_C` | `AttackRange = 800.0` | `Attack_DistanceLE800` | key `DistanceToTarget`, operation `LessOrEqual`, `FloatValue = 800.0` |

All three decorators: `NotifyObserver = ResultChange`, `FlowAbortMode = Self`,
`bInverseCondition = False`. `Self` is the engine-clamped maximum on a leaf task, not a downgrade.

**Requirement #5 — the compiled tree was verified, not the graph.** Read back through
`get_asset_meta`, whose `BehaviorTree Structure` block renders from compiled data:

```
n0_Selector
+- n1_Sequence
|  +- n2_MoveAway (Decorators: [( aborts self ) Blackboard: HealthPercent Is Less Than Or Equal To 0.250000]])
|  \- n3_Wait
\- n4_Sequence
   +- n5_MoveToTarget (Decorators: [( aborts self ) Blackboard: DistanceToTarget Is Greater Than 800.000000]])
   \- n6_Attack (Decorators: [( aborts self ) Blackboard: DistanceToTarget Is Less Than Or Equal To 800.000000]])
```

This matters because Phase 7 established that a clean save does **not** imply a rebuilt compile. The
acceptance probe was run twice; the block above is the second read.

### Decoration decisions (not translations — recorded as assumptions)

1. **`WaitTime = 0.1 s` and `RandomDeviation = 0.0`.** 0 of 40 generated documents supply
   `wait_seconds`, so `n3`'s duration is an implementation choice, kept identical to candidate #1's
   so the two trees are comparable.
2. **`AcceptanceRadius = 650`** follows the Phase 5C mapping `attack_range_cm − 150`. Consequence
   worth stating explicitly: `BTTask_EnemyMoveToTarget` succeeds at `d <= AcceptanceRadius + 150`,
   i.e. at exactly **800 cm** — the same number as the attack decorator's boundary. The handoff is
   coherent on paper and is the direct cause of the reachability defect measured below.
3. **`RetreatDistance = 1200`** is *below* the task's 1500 class default, so a node silently reading
   its default would retreat 300 cm too far. That it did not is proven positively: the task prints
   its own threshold, and the run logged `SUCCESS d=1718.2 thr=1050.0` — `1050 = 1200 − 150`. A
   default-reading node would have printed `1350.0`.

No generated logical error was repaired. The unreachable `n6` branch and the sawtooth are **measured
findings about the generated tree** and are left intact.

---

## Condition isolation for candidate #2 (requirement #6)

Each generated condition was tested on its own before any comparison ran, so a comparison result can
never be ambiguous about which condition produced it. Harness: `Content/Python/aura_p02_probe.py`
(run `p7p02_probe`), 2 trials × 4 phases, level `Lvl_Research_Trial`, controller tree asserted.

### Deviation — the health stimulus, and why it is a stimulus and not a behaviour change

`HealthPercent` is written by `AIController_ResearchEnemy.UpdateDerivedKeys` as
`CurrentHealth / MaxHealth`, and **nothing in the tree or the tasks can lower it**. To make the
low-health branch reachable at all, the probe applied damage through the pawn's own public damage
event: `enemy.call_method("SendDamage", (delta,))` — a **tuple** is required — with positive values
wounding and negative values healing. This is recorded as an implementation deviation with three
notes:

- It is an **external stimulus driven by the harness**, never by a behaviour tree or an action task,
  so it changes no generated decision. In the comparison run below it is not used at all.
- `BP_BasicEnemyAI.ReduceHealth` is a **plain subtract with no clamp**, and `Death` only fires at
  `health <= 0`, so an over-heal would leave `HealthPercent` above 1.0 and silently disable the
  retreat branch. Each heal was therefore set to land exactly on `MaxHealth`.
- `CurrentHealth` is **not instance-editable** — `set_editor_property`, `import_text` and the console
  `set` command all fail on a level-placed instance, and `send_damage` / `reduce_health` are not
  Python-visible. `SendDamage` is the only working route. Verified separately by
  `Content/Python/aura_health_stimulus_test.py`.

### Gate A — `health_percent <= 0.25` controls the retreat (`n2`)

Same tree, same geometry; only health differs.

| Phase | `CurrentHealth` | bb `HealthPercent` | Enemy displacement | bb `DistanceToTarget` |
|---|---|---|---|---|
| `healthy_600` (500 HP) | 500 | 1.00 | **0.0 cm** | 600.1 only |
| `wounded_600` (100 HP) | 100 | 0.20 | **835.6 / 835.1 cm** | 600.1 → 1719.0 |

**Verified.** At an identical 600 cm start the retreat task ran at `HealthPercent` 0.20 (a 835 cm
retreat, twice, ±0.5 cm) and never ran at 1.00 (zero displacement, and `bb_dist` never left 600.1).
No task-internal check can produce that: `BTTask_EnemyMoveAwayFromTarget` reads only `TargetActor`
from the blackboard, so the health decision had to come from the decorator.

### Gate B — `distance_to_target > 800` controls the approach (`n5`)

Same tree, same health; only distance differs.

| Phase | Requested | bb `DistanceToTarget` range | Enemy displacement |
|---|---|---|---|
| `healthy_600` | 600 cm | 600.1 only | **0.0 cm** |
| `healthy_1500` | 1500 cm | 631.5 ↔ 1749.3 | **868.8 / 869.6 cm** |

**Verified.** The approach task is refused at 600 cm (inside 800) and runs at 1500 cm. As with
candidate #1, the inverse direction is the weaker half — `AcceptanceRadius` stops the pawn for
reasons unrelated to the tree — but the *permission* half is clean.

### The sawtooth — predicted in Phase 5C, now measured

The Phase 5C analysis predicted that a low-health subtree with no hold child would oscillate once
`retreat_distance_cm > attack_range_cm`. The engine log contains exactly that pattern:

```
BTTask_EnemyMoveAwayFromTarget: SUCCESS d=1718.2 thr=1050.0
BTTask_EnemyMoveAwayFromTarget: FAILURE (already beyond retreat range) d=1718.2
BTTask_EnemyMoveAwayFromTarget: FAILURE (already beyond retreat range) d=1333.4
BTTask_EnemyMoveAwayFromTarget: SUCCESS d=1834.9 thr=1050.0
```

`SUCCESS` → precondition refusal → the sequence falls through → `n5` is permitted again → the
wounded enemy closes back inside 1200 → retreat re-arms → `SUCCESS` again. `FAILURE (retreat too
short)` never appeared, so the refusal is always the "already far enough" precondition, never a
failed approach to the goal.

**This is a finding about the generated tree, not a defect to fix.** It is left as generated. The
hold child whose absence causes it is exactly what Phase 5C's reference design adds, so the
measurement is a direct confirmation of that design rule.

### Startup artefact — `HealthPercent` reads 0.0 before the first timer tick

Every PIE start logged one `BTTask_EnemyMoveAwayFromTarget: FAILURE (no target)`. The controller's
`HealthPercent` write is on a 0.1 s timer set in `OnPossess`, so on the tree's first pass the key is
still 0.0 — which satisfies `<= 0.25` — and `n2` executes before `TargetActor` has been written.
The task correctly reports the missing target and the looped tree retries. This is a blackboard
startup race, not a task or decorator defect, and it appears once per session.

---

## Reachability finding: `n6_Attack` can never execute

This is the most important result of the candidate and it is a **generated logical defect**, not an
implementation error. It was measured decisively before the comparison ran.

### Test

`n6_Attack.AttackRange` was set to **−1.0** for one healthy 14 s run at 1500 cm. `BTTask_EnemyAttack`
contains a hard-coded `DistanceToTarget <= AttackRange` gate that fails the task **and prints a line
every time it executes**, so `AttackRange = −1` turns the task into an execution detector: the gate
can never pass, so any execution is visible even though nothing can ever fire.

### Result

```
BTTask_EnemyAttack lines in the run window: 0
```

Zero. The gate was never reached, so the task never ran. Movement in the same run, per sample:
1500 cm → **716.2 cm in 2.2 s**, then flat at exactly 716.2 cm for the remaining 12 s, with
`bb_dist == geo_cm` at every sample (the blackboard was not stale in steady state).

`AttackRange` was then restored to the faithful **800.0** and the decorators re-verified through
`get_asset_meta`.

### Mechanism

`n5` (`d > 800`) and `n6` (`d <= 800`) are opposite comparisons inside the **same sequence**. A
sequence stops at its first failing child, so `n6` is reachable only on a pass where `n5` returns
SUCCESS. `n5` succeeds at `d <= AcceptanceRadius 650 + 150 = 800`. Two independent reasons make that
pass impossible:

1. **The physical stopping distance is inside the attack band, not at its edge.** The pawn stops at
   **716.2 cm** (= `AcceptanceRadius` 650 + both capsule radii). At 716.2 cm the decorator
   `d > 800` is **false**, so on every subsequent loop pass `n4_Sequence` fails at its first child
   and `n6` is never evaluated.
2. **On the single arrival pass the key is stale.** The controller writes `DistanceToTarget` on a
   0.1 s timer, so the value the decorators see still reads > 800 at the moment `n5` succeeds — and
   `n6`'s `d <= 800` therefore also refuses.

Either mechanism alone is sufficient. The consequence in practice is stronger than "cannot attack":
**once the enemy has closed to 716.2 cm it is permanently inert**, because `n5` is now blocked by its
own decorator, `n6` is unreachable, and the low-health branch is refused at `HealthPercent` 1.00.

### Why this is a finding and not a repair

A one-line change — swapping the two children, or replacing the sequence with a selector — would make
the tree work. It would also delete the result. The generated output is preserved verbatim and the
tree is left exactly as specified. The correct report is *"this generated tree cannot attack, by
construction"*, not *"this tree now attacks"*.

This is also why the **absence of damage is never treated as evidence about the decorators** here:
`n6` produced no damage because it never executed, which says nothing about whether `n6`'s decorator
would have gated correctly had the node been reached.

---

## Candidate #2 — comparison against the baseline

Full methodology: `docs/BASELINE_COMPARISON.md` §13. Harness: `Content/Python/aura_p02_compare.py`,
a re-target of the Phase 7B harness (`RUN_ID p7cmp_p02_r1`, threshold 800 cm, ceiling 850 cm,
`P02CMP_*` outputs). Raw results: `results/gameplay/P02CMP_*.csv`.

**Three fresh trials were run for each subject.** Baseline results from Phase 7B were **not** reused:
they were produced against a different tree's threshold (300 cm), so "all relevant conditions remain
identical" could not be claimed. Nine fresh baseline trials' worth of phases were cheap enough to be
preferable to an equivalence argument.

| Metric | Candidate #2 | Baseline |
|---|---|---|
| Damage events / total damage | **0 / 0.0** | 68 / 340.0 |
| Events beyond 800 cm | **0 of 0** | 8 of 68 (11.8 %) |
| Max distance at damage | n/a — no event | 1421.2 cm |
| Reaction correctness | **`not_applicable`** | `fail` against the 800 cm threshold |
| Mean time to first damage | none in any phase | 1.13 s (0.67–1.36) |
| Move-task `SUCCESS` | 6 (3 trials × 2 far phases) | not applicable |
| Move-task `FAILURE` | **0** | not applicable |
| Retreat-task lines | 1 — `FAILURE (no target)`, startup only | not applicable |
| Attack-task executions | **0** | not applicable |
| Mean sample rate | 2.91 Hz | 2.93 Hz |

Per-phase damage (candidate #2 vs baseline): `far_1500` 0.0 vs 35.0, `mid_600` 0.0 vs 25.0,
`close_200` 0.0 vs 25.0, `far_1500_again` 0.0 vs 28.3.

Per-phase movement (candidate #2): `far_1500` 784.5 / 784.6 / 784.6 cm; `far_1500_again` 784.6 /
784.8 / 785.0 cm; `mid_600` **0.0**; `close_200` **0.0** — all three trials.

### Reading the result strictly

- **The generated enemy dealt zero damage in 12 of 12 phases**, and it is not for want of a target:
the baseline, on the same geometry and the same player, dealt 340.
- **The cause is the reachability defect, not the health gate.** Enemy health stayed at 500 with
  `HealthPercent` min = max = 1.00 across all 12 phases, so the retreat branch was never enabled and
  never interfered. The zero comes from `n4_Sequence` failing at `n5` combined with `n6` being
  unreachable.
- **The distance gates are visible as behaviour.** At 600 cm and 200 cm the enemy moved exactly
  0.0 cm in all six phases: `n5`'s `d > 800` is false there, so the approach task was never entered.
  This is a clean tree decision, in the same sense as candidate #1's `close_200` result.
- **Reaction correctness for the generated enemy must be reported as `not_applicable`, not as
  `pass`.** With no events there is nothing to judge. Reporting 0 violations as "100 % correct"
  would be the most misleading number this dataset could produce.
- The baseline's 8 events beyond 800 cm are **not a baseline failure**. The baseline has no range
  rule of its own; it is being scored against candidate #2's threshold only so the two columns are
  comparable.

### What the comparison does and does not establish

Established: with this tree, `BP_BasicEnemyAI` approaches when beyond 800 cm, does not approach inside
800 cm, never attacks, never retreats at full health, and reaches a permanent standstill at ~716 cm.
The tree's conditions gate the nodes they are attached to; the *composition* of those nodes makes the
attack action unreachable.

Not established: that the attack decorator would have gated correctly if reached (it never ran); that
the retreat branch behaves sensibly in a full scenario rather than under an injected stimulus; or
anything about candidates #3, #6, #5, #4, which are not implemented.

---

## Tooling and environment limitations (documented, not worked around silently)

1. **Compiled-tree introspection is blocked in Python.** `UBehaviorTree::BTGraph` and
   `UBehaviorTree::RootNode` are protected `UPROPERTY`s and cannot be read (`BehaviorTree: Property
   'BTGraph' ... is protected and cannot be read`; `Failed to find property 'root_node'`).
   `execute_unreal_python_readonly` is unavailable in Agent mode. Compiled-tree verification must go
   through `get_asset_meta` and PIE.
2. **A clean save does not recompile a behaviour tree** (see the defect section). Verified state, not
   saved state, is the only acceptable evidence.
3. **`get_asset_graph` lists root-level nodes only** — it omits decorator sub-nodes even on trees that
   definitely have them, so its node list is not evidence either way about decorators. `get_asset_meta`
   is the correct probe.
4. **The editor was background-throttled to ≈3 Hz during these runs** (phase A: 24 samples over 8 s).
   Consequences: per-frame sampling is coarse (~0.33 s), projectile spawn counts are unusable (a
   projectile can spawn and hit between samples, so "shots" reads zero while damage is recorded), and
   the reliable signal is the **damage delta plus the distance at that delta**. Earlier phases sampled
   at ~57 Hz; the sample rate must be recorded with every run and runs are only comparable at similar
   rates.
5. **Enemy location reads frequently fail during throttled sampling**, so the probe's `displacement`
   figure is `0 cm` even when the pawn demonstrably moves. The dedicated diagnostic (which reads
   velocity, not just position) is the movement evidence; the probe's displacement line should be
   disregarded.
6. **`register_slate_post_tick_callback` callbacks created from an inline `execute_unreal_python`
   script lose their module globals**, so such a callback cannot clean up and leaves PIE running. The
   harness must live in a module file under `Content/Python/` (this is why `aura_bt_probe.py` and
   `aura_bt_diag.py` exist as files). Do not `importlib.reload` a probe while its callback is
   registered.
7. **`begin_play` requested while a previous `end_play` is still tearing down can start PIE in the
   wrong level.** This produced one run that measured 25 s of `Lvl_FirstPerson`, a level containing no
   experimental enemy, with a report that looked superficially valid. Both harnesses now assert the
   PIE world name and refuse to measure otherwise. Always confirm the PIE world, not just the editor
   world.
8. **`BTTask_Wait`'s default `WaitTime` remains unverified** — the explicit `0.1` makes it moot for
   this tree, but the CDO default was never established.

---

## Candidate #3 — `round2/P04-G01`

### Identity

| Field | Value |
|---|---|
| Run / sample | `20261105_round2` / `P04-G01` |
| Raw file | `dataset/raw_outputs/20261105_round2/P04-G01.txt` — verbatim, unmodified |
| `behavior_id` | `range_adaptive_attacker` |
| `behavior_style` | `range_based` |
| `source_prompt_id` | `P04` |
| Schema | 2.0 |
| Validation | M1–M5 **`VALID`**, `manual_review = 0`, `correction_class = none`, no finding codes |
| Size | 12 nodes (3 composites, 2 nests), depth 3 |
| Parameters | `attack_range_cm` 1500, `retreat_distance_cm` 2000, `retreat_health_pct` 0.2 |

### Generated specification (verbatim structure)

```
n0 selector
 n1 sequence  [d < 350]        move_away, attack(can_attack==true), wait
 n5 sequence  [d <= 1500]      attack(can_attack==true), move_to_target, wait
 n9 sequence  [d > 1500]       move_to_target, wait
```

Three distance bands, conditions carried on **composites**, and the only tree in the six-candidate set
with two attack nodes. `retreat_health_pct` is declared but **no node tests health**, so it has no home
in this tree — recorded as unused rather than invented into a decorator.

### Translation to Unreal assets

`/Game/Research/AI/BT_Behavior_P04_G01`, built with the BT tooling. `bp_agent` **could not** create it:
`create_assets` has no `BehaviorTree` asset type and `UBehaviorTree` is `NotBlueprintable`.

| Node | Asset | Properties written explicitly |
|---|---|---|
| `n1_Sequence` | composite | decorator `DistanceToTarget < 350` |
| `n2` | `BTTask_EnemyMoveAwayFromTarget` | `RetreatDistance` **2000** |
| `n3` | `BTTask_EnemyAttack` | `AttackRange` **1500** + decorator `CanAttack Is Set` |
| `n4` | `BTTask_Wait` | `WaitTime` 0.1, `RandomDeviation` 0.0 |
| `n5_Sequence` | composite | decorator `DistanceToTarget <= 1500` |
| `n6` | `BTTask_EnemyAttack` | `AttackRange` **1500** + decorator `CanAttack Is Set` |
| `n7` | `BTTask_EnemyMoveToTarget` | `AcceptanceRadius` **1350** (= `attack_range_cm − 150`) |
| `n8` | `BTTask_Wait` | `WaitTime` 0.1 |
| `n9_Sequence` | composite | decorator `DistanceToTarget > 1500` |
| `n10` | `BTTask_EnemyMoveToTarget` | `AcceptanceRadius` **1350** |
| `n11` | `BTTask_Wait` | `WaitTime` 0.1 |

All five decorators: `NotifyObserver = ResultChange`, `FlowAbortMode = Self`, `bInverseCondition = False`.
Graph node ids `Task_0`–`Task_7` map `n2`–`n11`; empirically, `BTTask_EnemyMoveAwayFromTarget_C_0` = `n2`,
`BTTask_EnemyMoveToTarget_C_0` = `n7`, `BTTask_EnemyMoveToTarget_C_1` = `n10`.

### Decoration decisions (assumptions, not translations)

1. **Conditions on composites.** The JSON puts each band condition on the sequence, so each decorator
   is parented to its sequence — not to the first child. This is the placement Phase 4B showed to be
   load-bearing. `FlowAbortMode = Self` is applied to all three; the engine clamps leaf-task decorators
   to `Self` anyway.
2. **`can_attack` → native `BTDecorator_Blackboard` (`Is Set`).** A blueprint decorator cannot be
   completed with this tooling (no return node), so native decorators are the only route.
3. **`WaitTime = 0.1 s` is an implementation parameter**, not a translation: 0/40 documents supply
   `wait_seconds`, and Phase 4 measured a longer `Wait` quantising the fire rate above the weapon's
   own cooldown.
4. **`retreat_health_pct = 0.2` is deliberately not implemented.** No node in the tree tests health;
   adding a decorator would invent behaviour the model did not specify. It must not be reported as
   implemented.

### Verification of the compiled tree (requirement #5)

Read back through the asset metadata **twice**, independently of the build: the compiled structure
lists all five decorators, including the three on composites — the exact case Phase 4B caught going
silently missing from compiled data while the saved asset looked correct. A clean save is not evidence
of a rebuilt compile; only the structure read-back is.

### Condition isolation (requirement #6)

Four phases, one session (`aura_p04_probe.py`, 36 s): `close_200` 8 s, `mid_600` 8 s, `far_1800` 12 s,
`close_200_again` 8 s. Player health raised to 100000; enemy reset to spawn each phase; damage not
bookkept on teleport ticks.

| Phase | Samples | Damage events | First damage | Enemy moved | Distances at damage |
|---|---|---|---|---|---|
| `close_200` | 24 | 5 | 0.85 s | **0.0 cm** | 200.2 |
| `mid_600` | 23 | 6 | 0.67 s | 0.0 cm | 600.1 |
| `far_1800` | 35 | 5 | 2.67 s | 451.6 cm | 1348.6 |
| `close_200_again` | 23 | 5 | 1.00 s | 0.0 cm | 200.2 |

**Instrumentation defect found and fixed in this phase.** `_close_phase` read the distance-at-damage
column from `e[5]` (`bb_health_percent`) instead of `e[3]` (`geo_cm`), so the first run's
`max/min_geo_at_damage_cm` were a constant `1.0` — meaningless, and reported as void rather than as a
result. Fixed to `e[3]`; the table above is the corrected run. The earlier run's geo-at-damage columns
must never be cited.

**Runtime diagnosis added to the probe.** `AURA_DIAG` lines now record the retreat goal the task will
compute and compare it with the built navmesh:

```
AURA_DIAG retreat self=(0.0, 600.0, 90.2) target=(0.0, -200.0, 98.2) d=800.0
AURA_DIAG away_unit=(0.0000, 1.0000, -0.0100) goal=(0.0, 2599.9, 70.2)
AURA_DIAG navmesh x=[-1976.0, 1976.0] y=[-1976.0, 1976.0] z=10.0
AURA_DIAG goal_inside_navmesh=False best_reachable_d=2176.0 required=1850.0 achievable=True
```

### Reachability of each intended action

| Node | Action | Executes? | Evidence |
|---|---|---|---|
| `n2` | `move_away_from_target` | **entered, always fails** | 23 `FAILURE (retreat too short) d=200.159936 thr=1850.0` in three close phases |
| `n3` | `attack` (close band) | **never** | 0 `MoveAway … SUCCESS` lines in 3 trials, and the retreat prints on every terminal path |
| `n4` | `wait` (close band) | **never** | follows `n3` in a sequence that never passes `n2` |
| `n6` | `attack` (medium band) | **yes** | 35 damage events at 600.1 / 200.2 cm; the only in-range attack reachable in that band |
| `n7` | `move_to_target` (medium) | yes, no-ops | `d ≤ 1350` on entry, 0.0 cm moved |
| `n10` | `move_to_target` (far) | **yes** | 6 `SUCCESS`, 1 `FAILURE (arrived too far)`, ~118 cm closed per far phase |

`BTTask_EnemyAttack` prints **only when its own gate refuses**, so it can never prove execution. `n6`'s
execution is proved by the damage instead; `n3`'s non-execution is proved by the retreat's silence on
`SUCCESS`, which is the only gate in front of it.

### Root cause of the `n2` failure — generated parameter vs arena navmesh

Arithmetic, not timing. Navmesh `y ∈ [−1976, 1976]`; enemy spawns at `y = 600`; the retreat goal is
`y = 2600`. The task's success test requires `d ≥ 1850`, i.e. `y ≥ player_y + 1850`, which is `y ≥ 2100`
even at the widest edge of the close band — **above the 1976 cm ceiling, by ≥ 124 cm at every point in
the band.** The goal is also passed to `MoveToLocation` with `Project Destination to Navigation = false`,
so the off-navmesh goal is never clamped, the move never starts, and the task fails on its first tick.

**Control that rules out a broken task:** `BT_Behavior_RetreatTest` (`RetreatDistance` 1200, threshold
1050) logged `SUCCESS d=1718.2 … 1834.9 thr=1050.0` six times in this same arena. The task works when
its required separation fits inside the navmesh.

### Requirement #9 — generated defect vs Unreal/instrumentation

| Observation | Attributed to | Basis |
|---|---|---|
| `n3`/`n4` never execute | **generated parameter** × task behaviour | retreat 2000 cm is schema-legal but unsatisfiable in a 1976 cm navmesh with the enemy at y=600 |
| retreat fails without moving | **task implementation** | `Project Destination to Navigation = false`, and success is judged on the same tick family that started the move |
| attack shown as “0 lines” | **instrumentation** | the task prints only on refusal; absence is not evidence, so reachability was proved from the retreat's own prints instead |
| first run's geo-at-damage = 1.0 | **instrumentation bug** | wrong CSV column index, fixed; the run is void for those two columns |
| 2.9 Hz sample rate | **environment** | background PIE throttling; timing quantised at ≈0.34 s |
| `move_to_target` far arrival failed once | task/engine, not generated | the logged overshoot of Phase 5A, `d=1715.6` vs `AcceptanceRadius` 1350 |

### What is not claimed

- The retreat **policy** is unmeasured: no successful retreat exists in this arena, so the tree's
  intended disengage was never observed.
- `n3`'s `CanAttack` decorator was never isolated, because its node is unreachable. Its gating is
  **unverified**, not "working".
- `retreat_health_pct` was not implemented and was not exercised.

---

## Candidate #6 — `round2/P07-G01`

### Identity

| Field | Value |
|---|---|
| Source | `dataset/raw_outputs/20261105_round2/P07-G01.txt`, unmodified |
| `behavior_id` | `backaway_safe_shooter` |
| Style / prompt | `range_based` / P07 |
| Schema | 2.0 |
| Validation | **VALID**, `manual_review = 0`, `correction_class = none`, no finding codes |
| Nodes | 7 graph nodes + 2 decorators (10 structure entries incl. ROOT) |
| Parameters | `attack_range_cm` 900, `retreat_distance_cm` 1300, `retreat_health_pct` 0.2 |
| Unreal asset | `/Game/Research/AI/BT_Behavior_P07_G01` |

Implementation order placed it fourth (#1, #2, #3, **#6**, #5, #4) and it is the semantic-weakness
case in the selection: rule-clean, no validator finding, and its only attack is guarded on being
**far**.

### Generated specification (verbatim structure)

```
n0_Selector
+- n1_Sequence  (NO decorator)
|    n2_Action  move_away_from_target      <-- DEC: distance_to_target Less 900
|    n3_Action  wait                       <-- no decorator
\- n4_Sequence  (NO decorator)
     n5_Action  attack                     <-- DEC: distance_to_target GreaterOrEqual 900
     n6_Action  wait                       <-- no decorator
parameters: attack_range_cm 900, retreat_distance_cm 1300, retreat_health_pct 0.2
```

Both conditions sit on **leaf tasks**, and neither of the two sequences carries one. That is the
candidate #2 (`P02-G01`) placement, not candidate #3's composite hoisting.

### Translation to Unreal assets

| Generated | Unreal | Configuration |
|---|---|---|
| `n0` `selector` | ROOT `BTComposite_Selector` | — |
| `n1`, `n4` `sequence` | `Composite_1`, `Composite_2` (`BTComposite_Sequence`) | no decorators |
| `n2` `move_away_from_target` | `Task_0` `BTTask_EnemyMoveAwayFromTarget` | `RetreatDistance = 1300.0` |
| `n5` `attack` | `Task_2` `BTTask_EnemyAttack` | `AttackRange = 900.0` |
| `n3`, `n6` `wait` | `Task_1`, `Task_3` `BTTask_Wait` | `WaitTime = 0.1` |
| `n2` condition `d < 900` | `Decorator_1` `BTDecorator_Blackboard` | `ArithmeticOperation` `Less`, `FloatValue 900.0`, key `DistanceToTarget` |
| `n5` condition `d >= 900` | `Decorator_3` `BTDecorator_Blackboard` | `ArithmeticOperation` `GreaterOrEqual`, `FloatValue 900.0`, same key |

Node ids on the asset: `Composite_0/1/2`, `Task_0`–`Task_3`, `Decorator_1`, `Decorator_3`.

### Decoration decisions (assumptions, not translations)

1. **`GreaterOrEqual` clears the validator's float-equality finding.** Waiting for an exact `Equal`
   would never fire on a live blackboard; the generated operator is a range test and is built as one.
   No `C4` was raised on this document in the first place, so this is a build-side safety choice, not
   a correction.
2. **`WaitTime = 0.1 s` is an implementation parameter.** 0/40 documents supply `wait_seconds`.
   0.1 s keeps a loop containing an `attack` from quantising the fire rate above the weapon's own
   1.0 s cooldown (Phase 4).
3. **`retreat_health_pct = 0.2` is deliberately not implemented.** No node in this tree tests health.
   Adding a decorator would invent behaviour the model did not specify. It must not be reported as
   implemented.
4. **Both leaf decorators carry `NotifyObserver = ResultChange`, `FlowAbortMode = Self`,
   `bInverseCondition = False`.** `Self` is what the engine clamps a leaf-task decorator to anyway.
   It has a behavioural consequence here that placement on a composite would not: it aborts the
   running retreat the moment the condition flips (see below).

### Verification of the compiled tree (requirement #5)

The tree was built and saved through the BT tooling (`bp_agent` cannot create a `UBehaviorTree`),
then read back **independently of the build** through asset metadata, then re-verified item by item
from graph-node data in a separate scripted pass. All six checks passed:

| Check | Result |
|---|---|
| (a) exactly 7 graph nodes, exact names | PASS |
| (b) **zero** decorators on `Composite_1` and `Composite_2` | PASS |
| (c) `Decorator_1` key/operation/value = `DistanceToTarget` / `Less` / 900.0 | PASS |
| (d) `Decorator_3` key/operation/value = `DistanceToTarget` / `GreaterOrEqual` / 900.0 | PASS |
| (e) **zero** decorators on both waits, `WaitTime = 0.1` | PASS |
| (f) `RetreatDistance = 1300.0`, `AttackRange = 900.0` | PASS |

**Two tooling facts established here and worth carrying forward.**

- `unreal.AuraBehaviorTreeStatics.get_behavior_tree_structure()` takes an **asset-path string**, not
  an asset object.
- `UBehaviorTree::RootNode` is **protected**, so a true runtime-instance walk of a compiled tree is not
  reachable from Python. Verification is therefore from graph-node data carrying `ExecutionIndex`,
  which is what the engine compiles from. The tree's execution order was checked internally consistent
  as part of this.

### The generated defect — two mutually exclusive gates

This is the finding. Both branches of the selector are gated against the task they gate.

**Attack: a zero-width window.** The decorator admits `d ≥ 900`. `BTTask_EnemyAttack` refuses to fire
unless `DistanceToTarget <= AttackRange` = 900. Their intersection is the single point `d == 900.0`.
The probe measured `attack_window_width_cm = 0.0` in every phase. `n5` **executes** — 106 refusal
lines across three comparison trials — and never fires.

**Retreat: success is unreachable behind its own abort.** The decorator is `d < 900`; the task's
success test is `d ≥ RetreatDistance − 150 = 1150`. Because the decorator is on the task with
`FlowAbortMode = Self`, the task is killed the instant `d ≥ 900` — 250 cm before its own success test
can be satisfied. Across every run there are **0 `SUCCESS`** lines from
`BTTask_EnemyMoveAwayFromTarget`, a task that prints on every terminal path.

**The stop position is the abort, not the threshold.** At ≈500 cm·s⁻¹ and ≈3 FPS the pawn coasts
≈167 cm after the blackboard crosses 900: `mid_600` sampled 1051.2 → 1217.9, `close_200`
985.0 → 1151.5. Reading those endpoints as "the retreat reached its threshold" would be wrong.

**Consequence at 1500 cm: no branch admits anything.** `n1_Sequence` needs `d < 900`; `n4_Sequence`'s
first child needs `d ≤ 900` to fire. At `d = 1500` both fail, the selector loops, and the pawn stands
completely still with a flat 1500.0 cm blackboard — the measured 0.0 cm in both far phases.

### Condition isolation and action reachability (requirement #6)

Four phases, 8 s each, 32 s total (`aura_p07_probe.py`), player health 100000, enemy reset to spawn
per phase. Reproduced identically on two separate runs.

| Phase | Damage | Moved | Blackboard distance range |
|---|---|---|---|
| `far_1500` | 0.0 | **0.0 cm** | 1500.0 → 1500.0 |
| `mid_600` | 0.0 | 617.9 cm (y → 1217.9) | 600.1 → 1217.9 |
| `close_200` | 0.0 | 951.4 cm (y → 1551.4) | 200.2 → 1151.5 |
| `far_1500_again` | 0.0 | **0.0 cm** | 1500.0 → 1500.0 |

| Node | Action | Executes? | Evidence |
|---|---|---|---|
| `n2` | `move_away_from_target` | **yes** — and displaces the pawn | 618.0 / 951.3 cm moved in the two sub-900 phases; 0.0 cm in both far phases |
| `n3` | `wait` | **unobservable** | `BTTask_Wait` prints nothing; inferred from sequence position only |
| `n5` | `attack` | **executes, never fires** | 106 refusal lines; 0 damage; `attack_window_width_cm = 0.0` |
| `n6` | `wait` | **unobservable** | as `n3` |

**`n2`'s decorator is verified in both directions** — it executes below 900 and does not execute at
1500, which is what a purely "absence of movement" check could not have distinguished from a broken
task.

### Experimental control — `AttackRange = 10000`

Because `BTTask_EnemyAttack` prints only on refusal, zero damage admits two explanations: the gate
blocking a live branch, or a dead branch. The control separates them. `n5_Attack.AttackRange` was set
to `10000.0`, the identical probe re-run, then restored to `900.0` and re-verified.

| Phase | Control damage | Events | Distance at damage |
|---|---|---|---|
| `far_1500` | 20.0 | 4 | 1500.0 |
| `mid_600` | 5.0 | 1 | 1217.9 |
| `close_200` | 15.0 | 3 | 1151.5 |
| `far_1500_again` | 15.0 | 3 | 1500.0 |
| **Total** | **55.0** | **11** | — |

The control proves the weapon and damage path work, that the decorator genuinely admits execution at
`d ≥ 900` (it fired at 1500.0 cm, where the faithful run does nothing at all), and that the faithful
zero is caused by the generated contradiction rather than by a broken task or a stale decorator.

### Requirement #9 — generated defect vs Unreal/instrumentation

| Observation | Attributed to | Basis |
|---|---|---|
| 0 damage in every phase | **generated contradiction** | decorator admits `d ≥ 900`, in-task gate admits `d ≤ 900`; `attack_window_width_cm = 0.0`; control fires 11 events |
| retreat never reports `SUCCESS` | **generated contradiction** × decorator abort | abort at `d ≥ 900` precedes the task's own 1150 cm success test by 250 cm; 0 `SUCCESS` lines from a task that prints on every terminal path |
| 0.0 cm moved at 1500 cm | **generated logic** | neither branch is admitted at that distance; not a navigation failure |
| pawn stops ≈167 cm past 900 | **environment (sample rate)** | ≈500 cm·s⁻¹ coasting one frame at ≈3 FPS; the abort, not the threshold |
| one spurious far-band evaluation per teleport | **instrumentation** | each phase's first frame can read the previous phase's `DistanceToTarget`; cannot produce damage |
| control written under `P07PROBE_*` | **instrumentation** | running module predated the `OUTPUT_PREFIX` edit; copied to `P07CTRL_attackrange10000_*` and the faithful run re-written |
| `WARNING baseline reports a behaviour tree: unreadable` | **instrumentation** | `BP_AICharacter`'s stock `AIController` has no `BehaviorTreeAsset` property |
| 2.93 / 2.92 Hz sample rate | **environment** | background PIE throttling; timing quantised at ≈0.34 s |

### What is not claimed

- The 1300 cm retreat **policy** is unmeasured — the abort precedes the success test, so no
  successful disengage exists to observe.
- `n5`'s **blocking direction** was not isolated experimentally; the control substitutes for it.
- `n3_Wait` and `n6_Wait` were not observed to execute. Sequence position is not measurement.
- `retreat_health_pct` was not implemented and was not exercised.
- Nothing in this candidate was repaired. `RetreatDistance` 1300 and `AttackRange` 900 are exactly as
  generated, on a tree whose two gates contradict the two tasks they gate.

---

## Candidate #5 — `round2/P03-G02`

Source `dataset/raw_outputs/20261105_round2/P03-G02.txt`, unmodified: `behavior_id =
keep_distance_attack`, style `range_based`, 10 nodes, **REVIEW**, `manual_review = 1`,
`correction_class = mapping`, no `FAIL` codes. Findings: one **`L5`**.

> `AMBIGUOUS:L5:attack is not guarded by any distance_to_target condition on its path; weapon
> range is 5000 cm so it may fire far out of intended range`

Parameters `attack_range_cm` 1000, `retreat_distance_cm` 1500, `retreat_health_pct` 0.2 (**unused**
— no node tests health).

```
n0_Selector
+- n1_Sequence  (NO decorator)   n2_MoveAway       RetreatDistance=1500   [DEC: d Less 800]
|                                n3_Wait           WaitTime=0.1           (no decorator)
+- n4_Sequence  (NO decorator)   n5_MoveToTarget   AcceptanceRadius=850, ArrivalTolerance=150
|                                                                        [DEC: d Greater 1200]
|                                n6_Wait           WaitTime=0.1           (no decorator)
\- n7_Sequence  (NO decorator)   n8_Attack         AttackRange=1000       [DEC: CanAttack Set]
                                 n9_Wait           WaitTime=0.1           (no decorator)
```

### Build and verification (requirement #4)

`BT_Behavior_P03_G02` created with the BT tooling (`bp_agent` cannot create a `UBehaviorTree`),
saved, then read back **independently of the build** through asset metadata and re-verified from
graph-node data. **17/17 checks PASS**, including:

| Check | Result |
|---|---|
| 10 exact node names, in order | PASS |
| Decorators on `n1`, `n4`, `n7` | **zero**, all three |
| `n2` decorator | `DistanceToTarget` / `Less` / 800.0 |
| `n5` decorator | `DistanceToTarget` / `Greater` / 1200.0 |
| `n8` decorator | `CanAttack` / `BasicOperation = Set` |
| `NotifyObserver` / `FlowAbortMode` / `bInverseCondition` | `ResultChange` / `Self` / `False` on all three |
| `n2_RetreatDistance` | 1500.0 |
| `n5_AcceptanceRadius`, `ArrivalTolerance` | 850.0, 150 |
| `n8_AttackRange` | 1000.0 |
| Three `WaitTime` | 0.1 each |

No property needed a silent correction and nothing was repaired. `retreat_health_pct = 0.2` was
deliberately **not** implemented: no node tests health, so implementing it would have added
behaviour the model never asked for.

### Condition isolation and action reachability (requirement #5)

Four phases, 8 s each, 32 s total, player health 100000, enemy reset to spawn per phase. Run three
times: `aura_p03_probe` (with a retreat-goal / navmesh diagnostic), `aura_p03_probe2` (independent
projectile counting), `aura_p03_probe3` (via the canonical `aura_probe_generic`, reading
`Weapon.LastFireTime`).

| Phase | Damage | Moved | End separation | Blackboard distance | `weapon_fired` |
|---|---|---|---|---|---|
| `far_1500` | 0.0 | 834.5 cm | 2333.8 cm | 882.5 → 2333.8 | **0** |
| `mid_600` | 0.0 | **0.0 cm** | 600.1 cm | 600.1 → 600.1 | **0** |
| `close_200` | 0.0 | **0.0 cm** | 200.2 cm | 200.2 → 200.2 | **0** |
| `far_1500_again` | 0.0 | 834.9 cm | 2334.2 cm | 882.5 → 2334.2 | **0** |

Run-to-run spread is under 1 cm in every phase (835.3 / 834.3 / 834.5 at `far_1500`).
`P03PROBE2` recorded `projectiles_max = 0` and `samples_with_projectile = 0` in all four phases;
`P03PROBE3` recorded `weapon_fired = 0` with `last_fire_start = last_fire_end = 0.000` in all four.
The read path works — `P03PROBE3` logged `weapon_Damage 5.0`, `weapon_FireRate 1.0`,
`weapon_Range 5000.0`, `weapon_Accuracy 0.6`, `weapon_BulletSpeed 2500.0` from the live weapon, and
`BP_Projectile_C` as the projectile class.

`weapon_fired` is a **fired / not-fired flag** from `Weapon.LastFireTime`, not a shot count: the
control run below logs `weapon_fired = 1` on a phase with 5 damage events. A value of `0` therefore
means `LastFireTime` never moved, which is positive evidence of no shot.

| Node | Action | Executes? | Evidence |
|---|---|---|---|
| `n2` | `move_away_from_target` | **yes** — displaces the pawn, and does so in the band its own guard forbids | 835 cm at 1500 cm; **11 `SUCCESS`** lines |
| `n3` | `wait` | **unobservable** | `BTTask_Wait` prints nothing |
| `n5` | `move_to_target` | **yes** — returns immediately, without moving | **21 `SUCCESS`** lines, 0.0 cm moved in four phases |
| `n6` | `wait` | **unobservable** | as `n3` |
| `n8` | `attack` | **once, and refused** | one `BTTask_EnemyAttack: out of range - FAILURE` in the whole comparison |
| `n9` | `wait` | **unobservable** | as `n3` |

### The generated defect

**The attack branch is starved, not blocked, and the mechanism is priority.** `n1` and `n4` both sit
above `n7`, each ends in an **unguarded** `Wait`, and each therefore returns SUCCESS whenever its
first child succeeds — so the selector stops before `n7` on almost every pass.

| Line | Count | Meaning |
|---|---|---|
| `n1` failures | **22** | 16 `retreat too short` + 5 `already beyond retreat range` + 1 `no target` |
| `n5` attempts | 22 | every `n1` failure admits `n4` |
| `n5` `SUCCESS` / `FAILURE` | **21 / 1** | 21 immediate successes inside `AcceptanceRadius` 850; `arrived too far` = 0 |
| `n8` executions | **1** | only the single both-fail pass reached `n7` |
| `weapon_fired` | **0** | every phase, every probe, every trial |

22 = 21 + 1, so the arithmetic is closed: the one `n5` failure is the one `n8` execution, and at that
moment the pawn was at the far band and `BTTask_EnemyAttack`'s own gate refused. `n8` is therefore
**reachable in principle and unreachable in practice at 200 cm and 600 cm** — exactly the inverse of
candidate #6, where the branch executed 106 times and was blocked one layer down.

**Both leaf distance guards were observationally inert.** `n2` (`d < 800`) executed at `d = 1500`
and moved the pawn; `n5` (`d > 1200`) executed at 200 cm and 600 cm. Their authored values read back
correctly, so **the effective decorator state differs from the authored read-back and the 17/17
property verification could not detect it.** `OperationType` — the byte actually evaluated — is not
exposed by `AuraBehaviorTreeStatics`, and the subobject enumeration that would reach it failed
because `K2_GatherSubobjectDataForInstance` requires an `Actor`. **Mechanism unresolved.**

**Retreat succeeded here, against the prediction.** Candidates #3 and #6 both had a retreat that
could never report `SUCCESS`; #5 logged **11 `SUCCESS`** lines ending at 2334.4 cm. Not a repair and
not luck: `BTTask_EnemyMoveAwayFromTarget` asks for the move first and tests `d ≥ RetreatDistance −
150 = 1350` afterwards, and in the far band the player sits at y = −900, so a pawn at y = 600
already measures 1500 cm and passes on arrival. The off-navmesh goal `(0, 2100)` did not block it.
The corollary: the retreat only ever succeeded in the band its own guard forbids; in the bands it
permits it logged `retreat too short` 16 times.

**`CanAttack` was not the blocker.** For a Bool key, `BasicOperation = Set` means "must be true"
(`BlackboardKeyType_Bool.cpp:47`), and `bb_can_attack_true_rate` was ≥ 0.958 in every generated
phase — so `n8`'s decorator admitted. It also never denied anything, and is **unverified in the
blocking direction**.

### Positive control — `BT_Behavior_AttackAlways`, same probe, same arena

Because `BTTask_EnemyAttack` prints only on refusal, and because the attack branch is reached but
refused rather than absent, a control was required to separate "starved" from "dead".
`AIController_ResearchEnemy.BehaviorTreeAsset` was repointed at `BT_Behavior_AttackAlways`, the same
probe run, then repointed back to `BT_Behavior_P03_G02` and re-verified
(`controller_now = /Game/Research/AI/BT_Behavior_P03_G02`).

| Phase | Damage | Events | Distance at damage | Moved | `weapon_fired` | `LastFireTime` window |
|---|---|---|---|---|---|---|
| `far_1500` | 15.0 | 3 | 882.3 | 618.1 cm (y → −17.9) | 1 | 0.000 → 7.402 |
| `mid_600` | 25.0 | 5 | 600.1 | 0.0 | 1 | 7.402 → 16.737 |
| `close_200` | 30.0 | 6 | 200.2 | 0.0 | 1 | 16.737 → 24.738 |
| `far_1500_again` | 15.0 | 3 | 716.1 | 784.6 cm (y → −184.3) | 1 | 24.738 → 33.405 |

Three things are settled by it at once. The weapon, damage path and `LastFireTime` all work in this
exact setup. A distance decorator on a **leaf task does gate** here — `AttackAlways`'s `Less 1000`
guard failed its attack child at 1500 cm, `CombatLoop` **failed with it**, the selector fell through
to `ApproachLoop`, the pawn closed 618 cm to 882 cm and only then fired. And a trailing `Wait`
**cannot rescue a forbidden first child**, which is the wrong-way-round assumption that makes
candidate #5's second branch so hard to read from the log alone.

### Requirement #8 — generated defect vs Unreal/arena/instrumentation

| Observation | Attributed to | Basis |
|---|---|---|
| 0 damage in every phase, 0 `weapon_fired` | **generated logic** | `n1`/`n4` terminate the selector before `n7` on all but one pass in the whole run; the control produces 17 events / 85.0 damage in the same arena |
| attack branch ran once, at the far band only | **generated logic** | 22 `n1` failures = 21 `n5` successes + 1 `n5` failure; one `n8` line total |
| `n2` executes at 1500 cm despite `d < 800` | **Unreal implementation (unresolved)** | authored read-back shows 800.0; an identically typed decorator gated in `AttackAlways` the same session |
| `n5` executes at 200/600 cm despite `d > 1200` | **Unreal implementation (unresolved)** | as above |
| retreat `SUCCESS` at 2334 cm | **generated parameters + arena** | success band is 1350 cm and the player sits at y = −900; not the Phase 7D navmesh failure |
| `retreat too short` 16× | **generated parameters + arena** | needs the pawn at y ≥ 1350 (600 band) / ≥ 1750 (200 band) against a 1976 cm navmesh limit |
| 0.0 cm at 200 cm in all three trials | **generated logic** | the retreat cannot reach its band; `n5` succeeds without moving; `n7` is never admitted |
| movement variance across trials (0.0 vs 833 cm at `mid_600`) | **instrumentation / unresolved** | stale-blackboard artefact at ≈3 Hz can decide the first pass, and the first pass decides the phase |
| `WARNING baseline reports a behaviour tree: unreadable` | **instrumentation** | `BP_AICharacter`'s stock `AIController` has no `BehaviorTreeAsset` property |
| 2.91 Hz sample rate | **environment** | background PIE throttling; timing quantised at ≈0.34 s |

### What is not claimed

- The `L5` risk itself — "would it fire far out of intended range?" — is **unmeasured**. `n8` was
  observed once, refusing at ≈1500 cm; it was never seen attempting a shot inside 1000 cm.
- The mechanism behind the inert leaf decorators is **not identified**, only measured.
- `n3_Wait`, `n6_Wait` and `n9_Wait` were never observed to execute.
- `n8`'s `CanAttack Set` decorator was never observed to deny anything.
- `retreat_health_pct` was not implemented and was not exercised.
- Nothing in this candidate was repaired. `AttackRange` 1000, `RetreatDistance` 1500 and
  `AcceptanceRadius` 850 are exactly as generated, on a tree whose three guards sit on leaf tasks
  and whose three sequences carry none.

---

## Candidate #4 — `round2/P01-G02`

Source `dataset/raw_outputs/20261105_round2/P01-G02.txt`, unmodified: `behavior_id =
close_range_aggressor`, style `aggressive`, 5 nodes, **REVIEW**, `manual_review = 1`,
`correction_class = mapping`, no `FAIL` codes. Findings: one **`L3`**.

> `AMBIGUOUS:L3:duplicate sibling conditions: shadowing risk only, NOT unreachable (a failing
> child falls through), manual review required`

Parameters `attack_range_cm` 250, `retreat_distance_cm` 600 (**unused** — the tree has no retreat
node), `retreat_health_pct` 0.15 (**unused** — no node tests health).

```
n0_Selector
+- n1_Sequence  (NO decorator)   n2_Attack         AttackRange=250        [DEC: d LessOrEqual 250]
|                                n3_Wait           WaitTime=0.1           [DEC: d LessOrEqual 250]
\- n4_MoveToTarget               AcceptanceRadius=100, ArrivalTolerance=150
                                                                         [DEC: d Greater 250]
```

The generated JSON gives every action its own condition, and `n2` and `n3` carry **the same one**.
That duplication is the whole `L3` finding. Note also what is *absent*: no node covers
`retreat_distance_cm`, and the selector is a two-branch ladder, not a priority list — the attack
branch is **first**, the approach is the fallback.

### Build and verification (requirement #5)

`BT_Behavior_P01_G02` created through `AuraBehaviorTreeStatics.create_behavior_tree` +
`add_bt_node` (`bp_agent` cannot create a `UBehaviorTree`), saved, then read back **independently of
the build**. **17/17 assertions PASS**:

| Check | Result |
|---|---|
| 9 compiled nodes = ROOT + 2 composites + 3 tasks + 3 decorators | PASS |
| ROOT `BlackboardAsset` | `BB_EnemyBehavior` |
| `n0_Selector` parent / index | ROOT / 0 |
| `n1_Sequence` parent / index | `n0` / 0 |
| `n2_Attack` parent / index / class | `n1` / 0 / `BTTask_EnemyAttack_C` |
| `n2_Attack` `AttackRange` | 250.0 |
| `n3_Wait` parent / index / class | `n1` / 1 / `BTTask_Wait` |
| `n3_Wait` `WaitTime` / `RandomDeviation` | 0.1 / 0.0 |
| `n4_MoveToTarget` parent / index / class | `n0` / 1 / `BTTask_EnemyMoveToTarget_C` |
| `n4_MoveToTarget` `AcceptanceRadius` / `ArrivalTolerance` | 100.0 / 150.0 |
| Decorators on the two composites | **zero**, both |
| `n2` decorator (key / op / value) | `DistanceToTarget` / `LessOrEqual` / 250.0 |
| `n3` decorator (key / op / value) | `DistanceToTarget` / `LessOrEqual` / 250.0 — **the duplicate, present as authored** |
| `n4` decorator (key / op / value) | `DistanceToTarget` / `Greater` / 250.0 |
| `NotifyObserver` on all three | `ResultChange` |
| `FlowAbortMode` / `bInverseCondition` on all three | `Self` / `False` |
| Controller default after repointing + re-save | `/Game/Research/AI/BT_Behavior_P01_G02` |

No property needed a silent correction and nothing was repaired. `retreat_distance_cm` 600 and
`retreat_health_pct` 0.15 were deliberately **not** implemented: no node uses either, so
implementing them would have added behaviour the model never asked for.

**Two translation decisions, recorded as assumptions rather than translations:**

1. **`WaitTime = 0.1 s`, `RandomDeviation = 0.0`.** 0 of 40 generated documents supply
   `wait_seconds`. Kept identical to candidates #1, #2, #3, #6 and #5 so the trees stay comparable.
2. **`AcceptanceRadius = 100.0`** follows the Phase 5C mapping `attack_range_cm − 150`. Because
   `BTTask_EnemyMoveToTarget` reports success at `d <= AcceptanceRadius + 150`, the move succeeds at
   exactly **250 cm** — the same number as the attack decorator. On this tree the handoff is
   coherent and the approach genuinely enters the band; the measured standoff is 133.6–209.3 cm.

### Condition isolation and action reachability (requirement #6)

Five phases through the canonical `aura_probe_generic` (`p7p01g2_probe1`, prefix `P01G2PROBE`), 38 s
total, player health 100000, enemy reset to spawn per phase. `boundary_250` is added because this
tree's threshold is 250 and `close_200` alone would not test the edge.

| Phase | Damage | Events | Moved | End separation | Blackboard range | `weapon_fired` |
|---|---|---|---|---|---|---|
| `far_1500` | 25.0 | 5 | 1320.1 cm | 183.8 cm | 183.8 → 1500.0 | 1 |
| `mid_600` | 35.0 | 7 | 472.6 cm | 132.0 cm | 132.0 → 600.1 | 1 |
| `close_200` | 35.0 | 7 | **0.0 cm** | 200.2 cm | 132.0 → 200.2 | 1 |
| `boundary_250` | 40.0 | 8 | 68.2 cm | 183.6 cm | 183.6 → 250.1 | 1 |
| `far_1500_again` | 15.0 | 3 | 1329.2 cm | 174.9 cm | 174.9 → 1500.0 | 1 |

30 events / 150.0 damage over 38 s. The read path is live (`weapon_Damage 5.0`, `weapon_FireRate 1.0`,
`weapon_Range 5000.0`, `weapon_Accuracy 0.6`, `weapon_BulletSpeed 2500.0`, `BP_Projectile_C`).
`close_200`'s blackboard minimum of **132.0** is the previous phase's value persisting into the first
0.1 s tick — the staleness is visible, not inferred.

The decisive reachability evidence is the `boundary_250` phase sampled at 59 Hz:

| t (s) | geo (cm) | blackboard | projectiles | damage | enemy y |
|---|---|---|---|---|---|
| 0.050 | 250.1 | 250.1 | **1** | 0.00 | 600.0 |
| 0.085 | 250.1 | 250.1 | 0 | **5.00** | 600.0 |
| 0.202 | 248.4 | 250.1 | 0 | 0.00 | 598.3 |
| 0.298 | 230.0 | 244.5 | 0 | 0.00 | 579.8 |
| 0.399 | 191.6 | 219.4 | 0 | 0.00 | 541.2 |
| 0.449 | **183.6** | 183.6 | 0 | 0.00 | 533.0 |
| 1.050 | 183.6 | 183.6 | 1 | 0.00 | 533.0 |
| 1.102 | 183.6 | 183.6 | 0 | **5.00** | 533.0 |

The enemy starts 0.1 cm **outside** the band, moves 67 cm inward under `n4` (`d > 250` still true at
entry), stops dead at 183.6 cm and does not move again for 7.5 s while firing. The single 250.1 cm
damage event is a **carry-over projectile**: `projectiles = 1` is already present 35 ms earlier, while
the pawn is still at y = 600.0, so it was fired in the previous phase. It is the only out-of-band event
in the entire phase set and it is not a gate failure.

| Node | Action | Executes? | Evidence |
|---|---|---|---|
| `n2` | `attack` | **yes, repeatedly** | 55 landed events + 10 `out of range - FAILURE` lines in the comparison; in the probe, `weapon_fired = 1` in all five phases |
| `n3` | `wait` | **unobservable** | `BTTask_Wait` prints nothing |
| `n4` | `move_to_target` | **yes** — and only while out of band | 9 `SUCCESS` lines, exactly the 9 outside-band phases; 0.0 cm moved in all three `close_200` phases |

### The `L3` question answered: duplicates are redundant, not shadowing

The `L3` finding pre-registered exactly one risk — that duplicated sibling conditions might *shadow*
each other, leaving one child permanently unreachable behind an equivalent sibling — and explicitly
noted it is "NOT unreachable (a failing child falls through)". **The measured answer is that no
shadowing occurs.**

- `n2_Attack` fires continuously across all 12 comparison phases: 55 landed events plus 10 refused
  attempts. It is not shadowed, starved or skipped.
- `n4_MoveToTarget` runs and reports `SUCCESS` in exactly the 9 phases that begin outside the band,
  and in none of the 3 that begin inside it. Its `d > 250` guard is therefore effective in the
  permission direction and priority-consistent in the denial direction.
- Both children of `n1` read the *same* key inside the same evaluation window, so `n3`'s check cannot
  differ from `n2`'s: the duplicate is one redundant comparison, not a gate that can deny the branch
  after the attack has already run.

The contrast with the two prior failure modes is the finding, and it is a contrast in the *kind* of
sibling relation, not in decorator count:

| Candidate | Sibling relation on the attack path | Result |
|---|---|---|
| #2 `P02-G01` | **contradictory** (`d > 800` then `d <= 800` in one sequence) | attack unreachable, 0 damage |
| #5 `P03-G02` | **unguarded** siblings that each end in a `Wait` and succeed first | attack starved by priority, 0 damage |
| #4 `P01-G02` | **identical** duplicates | attack executes continuously, 275.0 damage |

**The attack node is also entered while out of band and refused by its own gate — 10 times.** Nine of
the ten `BTTask_EnemyAttack: out of range - FAILURE` lines land at a consistent ≈1.1 s offset into the
nine phases that begin outside the band, at which point the pawn is still ≈950 cm out; the tenth is at
the tail of trial 3's overshoot phase. `BTTask_EnemyAttack` prints **only** on refusal, so each line
proves `n2` executed and its own `DistanceToTarget <= AttackRange` check then declined to fire. Zero
of the ten produced damage. This is the mirror image of candidate #5, where the in-task gate was never
shown to matter: here it is demonstrably load-bearing.

### Requirement #9 — generated defect vs Unreal/arena/instrumentation

| Observation | Attributed to | Basis |
|---|---|---|
| 55 events / 275.0 damage, 0 out-of-band | **generated logic working as authored** | the attack branch is first in the selector and both guards agree with the task gate |
| 10 in-task refusals at ≈950 cm | **generated logic + Unreal task gate** | refusals are logged by `BTTask_EnemyAttack` itself; no damage resulted |
| duplicate condition did not shadow | **generated logic** | `n2` executed 65+ times; `n4` succeeded in exactly the 9 out-of-band phases |
| one 250.1 cm damage event | **instrumentation** | `projectiles = 1` 35 ms earlier with the pawn unmoved — carry-over from the previous phase |
| `close_200` blackboard min 132.0 vs geo 200.2 | **instrumentation** | `DistanceToTarget` is written on a 0.1 s timer; the first tick inherits the previous phase's value |
| ≈1.1 s offset before each refused attack | **Unreal implementation (unresolved)** | consistent 9/9 across phases, so not chance; mechanism is a hypothesis, not a measurement |
| trial 3 `far_1500_again` overshoot to 546.0 cm | **arena / AI move task (unresolved)** | 1 phase of 12; the pawn ran past a stationary target and had not returned when the phase ended |
| 59 Hz sample rate | **environment** | PIE ran unthrottled this session, unlike the previous five |
| `WARNING baseline reports a behaviour tree: unreadable` | **instrumentation** | `BP_AICharacter`'s stock `AIController` has no `BehaviorTreeAsset` property |

### What is not claimed

- The duplicate decorator's **abort** behaviour is unmeasured. `n3`'s identical condition carries
  `FlowAbortMode = Self` / `NotifyObserver = ResultChange`, so a separation *growing* past 250 cm
  during the 0.1 s wait would abort the sequence and drop the selector to `n4`. The protocol holds
  the player static while the enemy closes, so distance is monotonic and that path never ran.
- Decorator and in-task gate are **not separable for `n2`**: both read `DistanceToTarget` against
  250 cm. The pair is proven sufficient to keep all damage in band; which member refused on the 10
  out-of-band passes is not established. Unlike candidate #5, there is no evidence of inertness.
- The ≈1.1 s entry-while-out-of-band offset has **no identified mechanism**.
- The trial 3 overshoot is **not explained** and is reported as an anomaly.
- `n3_Wait` was never observed to execute, so the 0.1 s wait is not measurable here.
- `retreat_distance_cm` 600 and `retreat_health_pct` 0.15 were not implemented and not exercised.

---

## Repeatable comparison procedure: generated enemy vs baseline control

Purpose: measure reaction correctness, behaviour-failure count, damage dealt and responsiveness for
the generated enemy and for `BP_AICharacter`, under identical conditions.

**Frozen control group — never modified:** `BP_AICharacter`, `BP_WeaponBase`, `BP_Projectile`,
`BP_FirstPersonCharacter`, `DT_CharacterData`, `IN_GenericActions`, `Lvl_FirstPerson`.
`BP_AICharacter` remains the control; the experimental enemy remains `BP_BasicEnemyAI` with a swappable
`BehaviorTreeAsset` on `AIController_ResearchEnemy`.

Protocol:

1. **Arena** — `/Game/Research/Maps/Lvl_Research_Trial`, floor at z = 0, `NavMeshBoundsVolume` at
   `(0, 0, 200)`, enemy spawned at `(0, 600, 120)`, `PlayerStart` at `(0, -200, 120)`
   (800 cm spawn-to-spawn). Identical for both enemies.
2. **Subject installation** — one enemy actor in the level at a time. For the generated enemy, place
   `BP_BasicEnemyAI` and confirm `AIController_ResearchEnemy.BehaviorTreeAsset` points at the tree
   under test (read it back during PIE; do not assume). For the baseline, place `BP_AICharacter`
   unchanged. Record the subject's class and, for the generated enemy, the tree path.
3. **Player settings** — `BP_FirstPersonCharacter` with `CurrentHealth` raised to `100000` at session
   start so no run is truncated by player death. Player position is reset to a fixed distance at each
   phase start, and the player takes no input for the whole run so both subjects face the same
   stimulus.
4. **Phases** — `1500 cm / 8 s`, `600 cm / 5 s`, `200 cm / 6 s`, `1500 cm / 6 s`. Same order, same
   durations, both subjects. The repeat of 1500 cm at the end detects hysteresis.
5. **Combat settings** — identical for both: `FiringInterval` 1.0 s, `ShootingDamage` 5,
   `EnemyBulletSpeed` 2500, `ShootingRange` 5000. Confirm the baseline's own values against the parity
   bar before running.
6. **Metrics recorded per subject**
   - *Reaction correctness* — distance at each damage event, compared with that tree's own attack
     threshold. Pass = no damage event beyond threshold + tolerance.
   - *Damage dealt* — sum of player health deltas over the run, and events per phase.
   - *Responsiveness* — time from phase reset to first damage in that phase.
   - *Behaviour-failure count* — `BTTask_EnemyMoveToTarget` logs `SUCCESS` / `FAILURE (arrived too
     far) d=...`; count `FAILURE` lines from the log for the run window. For the baseline, which has no
     behaviour tree, record **"not applicable"** — not zero, because zero would imply comparable
     behaviour that was measured.
   - *Sample rate* — always recorded. Runs are only comparable at similar rates.
7. **Validity gates** — the run is void and must be repeated if: PIE did not come up in
   `Lvl_Research_Trial`; the controller's tree path is not the tree under test; the sample rate is
   below ~10 Hz for most of the run; or the enemy/player could not be resolved. A void run must be
   reported as void, never as a result.
8. **Reporting** — both subjects reported as a pair with the same phase table, plus the caveats above.
   Never compare a generated enemy measured at 3 Hz against a baseline measured at 57 Hz.

---

## Status

- **Candidate #1** (`round2/P01-G01`) built, repaired, behaviourally verified, and compared against the
  baseline in Phase 7B (`docs/BASELINE_COMPARISON.md` §§1–12). `BT_Behavior_P01_G01` is unmodified and
  remains reproducible.
- **Candidate #2** (`round2/P02-G01`) built, its three decorators verified in the *compiled* tree, its
  two testable conditions isolated, its sawtooth measured, and its comparison against the baseline run
  (Phase 7C, `docs/BASELINE_COMPARISON.md` §13). `BT_Behavior_P02_G01` is unmodified and reproducible by
  repointing the controller.
- **Candidate #3** (`round2/P04-G01`) built and verified (all five compiled decorators, three of them on
  composites), its four distance bands probed, and its comparison against the baseline run (Phase 7D,
  `docs/BASELINE_COMPARISON.md` §14). Reproducible by repointing the controller.
- **Candidate #6** (`round2/P07-G01`) built and verified (7 nodes, exactly two compiled decorators, both
  on leaf tasks, and zero on either sequence), its four bands probed **with a positive control**, and its
  comparison against the baseline run (Phase 7E, `docs/BASELINE_COMPARISON.md` §15).
  `BT_Behavior_P07_G01` is unmodified. Candidates #1, #2, #3 and #6 all remain in place, so any of them
  is reproducible by repointing `AIController_ResearchEnemy.BehaviorTreeAsset`.
- **Candidate #5** (`round2/P03-G02`) built and verified (10 nodes, exactly three compiled decorators, all
  three on leaf tasks and **zero** on the three sequences), its four bands probed three times plus a
  positive control, and its comparison against the baseline run (Phase 7F,
  `docs/BASELINE_COMPARISON.md` §16). `BT_Behavior_P03_G02` is unmodified and is **the live controller
  default** as of Phase 7F, so any PIE run in this project currently exercises candidate #5.
- **Measured generated defect, left intact:** candidate #2's `n6_Attack` is unreachable by construction
  (`n5 d>800` precedes `n6 d<=800` in one sequence, and the pawn stops at 716.2 cm inside the band), so
  the tree never attacks and becomes permanently inert once it has closed. It is a finding, not a bug
  to repair.
- **Measured generated defect, left intact:** candidate #3's close band is **dead code in this arena**.
  `retreat_distance_cm = 2000` needs 1850 cm of separation, which exceeds the 1976 cm navmesh half-extent
  from a close-band position, so `n2` always fails, `n1_Sequence` never advances, and `n3`/`n4` never
  execute. The tree silently degrades to two bands and still deals damage. Also a finding, not a bug.
- **Measured generated defect, left intact:** candidate #6's two branches are each **mutually exclusive
  with the task they gate**. `attack_range_cm` 900 with a `d >= 900` decorator leaves an admitted attack
  window of exactly `d == 900.0` (`attack_window_width_cm = 0.0`), while the task's own gate admits
  `d <= 900` — so the branch executes and never fires. `retreat_distance_cm` 1300 with a `d < 900`
  decorator under `FlowAbortMode = Self` kills the retreat at 900, 250 cm before the task's own 1150 cm
  success test — so the retreat never reports `SUCCESS`, yet still displaces the pawn 618–951 cm. Net
  result: **0 damage in every phase of every trial**, and complete immobility at 1500 cm. A positive
  control (`AttackRange = 10000`, restored afterwards) produced 55.0 damage over 11 events in the same
  arena, which attributes the zero to the generated logic rather than to the task or the harness.
- **Measured generated defect, left intact:** candidate #5's attack branch is **starved by priority**.
  `n1` and `n4` both precede `n7` in the selector and each ends in an **unguarded** `Wait`, so each
  returns SUCCESS whenever its first child does and the selector stops before `n7`. Across three trials
  `n1` failed 22 times, which admitted `n4` 22 times, whose `n5` returned SUCCESS immediately 21 times
  inside `AcceptanceRadius` 850 — and the single `n5` failure is the only pass that reached `n8`, which
  then refused at the far band. **`n8` executes once in the whole run and the weapon never fires**, so
  the `L5` "may fire far out of intended range" risk did not occur: the branch fails closed. Compounding
  it, both leaf distance guards were **observationally inert** (`n2` with `d < 800` moved the pawn at
  1500 cm; `n5` with `d > 1200` ran at 200 and 600 cm) while an identically typed decorator gated in the
  control run. A finding, not a bug to repair.
- **Candidate #4** (`round2/P01-G02`) built and verified (9 nodes, exactly three compiled decorators, all
  three on leaf tasks and **zero** on either composite, including the duplicated sibling condition
  present as authored), its band probed with an added `boundary_250` phase, and its comparison against
  the baseline run (Phase 7G, `docs/BASELINE_COMPARISON.md` §17). `BT_Behavior_P01_G02` is unmodified
  and is **the live controller default** as of Phase 7G, so any PIE run in this project currently
  exercises candidate #4. All six selected candidates are now in place and reproducible by repointing
  `AIController_ResearchEnemy.BehaviorTreeAsset`.
- **Measured outcome, left intact:** candidate #4 is the **second policy-compliant tree and the best
  measured**. 55 events / 275.0 damage across three trials, **0 of 55 events beyond its own 250 cm
  band**, 0 beyond the 300 cm ceiling, reaction correctness **PASS**. It closes 1 320 cm to a
  133.6–209.3 cm standoff and fires there. Its `L3` duplicate-sibling risk **did not materialise**: the
  attack branch executes continuously and the approach branch succeeds in exactly the 9 phases that
  begin outside the band. The in-task attack gate is also **demonstrably load-bearing** for the first
  time in the set — 10 `out of range - FAILURE` lines at ≈950 cm, none of which produced damage.
- `BT_Behavior_AttackAlways` and `BT_Behavior_RetreatTest` are development test trees and remain
  unmodified. They must never be reported as research behaviours.
- The comparison procedure is now **executed six times** (Phase 7B candidate #1, Phase 7C candidate
  #2, Phase 7D candidate #3, Phase 7E candidate #6, Phase 7F candidate #5, Phase 7G candidate #4) with
  a fresh subject pair each time; baseline results are never carried across candidates whose
  thresholds differ. Evaluation Set 2 is complete: all six selected trees are implemented, measured
  and compared.
- **Failure-mode taxonomy now stands at six:** #1 policy-compliant and working; #2 structurally
  self-blocking and inert; #3 environmentally unsatisfiable but still damaging; #6 internally
  contradictory across two layers — fully executed, silent, and dealing zero damage; #5
  **priority-starved by its own unguarded siblings** — fully mobile, logging 22 terminal task lines,
  and still dealing zero damage because the selector is satisfied one branch too early; #4
  **policy-compliant and working**, and the only tree whose branch order puts the attack first, which
  is what separates it from #5.
- The corpus's largest finding category (`12 × L5`, unguarded attack) now has the most measured
  evidence, and on that evidence it **fails closed rather than open**: #5's missing guard was not
  exploited because the same missing-guard pattern on `n2` and `n5` starved the branch first. That
  qualifier belongs in the RQ1 discussion of the `L5` rate. The second-largest (`2 × L3`, duplicate
  sibling conditions) is now measured and **harmless**: redundancy in a sibling pair costs one
  comparison; only *contradictory* or *unguarded* siblings cost a branch.

---

## 18. Phase 7H — closing evidence gap G1 (candidate #5's decorator behaviour)

G1 asked a single question: was candidate #5's far-range retreat — a leaf guarded by
`DistanceToTarget < 800` that nevertheless ran at 1 500 cm — caused by the generated tree, by
Unreal's decorator evaluation, or by the measurement harness? Answering it required *new*
instrumentation, because no existing observable separates "the decorator admitted the task" from
"the task never ran": `BTDecorator_Blackboard` writes nothing to the log, and
`BTTask_EnemyMoveAwayFromTarget` prints only on its failure paths.

Nothing measured earlier was re-run or edited. `BT_Behavior_P03_G02` (candidate #5),
`BT_Behavior_P01_G01`, `BT_Behavior_P02_G01`, `BT_Behavior_P04_G01`, `BT_Behavior_P07_G01`,
`BT_Behavior_P01_G02`, `BT_Behavior_AttackAlways` and `BT_Behavior_RetreatTest` remain byte-identical,
as do all earlier `results/gameplay/*` files and the validation CSVs.

### 18.1 Instruments added

| Asset / script | Path | Role |
|---|---|---|
| `BT_Test_Decorator_Guard250` | `/Game/Research/AI/BT_Test_Decorator_Guard250` | 5-node dev control: ROOT → `TestRoot` (Sequence) → [`Ctl_MoveAway` (RetreatDistance 1500.0) decorated `DistanceToTarget < 250`, `Ctl_Wait` 0.5 s]. Not a research behaviour. |
| `BT_Behavior_P03_G02_R1` | `/Game/Research/AI/BT_Behavior_P03_G02_R1` | Node-for-node rebuild of candidate #5 from its read-back (14 nodes). |
| `aura_g1_diag.py` | `Content/Python/aura_g1_diag.py` | Read-only runtime diagnostic: samples `BrainComponent.is_running()` and `get_move_status()` every editor frame, phases `far_1500` 6 s then `close_200` 8 s. |

`AIController_ResearchEnemy.BehaviorTreeAsset` was repointed for each run and **restored to
`BT_Behavior_P01_G02`** at the end of the phase. No behaviour tree asset was edited or re-saved.

### 18.2 What the move-away task actually does

Read from the graph of `/Game/Research/AI/BTTask_EnemyMoveAwayFromTarget` (a Blueprint task, not C++) —
this had been *inferred* before and is now verified:

- `ReceiveExecuteAI`: if `TargetActor` is invalid → print `FAILURE (no target)`; else compute 3-D
distance `d`; if `d < RetreatDistance` → issue `AIController.MoveToLocation(Pawn + Normal(Pawn − Target) ×
RetreatDistance)` with `ProjectDestinationToNavigation = false`, `AllowPartialPath = true`, and **return
without finishing** (latent); else print `FAILURE (already beyond retreat range) d=…`.
- `ReceiveTickAI` (fires when `GetMoveStatus == Idle`): if `d ≥ RetreatDistance − 150` → print
`SUCCESS d=… thr=…`; else print `FAILURE (retreat too short) d=… thr=…`.
- `ReceiveAbortAI`: `StopMovement` + `FinishAbort`.

So the task has an **entry precondition of its own** (`d < RetreatDistance`) and a 150 cm success band.
At `RetreatDistance = 1500` the goal sits at y = 2 100, outside the arena navmesh, and with
`ProjectDestinationToNavigation = false` the move degrades to a partial path that ends at the navmesh
edge (y ≈ 1 433) — which is exactly the 834–835 cm plateau measured three times in Phase 7F.

### 18.3 Runs

All four runs used the canonical probe (`aura_probe_generic.py`), the same arena, the same four phases
(`far_1500`, `mid_600`, `close_200`, `far_1500_again`; 8 s each) and the same 2.9–3.0 Hz sampling.

| Run | Tree | Displacement (1500 / 600 / 200 / 1500 cm) | Damage | Weapon fired |
|---|---|---|---|---|
| `G1GUARD` | `BT_Test_Decorator_Guard250` | 0.0 / 0.0 / 0.0 / 0.0 | 0 | 0 (no attack node) |
| `G1DIAG` | `BT_Test_Decorator_Guard250` | 0.0 / — / 0.0 / — | — | — |
| `G1P03R1` | `BT_Behavior_P03_G02_R1` | **617.9** / 0.0 / 0.0 / **617.9** (toward the player) | 15 / 20 / 20 / 20 | 1 / 1 / 1 / 1 |
| `G1P03ORIG` | `BT_Behavior_P03_G02` | **834.5** / 0.0 / 0.0 / **835.1** (away) | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |
| `G1P03R1B` | `BT_Behavior_P03_G02_R1` | **618.2** / 0.0 / 0.0 / **618.1** (toward the player) | 20 / 25 / 25 / 20 | 1 / 1 / 1 / 1 |

Run order was `R1 → ORIG → R1B`, i.e. an A/B/A sequence in one session, so run order and wall-clock
time cannot explain the difference.

### 18.4 Findings

1. **The tree does execute.** `BrainComponent.is_running()` returned 1 in 41 of 41 `G1DIAG` samples across
   both phases (`BehaviorTreeComponent`), while `get_move_status()` returned `Idle` throughout and
   displacement stayed 0.0. "Tree running" and "pawn moving" are therefore separate observables and the
   earlier zero-displacement results were not a dead tree.
2. **Decorator gating works when the observed key is stable.** In `G1GUARD`, the leaf guarded by
   `DistanceToTarget < 250` entered the task **12 times in 8 s at 200 cm** (`retreat too short d=200.16
   thr=1350.0` every ≈0.67 s) and **zero times in 8 s at 600 cm**. The same asymmetry reproduces in
   candidate #6's preserved data: with `DistanceToTarget < 900` it moved 0.0 cm in both 1 500 cm phases
   and 617.9 / 951.4 cm in the 600 / 200 cm phases. Unreal is honouring these decorators.
3. **A decorator can still admit one entry on a stale key.** At `far_1500_again` the guard control entered
   the task exactly once (one `already beyond retreat range d=1500.02` line) immediately after the phase
   teleport, because `DistanceToTarget` is a 0.1 s staircase written by `AIController_ResearchEnemy` and
   still carried the previous phase's 200 cm. The probe samples at 3 Hz and cannot resolve that window.
4. **The decisive result is that the original #5 asset and its own rebuild disagree.** A dump-and-diff of
   both trees reports **14 nodes, 0 differences** across role, class, node name, parent index and every
   property value, including the `Less / 800.0` and `Greater / 1200.0` decorators and
   `CanAttack Equal` — yet in the same session the original retreats 834.5 cm and deals no damage while
   the rebuild closes 617.9 cm and attacks (15–25 damage per phase, weapon fired in every phase). The two
   .uasset sizes differ by 102 bytes (19 782 vs 19 884). The difference is therefore **in the asset's
   compiled Behaviour Tree data, not in its graph**.
5. **Candidate #5's measured outcome must be restated.** Phase 7F's record stands unchanged as an
   *as-built* observation: the asset at `/Game/Research/AI/BT_Behavior_P03_G02` retreats at far range,
   never fires, and deals 0 damage in three runs. But the explanation recorded at the end of §17 —
   "priority-starved by its own unguarded siblings" — **does not survive G1**: the graph-identical rebuild
   attacks at the same distances with the same decorators, so the authored tree is not priority-starved.
   The defect belongs to the compiled artefact, i.e. to the Unreal implementation layer, and #5's gameplay
   numbers must be reported as an **implementation artefact**, not as a generated-logic failure.
6. **Reachability findings that survive unchanged:** the retreat task cannot act below
   `RetreatDistance − 150` (`retreat too short`), and its 1 500 cm goal is unreachable in this arena
   (`ProjectDestinationToNavigation = false`), so a generated `retreat` action is environmentally
   constrained independently of any decorator.

### 18.5 What remains unobservable

- The *contents* of the original asset's compiled data. `OperationType` (the byte `BTDecorator_Blackboard`
  actually compares) is not exposed by `AuraBehaviorTreeStatics`, and `UBehaviorTree::RootNode` is
  protected, so there is no supported runtime walk. What is proven is the divergence, not which compiled
  field holds it.
- Decorator-level logging does not exist, so a sub-0.33 s false-permit cannot be seen directly at 3 Hz.
- The A/B/A comparison uses three runs of the rebuild pair, not a fresh three-trial set; it establishes
  the direction of the divergence, not a distribution.

### 18.6 Files

`results/gameplay/G1GUARD_{phases,samples,session}.*`, `G1DIAG_samples.csv`, `G1DIAG_session.txt`,
`G1P03R1_*`, `G1P03ORIG_*`, `G1P03R1B_*`. No baseline re-run was required: G1 is a mechanism question and
the baseline is not implicated in it.

### 18.7 Documentation still to be corrected for this finding

- `docs/BASELINE_COMPARISON.md` §16 (candidate #5): the failure-cause line must be relabelled
  implementation artefact, keeping the measured numbers intact.
- `docs/RESEARCH_PROGRESS.md` §9: the Phase 7G row claiming "no refusal-line count exists" for candidate
  #1 is wrong — the count exists in `Saved/Logs/Cosmic_Animossity.log` and is **0** (verified in the audit,
  gap G2).
- The cross-candidate failure taxonomy (end of §17) needs #5 moved out of "starved by siblings" into
  "as-built compiled-data divergence", with `BT_Behavior_P03_G02_R1` cited as the control.
