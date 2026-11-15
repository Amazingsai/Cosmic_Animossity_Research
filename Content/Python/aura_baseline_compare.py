"""Controlled gameplay comparison: generated enemy vs the baseline control.

Subject "generated" = the placed BP_BasicEnemyAI driven by BT_Behavior_P01_G01.
Subject "baseline"  = BP_AICharacter, spawned at the experimental enemy's exact
                      transform and the experimental enemy destroyed, so only one
                      combatant is ever present in a session.

Both subjects face the identical arena, spawn geometry, player pawn, player
health, phase distances and phase durations. The only uncontrolled difference is
the subject itself (recorded in every row).

Design decisions that matter for validity:

* One PIE session per subject, three trials inside it. Phase boundaries are driven
  by wall clock, so a throttled editor does not stretch a phase - it only reduces
  the sample count, which is recorded per phase as sample_rate_hz.
* The PIE world name is asserted. An earlier phase produced a 25 s "result" from
  Lvl_FirstPerson, a level with no enemy in it, after begin_play was requested
  while a previous end_play was still tearing down.
* Damage is attributed only on ticks where no teleport happened; a teleport
  changes the geometry under the sample and would misattribute a pre-teleport hit
  to the new phase distance.
* enemy_moved_cm is measured at phase entry and exit, not from samples, because
  actor-location reads are frequently invalid at low sample rates.
* Distance at damage is a LOWER bound on the true distance: the subject closes on
  a stationary player, so a shot recorded beyond the threshold was at least that
  far. Violations therefore cannot be masked, only missed.

Writes CSV, one file per subject, into <project>/results/gameplay/. Every row
carries run_id and subject so a stale file cannot be mistaken for a fresh one.
"""

import os
import time
import traceback

import unreal

EXPECTED_WORLD = "Lvl_Research_Trial"
RUN_ID = "p7cmp_r1"
ENEMY_CLASS_FRAGMENT = "BP_BasicEnemyAI"
BASELINE_CLASS_PATH = "/Game/FirstPerson/Blueprints/AI/BP_AICharacter.BP_AICharacter_C"
BASELINE_CLASS_FRAGMENT = "BP_AICharacter"
ENEMY_CLASS_PATH = "/Game/FirstPerson/Blueprints/AI/BP_BasicEnemyAI.BP_BasicEnemyAI_C"
GEN_TREE_FRAGMENT = "BT_Behavior_P01_G01"

# (phase name, duration seconds, player distance from subject spawn, cm)
PHASES = (
    ("far_1500", 8.0, 1500.0),
    ("mid_600", 6.0, 600.0),
    ("close_200", 6.0, 200.0),
    ("far_1500_again", 6.0, 1500.0),
)
TRIALS = 3
THRESHOLD_CM = 300.0
CEILING_CM = 350.0
SETUP_BUDGET = 60.0

_s = {}

# Editor-world arena bookkeeping, so the combatant swap can be undone.
_level = {"donor_loc": None, "donor_rot": None, "prepared": None}


def _reset_state(subject):
    _s.clear()
    _s.update({
        "handle": None,
        "done": False,
        "error": None,
        "subject": subject,
        "world_name": None,
        "actor": None,
        "spawn_loc": None,
        "spawn_rot": None,
        "player": None,
        "player_z": None,
        "bb": None,
        "tree_desc": "",
        "trial": 0,
        "phase": 0,
        "phase_start": 0.0,
        "phase_samples": 0,
        "phase_damage": 0.0,
        "phase_first_damage": None,
        "phase_last_hp": None,
        "phase_start_xy": None,
        "just_teleported": False,
        "phase_rows": [],
        "events": [],
        "notes": [],
        "t0": 0.0,
        "wall_start": 0.0,
        "started": False,
    })


