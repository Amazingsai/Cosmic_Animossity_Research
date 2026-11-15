"""G1 diagnostic: is the behaviour tree executing, and does the leaf task tick?

The G1 control run (`G1GUARD`, tree `BT_Test_Decorator_Guard250`) moved 0.0 cm in
all four phases, *including* `close_200` where the leaf decorator `DistanceToTarget
< 250` must be TRUE. A zero displacement there is ambiguous between three very
different causes:

  1. the behaviour tree is not running at all in the session,
  2. the tree runs but the decorated `move_away` task is gated off in every phase,
  3. the task runs but the pawn never accepts a move request.

Neither the phase CSV nor the game log separates them: `BTDecorator_Blackboard`
prints nothing, and `BTTask_EnemyMoveAwayFromTarget` prints nothing either. This
module therefore samples the two runtime observables that do separate them, every
editor frame, alongside the same geometric and blackboard values the gameplay probe
records:

  * `controller.BrainComponent.is_running()` -- 1 while a behaviour tree is
    executing on the controller, 0 when none is,
  * `controller.get_move_status()` -- `Moving` only while a move request the tree
    issued is actually being followed.

Reading only. No asset is modified, no tree is swapped, and the controller keeps
whatever tree it is currently pointed at (reported in the session file so the run
is self-identifying).

Two phases: `far_1500` (decorator FALSE, 6 s) then `close_200` (decorator TRUE,
8 s). The second phase is the positive control; a task that is gated correctly
must move the pawn there and only there.
"""

import os
import time
import traceback

import unreal

EXPECTED_WORLD = "Lvl_Research_Trial"
ENEMY_FRAGMENT = "BP_BasicEnemyAI"
PHASES = (
    ("far_1500", 6.0, 1500.0),
    ("close_200", 8.0, 200.0),
)
SETUP_BUDGET = 60.0

_s = {}


