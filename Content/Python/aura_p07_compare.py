"""Controlled gameplay comparison for generated candidate #6 (round2/P07-G01).

Subject "generated" = the placed BP_BasicEnemyAI driven by BT_Behavior_P07_G01.
Subject "baseline"  = BP_AICharacter, spawned at the experimental enemy's exact
                      transform with the experimental enemy destroyed, so only one
                      combatant is ever present in a session.

This is the Phase 7B harness re-targeted a fourth time (candidate #1 -> #2 -> #3 -> #6),
not a new protocol: identical arena, spawn geometry, player pawn and player health,
phase distances, durations and order, combat settings, three trials per subject. The
phase set is deliberately unchanged so candidate #6's numbers are directly comparable
with #1, #2 and #3; none of 1500 / 600 / 200 sits on this tree's 900 cm band edge, so
this candidate does not inherit candidate #3's boundary artefact.

What changes, and why:
  * RUN_ID and the output prefix ("p7cmp_p07_r1" / "P07CMP_...") so candidate #6's results
    cannot overwrite candidate #1/#2/#3's CSVs, which stay untouched.
  * The band threshold follows the tree under test: candidate #6's generated branch split
    and its attack parameter are both 900 cm, so THRESHOLD_CM is 900 and the reaction
    ceiling is 950 (threshold + 50 cm sampling tolerance).
  * The generated subject's health is still sampled every tick: candidate #6 declares
    retreat_health_pct = 0.2 but its tree contains no health condition, so the recorded
    HealthPercent range is evidence that the parameter is unused rather than an assumption.
  * The retreat task's prints are the only window on whether n2 ever completed; the probe
    already established the requested 1300 cm goal is on-navmesh in every phase, so the
    comparison only has to record the consequence.

Validity rules carried over unchanged: the PIE world name is asserted; the generated
subject's controller must report the tree under test; damage is attributed only on ticks
with no teleport; distance at damage is a lower bound on the true firing distance.
"""

import os
import time
import traceback

import unreal

EXPECTED_WORLD = "Lvl_Research_Trial"
RUN_ID = "p7cmp_p07_r1"
ENEMY_CLASS_FRAGMENT = "BP_BasicEnemyAI"
ENEMY_CLASS_PATH = "/Game/FirstPerson/Blueprints/AI/BP_BasicEnemyAI.BP_BasicEnemyAI_C"
BASELINE_CLASS_FRAGMENT = "BP_AICharacter"
BASELINE_CLASS_PATH = "/Game/FirstPerson/Blueprints/AI/BP_AICharacter.BP_AICharacter_C"
GEN_TREE_FRAGMENT = "BT_Behavior_P07_G01"

PHASES = (
    ("far_1500", 8.0, 1500.0),
    ("mid_600", 6.0, 600.0),
    ("close_200", 6.0, 200.0),
    ("far_1500_again", 6.0, 1500.0),
)
TRIALS = 3
THRESHOLD_CM = 900.0
CEILING_CM = 950.0
SETUP_BUDGET = 60.0

_s = {}
_level = {"donor_loc": None, "donor_rot": None, "prepared": None}


def _reset_state(subject):
    _s.clear()
    _s.update({
        "handle": None, "done": False, "error": None, "subject": subject,
        "world_name": None, "actor": None, "spawn_loc": None, "spawn_rot": None,
        "player": None, "player_z": None, "bb": None, "tree_desc": "",
        "trial": 0, "phase": 0, "phase_start": 0.0, "phase_samples": 0,
        "phase_damage": 0.0, "phase_first_damage": None, "phase_last_hp": None,
        "phase_start_xy": None, "just_teleported": False, "phase_rows": [],
        "sample_rows": [], "events": [], "notes": [], "wall_start": 0.0,
        "started": False, "started_at": "", "phase_hp_start": None,
        "phase_enemy_hp_start": None, "phase_enemy_hp_end": None,
        "phase_bb_hp_min": None, "phase_bb_hp_max": None,
    })