def _project_dir():
    base = unreal.Paths.convert_relative_path_to_full(
        unreal.Paths.project_dir().replace("\\", "/")).replace("\\", "/")
    if not base.endswith("/"):
        base = base + "/"
    return base


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
        bb = unreal.AIBlueprintHelperLibrary.get_blackboard(actor)
        if bb is not None:
            return bb
    except Exception:
        pass
    try:
        controller = actor.get_controller()
        if controller is not None:
            return controller.get_editor_property("Blackboard")
    except Exception:
        pass
    return None


def _prepare_subject(world):
    """Resolve the combatant for this session and record how it is driven."""
    if _s["subject"] == "generated":
        actor = _find_by_class_fragment(world, ENEMY_CLASS_FRAGMENT)
        if actor is None:
            return False
        try:
            controller = actor.get_controller()
            asset = controller.get_editor_property("BehaviorTreeAsset")
            _s["tree_desc"] = str(asset.get_path_name()) if asset else "none"
        except Exception as exc:
            _s["tree_desc"] = "unreadable (%s)" % exc
        if GEN_TREE_FRAGMENT not in _s["tree_desc"]:
            _s["error"] = (
                "generated subject is not running %s - controller reports %r"
                % (GEN_TREE_FRAGMENT, _s["tree_desc"]))
            return False
    else:
        actor = _find_by_class_fragment(world, BASELINE_CLASS_FRAGMENT)
        if actor is None:
            _s["error"] = (
                "baseline BP_AICharacter absent from the PIE world; prepare_level() must "
                "place it before PIE starts")
            return False
        try:
            controller = actor.get_controller()
            tree = None
            if controller is not None:
                tree = controller.get_editor_property("BehaviorTreeAsset")
            _s["tree_desc"] = str(tree.get_path_name()) if tree else "none"
        except Exception:
            _s["tree_desc"] = "unreadable"
        if _s["tree_desc"] != "none":
            _s["notes"].append(
                "WARNING baseline reports a behaviour tree: %s" % _s["tree_desc"])
        weapon = None
        try:
            weapon = actor.get_editor_property("Weapon")
        except Exception:
            pass
        _s["notes"].append("baseline_weapon_spawned=%s" % (weapon is not None))
        try:
            clo = actor.get_actor_location()
            _s["notes"].append("baseline_pie_start=(%.1f,%.1f,%.1f)" % (clo.x, clo.y, clo.z))
        except Exception:
            pass

    _s["actor"] = actor
    _s["spawn_loc"] = actor.get_actor_location()
    _s["spawn_rot"] = actor.get_actor_rotation()
    try:
        _s["bb"] = _blackboard(actor)
    except Exception:
        _s["bb"] = None
    return True


def prepare_level(subject):
    """Swap the arena combatant in the EDITOR world, before PIE starts.

    This build exposes no runtime spawn (GameplayStatics has only decal / sound /
    emitter spawns, and UWorld exposes none), so the subject has to be placed in
    the editor world, which PIE then duplicates. The level is never saved, so the
    .umap on disk is left exactly as it was.
    """
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
    """Undo prepare_level(): drop baseline instances, restore the experimental enemy."""
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
    ploc = _s["player"].get_actor_location()
    _s["player_z"] = ploc.z
    try:
        current = float(_s["player"].get_editor_property("CurrentHealth"))
        _s["notes"].append("player_health_at_start=%.1f" % current)
        if current < 100000.0:
            _s["player"].set_editor_property("CurrentHealth", 100000.0)
    except Exception:
        _s["notes"].append("player health access failed")
    _s["notes"].append("subject=%s tree=%s player_z=%.1f" % (
        _s["subject"], _s["tree_desc"], _s["player_z"]))
    _s["t0"] = time.perf_counter()
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

    actor = _s["actor"]
    try:
        actor.modify()
    except Exception:
        pass
    if _s["spawn_loc"] is not None:
        try:
            actor.set_actor_location(_s["spawn_loc"], False, True)
            if _s["spawn_rot"] is not None:
                actor.set_actor_rotation(_s["spawn_rot"], False)
        except Exception as exc:
            _s["notes"].append("phase %s subject reset raised %s" % (name, exc))
    loc = actor.get_actor_location()
    _s["phase_start_xy"] = (round(loc.x, 1), round(loc.y, 1))

    player = _s["player"]
    if player is not None and _s["spawn_loc"] is not None:
        target = unreal.Vector(
            _s["spawn_loc"].x, _s["spawn_loc"].y - distance, _s["player_z"])
        try:
            player.modify()
            player.set_actor_location(target, False, True)
        except Exception as exc:
            _s["notes"].append("phase %s player teleport raised %s" % (name, exc))

    try:
        health = float(player.get_editor_property("CurrentHealth"))
    except Exception:
        health = -1.0
    _s["phase_health_start"] = health
    _s["phase_last_hp"] = health
    _s["notes"].append("trial%d %s requested=%.0f health_start=%.1f" % (
        _s["trial"] + 1, name, distance, health))


