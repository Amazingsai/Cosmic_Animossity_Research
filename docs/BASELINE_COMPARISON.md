# Baseline Comparison — Generated Candidates vs `BP_AICharacter`

Phase 7 controlled gameplay comparisons for DS 340W, addressing **RQ2** (gameplay
effectiveness).

One section per candidate. **§§1–12 are candidate #1** (`round2/P01-G01`, run `p7cmp_r1`);
**§13 is candidate #2** (`round2/P02-G01`, run `p7cmp_p02_r1`). The methodology in §§3–6 is shared
and is not restated for candidate #2 — only its differences are listed.

## Candidate #1 (`round2/P01-G01`)

| Field | Value |
|---|---|
| Run ID | `p7cmp_r1` |
| Date | 2026-11-15 |
| Engine | UE 5.7.4, Blueprint-only |
| Level | `/Game/Research/Maps/Lvl_Research_Trial` |
| Trials | 3 per subject, 4 phases per trial (12 phase measurements per subject) |
| Session model | One PIE session per subject; all three trials inside it |

---

## 1. Purpose

Compare the generated enemy (`BP_BasicEnemyAI` running `BT_Behavior_P01_G01`) against
the untouched manual baseline (`BP_AICharacter`) on the same arena, player, spawn
geometry, combat settings and phase durations, and quantify four things:

1. **Reaction correctness** — does the enemy attack only inside its intended range?
2. **Behaviour failure count** — how often do behaviour-tree tasks fail?
3. **Damage dealt** — total damage output per phase.
4. **Responsiveness** — time from phase start to first damage.

This is the first controlled comparison. It is a *procedure validation plus a first
measurement*, not a conclusion about RQ2 across candidates.

---

## 2. Subjects

| | Generated | Baseline |
|---|---|---|
| Blueprint | `BP_BasicEnemyAI` | `BP_AICharacter` (unmodified) |
| Controller | `AIController_ResearchEnemy_C` | stock `AIController` |
| Decision source | `BT_Behavior_P01_G01` | Event graph (no behaviour tree) |
| Blackboard | `BB_EnemyBehavior` | none |
| Attack gate | tree decorator `DistanceToTarget <= 300` + in-task gate | none (sight-based) |
| Contract verified at run time | controller's tree path asserted to contain `BT_Behavior_P01_G01`, else the session aborts | controller class is native `AIController`; `BehaviorTreeAsset` does not exist on it; blackboard absent (`bb_cm = -1` on every event) |

`BP_AICharacter` was not modified in any way. Its behaviour, as read from the asset:

- `BeginPlay` → `ApplyCharacterData` → spawn `BP_WeaponBase_C`, attach to `hand_r`,
  then set `Damage` 5, `Range` 5000, `Accuracy` 0.6, `FireRate` = 1/`FiringInterval` = 1.0,
  `Bullet Speed` 2500.
- `Tick` → `GetDataTableRow` → `AI MoveTo` (AcceptanceRadius 70) whose **OnSuccess** calls
  the `AIInteract` custom event; `Tick` also rotates the pawn to face the player.
- `AIInteract` → validate player and weapon → `SetActorRotation` → `Weapon.FireAt`.
  It is also bound to `PawnSensing.OnSeePawn`.
- `PawnSensing`: `SightRadius` **5000**, `PeripheralVisionAngle` 70, `SensingInterval` 0.5.

Neither firing path contains a distance check. The baseline is therefore a *proximity
rusher that also fires the moment it acquires sight*, and that is its design, not a defect.

---

## 3. Controlled conditions

| Variable | Value (identical for both subjects) |
|---|---|
| Level | `Lvl_Research_Trial` (asserted at PIE start; a mismatch aborts the session) |
| Subject spawn | `(0, 600, z)` — baseline sited on the experimental enemy's exact transform |
| Subject yaw | −90 (facing the player) |
| Combatants present | exactly one per session |
| Player pawn | unchanged `BP_FirstPersonCharacter`, no input, static |
| Player start | `(0, 600 − d, player_z)` |
| Player health | raised to 100000 before trials so no death truncates a phase |
| Phases | `far_1500` 8 s @1500 cm, `mid_600` 6 s @600, `close_200` 6 s @200, `far_1500_again` 6 s @1500 |
| Trial length | 26 s |
| Weapon | same `BP_WeaponBase_C`, damage 5 per hit (confirmed: every event delta = 5.00) |
| Sampling | one read per Slate tick, identical code path for both |

## 4. Uncontrolled differences (recorded, not corrected)

1. **No distance condition exists in the baseline.** "Reaction correctness" is undefined
   for a control that has no range rule. Its long-range shots are reported as a
   *difference in behaviour*, never as a failure.
2. **Acceptance radius**: baseline 70, generated 150. The baseline consequently closes
   closer (55–113 cm) than the generated enemy (152–219 cm).
3. **Fire cadence**: baseline 1.00 s (weapon `FireRate` 1.0); generated ≈1.33 s (tree cycle
   = attack task + `n3_Wait` 0.1 s + task overhead). Observed, not equalised.
4. **Controller class** differs (native `AIController` vs a Blueprint subclass).
5. **Tick cost** differs: the baseline is a fork of the player character and still carries
   a first-person mesh, camera, HUD and Enhanced Input handlers. It therefore does extra
   per-frame work the generated enemy does not.
6. **Sample rate** was ~2.9 Hz for both (editor background throttling); see §6.1.

---

## 5. Metric definitions

**Reaction correctness.** Distance at damage, measured per damage event. Because the
subject closes on a *stationary* player, the sampled distance is a **lower bound** on the
true firing distance: the shot was at least that far. Violations therefore cannot be
masked, only missed. Events are flagged `beyond_threshold` (>300 cm, the generated tree's
`attack_range_cm`) and `beyond_ceiling` (>350 cm).

**Behaviour failure count.** Count of `BTTask_EnemyMoveToTarget: FAILURE` lines from
`LogBlueprintUserMessages`; success count from the matching `SUCCESS` lines.

**Damage dealt.** Sum of player-health drops per phase. Player health never reached zero.

**Responsiveness.** Wall-clock seconds from phase start (post-teleport) to the first
health drop, resolved to ±1/(sample rate) ≈ ±0.33 s.

---

## 6. Validity controls

### 6.1 PIE background throttling — accounted for, not eliminated
The editor background-throttles PIE. Measured sample rates were **2.8–3.2 Hz** across
every phase of both subjects, against ~57 Hz when the editor is foreground. Rather than
force an editor preference, throttling is handled by design:

- Phase boundaries are driven by **wall clock**, so a throttled editor does not stretch a
  phase — it only reduces the sample count.
- `sample_rate_hz` is recorded per phase, so resolution is auditable.
- Both subjects were throttled *equally* (mean 2.9 Hz), so the comparison is fair; only
  absolute timing precision is reduced.
- The headline contrasts (4.20 s vs 1.30 s time-to-first-damage; 218.6 cm vs 1421.2 cm max
  firing distance) are an order of magnitude larger than the ±0.33 s quantisation, so they
  survive it. The `close_200` responsiveness difference (1.12 s vs 1.22 s) is **within**
  that quantisation and is not treated as a real difference.

### 6.2 Stale report files
Every row carries `run_id=p7cmp_r1` and `subject`, and each subject writes to its own
filename; a session also writes a notes file recording its own row and event counts. A
stale file cannot be mistaken for a fresh one. (A previously stale
`Saved/aura_bt_probe_report.txt` had been read as if current; that class of error is what
this guards against.)

### 6.3 Incorrect level loading
An earlier phase produced a superficially valid 25 s result from `Lvl_FirstPerson` — a
level with no enemy — because `begin_play` was requested while a previous `end_play` was
still tearing down. Now `start()` refuses if PIE is already active, and the session
**aborts** unless the PIE world is `Lvl_Research_Trial`. Both sessions recorded
`world=Lvl_Research_Trial`.

### 6.4 Teleport contamination
Damage bookkeeping is skipped on the tick a teleport occurs, so a hit landed before a
player teleport is never attributed to the new phase distance. (This was the source of a
manufactured 600.1 cm violation earlier.)

### 6.5 Module reload
The editor's Python caches imported modules. After editing the harness, `importlib.reload`
was run and the live code confirmed (`hasattr(prepare_level)`) before the session started;
a stale-module attempt is visible in the log as a failure against already-superseded code.

---

## 7. Results

### 7.1 Reaction correctness (distance at damage)

| Subject | Events | Beyond 300 cm | Beyond 350 cm | Max distance at damage |
|---|---|---|---|---|
| Generated | 36 | **0** | **0** | **218.6 cm** |
| Baseline | 67 | 12 (17.9 %) | 11 (16.4 %) | 1421.2 cm |

Generated enemy, per phase (all three trials identical to within 0.3 cm):

| Phase | max / min distance at damage |
|---|---|
| `far_1500` | 218.3 – 218.6 |
| `mid_600` | 152.5 – 152.6 |
| `close_200` | 200.2 |
| `far_1500_again` | 218.3 – 218.6 |

Baseline, per phase:

| Phase | max distance at damage | Beyond 300 cm |
|---|---|---|
| `far_1500` | 1049.0 | 4 |
| `far_1500_again` | 1421.2 | 7 |
| `mid_600` | 316.3 | 1 |
| `close_200` | 82.1 | 0 |

The baseline's long-range shots occur while it is still closing (e.g. trial 1
`far_1500_again`: 1421.2 cm at t=0.67 s, 926.0 at 1.67 s, 428.5 at 2.67 s, then 103.6 at
3.67 s) — consistent with its sight channel (`SightRadius` 5000) with no range gate. The
generated enemy produced no damage at all until it had closed to its attack band.

### 7.2 Behaviour failure count

| Subject | Move-task successes | Move-task failures | Failure rate |
|---|---|---|---|
| Generated | 9 (3 per trial) | **0** | 0.0 % |
| Baseline | 0 | n/a | not applicable — no tree, no tasks |

### 7.3 Damage dealt

| Subject | Events | Total damage | Mean damage/phase | Mean damage/hit |
|---|---|---|---|---|
| Generated | 36 | 180 | 15.0 | 5.00 |
| Baseline | 67 | 335 | 27.9 | 5.00 |

Per phase:

| Phase | Generated dmg/phase | Baseline dmg/phase | Ratio |
|---|---|---|---|
| `far_1500` | 15.0 | 33.3 | 2.22× |
| `mid_600` | 15.0 | 25.0 | 1.67× |
| `close_200` | 20.0 | 26.7 | 1.33× |
| `far_1500_again` | 10.0 | 26.7 | 2.67× |

Damage per hit is identical, so the whole difference is attack uptime: the baseline
sustains a 1.00 s cadence almost from phase start, while the generated enemy spends the
first ~2.6 s closing before it can fire at all.

### 7.4 Responsiveness (time to first damage)

| Phase | Generated | Baseline |
|---|---|---|
| `far_1500` | 4.195 s | 1.304 s |
| `mid_600` | 2.775 s | 1.338 s |
| `close_200` | 1.121 s | 1.222 s (within noise) |
| `far_1500_again` | 4.549 s | 0.783 s |

### 7.5 Movement (side evidence)

| Phase | Generated moved | Baseline moved |
|---|---|---|
| `far_1500` | 1284.5 – 1284.8 cm (ends y ≈ −684) | 1411.8 – 1445.8 cm (ends y ≈ −845) |
| `mid_600` | 451.2 – 451.3 (ends y ≈ 149.6) | 578.9 – 579.1 (ends y ≈ 24.6) |
| `close_200` | **0.0** (all three trials) | 117.9 (ends y = 482.1) |

---

## 8. Behaviour-tree decisions vs in-task safety checks (requirement 8)

The two mechanisms are **not** equally evidenced by this run, and are reported separately:

**Move gating — a genuine tree decision, cleanly evidenced.** `close_200` teleports the
player to 200 cm, inside the `distance > 300` decorator's false branch. In all three trials
the generated enemy moved **exactly 0.0 cm**. A task-internal safety check cannot produce
that: `BTTask_EnemyMoveToTarget` was never entered. This is the tree refusing the node.

**Attack gating — a tree decision, but confounded in this run.** 0 of 36 events beyond
300 cm is consistent with the `DistanceToTarget <= 300` decorator, but
`BTTask_EnemyAttack` also contains its own hard-coded `DistanceToTarget <= AttackRange`
gate, and its instance value is also 300. With both thresholds equal, this run **cannot**
separate the decorator from the task's safety check. The separation was established
earlier by the isolation run (`AttackRange` = 10000 *with* the decorator, which still
produced nothing beyond 289 cm; and *without* the decorator, which fired at 1500 cm). The
present result is therefore consistent with the decorator but does not independently prove
it.

**`n3_Wait`'s `can_attack != true` condition remains unverified** (unchanged from the
implementation log): the observed ~1.33 s cadence is identical with and without the
decorator at the resolution available.

---

## 9. Interpretation

- The generated enemy is **strictly range-disciplined** and the baseline is not. The
  generated tree never attacked outside its band in 36 events across 12 phases; the
  baseline attacked at up to 1421 cm, 17.9 % of its events beyond 300 cm.