def _project_dir():
    base = unreal.Paths.convert_relative_path_to_full(
        unreal.Paths.project_dir().replace("\\", "/")).replace("\\", "/")
    return base if base.endswith("/") else base + "/"


def _out_dir():
    path = os.path.join(_project_dir(), "results", "gameplay")
    if not os.path.isdir(path):
        os.makedirs(path)
    return path


def _write_csv(path, header, rows):
    lines = [",".join(header)]
    for row in rows:
        lines.append(",".join(str(v) for v in row))
    with open(path, "w") as handle:
        handle.write("\n".join(lines) + "\n")


def _world():
    return unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()


def _all_actors(world):
    try:
        return unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor)
    except Exception:
        return []


def _find_by_class_fragment(world, fragment):
    for actor in _all_actors(world):
        try:
            if fragment in actor.get_class().get_name():
                return actor
        except Exception:
            continue
    return None


def _blackboard(actor):
    try:
        controller = actor.get_controller()
        if controller is None:
            return None
        return controller.get_editor_property("Blackboard")
    except Exception:
        return None


def _prepare_subject(world):
    if _s["subject"] == "generated":
        actor = _find_by_class_fragment(world, ENEMY_CLASS_FRAGMENT)
        if actor is None:
            return False
        try:
            asset = actor.get_controller().get_editor_property("BehaviorTreeAsset")
            _s["tree_desc"] = str(asset.get_path_name()) if asset else "none"
        except Exception as exc:
            _s["tree_desc"] = "unreadable (%s)" % exc
        if GEN_TREE_FRAGMENT not in _s["tree_desc"]:
            _s["error"] = ("generated subject is not running %s - controller reports %r"
                           % (GEN_TREE_FRAGMENT, _s["tree_desc"]))
            return False
    else:
        actor = _find_by_class_fragment(world, BASELINE_CLASS_FRAGMENT)
        if actor is None:
            _s["error"] = ("baseline BP_AICharacter absent from the PIE world; "
                           "prepare_level() must place it before PIE starts")
            return False
        try:
            controller = actor.get_controller()
            tree = controller.get_editor_property("BehaviorTreeAsset") if controller else None
            _s["tree_desc"] = str(tree.get_path_name()) if tree else "none"
        except Exception:
            _s["tree_desc"] = "unreadable"
        if _s["tree_desc"] != "none":
            _s["notes"].append("WARNING baseline reports a behaviour tree: %s"
                               % _s["tree_desc"])
        try:
            _s["notes"].append("baseline_weapon_spawned=%s"
                               % (actor.get_editor_property("Weapon") is not None))
        except Exception:
            pass

    _s["actor"] = actor
    _s["spawn_loc"] = actor.get_actor_location()
    _s["spawn_rot"] = actor.get_actor_rotation()
    _s["bb"] = _blackboard(actor)
    if _s["subject"] == "generated":
        try:
            _s["notes"].append("subject_health_at_start=%.1f max=%.1f" % (
                float(actor.get_editor_property("CurrentHealth")),
                float(actor.get_editor_property("MaxHealth"))))
        except Exception:
            pass
    return True


def prepare_level(subject):
    """Swap the arena combatant in the EDITOR world, before PIE starts."""
    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    if world is None:
        return False, "no editor world"

    donor = None
    baseline = None
    for actor in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor):
        try:
            cname = actor.get_class().get_name()
        except Exception:
            continue
        if ENEMY_CLASS_FRAGMENT in cname and donor is None:
            donor = actor
        elif BASELINE_CLASS_FRAGMENT in cname and baseline is None:
            baseline = actor

    if donor is not None:
        _level["donor_loc"] = donor.get_actor_location()
        _level["donor_rot"] = donor.get_actor_rotation()

    if subject == "generated":
        if baseline is not None:
            sub.destroy_actor(baseline)
        if donor is None:
            return False, "no experimental enemy in the editor level"
        _level["prepared"] = "generated"
        return True, "editor level armed with the placed experimental enemy"

    if _level["donor_loc"] is None:
        return False, "no experimental enemy (and no recorded transform) to site the baseline"
    if baseline is None:
        cls = unreal.load_class(None, BASELINE_CLASS_PATH)
        if cls is None:
            return False, "could not load %s" % BASELINE_CLASS_PATH
        baseline = sub.spawn_actor_from_class(cls, _level["donor_loc"], _level["donor_rot"])
        if baseline is None:
            return False, "editor spawn of %s failed" % BASELINE_CLASS_PATH
    if donor is not None:
        sub.destroy_actor(donor)
    _level["prepared"] = "baseline"
    return True, "editor level armed with BP_AICharacter only"