def _close_phase():
    name, duration, distance = PHASES[_s["phase"]]
    actor = _s["actor"]
    end_xy = (None, None)
    try:
        loc = actor.get_actor_location()
        end_xy = (round(loc.x, 1), round(loc.y, 1))
    except Exception:
        pass
    moved = -1.0
    if _s["phase_start_xy"] and end_xy[0] is not None:
        moved = (((end_xy[0] - _s["phase_start_xy"][0]) ** 2
                  + (end_xy[1] - _s["phase_start_xy"][1]) ** 2) ** 0.5)

    events = [e for e in _s["events"]
              if e["trial"] == _s["trial"] + 1 and e["phase"] == name]
    geo_values = [e["geo_cm"] for e in events if e["geo_cm"] >= 0.0]
    bb_values = [e["bb_cm"] for e in events if e["bb_cm"] >= 0.0]

    _s["phase_rows"].append([
        RUN_ID,
        _s["subject"],
        _s["tree_desc"],
        _s["trial"] + 1,
        name,
        "%.0f" % distance,
        "%.1f" % duration,
        _s["phase_samples"],
        "%.1f" % (_s["phase_samples"] / duration if duration else 0.0),
        len(events),
        "%.1f" % _s["phase_damage"],
        "%.1f" % _s["phase_health_start"],
        "%.1f" % (max(geo_values) if geo_values else -1.0),
        "%.1f" % (min(geo_values) if geo_values else -1.0),
        "%.1f" % (max(bb_values) if bb_values else -1.0),
        "%.3f" % (_s["phase_first_damage"] if _s["phase_first_damage"] is not None else -1.0),
        "%.1f" % moved,
        ("%.1f" % _s["phase_start_xy"][1]) if _s["phase_start_xy"] else "",
        ("%.1f" % end_xy[1]) if end_xy[1] is not None else "",
    ])


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

    bb_dist = -1.0
    if _s["bb"] is not None:
        try:
            bb_dist = float(_s["bb"].get_value_as_float("DistanceToTarget"))
        except Exception:
            bb_dist = -1.0

    try:
        geo = float(actor.get_distance_to(player))
    except Exception:
        geo = -1.0
    try:
        health = float(player.get_editor_property("CurrentHealth"))
    except Exception:
        health = -1.0

    _s["phase_samples"] += 1

    if _s["just_teleported"]:
        _s["just_teleported"] = False
        _s["phase_last_hp"] = health
        return

    previous = _s["phase_last_hp"]
    if previous is not None and health >= 0.0 and health < previous - 0.001:
        delta = previous - health
        t_in_phase = now - _s["phase_start"]
        _s["phase_damage"] += delta
        if _s["phase_first_damage"] is None:
            _s["phase_first_damage"] = t_in_phase
        _s["events"].append({
            "run_id": RUN_ID,
            "subject": _s["subject"],
            "tree": _s["tree_desc"],
            "trial": _s["trial"] + 1,
            "phase": name,
            "requested_cm": distance,
            "t_s": round(t_in_phase, 3),
            "delta": round(delta, 2),
            "geo_cm": round(geo, 1),
            "bb_cm": round(bb_dist, 1),
            "beyond_threshold": 1 if (geo >= 0.0 and geo > THRESHOLD_CM) else 0,
            "beyond_ceiling": 1 if (geo >= 0.0 and geo > CEILING_CM) else 0,
        })
    _s["phase_last_hp"] = health


