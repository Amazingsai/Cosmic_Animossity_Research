"""Phase 7F condition-isolation probe for candidate #5 (round2/P03-G02).

Purpose: test each generated condition and the REACHABILITY of each intended action
BEFORE the baseline comparison runs. Single session, four distance bands, no comparison
bookkeeping beyond damage-at-distance.

The tree under test (`BT_Behavior_P03_G02`) is:

    n0_Selector
      n1_Sequence                        (no decorator)
        n2_MoveAway      RetreatDistance=1500   DEC: DistanceToTarget <  800
        n3_Wait          WaitTime=0.1           (no decorator)
      n4_Sequence                        (no decorator)
        n5_MoveToTarget  AcceptanceRadius=850   DEC: DistanceToTarget >  1200
        n6_Wait          WaitTime=0.1           (no decorator)
      n7_Sequence                        (no decorator)
        n8_Attack        AttackRange=1000       DEC: CanAttack Is Set
        n9_Wait          WaitTime=0.1           (no decorator)

Three observation points already exist inside the tasks, so no node has to be edited to
detect reachability:

  * BTTask_EnemyMoveAwayFromTarget prints on EVERY terminal path, including
    "SUCCESS d=<d> thr=<thr>" and "FAILURE (retreat too short)". thr = RetreatDistance
    - 150, so for this tree thr = 1350.0. A printed line therefore proves n2 executed.
  * BTTask_EnemyMoveToTarget prints "SUCCESS" / "FAILURE (arrived too far) d=.. thr=.."
    when the move reaches Idle. thr = AcceptanceRadius + 150 = 1000.0.
  * BTTask_EnemyAttack prints "out of range - FAILURE" whenever its internal
    DistanceToTarget <= AttackRange gate refuses. That gate is a safety check inside the
    task, NOT a tree condition, so its line proves n8 EXECUTED but is never counted as
    evidence that the CanAttack decorator did anything.

The geometry this probe measures rather than assumes:

  * n2's success test is d >= 1350 but its decorator aborts the task at d >= 800, so the
    abort precedes the success test by 550 cm. Separately, goal = self + 1500 away from a
    spawn at y = 600 gives y = 2100, which is outside the 1976 cm navmesh half-extent, so
    the move may not start at all (candidate #3's mechanism).
  * n5's success test is d <= 1000 but its decorator aborts at d <= 1200, so the abort
    precedes the success test by 200 cm.
  * Both sequences therefore always fail, so n7 is reached on every tick and the attack
    has no distance guard of its own (the L5 finding). It fires wherever the in-task gate
    permits, i.e. d <= 1000.
  * The consequence is a DEAD ANNULUS at 1000 < d <= 1200: the approach is disabled by
    its own decorator, the retreat is disabled by its own decorator, and the attack is
    refused by the task gate, so the tree cannot move the pawn again.

Phase markers are written to the log as "AURA_PHASE <name> start/end" because task prints
carry no phase information; the aggregate step buckets task lines by those windows.

Project rules honoured: level name asserted; PIE never started while PIE is active; player
health raised so no death truncates a phase; damage not bookkept on a teleport tick; no
time.sleep anywhere; nothing in any asset is modified by this script.
"""

import os
import time
import traceback

import unreal

EXPECTED_WORLD = "Lvl_Research_Trial"
RUN_ID = "p7p03g2_probe"
OUTPUT_PREFIX = "P03PROBE"
ENEMY_FRAGMENT = "BP_BasicEnemyAI"
GEN_TREE_FRAGMENT = "BT_Behavior_P03_G02"

# (name, duration_s, requested distance in cm)
PHASES = (
    ("far_1500", 8.0, 1500.0),
    ("mid_600", 8.0, 600.0),
    ("close_200", 8.0, 200.0),
    ("far_1500_again", 8.0, 1500.0),
)

SETUP_BUDGET = 60.0

# Task properties as compiled into BT_Behavior_P03_G02.
RETREAT_DISTANCE = 1500.0
RETREAT_TOLERANCE = 150.0
ACCEPTANCE_RADIUS = 850.0
ARRIVAL_TOLERANCE = 150.0
ATTACK_RANGE = 1000.0
DECORATOR_LOW = 800.0
DECORATOR_HIGH = 1200.0

RETREAT_REQUIRED = RETREAT_DISTANCE - RETREAT_TOLERANCE
APPROACH_REQUIRED = ACCEPTANCE_RADIUS + ARRIVAL_TOLERANCE

_s = {}