def restore_level():
    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    if world is None:
        return "no editor world"
    removed = 0
    donor_present = False
    for actor in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor):
        try:
            cname = actor.get_class().get_name()
        except Exception:
            continue
        if BASELINE_CLASS_FRAGMENT in cname:
            if sub.destroy_actor(actor):
                removed += 1
        elif ENEMY_CLASS_FRAGMENT in cname:
            donor_present = True
    restored = "already present"
    if not donor_present and _level["donor_loc"] is not None:
        cls = unreal.load_class(None, ENEMY_CLASS_PATH)
        if cls is None:
            restored = "FAILED to load %s" % ENEMY_CLASS_PATH
        else:
            spawned = sub.spawn_actor_from_class(cls, _level["donor_loc"], _level["donor_rot"])
            restored = "respawned" if spawned is not None else "FAILED to respawn"
    _level["prepared"] = None
    return "removed_baseline=%d experimental_enemy=%s" % (removed, restored)


def _begin_session(world):
    _s["world_name"] = world.get_name()
    _s["player"] = unreal.GameplayStatics.get_player_pawn(world, 0)
    if _s["player"] is None:
        _s["error"] = "no player pawn in PIE world"
        return False
    _s["player_z"] = _s["player"].get_actor_location().z
    try:
        current = float(_s["player"].get_editor_property("CurrentHealth"))
        _s["notes"].append("player_health_at_start=%.1f" % current)
        if current < 100000.0:
            _s["player"].set_editor_property("CurrentHealth", 100000.0)
    except Exception:
        _s["notes"].append("player health access failed")
    _s["notes"].append("subject=%s tree=%s player_z=%.1f"
                       % (_s["subject"], _s["tree_desc"], _s["player_z"]))
    _enter_phase(world, 0)
    return True


def _enter_phase(world, index):
    name, duration, distance = PHASES[index]
    _s["phase"] = index
    _s["phase_start"] = time.perf_counter()
    _s["phase_samples"] = 0
    _s["phase_damage"] = 0.0
    _s["phase_first_damage"] = None
    _s["just_teleported"] = True
    _s["phase_bb_hp_min"] = None
    _s["phase_bb_hp_max"] = None

    actor = _s["actor"]
    try:
        actor.modify()
        if _s["spawn_loc"] is not None:
            actor.set_actor_location(_s["spawn_loc"], False, True)
        if _s["spawn_rot"] is not None:
            actor.set_actor_rotation(_s["spawn_rot"], False)
    except Exception as exc:
        _s["notes"].append("phase %s subject reset raised %s" % (name, exc))
    try:
        _s["phase_start_xy"] = (round(actor.get_actor_location().x, 1),
                                round(actor.get_actor_location().y, 1))
    except Exception:
        _s["phase_start_xy"] = None
    try:
        _s["phase_enemy_hp_start"] = float(actor.get_editor_property("CurrentHealth"))
    except Exception:
        _s["phase_enemy_hp_start"] = None

    player = _s["player"]
    if player is not None and _s["spawn_loc"] is not None:
        target = unreal.Vector(_s["spawn_loc"].x, _s["spawn_loc"].y - distance,
                               _s["player_z"])
        try:
            player.modify()
            player.set_actor_location(target, False, True)
        except Exception as exc:
            _s["notes"].append("phase %s player teleport raised %s" % (name, exc))

    try:
        health = float(player.get_editor_property("CurrentHealth"))
    except Exception:
        health = -1.0
    _s["phase_hp_start"] = health
    _s["phase_last_hp"] = health
    _s["notes"].append("trial%d %s requested=%.0f health_start=%.1f"
                       % (_s["trial"] + 1, name, distance, health))
    unreal.log("AURA_PHASE trial%d %s start requested=%.0f"
               % (_s["trial"] + 1, name, distance))


