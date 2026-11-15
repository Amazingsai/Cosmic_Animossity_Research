"""Condition-isolation probe for generated candidate #2 (round2/P02-G01).

Tree under test: /Game/Research/AI/BT_Behavior_P02_G01

    n0_Selector
      n1_Sequence
        n2_MoveAway      [HealthPercent <= 0.25]   RetreatDistance = 1200
        n3_Wait                                    (no decorator)
      n4_Sequence
        n5_MoveToTarget  [DistanceToTarget > 800]  AcceptanceRadius = 650
        n6_Attack        [DistanceToTarget <= 800] AttackRange = 800

Purpose: test each generated condition INDIVIDUALLY, before any baseline
comparison, by changing only the input a condition reads.

  gate A  HealthPercent <= 0.25 on n2_MoveAway
          control   healthy_600    HealthPercent 1.20, distance 600 -> n2 must never run
          treatment wounded_600    HealthPercent 0.20, distance 600 -> n2 must run
          Same tree, same distance, same spawn; only the enemy's health differs.

  gate B  DistanceToTarget > 800 on n5_MoveToTarget
          wounded_1500 / healthy_1500 at 1500 cm -> n5 must run and the pawn must close
          healthy_600 at 600 cm                 -> n5 must not run, pawn must not close
          (wounded_1500 additionally exercises n2's "already beyond retreat range"
          failure path, which is what lets a wounded enemy fall through to approach.)

  reached / not reached for the attack branch is measured by damage, never by the
  in-task AttackRange gate (requirement #8).

Health stimulus: BP_BasicEnemyAI declares CurrentHealth = 600 and MaxHealth = 500, so
HealthPercent = CurrentHealth / MaxHealth is written by the controller's own 0.1 s
timer from the pawn's health. Setting the pawn's CurrentHealth is therefore the real
input path for gate A, not a blackboard write that the timer would overwrite.

Wall-clock phase boundaries (never time.sleep inside the callback), and the PIE world
and the controller's tree path are both asserted.
"""

import os
import time
import traceback

import unreal

EXPECTED_WORLD = "Lvl_Research_Trial"
RUN_ID = "p7p02_probe"
ENEMY_CLASS_FRAGMENT = "BP_BasicEnemyAI"
ENEMY_CLASS_PATH = "/Game/FirstPerson/Blueprints/AI/BP_BasicEnemyAI.BP_BasicEnemyAI_C"
TREE_FRAGMENT = "BT_Behavior_P02_G01"

HEALTHY_HEALTH = 500.0   # / MaxHealth 500 -> HealthPercent 1.00
WOUNDED_HEALTH = 100.0   # / MaxHealth 500 -> HealthPercent 0.20  (<= 0.25 gate)

# (phase name, duration s, player distance cm, enemy CurrentHealth)
PHASES = (
    ("healthy_600", 6.0, 600.0, HEALTHY_HEALTH),
    ("wounded_600", 12.0, 600.0, WOUNDED_HEALTH),
    ("wounded_1500", 12.0, 1500.0, WOUNDED_HEALTH),
    ("healthy_1500", 10.0, 1500.0, HEALTHY_HEALTH),
)
TRIALS = 2
SETUP_BUDGET = 60.0

_s = {}