def _reset():
    _s.clear()
    _s.update({
        "handle": None, "done": False, "error": None,
        "world_name": None, "actor": None, "player": None,
        "spawn_loc": None, "spawn_rot": None, "player_z": None, "bb": None,
        "tree_desc": "", "phase": 0, "phase_start": 0.0, "phase_samples": 0,
        "phase_damage": 0.0, "phase_first_damage": None, "phase_last_hp": None,
        "phase_start_xy": None, "phase_goal": None, "just_teleported": False,
        "phase_rows": [], "sample_rows": [], "events": [], "notes": [],
        "started": False, "started_at": "", "wall_start": 0.0,
        "bb_min": None, "bb_max": None,
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


def _find_actor(world, fragment):
    for actor in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor):
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


def _nav_bounds(world):
    for actor in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.RecastNavMesh):
        try:
            origin, extent = actor.get_actor_bounds(False)
            return origin, extent
        except Exception:
            return None, None
    return None, None


def _diagnose_geometry(world, label):
    """Record the retreat goal against the navmesh and the two abort/success gaps."""
    actor = _s["actor"]
    player = _s["player"]
    try:
        self_loc = actor.get_actor_location()
        tgt_loc = player.get_actor_location()
    except Exception as exc:
        _s["notes"].append("%s diag unavailable (%s)" % (label, exc))
        return

    dx = self_loc.x - tgt_loc.x
    dy = self_loc.y - tgt_loc.y
    dz = self_loc.z - tgt_loc.z
    distance = (dx * dx + dy * dy + dz * dz) ** 0.5
    if distance > 0.0:
        ux, uy, uz = dx / distance, dy / distance, dz / distance
    else:
        ux, uy, uz = 0.0, 1.0, 0.0
    gx = self_loc.x + ux * RETREAT_DISTANCE
    gy = self_loc.y + uy * RETREAT_DISTANCE

    origin, extent = _nav_bounds(world)
    inside = None
    if extent is not None:
        x_lo, x_hi = origin.x - extent.x, origin.x + extent.x
        y_lo, y_hi = origin.y - extent.y, origin.y + extent.y
        inside = (x_lo <= gx <= x_hi) and (y_lo <= gy <= y_hi)

    unreal.log("AURA_DIAG %s self=(%.1f, %.1f, %.1f) target=(%.1f, %.1f, %.1f) d=%.1f"
               % (label, self_loc.x, self_loc.y, self_loc.z,
                  tgt_loc.x, tgt_loc.y, tgt_loc.z, distance))
    unreal.log("AURA_DIAG %s away_unit=(%.4f, %.4f, %.4f) retreat_goal=(%.1f, %.1f) "
               "goal_inside_navmesh=%s"
               % (label, ux, uy, uz, gx, gy, inside))
    unreal.log("AURA_DIAG %s RETREAT success_needs_d>=%.1f abort_at_d>=%.1f shortfall=%.1f"
               % (label, RETREAT_REQUIRED, DECORATOR_LOW,
                  RETREAT_REQUIRED - DECORATOR_LOW))
    unreal.log("AURA_DIAG %s APPROACH success_needs_d<=%.1f abort_at_d<=%.1f shortfall=%.1f"
               % (label, APPROACH_REQUIRED, DECORATOR_HIGH,
                  DECORATOR_HIGH - APPROACH_REQUIRED))
    unreal.log("AURA_DIAG %s ATTACK distance_guard=none task_gate=d<=%.1f "
               "dead_band=(%.1f, %.1f] width=%.1f"
               % (label, ATTACK_RANGE, APPROACH_REQUIRED, DECORATOR_HIGH,
                  DECORATOR_HIGH - APPROACH_REQUIRED))
    _s["phase_goal"] = (round(gx, 1), round(gy, 1), inside)


