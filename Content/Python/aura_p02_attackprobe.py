"""Attack-branch reachability probe for candidate #2 (round2/P02-G01).

Question this answers, and why it needs its own run:

  n4_Sequence is  seq[ n5_MoveToTarget (DistanceToTarget > 800),
                      n6_Attack       (DistanceToTarget <= 800) ]

  The two child conditions are mutually exclusive, so n6 can only be entered on the
  one execution pass in which n5 returns SUCCESS and the sequence advances to its
  next child.  Whether that moment ever actually happens cannot be read from damage:
  BTTask_EnemyAttack contains its own `DistanceToTarget <= AttackRange` gate, and
  requirement #8 forbids citing that in-task gate as evidence about the tree.

  So this run is made unambiguous by setting n6_Attack's AttackRange to -1 for the
  duration: the in-task gate then refuses unconditionally and prints
  "BTTask_EnemyAttack: out of range - FAILURE" every single time the node executes,
  at any distance.  Counting those lines answers exactly one question - was n6 ever
  reached?  It fires nothing, so it cannot contaminate anything.

  The node property is restored to the faithful 800 immediately afterwards and the
  compiled tree is re-verified.

Single healthy phase at 1500 cm, where n5 is enabled and the enemy closes.
"""

import os
import time
import traceback

import unreal

EXPECTED_WORLD = "Lvl_Research_Trial"
RUN_ID = "p7p02_attackprobe"
ENEMY_FRAGMENT = "BP_BasicEnemyAI"
TREE_FRAGMENT = "BT_Behavior_P02_G01"
PHASE_SECONDS = 14.0
PLAYER_DISTANCE = 1500.0
SETUP_BUDGET = 60.0

_s = {}


def _reset():
    _s.clear()
    _s.update({"handle": None, "done": False, "error": None, "actor": None,
               "spawn_loc": None, "spawn_rot": None, "player": None, "player_z": 0.0,
               "bb": None, "tree_desc": "", "phase_start": 0.0, "samples": 0,
               "rows": [], "notes": [], "started": False, "wall_start": 0.0})


def _project_dir():
    base = unreal.Paths.convert_relative_path_to_full(
        unreal.Paths.project_dir().replace("\\", "/")).replace("\\", "/")
    return base if base.endswith("/") else base + "/"


def _world():
    return unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()


def _blackboard(actor):
    try:
        controller = actor.get_controller()
        return controller.get_editor_property("Blackboard") if controller else None
    except Exception:
        return None


def _prepare(world):
    for actor in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor):
        try:
            if ENEMY_FRAGMENT in actor.get_class().get_name():
                _s["actor"] = actor
                break
        except Exception:
            continue
    if _s["actor"] is None:
        _s["error"] = "no experimental enemy in the PIE world"
        return False
    _s["spawn_loc"] = _s["actor"].get_actor_location()
    _s["spawn_rot"] = _s["actor"].get_actor_rotation()
    try:
        asset = _s["actor"].get_controller().get_editor_property("BehaviorTreeAsset")
        _s["tree_desc"] = str(asset.get_path_name()) if asset else "none"
    except Exception as exc:
        _s["tree_desc"] = "unreadable (%s)" % exc
    if TREE_FRAGMENT not in _s["tree_desc"]:
        _s["error"] = "controller reports %r, expected %s" % (_s["tree_desc"], TREE_FRAGMENT)
        return False
    _s["bb"] = _blackboard(_s["actor"])
    _s["player"] = unreal.GameplayStatics.get_player_pawn(world, 0)
    if _s["player"] is None:
        _s["error"] = "no player pawn"
        return False
    try:
        _s["player"].set_editor_property("CurrentHealth", 100000.0)
    except Exception:
        pass
    _s["player_z"] = _s["player"].get_actor_location().z
    _s["notes"].append("tree=%s" % _s["tree_desc"])
    _s["notes"].append("player_health=%.1f" % float(
        _s["player"].get_editor_property("CurrentHealth")))
    return True


def _enter_phase():
    _s["phase_start"] = time.perf_counter()
    _s["samples"] = 0
    target = unreal.Vector(_s["spawn_loc"].x,
                           _s["spawn_loc"].y - PLAYER_DISTANCE,
                           _s["player_z"])
    try:
        _s["player"].modify()
        _s["player"].set_actor_location(target, False, True)
    except Exception as exc:
        _s["notes"].append("player teleport raised %s" % exc)


def _step():
    now = time.perf_counter()
    elapsed = now - _s["phase_start"]
    if elapsed >= PHASE_SECONDS:
        _s["done"] = True
        return
    actor = _s["actor"]
    player = _s["player"]
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
    try:
        geo = float(actor.get_distance_to(player))
    except Exception:
        geo = -1.0
    try:
        health = float(player.get_editor_property("CurrentHealth"))
    except Exception:
        health = -1.0
    try:
        loc = actor.get_actor_location()
        enemy_y = round(loc.y, 1)
    except Exception:
        enemy_y = None
    _s["samples"] += 1
    _s["rows"].append(["%.3f" % elapsed, "%.3f" % bb_hp, "%.1f" % bb_dist,
                       "%.1f" % geo, "%.1f" % health, enemy_y])


def _finish():
    out = os.path.join(_project_dir(), "results", "gameplay")
    if not os.path.isdir(out):
        os.makedirs(out)
    header = ["t_s", "bb_hp", "bb_dist_cm", "geo_cm", "player_hp", "enemy_y"]
    try:
        lines = [",".join([RUN_ID] + header)]
        for row in _s["rows"]:
            lines.append(",".join(str(v) for v in row))
        with open(os.path.join(out, "P02ATTACK_probe_samples.csv"), "w") as handle:
            handle.write("\n".join(lines) + "\n")
        with open(os.path.join(out, "P02ATTACK_probe_session.txt"), "w") as handle:
            handle.write("run_id=%s samples=%d done=%s\n" % (
                RUN_ID, len(_s["rows"]), _s["done"]))
            handle.write("finished_at=%s\n" % time.strftime("%Y.%m.%d-%H.%M.%S"))
            handle.write("started_at=%s\n" % _s.get("started_at", ""))
            if _s["error"]:
                handle.write("ERROR: %s\n" % _s["error"])
            for note in _s["notes"]:
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


def _tick(_delta):
    if _s.get("done") or _s.get("error"):
        return
    try:
        now = time.perf_counter()
        world = _world()
        if world is None:
            if now - _s["wall_start"] > SETUP_BUDGET:
                _s["error"] = "no game world within %.0f s" % SETUP_BUDGET
                _finish()
            return
        if not _s["started"]:
            if world.get_name() != EXPECTED_WORLD:
                _s["error"] = "PIE came up in %r" % world.get_name()
                _finish()
                return
            if not _prepare(world):
                _finish()
                return
            _enter_phase()
            _s["started"] = True
            return
        _step()
        if _s["done"]:
            _finish()
    except Exception:
        _s["error"] = traceback.format_exc()
        _finish()


def start():
    editor = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if editor.is_in_play_in_editor():
        return "REFUSED: PIE already active"
    _reset()
    _s["started_at"] = time.strftime("%Y.%m.%d-%H.%M.%S")
    print("attackprobe started_at=%s" % _s["started_at"])
    _s["wall_start"] = time.perf_counter()
    _s["handle"] = unreal.register_slate_post_tick_callback(_tick)
    editor.editor_request_begin_play()
    return "attack reachability probe started (%.0f s, healthy, %.0f cm)" % (
        PHASE_SECONDS, PLAYER_DISTANCE)