- That discipline costs throughput. The generated enemy dealt **1.86× less damage overall**
  (180 vs 335) and was **3.2× slower to first contact** at 1500 cm (4.20 s vs 1.30 s),
  because it must close ground it is not allowed to shoot across.
- At point-blank range the two converge: `close_200` shows 20.0 vs 26.7 damage per phase
  and 1.12 s vs 1.22 s to first damage. The gap is a range-policy effect, not a
  competence effect.
- No behaviour failures occurred for the generated enemy (0 of 9 move tasks).

This is a coherent RQ2 story for candidate #1: **policy-compliant but lower output**,
versus a control that is higher-output because it ignores range entirely. Whether
compliance is "better" depends on the research framing, not on these numbers alone.

---

## 10. Limitations

1. **One candidate, one baseline, one arena.** No generalisation to other candidates or
   other geometries yet.
2. **~2.9 Hz sampling.** Sub-0.33 s effects are invisible. Per-event *distances* are
   reliable (lower-bound argument); sub-0.33 s *timing* differences are not.
3. **Throttling not eliminated**, only accounted. If a future run happens to be
   foregrounded (~57 Hz), its sample rate will differ and should be recorded alongside.
4. **Attack-gating confound** (§8) — the in-run data cannot separate decorator from task
   gate at equal thresholds.
5. **Damage-unbounded player.** Player health was 100000 and never depleted, so no phase
   ended early; but "time to kill the default 100-health player" was not measured.
6. **Static player.** Player behaviour was held constant, not scripted; strafing or
   retreating play is untested.
7. **Baseline carries player-template overhead** (camera/HUD/input) that the generated
   enemy does not, which could affect frame time. Sample rates were equal, so this was not
   detectable here.
8. **Editor-world swap, never saved.** The baseline was placed in the editor world for the
   session and removed afterwards; the level file was never written. The restored actor is
   `BP_BasicEnemyAI_C_0` rather than the original `_1` — a name-only difference.
9. **Log-derived failure counts are not session-scoped.** The counts come from the current
   log file; the generated session's 9 successes were bucketed by timestamp
   (01:02:40–01:03:54) and the whole file contains zero `FAILURE` lines.
10. **`BehaviorTreeAsset` is absent on native `AIController`.** The baseline's tree field
    is `unreadable` by construction; BT-absence is established instead by controller class
    plus the missing blackboard.

---

## 11. Reproduction

1. Open `Lvl_Research_Trial`. Confirm PIE is stopped.
2. `importlib.reload(aura_baseline_compare)` if the harness was edited this session.
3. `aura_baseline_compare.start("generated")` — runs 3 trials × 4 phases against the
   placed experimental enemy; abort if the controller's tree is not `BT_Behavior_P01_G01`.
4. Wait ~90 s; the session ends PIE itself.
5. `aura_baseline_compare.restore_level()` — removes any baseline instance and restores
   the experimental enemy.
6. `aura_baseline_compare.start("baseline")` — swaps the combatant in the editor world,
   then runs the identical schedule.
7. Wait ~90 s, then `restore_level()` again.

The editor background-throttles PIE; do not `time.sleep` inside editor Python during a run
(it blocks the game thread and all phases expire at once).

---

## 12. Result files

| File | Contents |
|---|---|
| `results/gameplay/P7CMP_phase_metrics_generated.csv` | 12 phase rows, generated |
| `results/gameplay/P7CMP_phase_metrics_baseline.csv` | 12 phase rows, baseline |
| `results/gameplay/P7CMP_damage_events_generated.csv` | 36 per-event rows |
| `results/gameplay/P7CMP_damage_events_baseline.csv` | 67 per-event rows |
| `results/gameplay/P7CMP_combined_phase_metrics.csv` | 24 rows, both subjects |
| `results/gameplay/P7CMP_combined_damage_events.csv` | 103 rows, both subjects |
| `results/gameplay/P7CMP_summary.csv` | per-subject × per-phase aggregates |
| `results/gameplay/P7CMP_behavior_failures.csv` | task success/failure counts |
| `results/gameplay/P7CMP_session_generated.txt` | setup + per-phase notes |
| `results/gameplay/P7CMP_session_baseline.txt` | setup + per-phase notes |
| `Content/Python/aura_baseline_compare.py` | harness (subject-swappable) |

Original generated JSON, manifests, Round 1/Round 2 validation CSVs, `BP_AICharacter`,
`BP_WeaponBase`, `BP_Projectile`, `BP_FirstPersonCharacter`, `DT_CharacterData` and
`Lvl_FirstPerson` were not modified.

---

# 13. Candidate #2 — `round2/P02-G01`

| Field | Value |
|---|---|
| Run ID | `p7cmp_p02_r1` |
| Date | 2026-11-15 |
| Tree | `/Game/Research/AI/BT_Behavior_P02_G01` |
| Trials | 3 per subject, 4 phases per trial (12 phase measurements per subject) |
| Threshold | 800 cm (`attack_range_cm`); ceiling 850 cm |
| Harness | `Content/Python/aura_p02_compare.py` — the Phase 7B harness re-targeted, not rewritten |
| Outputs | `results/gameplay/P02CMP_*.csv` |

Implementation record, decoration decisions and the condition-isolation runs:
`docs/IMPLEMENTATION_LOG.md`, "Candidate #2".

## 13.1 Subjects and controlled conditions

Identical to §§2–3 with three changes, each forced by the tree under test:

| Variable | Candidate #1 | Candidate #2 |
|---|---|---|
| Controller tree | `BT_Behavior_P01_G01` | `BT_Behavior_P02_G01` (asserted at session start; a mismatch aborts) |
| Attack threshold | 300 cm | 800 cm |
| Approach `AcceptanceRadius` | 150 | 650 |
| Retreat task in the tree | none | `n2_MoveAway`, `RetreatDistance` 1200 |

Unchanged from Phase 7B: level `Lvl_Research_Trial` (asserted), subject spawn `(0, 600, z)` yaw −90,
one combatant present, static player with health raised to 100000, phases `far_1500` 8 s / `mid_600`
6 s / `close_200` 6 s / `far_1500_again` 6 s (26 s per trial), same `BP_WeaponBase_C` at 5 damage per
hit, one read per Slate tick.

**Three fresh baseline trials were run.** Phase 7B's baseline rows were deliberately **not reused**:
they were scored against candidate #1's 300 cm threshold, so "all relevant conditions remain
identical" would have been false. The baseline enemy, its controller and its behaviour were
unchanged; only the measurement window and the scoring threshold differ.

## 13.2 Uncontrolled differences (additional to §4)

7. **The generated enemy never attacks in this tree**, so there is no generated attack cadence to
   compare — unlike §4 item 3, the cadence difference is not a quantisation effect but an absence.
8. **The retreat branch cannot be exercised without an external stimulus.** `HealthPercent` can only
   fall if something damages the enemy, and nothing in the tree does. It was therefore left at 1.00
   for the whole comparison, and the retreat branch was tested separately under an injected
   `SendDamage` stimulus (`docs/IMPLEMENTATION_LOG.md`). The comparison is a **full-health**
   comparison and does not measure the retreat policy.

## 13.3 Results

### Reaction correctness

| Subject | Events | Beyond 800 cm | Beyond 850 cm | Max distance at damage | Verdict |
|---|---|---|---|---|---|
| Generated | **0** | 0 | 0 | n/a — no event | **`not_applicable`** |
| Baseline | 68 | 8 (11.8 %) | 8 (11.8 %) | 1421.2 cm | `fail` against this threshold |

The generated verdict is `not_applicable`, **not** `pass`. With zero damage events there is nothing
to score; reporting "0 violations of 0 events" as correctness would be a manufactured 100 %.

The baseline's 8 long-range events are a behaviour difference, not a regression: the baseline has no
range rule of its own (§4 item 1) and is scored against candidate #2's 800 cm only so the two columns
share a threshold. Worst cases are in `far_1500_again` — 1421.2 cm at t = 0.67 s, then 926.0 at
1.68 s, 427.0 at 2.67 s — i.e. it fires while closing, exactly as in Phase 7B.

### Behaviour failure count

| Line | Generated | Baseline |
|---|---|---|
| `BTTask_EnemyMoveToTarget: SUCCESS` | **6** | not applicable |
| `BTTask_EnemyMoveToTarget: FAILURE` | 0 | not applicable |
| `BTTask_EnemyMoveAwayFromTarget: SUCCESS` | 0 | not applicable |
| `BTTask_EnemyMoveAwayFromTarget: FAILURE` | **1** — `(no target)`, startup only | not applicable |
| `BTTask_EnemyAttack` (any) | **0** | not applicable |

6 successes = 3 trials × 2 far phases, so every phase that permitted an approach completed one. The
single retreat line is the known 0.1 s blackboard startup race, not a task failure.

### Damage dealt

| Subject | Events | Total | Per trial | Per phase |
|---|---|---|---|---|
| Generated | **0** | **0.0** | 0.00 | 0.0 |
| Baseline | 68 | 340.0 | 113.33 | 28.3 |

| Phase | Generated | Baseline |
|---|---|---|
| `far_1500` | 0.0 | 35.0 |
| `mid_600` | 0.0 | 25.0 |
| `close_200` | 0.0 | 25.0 |
| `far_1500_again` | 0.0 | 28.3 |

### Responsiveness

Generated: no first damage in any of the 12 phases (recorded as the `-1.000` sentinel, never as
0.000). Baseline: mean 1.13 s, range 0.67–1.36 s.

### Movement (side evidence)

| Phase | Generated moved | Baseline moved |
|---|---|---|
| `far_1500` | 784.5 / 784.6 / 784.6 cm (ends y ≈ −184.3) | 1444.9 / 1443.0 / 1445.7 cm |
| `far_1500_again` | 784.6 / 784.8 / 785.0 cm (ends y ≈ −184.5) | 1403.5 / 1405.5 / 1405.4 cm |
| `mid_600` | **0.0** (all trials) | 578.9 (all trials) |
| `close_200` | **0.0** (all trials) | 117.9 (all trials) |

Sample rate: 2.91 Hz generated, 2.93 Hz baseline — equal within noise, so §6.1 applies unchanged.

## 13.4 Behaviour-tree decisions vs in-task safety checks

**Move gating — a genuine tree decision, cleanly evidenced.** At 600 cm and 200 cm the generated enemy
moved **exactly 0.0 cm** in all six phases, because `n5`'s `DistanceToTarget > 800` decorator refused
the approach task before it was entered. `BTTask_EnemyMoveToTarget` cannot produce that on its own at
`AcceptanceRadius` 650 — it would have walked to ~800 cm.

**Attack gating — not evidenced at all in this run, and it must not be reported as passing.** The
generated enemy dealt zero damage, but `n6_Attack` **never executed**. A dedicated probe with
`AttackRange = −1.0` (a task that prints on every execution) produced zero `BTTask_EnemyAttack`
lines over 14 s at 1500 cm, so the node was never reached. The zero is therefore a
**reachability** result, not a gating result: it says nothing about whether `n6`'s decorator would
have refused correctly had the node run.

Mechanism: `n5` (`d > 800`) precedes `n6` (`d <= 800`) inside one sequence, so `n6` is reachable only
on a pass where `n5` returns SUCCESS — and `n5` succeeds at `d <= 650 + 150 = 800`. The pawn physically
stops at **716.2 cm**, where `d > 800` is false, so `n4_Sequence` fails at its first child on every
subsequent pass. On the arrival pass itself the 0.1 s-stale blackboard key still reads > 800, which
blocks `n6` a second way. Either mechanism alone is sufficient.

**Consequence beyond "cannot attack": permanent inertness.** After closing to 716.2 cm the enemy is
frozen for the rest of the run — no approach (`n5` blocked), no attack (`n6` unreachable), no retreat
(health 1.00). The `far_1500` phases show precisely this: 784.5 cm of travel in the first ~2 s, then
zero damage and no further movement for the remaining ~6 s.

**Not repaired.** Swapping the two children would fix the behaviour and destroy the finding. The tree
is exactly as generated and the defect is reported as a property of the generated output.

## 13.5 Interpretation

- The generated tree's **conditions work**; its **composition does not**. Both testable decorators
gated their own nodes correctly under isolation, yet the tree as a whole never attacks.
- This is the sharpest RQ2 result so far and it is a counter-example to the usual framing: a tree can
  be `VALID` at the schema level, compilable, decorator-correct, and still produce a non-functional
  enemy because of the **ordering** of sibling conditions the validator does not score.
- The baseline comparison remains informative even with a zero: 340 vs 0 damage and 1.13 s vs never,
  under identical conditions, is the largest gap either candidate has produced.
- Candidate #1 (policy-compliant, lower output) and candidate #2 (structurally self-blocking, no
  output) are qualitatively different failures, which is what a per-candidate report needs to preserve.

## 13.6 Limitations (additional to §10)

11. **The retreat branch was not measured in the comparison.** It was isolated separately under an
    injected `SendDamage` stimulus; a wounded-enemy comparison is a distinct experiment and was not run.