def _close_phase():
    name, duration, distance = PHASES[_s["phase"]]
    actor = _s["actor"]
    end_xy = (None, None)
    try:
        loc = actor.get_actor_location()
        end_xy = (round(loc.x, 1), round(loc.y, 1))
    except Exception:
        pass
    try:
        _s["phase_enemy_hp_end"] = float(actor.get_editor_property("CurrentHealth"))
    except Exception:
        _s["phase_enemy_hp_end"] = None
    moved = -1.0
    if _s["phase_start_xy"] and end_xy[0] is not None:
        moved = (((end_xy[0] - _s["phase_start_xy"][0]) ** 2
                  + (end_xy[1] - _s["phase_start_xy"][1]) ** 2) ** 0.5)

    events = [e for e in _s["events"]
              if e["trial"] == _s["trial"] + 1 and e["phase"] == name]
    geo_values = [e["geo_cm"] for e in events if e["geo_cm"] >= 0.0]
    bb_values = [e["bb_cm"] for e in events if e["bb_cm"] >= 0.0]

    def fmt(value):
        return "%.1f" % value if value is not None else ""

    _s["phase_rows"].append([
        RUN_ID, _s["subject"], _s["tree_desc"], _s["trial"] + 1, name,
        "%.0f" % distance, "%.1f" % duration, _s["phase_samples"],
        "%.1f" % (_s["phase_samples"] / duration if duration else 0.0),
        len(events), "%.1f" % _s["phase_damage"], "%.1f" % _s["phase_hp_start"],
        "%.1f" % (max(geo_values) if geo_values else -1.0),
        "%.1f" % (min(geo_values) if geo_values else -1.0),
        "%.1f" % (max(bb_values) if bb_values else -1.0),
        "%.3f" % (_s["phase_first_damage"] if _s["phase_first_damage"] is not None else -1.0),
        "%.1f" % moved,
        (fmt(_s["phase_start_xy"][1]) if _s["phase_start_xy"] else ""),
        (fmt(end_xy[1]) if end_xy[1] is not None else ""),
        fmt(_s["phase_enemy_hp_start"]), fmt(_s["phase_enemy_hp_end"]),
        fmt(_s["phase_bb_hp_min"]), fmt(_s["phase_bb_hp_max"]),
    ])
    unreal.log("AURA_PHASE trial%d %s end moved=%.1f damage=%.1f"
               % (_s["trial"] + 1, name, moved, _s["phase_damage"]))