def _reset_state():
    _s.clear()
    _s.update({
        "handle": None,
        "done": False,
        "error": None,
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
        "phase_rows": [],
        "sample_rows": [],
        "notes": [],
        "started": False,
        "just_teleported": False,
        "phase_start_xy": None,
        "phase_last_hp": None,
        "phase_hp_set": None,
        "phase_damage": 0.0,
        "phase_first_damage": None,
        "phase_bb_hp_first": None,
        "phase_bb_hp_last": None,
        "phase_bb_d_min": None,
        "phase_bb_d_max": None,
        "wall_start": 0.0,
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


def _find_enemy(world):
    for actor in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor):
        try:
            if ENEMY_CLASS_FRAGMENT in actor.get_class().get_name():
                return actor
        except Exception:
            continue
    return None


def _blackboard(actor):
    """This build has no AIBlueprintHelperLibrary, so go through the controller."""
    try:
        controller = actor.get_controller()
        if controller is None:
            return None
        return controller.get_editor_property("Blackboard")
    except Exception:
        return None


def _prepare(world):
    actor = _find_enemy(world)
    if actor is None:
        return False
    _s["actor"] = actor
    _s["spawn_loc"] = actor.get_actor_location()
    _s["spawn_rot"] = actor.get_actor_rotation()
    try:
        controller = actor.get_controller()
        asset = controller.get_editor_property("BehaviorTreeAsset")
        _s["tree_desc"] = str(asset.get_path_name()) if asset else "none"
    except Exception as exc:
        _s["tree_desc"] = "unreadable (%s)" % exc
    if TREE_FRAGMENT not in _s["tree_desc"]:
        _s["error"] = ("subject is not running %s - controller reports %r"
                       % (TREE_FRAGMENT, _s["tree_desc"]))
        return False
    _s["bb"] = _blackboard(actor)
    if _s["bb"] is None:
        _s["notes"].append("WARNING blackboard could not be resolved (retried every tick)")
    _s["notes"].append("tree=%s" % _s["tree_desc"])
    _s["notes"].append("enemy_spawn=(%.1f,%.1f,%.1f)" % (
        _s["spawn_loc"].x, _s["spawn_loc"].y, _s["spawn_loc"].z))
    return True


def _begin(world):
    _s["world_name"] = world.get_name()
    _s["player"] = unreal.GameplayStatics.get_player_pawn(world, 0)
    if _s["player"] is None:
        _s["error"] = "no player pawn in PIE world"
        return False
    _s["player_z"] = _s["player"].get_actor_location().z
    try:
        current = float(_s["player"].get_editor_property("CurrentHealth"))
        if current < 100000.0:
            _s["player"].set_editor_property("CurrentHealth", 100000.0)
        _s["notes"].append("player_health_at_start=%.1f" % current)
    except Exception:
        _s["notes"].append("player health access failed")
    max_health = "?"
    try:
        max_health = "%.1f" % float(_s["actor"].get_editor_property("MaxHealth"))
    except Exception:
        pass
    _s["notes"].append("enemy_max_health=%s" % max_health)
    _enter_phase(world, 0)
    return True


def _set_enemy_health(value):
    """The real input path for the HealthPercent gate.

    CurrentHealth is not instance editable, so it cannot be written directly. It is
    moved through the pawn's own damage event (SendDamage -> ReduceHealth, a plain
    subtraction) invoked by Unreal reflection: a positive delta wounds, a negative
    delta heals. SendDamage is never called by any behaviour tree or task, so this is
    an external stimulus, not part of the subject under test.
    """
    actor = _s["actor"]
    try:
        current = float(actor.get_editor_property("CurrentHealth"))
    except Exception as exc:
        _s["notes"].append("health read failed: %s" % exc)
        return -1.0
    delta = current - value
    if abs(delta) < 0.001:
        return current
    try:
        actor.call_method("SendDamage", (delta,))
        actual = float(actor.get_editor_property("CurrentHealth"))
    except Exception as exc:
        _s["notes"].append("health stimulus failed: %s" % exc)
        return -1.0
    _s["notes"].append("health stimulus: SendDamage(%.1f) -> CurrentHealth %.1f" % (delta, actual))
    return actual


def _enter_phase(world, index):
    name, duration, distance, health = PHASES[index]
    _s["phase"] = index
    _s["phase_start"] = time.perf_counter()
    _s["phase_samples"] = 0
    _s["phase_damage"] = 0.0
    _s["phase_first_damage"] = None
    _s["just_teleported"] = True
    _s["phase_bb_hp_first"] = None
    _s["phase_bb_hp_last"] = None
    _s["phase_bb_d_min"] = None
    _s["phase_bb_d_max"] = None

    actor = _s["actor"]
    try:
        actor.modify()
        if _s["spawn_loc"] is not None:
            actor.set_actor_location(_s["spawn_loc"], False, True)
        if _s["spawn_rot"] is not None:
            actor.set_actor_rotation(_s["spawn_rot"], False)
    except Exception as exc:
        _s["notes"].append("phase %s subject reset raised %s" % (name, exc))

    _s["phase_hp_set"] = _set_enemy_health(health)

    try:
        loc = actor.get_actor_location()
        _s["phase_start_xy"] = (round(loc.x, 1), round(loc.y, 1))
    except Exception:
        _s["phase_start_xy"] = None

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
        _s["phase_last_hp"] = float(player.get_editor_property("CurrentHealth"))
    except Exception:
        _s["phase_last_hp"] = None

    _s["notes"].append(
        "trial%d %s requested=%.0f enemy_health_set=%.1f (HealthPercent=%.2f)"
        % (_s["trial"] + 1, name, distance, _s["phase_hp_set"],
           (_s["phase_hp_set"] / 500.0) if _s["phase_hp_set"] > 0 else -1.0))


def _close_phase():
    name, duration, distance, health = PHASES[_s["phase"]]
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

    events = [r for r in _s["sample_rows"]
              if r["trial"] == _s["trial"] + 1 and r["phase"] == name and r["delta"] > 0]

    _s["phase_rows"].append([
        RUN_ID, _s["trial"] + 1, name, "%.0f" % distance,
        "%.1f" % _s["phase_hp_set"], "%.2f" % (_s["phase_hp_set"] / 500.0
                                              if _s["phase_hp_set"] > 0 else -1.0),
        "%.1f" % duration, _s["phase_samples"],
        "%.1f" % (_s["phase_samples"] / duration if duration else 0.0),
        ("%.2f" % _s["phase_bb_hp_first"]) if _s["phase_bb_hp_first"] is not None else "",
        ("%.2f" % _s["phase_bb_hp_last"]) if _s["phase_bb_hp_last"] is not None else "",
        ("%.1f" % _s["phase_bb_d_min"]) if _s["phase_bb_d_min"] is not None else "",
        ("%.1f" % _s["phase_bb_d_max"]) if _s["phase_bb_d_max"] is not None else "",
        len(events),
        "%.1f" % _s["phase_damage"],
        "%.3f" % (_s["phase_first_damage"]
                  if _s["phase_first_damage"] is not None else -1.0),
        "%.1f" % moved,
        ("%.1f" % _s["phase_start_xy"][1]) if _s["phase_start_xy"] else "",
        ("%.1f" % end_xy[1]) if end_xy[1] is not None else "",
    ])


def _step(world):
    now = time.perf_counter()
    name, duration, distance, health = PHASES[_s["phase"]]

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
            bb_hp = -1.0
        try:
            bb_dist = float(_s["bb"].get_value_as_float("DistanceToTarget"))
        except Exception:
            bb_dist = -1.0

    try:
        geo = float(actor.get_distance_to(player))
    except Exception:
        geo = -1.0
    try:
        health_now = float(player.get_editor_property("CurrentHealth"))
    except Exception:
        health_now = -1.0
    try:
        enemy_loc = actor.get_actor_location()
        enemy_xy = (round(enemy_loc.x, 1), round(enemy_loc.y, 1))
    except Exception:
        enemy_xy = (None, None)
    try:
        player_y = round(player.get_actor_location().y, 1)
    except Exception:
        player_y = None

    _s["phase_samples"] += 1
    if bb_hp >= 0.0:
        if _s["phase_bb_hp_first"] is None:
            _s["phase_bb_hp_first"] = bb_hp
        _s["phase_bb_hp_last"] = bb_hp
    if bb_dist >= 0.0:
        if _s["phase_bb_d_min"] is None or bb_dist < _s["phase_bb_d_min"]:
            _s["phase_bb_d_min"] = bb_dist
        if _s["phase_bb_d_max"] is None or bb_dist > _s["phase_bb_d_max"]:
            _s["phase_bb_d_max"] = bb_dist

    t_in_phase = now - _s["phase_start"]
    delta = 0.0
    if not _s["just_teleported"] and _s["phase_last_hp"] is not None \
            and health_now >= 0.0 and health_now < _s["phase_last_hp"] - 0.001:
        delta = _s["phase_last_hp"] - health_now
        _s["phase_damage"] += delta
        if _s["phase_first_damage"] is None:
            _s["phase_first_damage"] = t_in_phase
    _s["phase_last_hp"] = health_now
    _s["just_teleported"] = False

    _s["sample_rows"].append({
        "trial": _s["trial"] + 1,
        "phase": name,
        "t_s": round(t_in_phase, 3),
        "bb_hp": round(bb_hp, 3),
        "bb_dist": round(bb_dist, 1),
        "geo_cm": round(geo, 1),
        "player_hp": round(health_now, 1),
        "delta": round(delta, 2),
        "enemy_x": enemy_xy[0],
        "enemy_y": enemy_xy[1],
        "player_y": player_y,
    })


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
                _s["error"] = ("PIE came up in %r but this probe requires %r"
                               % (world.get_name(), EXPECTED_WORLD))
                _finish()
                return
            if not _prepare(world):
                if _s["error"] is not None:
                    _finish()
                elif now - _s["wall_start"] > SETUP_BUDGET:
                    _s["error"] = "subject not resolvable within %.0f s" % SETUP_BUDGET
                    _finish()
                return
            if not _begin(world):
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
    phase_header = ["run_id", "trial", "phase", "requested_cm", "enemy_health_set",
                    "health_percent_set", "duration_s", "samples", "sample_rate_hz",
                    "bb_hp_first", "bb_hp_last", "bb_dist_min", "bb_dist_max",
                    "damage_events", "damage_total", "first_damage_s",
                    "enemy_moved_cm", "enemy_start_y", "enemy_end_y"]
    sample_header = ["run_id", "trial", "phase", "t_s", "bb_hp", "bb_dist", "geo_cm",
                     "player_hp", "delta", "enemy_x", "enemy_y", "player_y"]
    try:
        _write_csv(os.path.join(out, "P02PROBE_phases.csv"), phase_header, _s["phase_rows"])
        sample_rows = []
        for r in _s["sample_rows"]:
            sample_rows.append([RUN_ID, r["trial"], r["phase"], "%.3f" % r["t_s"],
                                "%.3f" % r["bb_hp"], "%.1f" % r["bb_dist"],
                                "%.1f" % r["geo_cm"], "%.1f" % r["player_hp"],
                                "%.2f" % r["delta"], r["enemy_x"], r["enemy_y"],
                                r["player_y"]])
        _write_csv(os.path.join(out, "P02PROBE_samples.csv"), sample_header, sample_rows)
    except Exception:
        pass

    notes = list(_s["notes"])
    if _s["error"]:
        notes.append("ERROR: %s" % _s["error"])
    try:
        with open(os.path.join(out, "P02PROBE_session.txt"), "w") as handle:
            handle.write("run_id=%s\n" % RUN_ID)
            handle.write("phase_rows=%d samples=%d done=%s\n" % (
                len(_s["phase_rows"]), len(_s["sample_rows"]), _s["done"]))
            handle.write("finished_at=%s\n" % time.strftime("%Y.%m.%d-%H.%M.%S"))
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


def start():
    if _s.get("handle") is not None:
        return "a probe session is already registered"
    editor = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if editor.is_in_play_in_editor():
        return "REFUSED: PIE already active; stop it so the run cannot inherit the wrong level"
    _reset_state()
    _s["notes"].append("started_at=%s" % time.strftime("%Y.%m.%d-%H.%M.%S"))
    _s["wall_start"] = time.perf_counter()
    try:
        _s["handle"] = unreal.register_slate_post_tick_callback(_tick)
    except Exception as exc:
        return "could not register tick callback: %s" % exc
    try:
        editor.editor_request_begin_play()
    except Exception as exc:
        return "begin_play failed: %s" % exc
    return "probe session started: trials=%d phases=%d" % (TRIALS, len(PHASES))


def status():
    index = _s.get("phase", 0)
    if not isinstance(index, int) or index < 0 or index >= len(PHASES):
        phase_label = "done" if _s.get("done") else "idle"
    else:
        phase_label = PHASES[index][0]
    return ("running=%s done=%s error=%s trial=%d phase=%s world=%s phase_rows=%d samples=%d"
            % (_s.get("handle") is not None, bool(_s.get("done")),
               bool(_s.get("error")), _s.get("trial", 0) + 1, phase_label,
               _s.get("world_name"), len(_s.get("phase_rows") or []),
               len(_s.get("sample_rows") or [])))