12. **Log-derived counts come from a timestamp window with ~20 s padding on each side**, so the
    generated and baseline windows overlap by ~11 s of padding. The generated counts (6 move
    successes, 1 startup retreat line) match 3 trials × 2 far phases exactly, so the bucketing error
    cannot have moved them, but the windows are not disjoint and that is recorded rather than hidden.
13. **Zero damage makes reaction correctness and responsiveness undefined for the generated enemy.**
    Both are reported as n/a rather than as perfect.
14. **`P02CMP_combined_damage_events.csv` contains only baseline rows** (68) because the generated
    side has no events; its header is the shared schema, so the file is not empty by accident.

## 13.7 Reproduction

1. Open `Lvl_Research_Trial`; confirm PIE is stopped and the controller's `BehaviorTreeAsset` is
   `BT_Behavior_P02_G01`.
2. `aura_p02_compare.start("generated")`; wait ~90 s; `restore_level()`.
3. `aura_p02_compare.start("baseline")`; wait ~90 s; `restore_level()`.
4. Aggregate to `P02CMP_summary.csv`; count task lines per timestamp window for
   `P02CMP_behavior_failures.csv`.

## 13.8 Result files

| File | Contents |
|---|---|
| `results/gameplay/P02CMP_phase_metrics_generated.csv` | 12 phase rows, generated |
| `results/gameplay/P02CMP_phase_metrics_baseline.csv` | 12 phase rows, baseline |
| `results/gameplay/P02CMP_damage_events_generated.csv` | header only — zero events |
| `results/gameplay/P02CMP_damage_events_baseline.csv` | 68 per-event rows |
| `results/gameplay/P02CMP_combined_phase_metrics.csv` | 24 rows, both subjects |
| `results/gameplay/P02CMP_combined_damage_events.csv` | 68 rows, baseline only |
| `results/gameplay/P02CMP_summary.csv` | per-subject aggregates |
| `results/gameplay/P02CMP_behavior_failures.csv` | task line counts per subject |
| `results/gameplay/P02CMP_samples_generated.csv`, `..._baseline.csv` | raw per-sample series |
| `results/gameplay/P02CMP_session_generated.txt`, `..._baseline.txt` | setup + per-phase notes |
| `results/gameplay/P02PROBE_phases.csv`, `P02PROBE_samples.csv`, `P02PROBE_session.txt` | condition-isolation probe (health gate, sawtooth) |
| `results/gameplay/P02ATTACK_probe_samples.csv`, `P02ATTACK_probe_session.txt` | `AttackRange = −1` reachability probe |
| `Content/Python/aura_p02_compare.py`, `aura_p02_probe.py`, `aura_p02_attackprobe.py` | harnesses |

No raw JSON output, manifest, Round 1/Round 2 validation CSV, `BP_AICharacter`, `BP_WeaponBase`,
`BP_Projectile`, `BP_FirstPersonCharacter`, `DT_CharacterData` or `Lvl_FirstPerson` was modified.

---

# 14. Candidate #3 — `round2/P04-G01`

| Field | Value |
|---|---|
| Run ID | `p7cmp_p04_r1` |
| Date | 2026-11-15 |
| Tree | `/Game/Research/AI/BT_Behavior_P04_G01` |
| Trials | 3 per subject, 4 phases per trial (12 phase measurements per subject) |
| Threshold | 1500 cm (`attack_range_cm`); ceiling 1550 cm |
| Harness | `Content/Python/aura_p04_compare.py` — the Phase 7B harness re-targeted a third time |
| Outputs | `results/gameplay/P04CMP_*.csv` |

Implementation record, decoration decisions and the condition-isolation probe:
`docs/IMPLEMENTATION_LOG.md`, "Candidate #3".

## 14.1 Subjects and controlled conditions

Identical to §§2–3 with four changes, each forced by the tree under test:

| Variable | Candidate #2 | Candidate #3 |
|---|---|---|
| Controller tree | `BT_Behavior_P02_G01` | `BT_Behavior_P04_G01` (asserted at session start; a mismatch aborts) |
| Attack threshold | 800 cm (one attack node) | 1500 cm (**two** attack nodes, `n3` and `n6`) |
| Approach `AcceptanceRadius` | 650 | 1350 on both approach nodes |
| Retreat task in the tree | `n2_MoveAway`, `RetreatDistance` 1200 | `n2_MoveAway`, `RetreatDistance` **2000** |

Unchanged from Phase 7B/7C: level `Lvl_Research_Trial` (asserted), subject spawn `(0, 600, 120)` yaw
−90, one combatant present, static player with health raised to 100000, phases `far_1500` 8 s /
`mid_600` 6 s / `close_200` 6 s / `far_1500_again` 6 s (26 s per trial), same `BP_WeaponBase_C` at
5 damage per hit, one read per Slate tick.

**Three fresh baseline trials were run.** Phases 7B/7C baseline rows were again **not reused**: the
scoring threshold changed from 800 to 1500 cm, so "all relevant conditions remain identical" would
have been false. The baseline enemy was unmodified; only the measurement window and threshold differ.

Sample rate: **2.89 Hz generated, 2.92 Hz baseline** — identical within noise, but both are
background-throttled values, so §6.1 applies in full and every timing figure below is quantised at
≈0.34 s.

## 14.2 Uncontrolled differences (additional to §§4 and 13.2)

9. **`far_1500` sits exactly on a decorator boundary.** This tree splits at `d <= 1500` / `d > 1500`,
   and the phase requests 1500 cm. The blackboard distance includes the vertical offset (~8 cm), so it
   read slightly above 1500 and the *far* branch engaged first: the enemy closed ~118 cm to ≈1382 cm
   and only then fired. The intended reading of the phase — "already inside the medium band" — is
   therefore not what happened, and the approach delay is part of the measured response time.
10. **The close band cannot be exercised as designed.** `n2_MoveAway` cannot satisfy its own success
    test anywhere in that band (§14.4), so `close_200` measures the tree's **fall-through**, not its
    retreat policy. The retreat branch's behaviour is unmeasured; only its failure is.
11. **The baseline has no behaviour tree at all**, so "behaviour failure count" is undefined for it.
    Its column is `not applicable`, never `0`.

## 14.3 Results

### Reaction correctness (distance at damage, threshold 1500 cm)

| Subject | Events | Beyond 1500 cm | Beyond 1550 cm | Max distance at damage | Min distance at damage | Verdict |
|---|---|---|---|---|---|---|
| Generated | 35 | 1 | **0** | 1500.0 cm | 200.2 cm | **`pass`** |
| Baseline | 64 | 0 | 0 | 1259.2 cm | 68.8 cm | `pass` (against a rule it does not have) |

The single generated event on the boundary is in `far_1500_again` trial 1 at 1500.0 cm, i.e. at or
within 0.1 cm of the declared range — inside the 1550 cm sampling tolerance and therefore not a
violation. Both subjects stayed inside 1500 cm throughout, so this phase distinguishes them by
**volume and cadence, not by range compliance**.

### Behaviour failure count

| Line | Generated | Baseline |
|---|---|---|
| `BTTask_EnemyMoveToTarget: SUCCESS` | 6 | not applicable |
| `BTTask_EnemyMoveToTarget: FAILURE (arrived too far)` | 1 | not applicable |
| `BTTask_EnemyMoveAwayFromTarget: SUCCESS` | **0** | not applicable |
| `BTTask_EnemyMoveAwayFromTarget: FAILURE (retreat too short)` | **23** | not applicable |
| `BTTask_EnemyMoveAwayFromTarget: FAILURE (no target)` | 1 — startup race | not applicable |
| `BTTask_EnemyAttack` (any) | **0** | not applicable |

23 retreat failures across three `close_200` phases is 7–8 per 6 s phase at 2.89 Hz, i.e. **every
tick of every close phase**. The 6 approach successes are 3 trials × 2 far phases. The single
`arrived too far` line is the Phase 5A stop overshoot reappearing on the far node.

### Damage dealt

| Subject | Events | Total | Per trial | Per phase | Hits per second |
|---|---|---|---|---|---|
| Generated | 35 | **175.0** | 58.33 | 14.6 | 0.45 |
| Baseline | 64 | **320.0** | 106.67 | 26.7 | 0.82 |

| Phase | Generated (mean) | Baseline (mean) |
|---|---|---|
| `far_1500` | 11.67 | 33.33 |
| `mid_600` | 18.33 | 23.33 |
| `close_200` | 15.00 | 26.67 |
| `far_1500_again` | 13.33 | 23.33 |

The baseline dealt **1.83×** the generated tree's damage. Every hit is worth 5.0 (35 × 5 = 175,
64 × 5 = 320), so the difference is entirely hit count, not hit size.

### Responsiveness (time to first damage)

| Phase | Generated (mean) | Baseline (mean) |
|---|---|---|
| `far_1500` | **3.19 s** (2.89 / 3.34 / 3.33) | 1.23 s (0.69 / 1.66 / 1.34) |
| `mid_600` | 1.55 s (0.98 / 1.66 / 2.00) | 1.34 s (1.01 / 1.67 / 1.34) |
| `close_200` | 1.46 s (1.66 / 1.02 / 1.69) | 1.12 s (1.01 / 0.99 / 1.35) |
| `far_1500_again` | 2.45 s (0.68 / 1.99 / 4.66) | 1.21 s (1.32 / 1.00 / 1.33) |
| All phases | 2.16 s | 1.23 s |

The generated tree is **1.8× slower overall and 2.6× slower at 1500 cm**, and that gap is
structural: it must first close inside its own 1500 cm band (§14.2 item 9), whereas the baseline's
`ShootingRange` is 5000 and it fires while closing.

### Movement (side evidence)

| Phase | Generated moved | Baseline moved |
|---|---|---|
| `far_1500` | 118.1 / 117.8 / 117.8 cm (ends y ≈ 482) | 1447.9 / 1445.6 / 1443.0 cm |
| `far_1500_again` | 117.8 / 117.8 / 117.9 cm | 1399.9 / 1405.2 / 1399.8 cm |
| `mid_600` | **0.0** (all trials) | 578.9 / 578.9 / 579.5 cm |
| `close_200` | **0.0** (all trials) | 117.9 / 117.9 / 118.3 cm |

The generated enemy's two zero-movement phases are not the same cause, and the difference matters:
`mid_600` is a **correct tree decision** (`n7`'s `AcceptanceRadius` 1350 already contains 600 cm, so
nothing needed to move), while `close_200` is the **retreat task failing without displacing the pawn**
(§14.4).

## 14.4 Behaviour-tree decisions vs in-task safety checks

**`n6_Attack` executes — proved positively, by damage.** `BTTask_EnemyAttack` prints only when its own
gate refuses, so the absence of attack lines proves nothing. The positive evidence is the damage
itself: all **35** events came from `n6`, at 200.2 cm and 600.1 cm and 1382–1500 cm — the distances at
which `n6` is the only reachable attacker (`n3` is proved unreachable below, and `n7`/`n10` are movement
tasks that fire no weapon). `n6`'s own gate never had to refuse — 0 `out of range` lines — which is
expected because both attack nodes carry `AttackRange` 1500 and no phase exceeded it.

**`n3_Attack` and `n4_Wait` never execute — proved, not inferred.** The retreat task prints on **every**
terminal path (`SUCCESS`, `no target`, `target invalid`, `already beyond retreat range`,
`retreat too short`). Across three trials there were **0 `SUCCESS`** lines, so `n2` never returned
SUCCESS, so `n1_Sequence` never advanced past its first child, so `n3` was never entered. The 23
`retreat too short` lines are the failure that ends the branch on each attempt.

**Mechanism: the generated retreat distance is unsatisfiable in this arena — arithmetic, not timing.**
Measured at runtime by the probe: `RecastNavMesh` bounds are `x ∈ [−1976, 1976]`, `y ∈ [−1976, 1976]`
(origin `(0, 0, 10)`, extent `(1976, 1976, 0)`), the floor plane is 2000 × 2000 centred on the origin,
and the enemy spawns at `y = 600`.

- The task's success test is `d ≥ RetreatDistance − 150 = 1850` cm.
- Away from the player is `+Y`, so the retreat goal is `y = 600 + 2000 = 2600`, i.e. **624 cm beyond
the navmesh edge**.
- A successful retreat therefore needs final `y ≥ player_y + 1850`. Across the whole close band
  (`d < 350`, so `player_y ∈ (250, 600]`) that is `y ≥ 2100` at best and `y ≥ 2450` at worst — all
  above the 1976 ceiling.
- Best separation physically obtainable in the band: `1976 − 250.1 = 1725.9` cm. **Shortfall ≥ 124 cm
  for every point in the band**, so no amount of extra time helps.

Why that failure is *silent and immobile*: `BTTask_EnemyMoveAwayFromTarget` passes its computed goal
to `MoveToLocation` with `Project Destination to Navigation = false`, so the off-navmesh goal is never
clamped. The move yields no usable path, the pawn never leaves `(0, 600)`, `GetMoveStatus` stays
`Idle`, and the very next tick evaluates `d = 200.16 < 1850` and fails the task — which is exactly the
23 `d=200.159936 thr=1850.0` lines and the measured 0.0 cm.