def _step(world):
    now = time.perf_counter()
    name, duration, distance = PHASES[_s["phase"]]

    if now - _s["phase_start"] >= duration:
        _close_phase()
        if _s["phase"] + 1 < len(PHASES):
            _enter_phase(world, _s["phase"] + 1)
        else:
            _s["trial"] += 1
            if _s["trial"] >= TRIALS:
                _s["done"] = True
                return
            _enter_phase(world, 0)
        return

    actor = _s["actor"]
    player = _s["player"]
    if actor is None or player is None:
        return

    bb_hp = -1.0
    bb_dist = -1.0
    if _s["bb"] is None:
        _s["bb"] = _blackboard(actor)
    if _s["bb"] is not None:
        try:
            bb_hp = float(_s["bb"].get_value_as_float("HealthPercent"))
        except Exception:
            pass
        try:
            bb_dist = float(_s["bb"].get_value_as_float("DistanceToTarget"))
        except Exception:
            pass
    if bb_hp >= 0.0:
        if _s["phase_bb_hp_min"] is None or bb_hp < _s["phase_bb_hp_min"]:
            _s["phase_bb_hp_min"] = bb_hp
        if _s["phase_bb_hp_max"] is None or bb_hp > _s["phase_bb_hp_max"]:
            _s["phase_bb_hp_max"] = bb_hp

    try:
        geo = float(actor.get_distance_to(player))
    except Exception:
        geo = -1.0
    try:
        health = float(player.get_editor_property("CurrentHealth"))
    except Exception:
        health = -1.0
    try:
        enemy_hp = float(actor.get_editor_property("CurrentHealth"))
    except Exception:
        enemy_hp = -1.0

    _s["phase_samples"] += 1
    t_in_phase = now - _s["phase_start"]

    delta = 0.0
    if not _s["just_teleported"] and _s["phase_last_hp"] is not None \
            and health >= 0.0 and health < _s["phase_last_hp"] - 0.001:
        delta = _s["phase_last_hp"] - health
        _s["phase_damage"] += delta
        if _s["phase_first_damage"] is None:
            _s["phase_first_damage"] = t_in_phase
        _s["events"].append({
            "trial": _s["trial"] + 1, "phase": name, "requested_cm": distance,
            "t_s": round(t_in_phase, 3), "delta": round(delta, 2),
            "geo_cm": round(geo, 1), "bb_cm": round(bb_dist, 1),
            "beyond_threshold": 1 if (geo >= 0.0 and geo > THRESHOLD_CM) else 0,
            "beyond_ceiling": 1 if (geo >= 0.0 and geo > CEILING_CM) else 0,
        })
    _s["phase_last_hp"] = health
    _s["just_teleported"] = False

    _s["sample_rows"].append([
        RUN_ID, _s["subject"], _s["trial"] + 1, name, "%.3f" % t_in_phase,
        "%.1f" % geo, "%.1f" % bb_dist, "%.3f" % bb_hp, "%.1f" % health,
        "%.1f" % enemy_hp, "%.2f" % delta])


def _tick(_delta_seconds):
    if _s.get("done") or _s.get("error"):
        return
    try:
        now = time.perf_counter()
        world = _world()
        if world is None:
            if now - _s["wall_start"] > SETUP_BUDGET:
                _s["error"] = "no game world within %.0f s - PIE never started" % SETUP_BUDGET
                _finish()
            return

        if not _s["started"]:
            if world.get_name() != EXPECTED_WORLD:
                _s["error"] = ("PIE came up in %r but this comparison requires %r"
                               % (world.get_name(), EXPECTED_WORLD))
                _finish()
                return
            if not _prepare_subject(world):
                if _s["error"] is None and now - _s["wall_start"] > SETUP_BUDGET:
                    _s["error"] = "subject not resolvable within %.0f s" % SETUP_BUDGET
                    _finish()
                    return
                if _s["error"] is not None:
                    _finish()
                return
            if not _begin_session(world):
                _finish()
                return
            _s["started"] = True
            return

        _step(world)
        if _s["done"]:
            _finish()
    except Exception:
        _s["error"] = traceback.format_exc()
        _finish()