def _reset():
    _s.clear()
    _s.update({
        "handle": None, "done": False, "error": None, "started": False,
        "world_name": None, "actor": None, "controller": None, "player": None,
        "brain": None, "bb": None, "tree_desc": "", "spawn_loc": None,
        "spawn_rot": None, "player_z": None, "notes": [],
        "phase": 0, "phase_start": 0.0, "phase_rows": [], "rows": [],
        "wall_start": 0.0, "started_at": "",
        "phase_samples": 0, "phase_brain_on": 0, "phase_moving": 0,
        "phase_start_xy": None, "phase_max_disp": 0.0,
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


def _begin_session(world):
    _s["world_name"] = world.get_name()
    if _s["world_name"] != EXPECTED_WORLD:
        _s["error"] = "PIE came up in %r but this diagnostic requires %r" % (
            _s["world_name"], EXPECTED_WORLD)
        return False
    actor = _find_actor(world, ENEMY_FRAGMENT)
    if actor is None:
        return False
    _s["actor"] = actor
    try:
        controller = actor.get_controller()
    except Exception:
        controller = None
    _s["controller"] = controller
    if controller is None:
        _s["error"] = "enemy has no AI controller"
        return False
    try:
        asset = controller.get_editor_property("BehaviorTreeAsset")
        _s["tree_desc"] = str(asset.get_path_name()) if asset else "none"
    except Exception as exc:
        _s["tree_desc"] = "unreadable (%s)" % exc
    try:
        _s["brain"] = controller.get_editor_property("BrainComponent")
    except Exception:
        _s["brain"] = None
    try:
        _s["bb"] = controller.get_editor_property("Blackboard")
    except Exception:
        _s["bb"] = None
    _s["spawn_loc"] = actor.get_actor_location()
    _s["spawn_rot"] = actor.get_actor_rotation()
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
    _s["notes"].append("tree_reported_by_controller=%s" % _s["tree_desc"])
    _s["notes"].append("brain_component=%s" % (
        _s["brain"].get_class().get_name() if _s["brain"] else "None"))
    _enter_phase(world, 0)
    return True


def _enter_phase(world, index):
    name, duration, distance = PHASES[index]
    _s["phase"] = index
    _s["phase_start"] = time.perf_counter()
    _s["phase_samples"] = 0
    _s["phase_brain_on"] = 0
    _s["phase_moving"] = 0
    _s["phase_max_disp"] = 0.0
    actor = _s["actor"]
    try:
        actor.modify()
        if _s["spawn_loc"] is not None:
            actor.set_actor_location(_s["spawn_loc"], False, True)
        if _s["spawn_rot"] is not None:
            actor.set_actor_rotation(_s["spawn_rot"], False)
    except Exception as exc:
        _s["notes"].append("phase %s reset raised %s" % (name, exc))
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
        brain_on = 1 if (_s["brain"] is not None and _s["brain"].is_running()) else 0
    except Exception:
        brain_on = -1
    unreal.log("G1DIAG phase %s start requested=%.0f brain_running=%d"
               % (name, distance, brain_on))


def _close_phase():
    name, duration, distance = PHASES[_s["phase"]]
    _s["phase_rows"].append([
        name, "%.0f" % distance, "%.1f" % duration,
        _s["phase_samples"], _s["phase_brain_on"], _s["phase_moving"],
        "%.1f" % _s["phase_max_disp"],
        ("%.1f" % _s["phase_start_xy"][1]) if _s["phase_start_xy"] else "",
    ])
    unreal.log("G1DIAG phase %s end samples=%d brain_on=%d moving=%d max_disp=%.1f"
               % (name, _s["phase_samples"], _s["phase_brain_on"],
                  _s["phase_moving"], _s["phase_max_disp"]))


def _move_status():
    try:
        return str(_s["controller"].get_move_status())
    except Exception:
        return "n/a"


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
    t_in_phase = now - _s["phase_start"]
    brain_on = -1
    try:
        brain_on = 1 if (_s["brain"] is not None and _s["brain"].is_running()) else 0
    except Exception:
        brain_on = -1
    status = _move_status()
    bb_dist = -1.0
    if _s["bb"] is not None:
        try:
            bb_dist = float(_s["bb"].get_value_as_float("DistanceToTarget"))
        except Exception:
            pass
    try:
        geo = float(actor.get_distance_to(_s["player"]))
    except Exception:
        geo = -1.0
    try:
        loc = actor.get_actor_location()
        ex, ey = round(loc.x, 1), round(loc.y, 1)
    except Exception:
        ex, ey = -1.0, -1.0
    disp = -1.0
    if _s["phase_start_xy"] and ex != -1.0:
        disp = (((ex - _s["phase_start_xy"][0]) ** 2
                 + (ey - _s["phase_start_xy"][1]) ** 2) ** 0.5)
        if disp > _s["phase_max_disp"]:
            _s["phase_max_disp"] = disp
    _s["phase_samples"] += 1
    if brain_on == 1:
        _s["phase_brain_on"] += 1
    if "Moving" in status:
        _s["phase_moving"] += 1
    _s["rows"].append([
        name, "%.3f" % t_in_phase, brain_on, status, "%.1f" % bb_dist,
        "%.1f" % geo, ex, ey, "%.1f" % disp,
    ])


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
                _s["error"] = "subject not resolvable within %.0f s" % SETUP_BUDGET
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
    header = ["phase", "t_s", "brain_running", "move_status", "bb_cm",
              "geo_cm", "enemy_x", "enemy_y", "disp_cm"]
    try:
        _write_csv(os.path.join(out, "G1DIAG_samples.csv"), header, _s["rows"])
    except Exception:
        pass
    notes = list(_s["notes"])
    if _s["error"]:
        notes.append("ERROR: %s" % _s["error"])
    try:
        with open(os.path.join(out, "G1DIAG_session.txt"), "w") as handle:
            handle.write("started_at=%s finished_at=%s\n"
                         % (_s.get("started_at", ""),
                            time.strftime("%Y.%m.%d-%H.%M.%S")))
            handle.write("phases=%s\n" % [p[0] for p in PHASES])
            handle.write("samples=%d\n" % len(_s["rows"]))
            for row in _s["phase_rows"]:
                handle.write("phase_row=%s\n" % row)
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
        return "a diagnostic session is already registered"
    editor = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if editor.is_in_play_in_editor():
        return "REFUSED: PIE already active"
    _reset()
    _s["started_at"] = time.strftime("%Y.%m.%d-%H.%M.%S")
    _s["wall_start"] = time.perf_counter()
    try:
        _s["handle"] = unreal.register_slate_post_tick_callback(_tick)
    except Exception as exc:
        return "could not register tick callback: %s" % exc
    try:
        editor.editor_request_begin_play()
    except Exception as exc:
        return "begin_play failed: %s" % exc
    return "diagnostic started phases=%d total_s=%.0f" % (
        len(PHASES), sum(p[1] for p in PHASES))


def status():
    index = _s.get("phase", 0)
    label = PHASES[index][0] if isinstance(index, int) and 0 <= index < len(PHASES) else "done"
    return ("running=%s done=%s error=%s phase=%s tree=%s rows=%d"
            % (_s.get("handle") is not None, bool(_s.get("done")),
               bool(_s.get("error")), label, _s.get("tree_desc"), len(_s.get("rows") or [])))