**The retreat task itself works; the parameter does not fit.** The same task logged
`SUCCESS d=1718.2 … 1834.9 thr=1050.0` six times in this same arena from `BT_Behavior_RetreatTest`
(`RetreatDistance` 1200, so threshold 1050). At that setting the required separation fits inside the
navmesh, and the retreat completes. This is the control that rules out "the retreat task is broken".

**Consequence beyond "no retreat": the tree silently loses its close band.** `n1_Sequence` fails at
`n2` on every pass, so the selector falls through to `n5` (`d <= 1500`), which attacks immediately and
moves nothing. `range_adaptive_attacker` therefore behaves as a **two-band tree** (attack within
1500, approach beyond) and never disengages — while still dealing damage, which is what hides the
defect from a damage-only metric.

**Not repaired.** Reducing `RetreatDistance`, projecting the goal to the navmesh, or moving `n3` ahead
of `n2` would each fix the behaviour and destroy the finding.

## 14.5 Interpretation

- This is a **third, distinct failure mode** in the candidate set:
  #1 policy-compliant and working; #2 structurally self-blocking and inert; #3 **environmentally
  unsatisfiable**, with a silent fall-through that still damages. A per-candidate report has to keep
  these apart, because they fail RQ2 for different reasons.
- `VALID` under M1–M5 did not imply reachability for the third time. The validator cannot know the
  arena's navigable extent; a generated `retreat_distance_cm = 2000` is schema-legal (100–4000) and
  contradicts nothing internal. **Reachability has to be tested per branch at implementation time**,
  which is what the probe does and what a schema cannot.
- Attribution matters here and is narrower than for candidate #2: the control flow is sound, and on a
  navmesh extending ≥ 2450 cm from the player the same tree would retreat and `n3` would fire. The
  defect is a **parameter/environment incompatibility**, amplified by a task that does not project its
  goal. It is preserved as generated, and it is reported as such rather than as a logic error.
- The baseline comparison still discriminates: 320 vs 175 damage and 1.23 s vs 2.16 s under identical
  conditions. The generated tree is functional but roughly **half as effective**, and the deficit is
  concentrated at long range where its own band rule forces an approach the baseline does not need.

## 14.6 Limitations (additional to §§10 and 13.6)

15. **Sample rate 2.89 / 2.92 Hz** (background-throttled PIE, §6.1). Timing is quantised at ≈0.34 s
    and the `far_1500` phase contains only ~24 samples.
16. **The retreat branch's policy is unmeasured.** No successful retreat exists in this arena at this
    parameter value, so only the failure is measured. Its *intended* behaviour (2000 cm disengage,
    then attack and wait) is untestable without changing either the parameter or the arena — both of
    which would break comparability with the other five candidates.
17. **Log windows are the exact session windows** (`21.33.11–21.34.31`, `21.35.02–21.36.23`, shifted
    +5 h to log time), not padded. The counts reconcile exactly with 3 trials × 3 close phases, so no
    padding was needed to make them attribution-safe.
18. **`close_200` measures a fall-through, not a retreat** (§14.2 item 10). It must not be cited as
    evidence about retreat behaviour.

## 14.7 Reproduction

1. Open `Lvl_Research_Trial`; confirm PIE is stopped and the controller's `BehaviorTreeAsset` is
   `BT_Behavior_P04_G01`.
2. `aura_p04_compare.start("generated")`; wait ~100 s; `restore_level()`.
3. `aura_p04_compare.start("baseline")`; wait ~100 s; `restore_level()`.
4. `aura_p04_aggregate.run()` writes the combined, summary and behaviour-failure CSVs.
5. Condition isolation: `aura_p04_probe.start()` (4 phases, 36 s) then re-read `AURA_DIAG` in the log.

## 14.8 Result files

| File | Contents |
|---|---|
| `results/gameplay/P04CMP_phase_metrics_generated.csv` | 12 phase rows, generated |
| `results/gameplay/P04CMP_phase_metrics_baseline.csv` | 12 phase rows, baseline |
| `results/gameplay/P04CMP_damage_events_generated.csv` | 35 per-event rows |
| `results/gameplay/P04CMP_damage_events_baseline.csv` | 64 per-event rows |
| `results/gameplay/P04CMP_combined_phase_metrics.csv` | 24 rows, both subjects |
| `results/gameplay/P04CMP_combined_damage_events.csv` | 99 rows, both subjects |
| `results/gameplay/P04CMP_summary.csv` | per-subject aggregates |
| `results/gameplay/P04CMP_behavior_failures.csv` | task line counts per subject |
| `results/gameplay/P04CMP_samples_generated.csv`, `..._baseline.csv` | raw per-sample series |
| `results/gameplay/P04CMP_session_generated.txt`, `..._baseline.txt` | setup + per-phase notes |
| `results/gameplay/P04PROBE_phases.csv`, `P04PROBE_samples.csv`, `P04PROBE_session.txt` | condition-isolation probe (current run, corrected geometry columns) |
| `Content/Python/aura_p04_compare.py`, `aura_p04_probe.py`, `aura_p04_aggregate.py` | harnesses |

No raw JSON output, manifest, Round 1/Round 2 validation CSV, `BP_AICharacter`, `BP_WeaponBase`,
`BP_Projectile`, `BP_FirstPersonCharacter`, `DT_CharacterData`, `Lvl_FirstPerson`,
`BT_Behavior_P01_G01` or `BT_Behavior_P02_G01` was modified.

---

# 15. Candidate #6 — `round2/P07-G01`

Fourth controlled comparison, same protocol as §§1–12, 13 and 14. Source document
`dataset/raw_outputs/20261105_round2/P07-G01.txt`: `behavior_id = backaway_safe_shooter`, style
`range_based`, prompt P07, schema 2.0, **VALID**, `manual_review = 0`, `correction_class = none`, no
finding codes. Parameters `attack_range_cm` 900, `retreat_distance_cm` 1300, `retreat_health_pct` 0.2
(unused — no node tests health).

```
n0_Selector
+- n1_Sequence  (NO decorator)      n2_MoveAway  RetreatDistance=1300  [DEC: d Less 900]
|                                   n3_Wait      WaitTime=0.1         (no decorator)
\- n4_Sequence  (NO decorator)      n5_Attack    AttackRange=900       [DEC: d GreaterOrEqual 900]
                                    n6_Wait      WaitTime=0.1         (no decorator)
```

## 15.1 Subjects and controlled conditions

| Item | Generated | Baseline |
|---|---|---|
| Pawn | `BP_BasicEnemyAI_C` | `BP_AICharacter_C` |
| Tree | `BT_Behavior_P07_G01` | none (no tree, no blackboard) |
| Trials | 3 × 4 phases | 3 × 4 phases |
| Arena | `Lvl_Research_Trial`, enemy `(0, 600, 120)` yaw −90 | identical |
| Player | `BP_FirstPersonCharacter`, `CurrentHealth` 100000, no input | identical |
| Phases | `far_1500` 8 s, `mid_600` 6 s, `close_200` 6 s, `far_1500_again` 6 s | identical |
| Combat | `FiringInterval` 1.0, `ShootingDamage` 5, `EnemyBulletSpeed` 2500, `ShootingRange` 5000 | identical |
| Run id | `p7cmp_p07_r1` | same run |

Session windows: generated `2026.11.14 22.02.15 → 22.03.36`, baseline `22.04.13 → 22.05.34` (log
time = session clock + 5 h, crossing midnight). Both reconcile with 12 phase rows per subject.

## 15.2 Uncontrolled differences (additional to §§4, 13.2 and 14.2)

1. **Phase durations differ from the condition-isolation probe.** The probe uses 8 s per phase (32 s);
   the comparison keeps the 8/6/6/6 split used for candidates #1, #2 and #3 so the baseline numbers
   stay comparable to earlier phases. Both retain the same four distances, and none of them sits on
   the 900 cm edge, so no phase is scored on a boundary artefact.
2. **Baseline `tree_desc = unreadable`.** `BP_AICharacter`'s stock `AIController` exposes no
   `BehaviorTreeAsset` property, so the descriptive read raised and the harness logged
   `WARNING baseline reports a behaviour tree: unreadable`. This is an artefact of reading a tree
   field from a pawn that has no tree; it is not a measurement failure.
3. **Sample rate 2.93 Hz generated / 2.92 Hz baseline** — background-throttled PIE, compared at the
   same rate, so the pair is comparable (§10 item 1).

## 15.3 Results

### Damage dealt

| Subject | Events | Total | Per trial | Per phase | Hits per second |
|---|---|---|---|---|---|
| Generated | **0** | **0.0** | 0.00 | 0.00 | 0.00 |
| Baseline | 64 | **320.0** | 106.67 | 26.67 | 0.82 |

| Phase | Generated (mean) | Baseline (mean, events) |
|---|---|---|
| `far_1500` | 0.00 | 35.00 (7) |
| `mid_600` | 0.00 | 25.00 (5) |
| `close_200` | 0.00 | 23.33 (4.67) |
| `far_1500_again` | 0.00 | 23.33 (4.67) |

The generated tree dealt **no damage in any phase of any trial**. Every hit is worth 5.0, so the
baseline's 64 events are 320.0 while the generated tree's 0 events are 0.0.

### Responsiveness (time to first damage)

| Subject | Mean first damage | Basis |
|---|---|---|
| Generated | **n/a** | no damage event exists to time |
| Baseline | **1.31 s** | 12 phase rows |

`n/a` is recorded rather than `0`, because zero would imply a measured latency that does not exist.

### Reaction correctness

| Subject | Verdict | Events beyond threshold | Max geo at damage | Min geo at damage |
|---|---|---|---|---|
| Generated | **`not_applicable`** | — | −1.0 (sentinel) | −1.0 (sentinel) |
| Baseline | `fail` | 4 beyond 900, 3 beyond 950 | 1421.2 cm | 68.8 cm |

The sentinel −1.0 is the harness's "no event" value, not a distance. The baseline's `fail` is a
**metric-definition artefact**, not a baseline defect: the 900 cm threshold and 950 cm ceiling are
taken from candidate #6's authored `attack_range_cm`, and the baseline has no authored range — it
fires to 1421.2 cm because its own `ShootingRange` is 5000. The same mechanism produced the baseline
`fail` in Phase 7C at ceiling 850; candidate #3's baseline `pass`ed only because the 1550 cm ceiling
happened to exceed the baseline's 1259 cm maximum.

### Movement (side evidence)

| Phase | Generated moved | Baseline moved |
|---|---|---|
| `far_1500` | **0.0 cm** (all trials) | 1445.0 cm |
| `mid_600` | 618.0 cm (y → 1217.9) | 578.9 cm |
| `close_200` | 951.3 cm (y → 1551.4) | 118.0 cm |
| `far_1500_again` | **0.0 cm** (all trials) | 1405.4 cm |

This inverts the pattern of candidates #1, #2 and #3: the generated enemy **moves where the baseline
barely does** and stands still where the baseline charges. Its two zero-movement phases are the far
band, where no branch is admitted (§15.4).

### Condition isolation (probe, run `p7p07_probe`, 4 × 8 s)

Reproduced identically on two separate runs:

| Phase | Damage | Moved | Blackboard distance range |
|---|---|---|---|
| `far_1500` | 0.0 | **0.0 cm** | 1500.0 → 1500.0 |
| `mid_600` | 0.0 | 617.9 cm (y → 1217.9) | 600.1 → 1217.9 |
| `close_200` | 0.0 | 951.4 cm (y → 1551.4) | 200.2 → 1151.5 |
| `far_1500_again` | 0.0 | **0.0 cm** | 1500.0 → 1500.0 |

## 15.4 Behaviour-tree decisions vs in-task safety checks

**Both gates are tree decisions, and both are provably wrong in the same way — they are mutually
exclusive with the task they gate.**

**The attack branch is a zero-width window.** `n5_Attack` carries a decorator admitting `d ≥ 900`
(`GreaterOrEqual`, `FloatValue` 900.0, `NotifyObserver = ResultChange`, `FlowAbortMode = Self`).
`BTTask_EnemyAttack` then refuses to fire unless `DistanceToTarget <= AttackRange` = 900. The
intersection of the two admitted sets is the single value `d == 900.0`; the probe recorded
`attack_window_width_cm = 0.0` in **every** phase. `n5` **does execute** — 106 refusal lines across
the three trials — and never fires once. Zero damage is therefore a **tree defect**, not a broken
task: the branch is admitted and then blocked one layer down, with no error and no movement signature.

**The retreat branch can never report success.** `n2_MoveAway`'s decorator is `d < 900`; the same
decorator with `FlowAbortMode = Self` **aborts the running latent task the instant `d ≥ 900`**, while
the task's own success test needs `d ≥ RetreatDistance − 150 = 1150`. So the abort fires 250 cm
before the success test can ever be met. Across all runs there were **0 `SUCCESS`** lines from
`BTTask_EnemyMoveAwayFromTarget` — and that task prints on every terminal path, so its silence on
`SUCCESS` is positive evidence, not absence of evidence.

**The pawn's stop position is the abort, not the task threshold.** At ≈500 cm·s⁻¹ and ≈3 FPS the
pawn coasts roughly one frame (≈167 cm) after the blackboard crosses 900: `mid_600` sampled
1051.2 → 1217.9, `close_200` 985.0 → 1151.5. That overshoot must not be read as the task reaching
its 1150 cm threshold — it is the decorator killing the move while the pawn is still travelling.
The authored 1300 cm disengage is **never reached** and remains unmeasured.