def _begin_session(world):
    _s["world_name"] = world.get_name()
    if _s["world_name"] != EXPECTED_WORLD:
        _s["error"] = ("PIE came up in %r but this probe requires %r"
                       % (_s["world_name"], EXPECTED_WORLD))
        return False
    actor = _find_actor(world, ENEMY_FRAGMENT)
    if actor is None:
        return False
    _s["actor"] = actor
    try:
        asset = actor.get_controller().get_editor_property("BehaviorTreeAsset")
        _s["tree_desc"] = str(asset.get_path_name()) if asset else "none"
    except Exception as exc:
        _s["tree_desc"] = "unreadable (%s)" % exc
    if GEN_TREE_FRAGMENT not in _s["tree_desc"]:
        _s["error"] = ("controller is not running %s - reports %r"
                       % (GEN_TREE_FRAGMENT, _s["tree_desc"]))
        return False
    _s["spawn_loc"] = actor.get_actor_location()
    _s["spawn_rot"] = actor.get_actor_rotation()
    _s["bb"] = _blackboard(actor)

    player = unreal.GameplayStatics.get_player_pawn(world, 0)
    if player is None:
        return False
    _s["player"] = player
    _s["player_z"] = player.get_actor_location().z
    try:
        current = float(player.get_editor_property("CurrentHealth"))
        if current < 100000.0:
            player.set_editor_property("CurrentHealth", 100000.0)
        _s["notes"].append("player_health_at_start=%.1f" % current)
    except Exception:
        _s["notes"].append("player health access failed")

    _s["notes"].append("subject=generated tree=%s" % _s["tree_desc"])
    try:
        _s["notes"].append("enemy_health_start=%.1f max=%.1f" % (
            float(actor.get_editor_property("CurrentHealth")),
            float(actor.get_editor_property("MaxHealth"))))
    except Exception:
        pass
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
    _s["bb_min"] = None
    _s["bb_max"] = None
    _s["phase_goal"] = None

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
        loc = actor.get_actor_location()
        _s["phase_start_xy"] = (round(loc.x, 1), round(loc.y, 1))
    except Exception:
        _s["phase_start_xy"] = None

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
    _s["phase_last_hp"] = health
    unreal.log("AURA_PHASE %s start requested=%.0f health=%.1f"
               % (name, distance, health))
    _diagnose_geometry(world, name)


def _phase_events(name):
    return [e for e in _s["events"] if e["phase"] == name]


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
        end_geo = round(float(actor.get_distance_to(_s["player"])), 1)
    except Exception:
        end_geo = -1.0
    moved = -1.0
    if _s["phase_start_xy"] and end_xy[0] is not None:
        moved = (((end_xy[0] - _s["phase_start_xy"][0]) ** 2
                  + (end_xy[1] - _s["phase_start_xy"][1]) ** 2) ** 0.5)

    events = _phase_events(name)
    geo = [e["geo"] for e in events if e["geo"] >= 0.0]
    goal = _s["phase_goal"] or ("", "", "")
    in_dead_band = 1 if (0.0 < end_geo <= DECORATOR_HIGH
                         and end_geo > APPROACH_REQUIRED) else 0

    _s["phase_rows"].append([
        RUN_ID, name, "%.0f" % distance, "%.1f" % duration, _s["phase_samples"],
        "%.1f" % (_s["phase_samples"] / duration if duration else 0.0),
        len(events), "%.1f" % _s["phase_damage"],
        "%.1f" % (max(geo) if geo else -1.0),
        "%.1f" % (min(geo) if geo else -1.0),
        "%.3f" % (_s["phase_first_damage"]
                  if _s["phase_first_damage"] is not None else -1.0),
        "%.1f" % moved,
        ("%.1f" % _s["phase_start_xy"][1]) if _s["phase_start_xy"] else "",
        ("%.1f" % end_xy[1]) if end_xy[1] is not None else "",
        "%.1f" % end_geo, in_dead_band,
        "%.1f" % (_s["bb_min"] if _s["bb_min"] is not None else -1.0),
        "%.1f" % (_s["bb_max"] if _s["bb_max"] is not None else -1.0),
        goal[0], goal[1], goal[2],
    ])
    unreal.log("AURA_PHASE %s end moved=%.1f damage=%.1f end_geo=%.1f dead_band=%d"
               % (name, moved, _s["phase_damage"], end_geo, in_dead_band))