def _tick(_delta_seconds):
    if _s["done"] or _s["error"]:
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
                _s["error"] = (
                    "PIE came up in %r but this comparison requires %r" % (
                        world.get_name(), EXPECTED_WORLD))
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
    events = _s["events"]
    phase_rows = _s["phase_rows"]
    out = _out_dir()

    event_header = ["run_id", "subject", "tree", "trial", "phase", "requested_cm",
                    "t_s", "delta", "geo_cm", "bb_cm",
                    "beyond_threshold", "beyond_ceiling"]
    event_rows = []
    for e in events:
        event_rows.append([e["run_id"], e["subject"], e["tree"], e["trial"], e["phase"],
                           "%.0f" % e["requested_cm"], "%.3f" % e["t_s"],
                           "%.2f" % e["delta"], "%.1f" % e["geo_cm"],
                           "%.1f" % e["bb_cm"], e["beyond_threshold"],
                           e["beyond_ceiling"]])

    phase_header = ["run_id", "subject", "tree", "trial", "phase", "requested_cm",
                    "duration_s", "samples", "sample_rate_hz", "damage_events",
                    "damage_total", "health_at_phase_start", "max_geo_at_damage_cm",
                    "min_geo_at_damage_cm", "max_bb_at_damage_cm",
                    "first_damage_s", "subject_moved_cm", "subject_start_y",
                    "subject_end_y"]

    try:
        _write_csv(os.path.join(out, "P7CMP_phase_metrics_%s.csv" % _s["subject"]),
                   phase_header, phase_rows)
        _write_csv(os.path.join(out, "P7CMP_damage_events_%s.csv" % _s["subject"]),
                   event_header, event_rows)
    except Exception:
        pass

    notes = list(_s["notes"])
    if _s["error"]:
        notes.append("ERROR: %s" % _s["error"])
    try:
        with open(os.path.join(out, "P7CMP_session_%s.txt" % _s["subject"]), "w") as handle:
            handle.write("run_id=%s subject=%s\n" % (RUN_ID, _s["subject"]))
            handle.write("phase_rows=%d damage_events=%d done=%s\n" % (
                len(phase_rows), len(event_rows), _s["done"]))
            for note in notes:
                handle.write(note + "\n")
    except Exception:
        pass

    handle = _s["handle"]
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
    _s["wall_start"] = time.perf_counter()
    try:
        _s["handle"] = unreal.register_slate_post_tick_callback(_tick)
    except Exception as exc:
        return "could not register tick callback: %s" % exc
    try:
        editor.editor_request_begin_play()
    except Exception as exc:
        return "begin_play failed: %s" % exc
    return "session started for subject=%s trials=%d phases=%d" % (
        subject, TRIALS, len(PHASES))


def status():
    # Tolerant of an empty/uninitialised _s (status() may be called before start()).
    subject = _s.get("subject")
    index = _s.get("phase", 0)
    if subject is None:
        phase_label = "idle"
    elif not isinstance(index, int) or index < 0 or index >= len(PHASES):
        phase_label = "done" if _s.get("done") else "idle"
    else:
        phase_label = PHASES[index][0]
    return ("subject=%s running=%s done=%s error=%s trial=%d phase=%s world=%s "
            "phase_rows=%d events=%d" % (
                subject, _s.get("handle") is not None,
                bool(_s.get("done")),
                bool(_s.get("error")), _s.get("trial", 0) + 1,
                phase_label,
                _s.get("world_name"),
                len(_s.get("phase_rows") or []),
                len(_s.get("events") or [])))