**The far band has no branch at all.** `d ≥ 900` admits only `n4_Sequence`, whose first child `n5`
requires `d ≤ 900` to fire; `n1_Sequence` requires `d < 900`. Between them, at `d = 1500` **neither
sequence can complete**, `n5` fails its in-task gate and `n1` fails at `n2`'s decorator, and the
selector loops. That is the measured 0.0 cm and the 1500.0 cm flat blackboard in both far phases.

**The control run settles the attribution.** Temporarily setting `n5_Attack.AttackRange = 10000.0`
(restored to 900.0 and re-verified afterwards) produced, on the same probe and arena:

| Phase | Control damage | Events | Distance at damage |
|---|---|---|---|
| `far_1500` | 20.0 | 4 | 1500.0 |
| `mid_600` | 5.0 | 1 | 1217.9 |
| `close_200` | 15.0 | 3 | 1151.5 |
| `far_1500_again` | 15.0 | 3 | 1500.0 |
| **Total** | **55.0** | **11** | — |

This proves three separate things at once: the weapon and damage path work; the decorator really does
admit execution at `d ≥ 900` (it fired at 1500.0 cm); and the faithful zero is caused by the
generated contradiction, not by a dead task, a stale decorator, or an instrumentation failure.

**Not repaired.** Raising `AttackRange`, lowering the decorator's 900, or reversing the retreat's
inequality would each restore function and destroy the finding.

## 15.5 Interpretation

- This is a **fourth, distinct failure mode**, and the first that is *semantic* rather than
  structural or environmental: #1 policy-compliant and working; #2 structurally self-blocking and
  inert; #3 environmentally unsatisfiable but still damaging; #6 **internally contradictory across
  two layers**, fully executed, and dealing zero damage.
- It is the cleanest demonstration so far that **`VALID` under M1–M5 says nothing about
  reachability or about agreement between a generated condition and an action's own precondition.**
  This tree has no finding code, no manual review, 7 nodes, and a perfect compile. Its defect lives
  in the relationship between a decorator's threshold and the task's parameter — a relationship no
  schema-level validator inspects.
- The failure is **silent by design of the tooling**, not by accident: neither task reports the
  contradiction. `BTTask_EnemyAttack` prints only on refusal (which it did, 106 times), and
  `BTTask_EnemyMoveAwayFromTarget` only on a terminal state (which it reached, as failure, while
  still displacing the pawn). A reviewer reading only the log would see a retreating enemy and a
  tree that "runs".
- The comparison still discriminates absolutely: 320.0 vs 0.0 damage under identical conditions is
  a total separation, and it is the widest gap in the candidate set. It is also the least
  informative about *quality*, because the generated tree is not merely worse — it is inert.
  Reporting it as "0 % of baseline damage" without the mechanism would be true and useless.

## 15.6 Limitations (additional to §§10, 13.6 and 14.6)

19. **Stale-blackboard artefact at ~3 FPS.** Each phase's first frame can still read the previous
    phase's `DistanceToTarget`, producing one spurious far-band `out of range` evaluation per
    teleport. It cannot produce damage (the gate refuses above 900) and must be read as an
    instrumentation effect, not as a decorator failure.
20. **`n5`'s blocking direction is not isolable in this arena.** `n5` executes in every phase, but
    the retreat resolves the `d < 900` band first, so the tree never reaches the attack branch in a
    state where a clean blocking test could be staged. The control run substitutes for it: with the
    gate widened, `n5` fires everywhere it is admitted.
21. **The 1300 cm retreat policy is unmeasured.** No successful retreat exists under this tree — the
    abort precedes the success test by 250 cm — so only the abort is observed. Reaching the policy
    would require changing the parameter or the decorator, both of which would break faithfulness.
22. **`n3_Wait` and `n6_Wait` print nothing.** `BTTask_Wait` is unobservable by design; their
    execution is inferred from sequence position only, and is not claimed measured.
23. **Control data was written under `P07PROBE_*`** because the running module predated the
    `OUTPUT_PREFIX` edit. It was copied to `P07CTRL_attackrange10000_*` and the faithful run then
    overwrote `P07PROBE_*` correctly. `importlib.reload` against a live session is unsafe and
    silently destroyed probe state once in this phase.
24. **Pre-existing leaked `_tick` callback.** A callback with co_filename `"<string>"`, not from
    this phase's harnesses, logs `NameError: name '_s' is not defined` at ≈3 Hz throughout. It
    predates this work, does not match any `BTTask_` prefix, and so does not corrupt task counts.

## 15.7 Reproduction

1. Open `Lvl_Research_Trial`; confirm PIE is stopped and the controller's `BehaviorTreeAsset` is
   `BT_Behavior_P07_G01`.
2. `aura_p07_compare.start("generated")`; wait ~95 s; restore the arena.
3. `aura_p07_compare.start("baseline")`; wait ~95 s; restore the arena.
4. `aura_p07_aggregate.run()` writes the combined, summary and behaviour-failure CSVs, deriving each
   subject's log window from its own session file and shifting it +5 h.
5. Condition isolation: `aura_p07_probe.start()` (4 phases, 32 s), then re-read the `AURA_DIAG`
   lines. Repeat with `n5_Attack.AttackRange = 10000.0` for the control, then restore 900.0 and
   re-verify before continuing.

## 15.8 Result files

| File | Contents |
|---|---|
| `results/gameplay/P07CMP_phase_metrics_generated.csv` | 12 phase rows, generated |
| `results/gameplay/P07CMP_phase_metrics_baseline.csv` | 12 phase rows, baseline |
| `results/gameplay/P07CMP_damage_events_generated.csv` | header only — zero events |
| `results/gameplay/P07CMP_damage_events_baseline.csv` | 64 per-event rows |
| `results/gameplay/P07CMP_combined_phase_metrics.csv` | 24 rows, both subjects |
| `results/gameplay/P07CMP_combined_damage_events.csv` | 64 rows, both subjects |
| `results/gameplay/P07CMP_summary.csv` | per-subject aggregates |
| `results/gameplay/P07CMP_behavior_failures.csv` | task line counts per subject |
| `results/gameplay/P07CMP_samples_generated.csv`, `..._baseline.csv` | raw per-sample series |
| `results/gameplay/P07CMP_session_generated.txt`, `..._baseline.txt` | setup + per-phase notes |
| `results/gameplay/P07PROBE_phases.csv`, `P07PROBE_samples.csv`, `P07PROBE_session.txt` | faithful condition-isolation probe |
| `results/gameplay/P07CTRL_attackrange10000_phases.csv`, `..._samples.csv`, `..._session.txt` | experimental control (`AttackRange` 10000) |
| `Content/Python/aura_p07_compare.py`, `aura_p07_probe.py`, `aura_p07_aggregate.py` | harnesses |

No raw JSON output, manifest, Round 1/Round 2 validation CSV, `BP_AICharacter`, `BP_WeaponBase`,
`BP_Projectile`, `BP_FirstPersonCharacter`, `DT_CharacterData`, `Lvl_FirstPerson`,
`BT_Behavior_P01_G01`, `BT_Behavior_P02_G01` or `BT_Behavior_P04_G01` was modified.

---

# 16. Candidate #5 — `round2/P03-G02`

Fifth controlled comparison, same protocol as §§1–12 and 13–15. Source document
`dataset/raw_outputs/20261105_round2/P03-G02.txt` (unmodified): `behavior_id =
keep_distance_attack`, style `range_based`, 10 nodes, **REVIEW**, `manual_review = 1`,
`correction_class = mapping`, no `FAIL` codes. Its single finding is **`L5`**:

> `AMBIGUOUS:L5:attack is not guarded by any distance_to_target condition on its path; weapon
> range is 5000 cm so it may fire far out of intended range`

Parameters `attack_range_cm` 1000, `retreat_distance_cm` 1500, `retreat_health_pct` 0.2
(**unused** — no node tests health, third candidate in a row).

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