def _step(world):
    now = time.perf_counter()
    name, duration, distance = PHASES[_s["phase"]]

    if now - _s["phase_start"] >= duration:
        _close_phase()
        if _s["phase"] + 1 < len(PHASES):
            _enter_phase(world, _s["phase"] + 1)
        else:
            _s["done"] = True
        return

    actor = _s["actor"]
    player = _s["player"]
    if actor is None or player is None:
        return

    bb_dist = -1.0
    bb_hp = -1.0
    bb_can = -1
    if _s["bb"] is None:
        _s["bb"] = _blackboard(actor)
    if _s["bb"] is not None:
        try:
            bb_dist = float(_s["bb"].get_value_as_float("DistanceToTarget"))
        except Exception:
            pass
        try:
            bb_hp = float(_s["bb"].get_value_as_float("HealthPercent"))
        except Exception:
            pass
        try:
            bb_can = 1 if _s["bb"].get_value_as_bool("CanAttack") else 0
        except Exception:
            bb_can = -1
    if bb_dist >= 0.0:
        if _s["bb_min"] is None or bb_dist < _s["bb_min"]:
            _s["bb_min"] = bb_dist
        if _s["bb_max"] is None or bb_dist > _s["bb_max"]:
            _s["bb_max"] = bb_dist

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
    try:
        eloc = actor.get_actor_location()
        ex, ey = round(eloc.x, 1), round(eloc.y, 1)
    except Exception:
        ex, ey = -1.0, -1.0

    _s["phase_samples"] += 1
    t_in_phase = now - _s["phase_start"]

    delta = 0.0
    if not _s["just_teleported"] and _s["phase_last_hp"] is not None \
            and health >= 0.0 and health < _s["phase_last_hp"] - 0.001:
        delta = _s["phase_last_hp"] - health
        _s["phase_damage"] += delta
        if _s["phase_first_damage"] is None:
            _s["phase_first_damage"] = t_in_phase
        _s["events"].append({"phase": name, "t_s": round(t_in_phase, 3),
                             "delta": round(delta, 2), "geo": round(geo, 1),
                             "bb": round(bb_dist, 1)})
    _s["phase_last_hp"] = health
    _s["just_teleported"] = False

    _s["sample_rows"].append([
        RUN_ID, name, "%.3f" % t_in_phase, "%.1f" % geo, "%.1f" % bb_dist,
        "%.3f" % bb_hp, bb_can, "%.1f" % health, "%.1f" % enemy_hp,
        ex, ey, "%.2f" % delta])


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
            if _begin_session(world):
                _s["started"] = True
                return
            if _s["error"] is None and now - _s["wall_start"] > SETUP_BUDGET:
                _s["error"] = ("subject not resolvable within %.0f s "
                               "(no BP_BasicEnemyAI or no player pawn in %r)"
                               % (SETUP_BUDGET, _s.get("world_name")))
                _finish()
                return
            if _s["error"] is not None:
                _finish()
            return
        _step(world)
        if _s["done"]:
            _finish()
    except Exception:
        _s["error"] = traceback.format_exc()
        _finish()


def _finish():
    out = _out_dir()
    phase_header = ["run_id", "phase", "requested_cm", "duration_s", "samples",
                    "sample_rate_hz", "damage_events", "damage_total",
                    "max_geo_at_damage_cm", "min_geo_at_damage_cm",
                    "first_damage_s", "enemy_moved_cm", "enemy_start_y",
                    "enemy_end_y", "enemy_end_geo_cm", "end_in_dead_band",
                    "bb_dist_min", "bb_dist_max",
                    "retreat_goal_x", "retreat_goal_y", "retreat_goal_inside_navmesh"]
    sample_header = ["run_id", "phase", "t_s", "geo_cm", "bb_cm",
                     "bb_health_percent", "bb_can_attack", "player_hp", "enemy_hp",
                     "enemy_x", "enemy_y", "delta"]
    try:
        _write_csv(os.path.join(out, "%s_phases.csv" % OUTPUT_PREFIX),
                   phase_header, _s["phase_rows"])
        _write_csv(os.path.join(out, "%s_samples.csv" % OUTPUT_PREFIX),
                   sample_header, _s["sample_rows"])
    except Exception:
        pass

    notes = list(_s["notes"])
    if _s["error"]:
        notes.append("ERROR: %s" % _s["error"])
    try:
        with open(os.path.join(out, "%s_session.txt" % OUTPUT_PREFIX), "w") as handle:
            handle.write("run_id=%s\n" % RUN_ID)
            handle.write("phase_rows=%d events=%d samples=%d done=%s\n" % (
                len(_s["phase_rows"]), len(_s["events"]),
                len(_s["sample_rows"]), _s["done"]))
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


def start():
    if _s.get("handle") is not None:
        return "a probe session is already registered"
    editor = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if editor.is_in_play_in_editor():
        return "REFUSED: PIE already active"
    _reset()
    _s["started_at"] = time.strftime("%Y.%m.%d-%H.%M.%S")
    _s["wall_start"] = time.perf_counter()
    print("probe started_at=%s" % _s["started_at"])
    try:
        _s["handle"] = unreal.register_slate_post_tick_callback(_tick)
    except Exception as exc:
        return "could not register tick callback: %s" % exc
    try:
        editor.editor_request_begin_play()
    except Exception as exc:
        return "begin_play failed: %s" % exc
    total = sum(p[1] for p in PHASES)
    return "probe started phases=%d total_s=%.0f" % (len(PHASES), total)


def status():
    index = _s.get("phase", 0)
    if not isinstance(index, int) or index < 0 or index >= len(PHASES):
        label = "done" if _s.get("done") else "idle"
    else:
        label = PHASES[index][0]
    return ("running=%s done=%s error=%s phase=%s world=%s phase_rows=%d samples=%d"
            % (_s.get("handle") is not None, bool(_s.get("done")),
               bool(_s.get("error")), label, _s.get("world_name"),
               len(_s.get("phase_rows") or []), len(_s.get("sample_rows") or [])))