def _finish():
    out = _out_dir()
    event_header = ["run_id", "subject", "tree", "trial", "phase", "requested_cm",
                    "t_s", "delta", "geo_cm", "bb_cm", "beyond_threshold",
                    "beyond_ceiling"]
    event_rows = []
    for e in _s["events"]:
        event_rows.append([RUN_ID, _s["subject"], _s["tree_desc"], e["trial"], e["phase"],
                           "%.0f" % e["requested_cm"], "%.3f" % e["t_s"],
                           "%.2f" % e["delta"], "%.1f" % e["geo_cm"],
                           "%.1f" % e["bb_cm"], e["beyond_threshold"],
                           e["beyond_ceiling"]])

    phase_header = ["run_id", "subject", "tree", "trial", "phase", "requested_cm",
                    "duration_s", "samples", "sample_rate_hz", "damage_events",
                    "damage_total", "health_at_phase_start", "max_geo_at_damage_cm",
                    "min_geo_at_damage_cm", "max_bb_at_damage_cm", "first_damage_s",
                    "subject_moved_cm", "subject_start_y", "subject_end_y",
                    "enemy_health_start", "enemy_health_end", "bb_health_percent_min",
                    "bb_health_percent_max"]
    sample_header = ["run_id", "subject", "trial", "phase", "t_s", "geo_cm", "bb_cm",
                     "bb_health_percent", "player_hp", "enemy_hp", "delta"]

    try:
        _write_csv(os.path.join(out, "P07CMP_phase_metrics_%s.csv" % _s["subject"]),
                   phase_header, _s["phase_rows"])
        _write_csv(os.path.join(out, "P07CMP_damage_events_%s.csv" % _s["subject"]),
                   event_header, event_rows)
        _write_csv(os.path.join(out, "P07CMP_samples_%s.csv" % _s["subject"]),
                   sample_header, _s["sample_rows"])
    except Exception:
        pass

    notes = list(_s["notes"])
    if _s["error"]:
        notes.append("ERROR: %s" % _s["error"])
    try:
        with open(os.path.join(out, "P07CMP_session_%s.txt" % _s["subject"]), "w") as handle:
            handle.write("run_id=%s subject=%s\n" % (RUN_ID, _s["subject"]))
            handle.write("phase_rows=%d damage_events=%d samples=%d done=%s\n" % (
                len(_s["phase_rows"]), len(event_rows), len(_s["sample_rows"]), _s["done"]))
            handle.write("started_at=%s finished_at=%s\n" % (
                _s.get("started_at", ""), time.strftime("%Y.%m.%d-%H.%M.%S")))
            for note in notes:
                handle.write(note + "\n")
    except Exception:
        pass

    handle = _s.get("handle")
    if handle is not None:
        try:
            unreal.unregister_slate_post_tick_callback(handle)
        except Exception:
            pass
        _s["handle"] = None
    try:
        unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).editor_request_end_play()
    except Exception:
        pass


def start(subject):
    if subject not in ("generated", "baseline"):
        return "subject must be 'generated' or 'baseline'"
    if _s.get("handle") is not None:
        return "a session is already registered"
    editor = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if editor.is_in_play_in_editor():
        return "REFUSED: PIE already active; stop it so the run cannot inherit the wrong level"
    _reset_state(subject)
    ok, message = prepare_level(subject)
    if not ok:
        return "REFUSED: %s" % message
    _s["notes"].append("level_prep: %s" % message)
    _s["started_at"] = time.strftime("%Y.%m.%d-%H.%M.%S")
    print("%s session started_at=%s" % (subject, _s["started_at"]))
    _s["wall_start"] = time.perf_counter()
    try:
        _s["handle"] = unreal.register_slate_post_tick_callback(_tick)
    except Exception as exc:
        return "could not register tick callback: %s" % exc
    try:
        editor.editor_request_begin_play()
    except Exception as exc:
        return "begin_play failed: %s" % exc
    return "session started for subject=%s trials=%d phases=%d threshold=%.0f" % (
        subject, TRIALS, len(PHASES), THRESHOLD_CM)


def status():
    subject = _s.get("subject")
    index = _s.get("phase", 0)
    if subject is None:
        phase_label = "idle"
    elif not isinstance(index, int) or index < 0 or index >= len(PHASES):
        phase_label = "done" if _s.get("done") else "idle"
    else:
        phase_label = PHASES[index][0]
    return ("subject=%s running=%s done=%s error=%s trial=%d phase=%s world=%s "
            "phase_rows=%d events=%d samples=%d"
            % (subject, _s.get("handle") is not None, bool(_s.get("done")),
               bool(_s.get("error")), _s.get("trial", 0) + 1, phase_label,
               _s.get("world_name"), len(_s.get("phase_rows") or []),
               len(_s.get("events") or []), len(_s.get("sample_rows") or [])))