This is the first candidate in the set that is **not** `VALID`, and the first whose finding is
about a condition that is *absent* rather than misplaced or contradictory. All three sequences
carry **no decorator of their own**; all three conditions sit on **leaf tasks** (candidate #2's
placement pattern, not candidate #3's composite hoisting).

**The question this candidate was built to answer** (§10, item 7 of the Phase 7 plan): #6 proved a
distance gate can admit nothing, so #5 had to show what an **ungated** attack actually does once
`AttackRange` is written from `attack_range_cm` = 1000 — i.e. whether the corpus's largest finding
category (`12 × L5`) produces over-firing, under-firing, or something else.

## 16.1 Subjects and controlled conditions

| Item | Generated | Baseline |
|---|---|---|
| Pawn | `BP_BasicEnemyAI_C` | `BP_AICharacter_C` |
| Tree | `BT_Behavior_P03_G02` | none (no tree, no blackboard) |
| Trials | 3 × 4 phases | 3 × 4 phases |
| Arena | `Lvl_Research_Trial`, enemy `(0, 600, 120)` yaw −90 | identical |
| Player | `BP_FirstPersonCharacter`, `CurrentHealth` 100000, no input | identical |
| Phases | `far_1500` 8 s, `mid_600` 6 s, `close_200` 6 s, `far_1500_again` 6 s | identical |
| Combat | `FiringInterval` 1.0, `ShootingDamage` 5, `EnemyBulletSpeed` 2500, `ShootingRange` 5000 | identical |
| Run id | `p7cmp_p03g2_r1` | same run |

Session windows: generated `2026.11.14 22.34.10 → 22.35.31`, baseline `22.35.56 → 22.37.17` (log
time = session clock + 5 h, crossing midnight). Both reconcile with 12 phase rows and 228 samples
per subject.

## 16.2 Uncontrolled differences (additional to §§4, 13.2, 14.2 and 15.2)

1. **Baseline `tree_desc = unreadable`.** `BP_AICharacter`'s stock `AIController` exposes no
   `BehaviorTreeAsset` property, so the descriptive read raised and the harness logged
   `WARNING baseline reports a behaviour tree: unreadable`. Reading a tree field from a pawn that
   has no tree; not a measurement failure. Identical to §15.2 item 2.
2. **Sample rate 2.91 Hz both subjects** — background-throttled PIE, compared at the same rate, so
   the pair is comparable (§10 item 1). Timing is quantised at ≈0.34 s and every latency below
   must be read against that floor.
3. **Phase durations differ from the condition-isolation probes**, which use 8 s per phase
   (32 s total). The comparison keeps the 8/6/6/6 split used for #1, #2, #3 and #6 so the baseline
   numbers stay comparable across phases.
4. **`n3_Wait`, `n6_Wait` and `n9_Wait` are unobservable** — `BTTask_Wait` prints nothing. Their
   execution is inferred from sequence position and is never claimed as measured.

## 16.3 Results

### Damage dealt

| Subject | Events | Total | Per trial | Per phase | Hits per second |
|---|---|---|---|---|---|
| Generated | **0** | **0.0** | 0.00 | 0.00 | 0.00 |
| Baseline | 66 | **330.0** | 110.00 | 27.50 | 0.85 |

| Phase | Generated (mean) | Baseline (mean, events) |
|---|---|---|
| `far_1500` | 0.00 | 35.00 (7) |
| `mid_600` | 0.00 | 25.00 (5) |
| `close_200` | 0.00 | 25.00 (5) |
| `far_1500_again` | 0.00 | 25.00 (5) — trials 30.0 / 20.0 / 25.0 |

The generated tree dealt **no damage in any phase of any trial**. Every hit is worth 5.0, so the
baseline's 66 events are 330.0 against 0.

### Responsiveness (time to first damage)

| Subject | Mean first damage | Basis |
|---|---|---|
| Generated | **n/a** | no damage event exists to time |
| Baseline | **1.14 s** | 12 phase rows, range 0.67–1.67 s |

`n/a` is recorded rather than `0`, because zero would imply a measured latency that does not exist.
The baseline's 1.14 s sits inside the 1.13–1.31 s band measured for this same subject across Phases
7C–7F, and at a 0.34 s quantisation floor it is indistinguishable from its own 1.0 s firing interval
plus activation.

### Reaction correctness

| Subject | Verdict | Events beyond threshold | Max geo at damage | Min geo at damage |
|---|---|---|---|---|
| Generated | **`not_applicable`** | — | −1.0 (sentinel) | −1.0 (sentinel) |
| Baseline | `fail` | 3 beyond 1000, 3 beyond 1050 | 1421.2 cm | 69.0 cm |

The sentinel −1.0 is the harness's "no event" value, not a distance. The baseline's `fail` is the
**same metric-definition artefact** as §§14.3 and 15.3: the 1000 cm threshold and 1050 cm ceiling
are taken from candidate #5's authored `attack_range_cm`, and the baseline has no authored range —
it fires to its own `ShootingRange` 5000. The three offending phase maxima are 1421.2 / 1382.2 /
1421.2 cm, all in `far_1500` or `far_1500_again`. This is not baseline drift; it is the same
subject scored against this candidate's number.

### Movement (side evidence)

| Phase | Generated moved (trial 1 / 2 / 3) | Baseline moved (trial 1 / 2 / 3) |
|---|---|---|
| `far_1500` | 835.1 / 335.3 / 242.5 cm | 1447.0 / 1445.9 / 1445.8 cm |
| `mid_600` | **0.0** / 833.2 / 820.0 cm | 578.9 / 579.6 / 578.9 cm |
| `close_200` | **0.0 / 0.0 / 0.0 cm** | 117.9 / 118.3 / 117.9 cm |
| `far_1500_again` | 335.0 / 392.8 / 170.6 cm | 1402.0 / 1397.1 / 1405.3 cm |

The generated enemy **moved in 8 of 12 phases**, between 170.6 and 835.1 cm, and ended those
phases **further away** than it started (`far_1500` trial 1 ended at y = 1434.0, separation
2334.4 cm). This is the opposite of candidate #6, whose generated enemy was immobile in exactly
the phases this tree moves in. The baseline closed every phase to 69.0–105.9 cm.

`bb_can_attack_true_rate` was ≥ 0.958 in every generated phase (0.958 in trial 1 `far_1500`, 1.000
elsewhere); `bb_health_percent` was 1.0 min *and* max in all 12 phases and enemy health stayed
500/500, so no health-gated behaviour could arm and none is present to arm.

### Condition isolation (three probe runs, 4 × 8 s each)

| Phase | Moved | End separation | Blackboard distance | `weapon_fired` |
|---|---|---|---|---|
| `far_1500` | 834.5 cm | 2333.8 cm | 882.5 → 2333.8 | **0** |
| `mid_600` | **0.0 cm** | 600.1 cm | 600.1 → 600.1 | **0** |
| `close_200` | **0.0 cm** | 200.2 cm | 200.2 → 200.2 | **0** |
| `far_1500_again` | 834.9 cm | 2334.2 cm | 882.5 → 2334.2 | **0** |

Reproduced on three separate runs (`P03PROBE` 835.3 / 0.0 / 0.0 / 834.1 cm, `P03PROBE2` 834.3 /
0.0 / 0.0 / 835.2 cm, `P03PROBE3` 834.5 / 0.0 / 0.0 / 834.9 cm). `P03PROBE2` also recorded
`projectiles_max = 0` and `samples_with_projectile = 0` in all four phases; `P03PROBE3` recorded
`weapon_fired = 0` with `last_fire_start = last_fire_end = 0.000` in all four. The read path itself
is sound: `P03PROBE3`'s session file logged `weapon_Damage 5.0`, `weapon_FireRate 1.0`,
`weapon_Range 5000.0`, `weapon_Accuracy 0.6`, `weapon_BulletSpeed 2500.0` from the live weapon.

`weapon_fired` is a **fired / not-fired flag** derived from `Weapon.LastFireTime`, not a shot
count — the control below logs `weapon_fired = 1` for a phase that recorded 5 damage events. Its
value of `0` here therefore states that `LastFireTime` never moved at all, which is positive
evidence that no shot was fired rather than an absence of sampling.

`P03PROBE` additionally computed the retreat goal: `(0, 2100)` from the spawn position, evaluated
`retreat_goal_inside_navmesh = False` against the measured bounds `x, y ∈ [−1976, 1976]`.

## 16.4 Behaviour-tree decisions vs in-task safety checks

**The authored tree is correct on paper and wrong in execution, and neither task reports it.**

**What the decorators say.** Read back from the compiled asset: `n2` carries `DistanceToTarget /
Less / 800.0`, `n5` carries `DistanceToTarget / Greater / 1200.0`, `n8` carries `CanAttack /
BasicOperation = Set`; all three `NotifyObserver = ResultChange`, `FlowAbortMode = Self`,
`bInverseCondition = False`; **zero** decorators on `n1`, `n4`, `n7`. For a Bool key, `Set` means
"must be true" (`BlackboardKeyType_Bool.cpp:47`), and `CanAttack` read true in ≥ 95.8 % of samples,
so `n8`'s decorator **was not the blocker**. It also never had a chance to block, and is therefore
**unverified in the blocking direction**.

**What the engine would have done if the leaf guards were effective.** A forbidden child fails its
enclosing composite rather than being skipped past an unguarded sibling (`BTCompositeNode.cpp`,
`bResult = true` then per-decorator `WrappedCanExecute`). So effective guards would have produced
exactly three mutually exclusive bands: retreat below 800, approach above 1200, attack in between.
That is the behaviour the JSON specifies. It is **not** what was measured — and the control run
proves the semantics are what the source says they are (below).

**Both leaf guards were observationally inert.**

- `n2_MoveAway` executed and displaced the pawn in the **far** band, where `d < 800` is false:
  835.1 / 335.3 / 242.5 cm at `far_1500` and 335.0 / 392.8 / 170.6 cm at `far_1500_again`.
  `BTTask_EnemyMoveAwayFromTarget` logged **11 `SUCCESS`** lines in the comparison window.
- `n5_MoveToTarget` executed in the **close** band, where `d > 1200` is false: **21 `SUCCESS`**
  lines, 0.0 cm moved in all three `close_200` phases and in `mid_600` trial 1, because the pawn
  is already inside `AcceptanceRadius` 850 and the task returns immediately.

In the same arena, same session and same controller, `BT_Behavior_AttackAlways`'s `Less 1000`
decorator **did** gate. The effective decorator state inside `BT_Behavior_P03_G02` therefore
differs from its authored read-back, and the 17/17 property verification could not detect it —
property read-back and decorator evaluation are different things. **The mechanism is unresolved:**
`OperationType` (the byte actually evaluated) is not exposed by `AuraBehaviorTreeStatics`, and the
subobject enumeration that would reach it failed because `K2_GatherSubobjectDataForInstance`
requires an `Actor`.

**Why that yields exactly zero damage — the arithmetic from the measured log counts.**

| Line | Count | Meaning |
|---|---|---|
| `n1` failures | **22** | 16 `retreat too short` + 5 `already beyond retreat range` + 1 `no target` |
| `n5` attempts | 22 | every `n1` failure admits `n4` |
| `n5` `SUCCESS` | **21** | returns immediately inside `AcceptanceRadius` 850 |
| `n5` `FAILURE` | **1** | generic failure, not `arrived too far` (that count is 0) |
| `n8` executions | **1** | reached only when **both** `n1` and `n4` fail |
| `n8` `out of range - FAILURE` | **1** | refused at the far band |
| `weapon_fired` | **0** | in every phase of every probe and every trial |

22 = 21 + 1, and the single `n5` failure is the only pass that reached `n7`. The chain is
mechanical: `n1` succeeds → the selector stops; `n1` fails → `n4` runs and its `n5` succeeds → the
`n6` `Wait` sits behind an **unguarded** SUCCESS, so `n4` returns SUCCESS and the selector stops
again. `n7` is entered only in the both-fail window, and on that one pass `n8` fired nothing
because the pawn was at the far band and the task's own `DistanceToTarget <= AttackRange` gate
refused. `BTTask_EnemyAttack` prints **only on refusal**, so that single line is also the proof
that `n8` executed at least once: the branch is **reachable, and unreachable in practice**.

**The `Wait` does not rescue a forbidden child — the control settled this.** A two-child sequence
whose first child is forbidden fails; its trailing `Wait` never runs, so the selector falls through.
The control (`BT_Behavior_AttackAlways`, whose `CombatLoop` attack child carries `d < 1000`) shows
it directly: at `far_1500` the guarded attack child failed, `CombatLoop` failed, the selector fell
through to `ApproachLoop`, the pawn **closed 618.1 cm** (y 600.0 → −17.9) and only then fired.

**Positive control — `BT_Behavior_AttackAlways`, same probe, same arena.**

| Phase | Damage | Events | Distance at damage | Moved | `weapon_fired` | `LastFireTime` window |
|---|---|---|---|---|---|---|
| `far_1500` | 15.0 | 3 | 882.3 | 618.1 cm (y → −17.9) | 1 | 0.000 → 7.402 |
| `mid_600` | 25.0 | 5 | 600.1 | 0.0 | 1 | 7.402 → 16.737 |
| `close_200` | 30.0 | 6 | 200.2 | 0.0 | 1 | 16.737 → 24.738 |
| `far_1500_again` | 15.0 | 3 | 716.1 | 784.6 cm (y → −184.3) | 1 | 24.738 → 33.405 |

The control proves the weapon, the damage path, the projectile class and `LastFireTime` all work
in this exact setup, and that a distance decorator on a leaf task **does** gate here. The faithful
zero cannot be attributed to a dead task, a stale asset, a broken weapon or a harness fault.

The controller was repointed back to `BT_Behavior_P03_G02` and re-saved afterwards; verified
`controller_now = /Game/Research/AI/BT_Behavior_P03_G02`.

**Retreat succeeded — the pre-registered prediction was wrong.** Candidates #3 and #6 both produced
a retreat that could never report `SUCCESS`, so the *prediction* for #5 was another dead retreat.
It did not happen: 11 `SUCCESS` lines, ending at 2334.4 cm separation. The reason is arithmetic,
not luck. `BTTask_EnemyMoveAwayFromTarget` asks for the move first and tests `d ≥ RetreatDistance −
150 = 1350` after it goes idle. In the far band the player sits at y = −900, so a pawn at y = 600
already measures 1500 cm and the test passes once the move resolves — no 1850 cm of separation is
required, unlike candidate #3's 2000 cm request. The off-navmesh goal `(0, 2100)` did **not** block
it, which is the opposite of the Phase 7D failure.

The corollary is worth stating plainly: **the retreat only ever succeeded in the band its own guard
forbids.** In the bands the guard permits (200 cm, 600 cm) it logged `retreat too short` 16 times —
from y = 600 the success test needs the pawn at y ≥ 1350 (600 cm band) or y ≥ 1750 (200 cm band)
against the 1976 cm navmesh limit, and in four phases it moved 0.0 cm at all.

## 16.5 Interpretation

> **Correction added in Phase 7H (evidence gap G1) — read this before the interpretation below.**
> The measurements in §16 stand exactly as recorded: the asset at `/Game/Research/AI/BT_Behavior_P03_G02`
> does retreat in the far band, never fire, and deal 0 damage in three comparison trials. The *cause*
> given below does **not** survive G1. A node-for-node rebuild of the same tree
> (`/Game/Research/AI/BT_Behavior_P03_G02_R1`, 14 nodes, **0 differences** across role, class, node
> name, parent index and every property value, including the `Less / 800.0` and `Greater / 1200.0`
> decorators) closes 618 cm to a 882 cm standoff and **attacks** in the identical probe: 15/20/20/20 and
> 20/25/25/20 damage in an order-controlled `R1 → ORIG → R1B` sequence. The authored tree is therefore
> **not** priority-starved; the divergence is between the original asset's compiled Behaviour Tree data
> and its own graph, i.e. an **Unreal implementation artefact**, not a generated-logic failure. See
> `docs/IMPLEMENTATION_LOG.md` §18. Any claim that #5's numbers measure its generated logic must be
> withdrawn, and the `L5` discussion must cite #5 as an artefact case.

- This is a **fifth, distinct failure mode: priority starvation through inert leaf guards.** It is
  the mirror image of candidate #2. #2's attack was unreachable because a *preceding sibling's*
  condition was effective; #5's attack is unreachable in practice because the preceding siblings'
  conditions are **not** effective and their tasks nevertheless succeed. The tree is not
  self-blocking — it is *self-satisfying* one branch too early.
- **The `L5` prediction inverted.** The validator said the missing guard means the attack "may fire
  far out of intended range". It never fired at all. `L5` correctly identified the missing
  condition; it could not anticipate that the same missing-condition pattern on `n2` and `n5` would
  starve the branch it was worried about. On this evidence the corpus's largest finding category
  fails **closed**, not open — an important qualifier for RQ1's headline rate.
- **Zero damage with motion is harder to detect than zero damage with immobility.** Candidate #6
  stood still and did nothing; #5 walks 170–835 cm through 8 of 12 phases, retreats to 2334 cm,
  logs 22 terminal task lines, and still never puts a projectile in the air. A reviewer, or a
  metric that only watches movement or only watches the log, would score this tree as *running*.
- **Both authored distance guards were wrong about the same thing** — they describe a keep-distance
  policy the engine never enforced. Whatever the mechanism, the epistemic point stands: a 17/17
  property read-back is not evidence that a compiled decorator gates, exactly as a clean M1–M5
  `VALID` is not evidence that a branch is reachable.
- **Damage separates absolutely and uninformatively:** 330.0 vs 0.0 under identical conditions. As
  with #6, the interesting result is the mechanism, not the ratio.

## 16.6 Limitations (additional to §§10, 13.6, 14.6 and 15.6)

25. **Decorator inertness is measured, not explained.** The two leaf guards were shown not to gate
    while an identically typed decorator gated in the same session, but the evaluated
    `OperationType` byte cannot be read from Python in this project, so the cause is unknown.
    Treat "this decorator gates" as unproven for every tree built so far except where a control run
    measured it.
26. **Trial-to-trial movement variance is recorded, not explained.** `mid_600` moved 0.0 / 833.2 /
    820.0 cm across three trials with identical setup, and `far_1500` moved 835.1 / 335.3 / 242.5.
    The startup artefact below is a plausible contributor and is not established as the cause.
27. **Stale-blackboard artefact at ~3 FPS.** `DistanceToTarget` reads `0.0` before the controller's
    first 0.1 s tick, and each phase's first frame can read the previous phase's distance. Both can
    admit branches whose guards would otherwise be false for one evaluation. Neither can produce
    damage — the attack gate and the weapon both refuse — but they do affect which branch wins the
    first pass, which is exactly the branch that decides the whole phase in this tree.
28. **The `L5` risk itself is untested.** Because `n8` executes only in the both-fail window at the
    far band, the tree was never observed attempting a shot inside 1000 cm, so "would it fire far
    out of range if it ever engaged?" has **no measurement**. The only observation of `n8` is one
    in-task refusal at ≈1500 cm.
29. **`n8`'s `CanAttack Set` decorator is unverified in the blocking direction** — `CanAttack` was
    true in ≥ 95.8 % of samples and the branch ran once; nothing was ever denied.
30. **The 1500 cm retreat policy succeeded for a degenerate reason** (the player is far away, so the
    success test is met on arrival), which means the policy value is not really exercised. Only 11
    terminal states and their end separations are measured.
31. **`n3_Wait`, `n6_Wait`, `n9_Wait` were not observed to execute.** `BTTask_Wait` prints nothing;
    sequence position is not measurement.
32. **`retreat_health_pct` 0.2 was not implemented** (no node tests health) and was not exercised.

## 16.7 Reproduction

1. Open `Lvl_Research_Trial`; confirm PIE is stopped and `AIController_ResearchEnemy.BehaviorTreeAsset`
   is `BT_Behavior_P03_G02`.
2. `aura_p03_compare.start("generated")`; wait ~81 s; restore the arena.
3. `aura_p03_compare.start("baseline")`; wait ~81 s; restore the arena.
4. `aura_p03_aggregate.run()` writes the combined, summary and behaviour-failure CSVs, deriving each
   subject's log window from its own session file and shifting it +5 h.
5. Condition isolation: `aura_p03_probe` / `aura_p03_probe2`, then the canonical parameterised
   `aura_probe_generic.configure(tree, run_id, prefix)` (4 phases, 32 s), then re-read the
   `AURA_DIAG` lines.
6. Positive control: repoint the controller at `BT_Behavior_AttackAlways`, run the same probe, then
   repoint back to `BT_Behavior_P03_G02`, re-save, and re-read the property back before continuing.

## 16.8 Result files

| File | Contents |
|---|---|
| `results/gameplay/P03CMP_phase_metrics_generated.csv` | 12 phase rows, generated |
| `results/gameplay/P03CMP_phase_metrics_baseline.csv` | 12 phase rows, baseline |
| `results/gameplay/P03CMP_damage_events_generated.csv` | header only — zero events |
| `results/gameplay/P03CMP_damage_events_baseline.csv` | 66 per-event rows |
| `results/gameplay/P03CMP_combined_phase_metrics.csv` | 24 rows, both subjects |
| `results/gameplay/P03CMP_combined_damage_events.csv` | 66 rows, both subjects |
| `results/gameplay/P03CMP_summary.csv` | per-subject aggregates |
| `results/gameplay/P03CMP_behavior_failures.csv` | task line counts per subject |
| `results/gameplay/P03CMP_samples_generated.csv`, `..._baseline.csv` | raw per-sample series (228 each) |
| `results/gameplay/P03CMP_session_generated.txt`, `..._baseline.txt` | setup + per-phase notes |
| `results/gameplay/P03PROBE_phases.csv`, `P03PROBE_samples.csv`, `P03PROBE_session.txt` | probe run 1, with the retreat-goal / navmesh diagnostic |
| `results/gameplay/P03PROBE2_*` | probe run 2, projectiles counted independently of `LastFireTime` |
| `results/gameplay/P03PROBE3_*` | probe run 3 (decisive), `weapon_fired` / `LastFireTime` columns |
| `results/gameplay/P03CTRL_*` | positive control on `BT_Behavior_AttackAlways` |
| `Content/Python/aura_p03_probe.py`, `aura_p03_probe2.py`, `aura_probe_generic.py`, `aura_p03_compare.py`, `aura_p03_aggregate.py` | harnesses |

No raw JSON output, manifest, Round 1/Round 2 validation CSV, `BP_AICharacter`, `BP_WeaponBase`,
`BP_Projectile`, `BP_FirstPersonCharacter`, `DT_CharacterData`, `Lvl_FirstPerson`,
`BT_Behavior_P01_G01`, `BT_Behavior_P02_G01`, `BT_Behavior_P04_G01` or `BT_Behavior_P07_G01` was
modified. `BT_Behavior_P03_G02` carries `AttackRange` 1000.0, `RetreatDistance` 1500.0 and
`AcceptanceRadius` 850.0 exactly as generated.

---

# 17. Candidate #4 — `round2/P01-G02`

Sixth and final controlled comparison, same protocol as §§1–12 and 13–16. Source document
`dataset/raw_outputs/20261105_round2/P01-G02.txt` (unmodified): `behavior_id =
close_range_aggressor`, style `aggressive`, 5 nodes, **REVIEW**, `manual_review = 1`,
`correction_class = mapping`, no `FAIL` codes. Its single finding is **`L3`**:

> `AMBIGUOUS:L3:duplicate sibling conditions: shadowing risk only, NOT unreachable (a failing
> child falls through), manual review required`

Parameters `attack_range_cm` 250, `retreat_distance_cm` 600 (**unused** — no retreat node exists),
`retreat_health_pct` 0.15 (**unused** — no node tests health, fourth candidate in a row).

```
n0_Selector
+- n1_Sequence  (NO decorator)   n2_Attack         AttackRange=250        [DEC: d LessOrEqual 250]
|                                n3_Wait           WaitTime=0.1           [DEC: d LessOrEqual 250]
\- n4_MoveToTarget               AcceptanceRadius=100, ArrivalTolerance=150
                                                                         [DEC: d Greater 250]
```

`n4` is a direct child of `n0_Selector` at index 1 — a **sibling of the sequence**, not of `n3`.
`n1`'s two children are `n2_Attack` and `n3_Wait`. All three conditions sit on leaf tasks and
**none on a composite**, so this tree has the same decorator-placement pattern as candidates #1,
#2 and #5 rather than #3's composite hoisting.

**The question this candidate was built to answer** (§10): the five earlier candidates all had a
branch that either never ran or ran with its guard inert, so `P01-G02` had to show whether
duplicated sibling conditions *shadow* each other in the engine — one child permanently
unreachable behind an equivalent sibling — or merely retry the same action. That is the difference
between a scoring rule that flags a real defect and one that flags a redundancy.

## 17.1 Subjects and controlled conditions

| Item | Generated | Baseline |
|---|---|---|
| Pawn | `BP_BasicEnemyAI_C` | `BP_AICharacter_C` |
| Tree | `BT_Behavior_P01_G02` | none (no tree, no blackboard) |
| Trials | 3 × 4 phases | 3 × 4 phases |
| Arena | `Lvl_Research_Trial`, enemy `(0, 600, 120)` yaw −90 | identical |
| Player | `BP_FirstPersonCharacter`, `CurrentHealth` 100000, no input | identical |
| Phases | `far_1500` 8 s, `mid_600` 6 s, `close_200` 6 s, `far_1500_again` 6 s | identical |
| Combat | `FiringInterval` 1.0, `ShootingDamage` 5, `EnemyBulletSpeed` 2500, `ShootingRange` 5000 | identical |
| Threshold / ceiling | 250 cm / 300 cm (this tree's own `attack_range_cm`) | same numbers |
| Run id | `p7cmp_p01g2_r1` | same run |

Session windows: generated `2026.11.14 23.02.08 → 23.03.27`, baseline `23.03.44 → 23.05.03` (log
time = session clock + 5 h, crossing midnight). Both reconcile with 12 phase rows; 4 639 and 4 570
samples respectively.

## 17.2 Uncontrolled differences (additional to §§4, 13.2, 14.2, 15.2 and 16.2)

1. **Sample rate 59.5 Hz (generated) and 58.7 Hz (baseline), not 2.9 Hz.** PIE ran unthrottled this
   session, so timing is quantised at ≈0.017 s instead of ≈0.34 s. This is a genuine condition
   change against the five earlier comparisons and is **accounted for, not corrected**: both
   subjects of this pair were measured in the same state, so the pairwise comparison is internally
   valid; damage totals are cumulative health deltas and do not depend on the sampling rate; and
   event counts cannot differ from resolution because hits arrive at ≈1 s cadence, far wider than
   either sample window. Cross-candidate *latency resolution* is not comparable, and `mean
   first_damage_s` is reported to two decimals here where earlier phases could only support one.
2. **Baseline `tree_desc = unreadable`** — `BP_AICharacter`'s stock `AIController` exposes no
   `BehaviorTreeAsset` property. Identical to §§15.2 and 16.2.
3. **Blackboard basis and staleness.** `AIController_ResearchEnemy.UpdateDerivedKeys` writes
   `DistanceToTarget` from `GetDistanceTo` on a **0.1 s looping timer**, so the key is a staircase,
   not a continuous signal, and each phase's first evaluation can read the previous phase's value.
   Both are visible in the probe samples and both are bounded at 0.1 s.
4. **Cross-phase projectile carry-over.** A shot fired in the last moments of one phase can land in
   the next. Measured once, at `boundary_250` (probe): `projectiles = 1` at t = 0.050 s and the first
   damage at t = 0.085 s, at 250.1 cm, before the enemy had moved (see §17.4).
5. **`n3_Wait` is unobservable** — `BTTask_Wait` prints nothing, so sequence completion cannot be
   read from the log.

## 17.3 Results

### Reaction correctness (distance at damage, threshold 250 cm)

| Trial | `far_1500` | `mid_600` | `close_200` | `far_1500_again` |
|---|---|---|---|---|
| 1 | 179.1 | 134.4 | 200.2 | 185.2 |
| 2 | 184.2 | 133.6 | 200.2 | 185.6 |
| 3 | 181.2 | 136.4 | 200.2 | **209.3** (min 158.9) |

**Generated: 0 events beyond 250 cm, 0 beyond the 300 cm ceiling. PASS.** Every one of the 55 damage
events landed inside the tree's own authored band, including the three phases that start at 200 cm.

| Subject | Events beyond 250 cm | Beyond 300 cm ceiling | Max distance at damage |
|---|---|---|---|
| generated | **0** | **0** | 209.3 cm |
| baseline | 16 | 15 | 1275.6 cm |

The baseline **fails** the same test: `BP_AICharacter` has no distance condition anywhere, fires from
its weapon's full 5000 cm range, and 15 of its 77 events landed beyond the ceiling — the widest at
1275.6 cm, i.e. 5× the generated tree's authored band.

### Behaviour failure count

| Task line | Generated | Baseline |
|---|---|---|
| `BTTask_EnemyMoveToTarget: SUCCESS` | **9** | 0 |
| `BTTask_EnemyMoveToTarget: FAILURE` (any form) | **0** | 0 |
| `BTTask_EnemyAttack: out of range - FAILURE` | **10** | 0 |
| `BTTask_EnemyMoveAwayFromTarget: …` (all forms) | **0** | 0 |

The 9 move successes are exactly the 9 phases that begin outside the band (3 × `far_1500`, 3 ×
`mid_600`, 3 × `far_1500_again`) — never the three `close_200` phases, where the enemy is already
inside. The baseline's zero is **not applicable**, not a measurement of good behaviour: it has no
behaviour tree and prints no task lines.

The 10 attack refusals are the interesting line and are analysed in §17.4.

### Damage dealt

| Subject | Events | Damage | Per trial |
|---|---|---|---|
| generated | 55 | **275.0** | 91.7 |
| baseline | 77 | **385.0** | 128.3 |

Per trial: generated 19 / 18 / 18, baseline 26 / 25 / 26. The generated tree deals **71 % of the
baseline's damage in the same sessions**, the closest any generated candidate comes to the control:
candidate #1 managed 180.0 against 335.0 (54 %), candidate #3 175.0 against 320.0 (55 %), and
candidates #2, #5 and #6 dealt nothing at all.

### Responsiveness (time to first damage)

| Phase | Generated (trial 1/2/3) | Baseline (trial 1/2/3) |
|---|---|---|
| `far_1500` | 3.039 / 2.923 / 3.010 | 0.913 / 1.236 / 0.585 |
| `mid_600` | 1.303 / 1.209 / 1.332 | 0.787 / 0.906 / 0.273 |
| `close_200` | 0.584 / 0.653 / 0.846 | 0.752 / 0.929 / 0.118 |
| `far_1500_again` | 2.952 / 2.919 / 3.127 | 1.199 / 1.366 / 0.652 |
| mean first damage | **1.99 s** | **0.81 s** |

The generated tree is consistently slower and the delay is **structured, not noise**: ≈3.0 s at
1500 cm, ≈1.3 s at 600 cm, ≈0.7 s at 200 cm. That is the cost of actually closing to 250 cm before
firing, ≈1 320 cm of travel at the pawn's ≈500 cm/s. The baseline instead shoots on contact from
wherever it stands, which is faster and is exactly why it fails reaction correctness.

### Movement (side evidence)

| Phase | Generated moved (cm) | End separation | Baseline moved (cm) | End separation |
|---|---|---|---|---|
| `far_1500` | 1324.9 / 1319.7 / 1322.7 | 179.1 / 184.2 / 181.2 | 1394.5 / 1386.3 / 1386.5 | 107.8 / 119.0 / 118.8 |
| `mid_600` | 470.1 / 470.9 / 468.0 | 134.4 / 133.6 / 136.4 | 506.8 / 509.6 / 501.8 | 98.8 / 97.6 / 102.8 |
| `close_200` | **0.0 / 0.0 / 0.0** | 200.2 | 101.3 / 106.6 / 109.1 | 103.8 / 99.1 / 97.3 |
| `far_1500_again` | 1318.6 / 1318.2 / **1512.3** | 185.2 / 185.6 / **546.0** | 1393.6 / 1389.4 / 1393.5 | 112.1 / 116.0 / 112.2 |

Both subjects close to a stable firing standoff and stay there. Two differences survive: the
generated enemy settles **further out** (133.6–209.3 cm vs 97.3–119.0 cm), and it does **not move at
all** from 200 cm, where the baseline still walks 101–109 cm closer. Trial 3's `far_1500_again` is
the one anomaly: 1 512.3 cm of travel and an end separation of 546.0 cm, i.e. the pawn ran **past**
the stationary player and was still out of band when the phase ended (3 events only). Cause not
established; see §17.6.

## 17.4 Behaviour-tree decisions vs in-task safety checks

This is the candidate that finally separates the two layers, because both fired in the same run.

**The attack node is reached while out of band, and refused by its own gate.** Ten
`BTTask_EnemyAttack: out of range - FAILURE` lines, **nine of them at a consistent ≈1.1 s offset into
nine separate phases** (the three `far_1500`, three `mid_600` and three `far_1500_again`), plus one
at the tail of the overshoot phase. At 1.1 s the pawn is still ≈950 cm out. `BTTask_EnemyAttack`
prints **only** on refusal, so each of those ten lines is positive proof that `n2_Attack` *executed*
and that its own `DistanceToTarget <= AttackRange` check then refused to fire. Zero of the ten
produced damage.

That is the opposite of candidate #5, and it matters for the corpus: on this tree the in-task safety
check is **load-bearing**, not decorative.

**No out-of-band shot was ever produced.** The attack decorator and the in-task gate read the same
blackboard key against the same 250 cm boundary, and the safety check caught every pass the decorator
let through. So this run cannot attribute the refusals to one layer rather than the other — but it
does establish that the *pair* is sufficient to keep all 55 events inside the band, which is the
policy question the `L3` finding is actually about.

**The `boundary_250` probe phase (probe only, not part of the comparison) closed the reachability
arithmetic.** At exactly 250 cm requested the true separation is 250.1 cm, i.e. a hair *outside* the
band:

| t (s) | geo (cm) | blackboard (cm) | projectiles | damage | enemy y |
|---|---|---|---|---|---|
| 0.050 | 250.1 | 250.1 | **1** | 0.00 | 600.0 |
| 0.085 | 250.1 | 250.1 | 0 | **5.00** | 600.0 |
| 0.202 | 248.4 | 250.1 | 0 | 0.00 | 598.3 |
| 0.298 | 230.0 | 244.5 | 0 | 0.00 | 579.8 |
| 0.399 | 191.6 | 219.4 | 0 | 0.00 | 541.2 |
| 0.449 | 183.6 | 183.6 | 0 | 0.00 | 533.0 |
| 1.050 | 183.6 | 183.6 | 1 | 0.00 | 533.0 |
| 1.102 | 183.6 | 183.6 | 0 | **5.00** | 533.0 |

The lone 250.1 cm damage event — the only event in the whole phase set that sits outside the band —
arrives at t = 0.085 s with `projectiles = 1` already present at t = 0.050 s, i.e. it is a
**carry-over projectile fired during the previous phase**, not a shot taken at 250.1 cm. The enemy
then **moves 67 cm inward and stops dead at 183.6 cm**, which is `n4_MoveToTarget` running because
`d > 250` was still true at phase entry, then ceding to `n1` the moment the band was entered. The
first genuine in-band shot is at t = 1.102 s from 183.6 cm.

**Duplicate sibling conditions did not shadow anything.** The `L3` risk does not materialise. Three
independent readings say so: `n2_Attack` fires continuously (55 landed events plus 10 refused
attempts, across all 12 phases); `n4_MoveToTarget` runs and succeeds in exactly the 9 phases where
the band is violated and never in the 3 where it is not; and the tree never once failed to act. The
second condition is redundant — both children read the same key inside the same evaluation window,
so `n3`'s check cannot differ from `n2`'s — but redundancy is not the same defect as contradiction.
Candidate #2's siblings were **contradictory** (`d > 800` then `d <= 800` in one sequence) and
starved the attack; #5's siblings were **unguarded** and starved it by priority. `P01-G02`'s
siblings are **identical**, and an identical repeat costs one comparison, not a branch.

| Node | Action | Executes? | Evidence |
|---|---|---|---|
| `n2` | `attack` | **yes, repeatedly** | 55 landed events + 10 `out of range - FAILURE` lines |
| `n3` | `wait` | **unobservable** | `BTTask_Wait` prints nothing |
| `n4` | `move_to_target` | **yes** — and only when the band is violated | 9 `SUCCESS` lines = 9 outside-band phases; 0.0 cm moved from 200 cm in all three trials |

## 17.5 Interpretation

- **This is the second policy-compliant generated tree, and the best-measured one.** #1 passed its
  300 cm test with 36 events / 180.0 damage; #4 passes a 250 cm test with **55 events / 275.0** and
  zero violations. Three of the six selected candidates (#2, #6, #5) deal **no damage at all**.
- **`REVIEW (L3)` out-performed four `VALID` trees.** The classification that flagged this tree for
  human attention identified a real redundancy, and the redundancy is harmless. The scoring rule is
  not wrong that duplicates are worth a look — it is simply not predictive of behaviour. That
  belongs in the RQ1 discussion next to candidate #2's `VALID`-but-inert result.
- **Priority order is what makes this tree work, and it is the exact inverse of #5.** `n1` is the
  attack branch and it is *first*; `n4` (approach) is the fallback. #5 put the attack *last* behind
  two branches that succeeded without it. Neither tree has a decorator on a sequence — the branch
  order alone decides the outcome. That is one of the cleanest single-variable contrasts in the set.
- **The in-task gate is not a formality here.** Ten refusals at ≈950 cm prove the attack task is
  entered well outside its band, and the tree still never fired out of range, because the task
  re-checks the same key before committing. Any audit that only inspects decorators would
  mis-describe this tree's safety as resting on `n2`'s decorator alone.
- **`retreat_distance_cm` 600 and `retreat_health_pct` 0.15 are dead parameters.** No retreat node
  and no health test exist in the tree, so neither was implemented. Four candidates in a row now
  declare parameters their structure cannot use.
- **The distance policy has a measurable cost and a measurable benefit**, and for once both are
  visible in one figure: 1.99 s to first damage against the baseline's 0.81 s, bought against 0 of
  55 violations versus 15 of 77. That is the trade the generated behaviour makes, stated as
  measurement rather than intent.

## 17.6 Limitations (additional to §§10, 13.6, 14.6, 15.6 and 16.6)

33. **The sample rate changed for this phase** — 59 Hz against 2.9 Hz for the previous five, because
    PIE ran unthrottled. Damage totals and event counts are unaffected (cumulative health deltas;
    hits ≈1 s apart); sub-0.34 s latency comparisons against earlier candidates are not supported.
34. **One damage event in the whole set sits outside the band (250.1 cm) and is a cross-phase
    carry-over**, not a gate failure — `projectiles = 1` precedes it by 35 ms and the enemy had not
    moved. Recorded as instrumentation, counted in neither the pass nor the fail column of §17.3.
35. **The duplicate decorator's abort behaviour is unmeasured.** `n3`'s condition carries
    `FlowAbortMode = Self` and `NotifyObserver = ResultChange`, so a separation that *grows* past
    250 cm while the 0.1 s wait is running would abort the sequence mid-flight and drop the selector
    to `n4`. The protocol holds the player static with the enemy closing, so distance is monotonic
    here and that path never occurred. It is a real untested branch of this tree's behaviour.
36. **Decorator vs in-task gate is not separable for `n2`.** Both read `DistanceToTarget` against
    250 cm, so the run proves the *pair* refuses out-of-band shots but not which member did the
    refusing on the 10 refused passes. Unlike candidate #5 there is no evidence of inertness here.
37. **Why the attack node is entered at ≈1.1 s into each out-of-band phase is not established.** The
    offset is consistent across 9 of 9 phases, which rules out coincidence; the candidate mechanism
    is a decorator evaluation straddling one 0.1 s blackboard write, but that is a hypothesis, not a
    measurement. Same status as candidate #5's inert leaf guards: measured, unexplained.
38. **Trial 3's `far_1500_again` overshoot (546.0 cm end separation, 1 512.3 cm travelled) is
    unexplained.** The pawn ran past a stationary target and did not return inside the band before
    the phase ended. It is 1 phase of 12 and the cause is not attributed.
39. **`n3_Wait` was never observed to execute** and the 0.1 s wait duration is not measurable here.
40. **`retreat_distance_cm` 600 and `retreat_health_pct` 0.15 were not implemented** (no node uses
    either) and were not exercised.

## 17.7 Reproduction

1. Open `Lvl_Research_Trial`; confirm PIE is stopped and `AIController_ResearchEnemy.BehaviorTreeAsset`
   is `BT_Behavior_P01_G02`.
2. `aura_p01g02_compare.start("generated")`; wait ~82 s; `restore_level()` is **not** called between
   subjects — the second call re-arms the arena itself.
3. `aura_p01g02_compare.start("baseline")`; wait ~82 s; then `aura_p01g02_compare.restore_level()`.
4. `aura_p01g02_aggregate.run()` writes the combined, summary and behaviour-failure CSVs, deriving
   each subject's log window from its own session file and shifting it +5 h.
5. Condition isolation: the canonical parameterised `aura_probe_generic.configure(tree, run_id,
   prefix, phases)` with five phases — `far_1500` 8 s, `mid_600` 8 s, `close_200` 8 s,
   `boundary_250` 8 s, `far_1500_again` 6 s (38 s total). The `boundary_250` phase exists only to
   test the exact band edge and is deliberately **not** part of the comparison phase set.
6. No control tree was needed for this candidate: the attack path fired 55 times, so "is the weapon
   alive" was answered by the treatment itself rather than by a substitute tree.

## 17.8 Result files

| File | Contents |
|---|---|
| `results/gameplay/P01G2CMP_phase_metrics_generated.csv` | 12 phase rows, generated |
| `results/gameplay/P01G2CMP_phase_metrics_baseline.csv` | 12 phase rows, baseline |
| `results/gameplay/P01G2CMP_damage_events_generated.csv` | 55 per-event rows |
| `results/gameplay/P01G2CMP_damage_events_baseline.csv` | 77 per-event rows |
| `results/gameplay/P01G2CMP_combined_phase_metrics.csv` | 24 rows, both subjects |
| `results/gameplay/P01G2CMP_combined_damage_events.csv` | 132 rows, both subjects |
| `results/gameplay/P01G2CMP_summary.csv` | per-subject aggregates |
| `results/gameplay/P01G2CMP_behavior_failures.csv` | task line counts per subject |
| `results/gameplay/P01G2CMP_samples_generated.csv`, `..._baseline.csv` | raw per-sample series (4 639 / 4 570) |
| `results/gameplay/P01G2CMP_session_generated.txt`, `..._baseline.txt` | setup + per-phase notes |
| `results/gameplay/P01G2PROBE_phases.csv`, `P01G2PROBE_samples.csv`, `P01G2PROBE_session.txt` | condition-isolation probe, five phases incl. `boundary_250` |
| `Content/Python/aura_p01g02_compare.py`, `aura_p01g02_aggregate.py`, `aura_probe_generic.py` | harnesses |

Preservation re-verified after the run: `results/validation_round1.csv` `ba199d65f1d5136f`,
`results/validation_round2.csv` `ee06fa9c9232f568`, `results/validation_combined.csv`
`e0ffbc7220ca66ba`, `results/generation_validation.csv` `a62b806f988c70c7` — all four unchanged from
the Phase 6 records; 42 raw artefacts (40 `.txt` + 2 `manifest.csv`) hash to aggregate
`d62e84ab3e2ff38c`. No `BT_Behavior_P01_G01`, `P02_G01`, `P04_G01`, `P07_G01`, `P03_G02` or
`BT_Behavior_AttackAlways` asset, and no earlier `results/gameplay/P0*` file, was modified.
`BT_Behavior_P01_G02` carries `AttackRange` 250.0, `AcceptanceRadius` 100.0 and `ArrivalTolerance`
150.0 exactly as derived from the generated parameters.

