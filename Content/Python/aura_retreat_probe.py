"""Focused PIE probe for the BTTask_EnemyMoveAwayFromTarget retreat verification.

One phase only. At session start it:
  1. resolves the enemy by class-name fragment and its AI controller,
  2. records the enemy's start location and the start distance to the player,
  3. teleports the player to 300 cm from the enemy on the +Y side, so the retreat
     direction is -Y and the 1500 cm retreat goal (y = enemy - 1500) stays well
     inside the 4000x4000 cm SM_Floor (x,y in +/-2000),
  4. swaps the running behaviour tree to BT_Behavior_RetreatTest through
     AIController.RunBehaviorTree, so no controller or level asset is edited,
  5. samples blackboard distance, geometric distance, move status, BT-running
     state and the enemy location every editor frame for 10 s.

The tree is swapped at runtime rather than by editing AIController_ResearchEnemy:
the controller asset keeps pointing at BT_Behavior_AttackAlways and nothing about
the approach/attack milestone is disturbed.

Results are written to Saved/aura_retreat_probe_report.txt when the run completes,
and progress to Saved/aura_retreat_probe_status.txt while it runs. The module is
loaded from disk because inline Aura scripts lose their namespace once the call
returns, which breaks long-lived tick callbacks.
"""

import os
import time
import traceback

import unreal

ENEMY_CLASS_FRAGMENT = "BP_BasicEnemyAI"
BB_KEY = "DistanceToTarget"
RETREAT_TREE_PATH = "/Game/Research/AI/BT_Behavior_RetreatTest.BT_Behavior_RetreatTest"
PHASE_DURATION = 12.0
PLAYER_OFFSET = (0.0, 300.0, 0.0)
# Expected value of the retreat node's instance property in BT_Behavior_RetreatTest.
# Deliberately different from the task class default (1500) so the measurement can
# prove the tree node's own value drives the task, not the class default.
RETREAT_DISTANCE = 1800.0

# Wall clock budget for PIE to start and the enemy to appear. PIE startup from a
# backgrounded editor is slow, so this is generous.
PROBE_BUDGET = 90.0

_s = {}
_eds = None


def _saved_file(name):
    base = unreal.Paths.convert_relative_path_to_full(
        unreal.Paths.project_saved_dir().replace("\\", "/")).replace("\\", "/")
    if not base.endswith("/"):
        base = base + "/"
    return os.path.join(base, name)


def _reset():
    _s.clear()
    _s.update({
        "handle": None,
        "done": False,
        "error": None,
        "enemy": None,
        "bb": None,
        "controller": None,
        "t0": 0.0,
        "started": False,
        "samples": [],
        "notes": [],
        "loc_sources": {},
        "swap": None,
        "start_loc": None,
        "start_player_loc": None,
        "wall_start": 0.0,
        "world_name": None,
        "world_null_ticks": 0,
        "last_status": 0.0,
    })


_reset()


def _game_world():
    global _eds
    if _eds is None:
        _eds = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    return _eds.get_game_world()


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


def _blackboard(enemy):
    try:
        bb = unreal.AIBlueprintHelperLibrary.get_blackboard(enemy)
        if bb is not None:
            return bb
    except Exception:
        pass
    try:
        controller = enemy.get_controller()
        if controller is not None:
            return controller.get_editor_property("Blackboard")
    except Exception:
        pass
    return None


def _actor_loc(actor):
    """Location with fallbacks; returns (loc_tuple_or_None, source_label)."""
    try:
        el = actor.get_actor_location()
        return (float(el.x), float(el.y), float(el.z)), "get_actor_location"
    except Exception:
        pass
    try:
        tr = actor.get_actor_transform()
        t = tr.translation
        return (float(t.x), float(t.y), float(t.z)), "get_actor_transform"
    except Exception:
        pass
    try:
        root = actor.get_editor_property("RootComponent")
        w = root.get_world_location()
        return (float(w.x), float(w.y), float(w.z)), "root_component"
    except Exception:
        return None, "none"


def _bt_running(enemy):
    try:
        brain = enemy.get_controller().get_editor_property("BrainComponent")
        if brain is None:
            return -1
        return 1 if brain.is_running() else 0
    except Exception:
        return -1


def _move_status(enemy):
    try:
        status = enemy.get_controller().get_move_status()
        return str(status)
    except Exception:
        return "n/a"


def _begin_session(world):
    _s["world_name"] = world.get_name()
    enemy = _find_by_class_fragment(world, ENEMY_CLASS_FRAGMENT)
    if enemy is None:
        return
    _s["enemy"] = enemy
    _s["bb"] = _blackboard(enemy)
    try:
        _s["controller"] = enemy.get_controller()
    except Exception:
        _s["controller"] = None

    loc, source = _actor_loc(enemy)
    _s["start_loc"] = loc
    _s["notes"].append("world=%s enemy=%s class=%s start_loc=%s (source=%s)" % (
        _s["world_name"], enemy.get_actor_label(), enemy.get_class().get_name(),
        ("(%.1f, %.1f, %.1f)" % loc) if loc else "unavailable", source))
    _s["notes"].append("blackboard_resolved=%s controller=%s" % (
        _s["bb"] is not None, _s["controller"] is not None))

    player = unreal.GameplayStatics.get_player_pawn(world, 0)
    if player is None:
        _s["notes"].append("player pawn missing at session start")
        return

    try:
        player.set_editor_property("CurrentHealth", 100000.0)
    except Exception:
        _s["notes"].append("player health raise failed (harmless: the retreat tree "
                           "contains no attack task)")

    player_loc, _psrc = _actor_loc(player)
    _s["start_player_loc"] = player_loc
    if loc is not None and player_loc is not None:
        start_dist = ((loc[0] - player_loc[0]) ** 2 +
                      (loc[1] - player_loc[1]) ** 2 +
                      (loc[2] - player_loc[2]) ** 2) ** 0.5
        _s["notes"].append("start_distance=%.1f cm (player at (%.1f, %.1f, %.1f))" % (
            start_dist, player_loc[0], player_loc[1], player_loc[2]))

        # Close starting distance: 300 cm, placed on the +Y side of the enemy so
        # the retreat direction is -Y (room from y=600 down to the floor at -2000).
        target = unreal.Vector(loc[0] + PLAYER_OFFSET[0],
                               loc[1] + PLAYER_OFFSET[1],
                               player_loc[2])
        moved = False
        try:
            player.modify()
        except Exception:
            pass
        try:
            moved = bool(player.set_actor_location(target, False, True))
        except Exception:
            _s["notes"].append("teleport raised: %s" %
                               traceback.format_exc(limit=1).replace("\n", " "))
        _s["notes"].append("teleport player to (%.1f, %.1f, %.1f) moved=%s" % (
            target.x, target.y, target.z, moved))
        _s["notes"].append("expected retreat direction=-Y  expected goal y=%.1f "
                           "(node RetreatDistance=%.0f, class default 1500)" %
                           (loc[1] - RETREAT_DISTANCE, RETREAT_DISTANCE))

    _swap_tree()
    _s["t0"] = time.perf_counter()
    _s["started"] = True


def _swap_tree():
    tree = None
    try:
        tree = unreal.load_object(None, RETREAT_TREE_PATH)
    except Exception:
        _s["notes"].append("retreat tree load raised: %s" %
                           traceback.format_exc(limit=1).replace("\n", " "))
    if tree is None:
        _s["swap"] = "load failed for %s" % RETREAT_TREE_PATH
        _s["notes"].append(_s["swap"])
        return
    ok = False
    try:
        ok = bool(_s["controller"].run_behavior_tree(tree))
    except Exception:
        _s["swap"] = "run_behavior_tree raised: %s" % \
            traceback.format_exc(limit=1).replace("\n", " ")
        _s["notes"].append(_s["swap"])
        return
    _s["swap"] = "BT_Behavior_RetreatTest run_behavior_tree=%s" % ok
    _s["notes"].append(_s["swap"])


def _step(world):
    now = time.perf_counter()
    if not _s["started"]:
        return
    elapsed = now - _s["t0"]
    if elapsed >= PHASE_DURATION:
        _s["done"] = True
        return

    enemy = _s["enemy"]
    player = unreal.GameplayStatics.get_player_pawn(world, 0)

    bb_dist = -1.0
    if _s["bb"] is not None:
        try:
            bb_dist = float(_s["bb"].get_value_as_float(BB_KEY))
        except Exception:
            bb_dist = -1.0

    geo_dist = -1.0
    if player is not None:
        try:
            geo_dist = float(enemy.get_distance_to(player))
        except Exception:
            geo_dist = -1.0

    loc, source = _actor_loc(enemy)
    _s["loc_sources"][source] = _s["loc_sources"].get(source, 0) + 1

    _s["samples"].append({
        "t": round(elapsed, 3),
        "bb": round(bb_dist, 2),
        "geo": round(geo_dist, 2),
        "ms": _move_status(enemy),
        "run": _bt_running(enemy),
        "loc": loc,
        "src": source,
    })


def _tick(_delta_seconds):
    if _s["done"] or _s["error"]:
        return
    try:
        now = time.perf_counter()
        world = _game_world()
        if world is None:
            _s["world_null_ticks"] += 1
            _write_status()
            if now - _s["wall_start"] > PROBE_BUDGET:
                _s["error"] = ("no game world within %.0f s - PIE never started"
                               % PROBE_BUDGET)
                _finish()
            return
        if _s["enemy"] is None:
            _begin_session(world)
            _write_status()
            if _s["enemy"] is None and now - _s["wall_start"] > PROBE_BUDGET:
                _s["error"] = ("enemy (class name contains %r) not found in world %s "
                               "within %.0f s" % (ENEMY_CLASS_FRAGMENT,
                                                  world.get_name(), PROBE_BUDGET))
                _finish()
            return
        _step(world)
        _write_status()
        if _s["done"]:
            _finish()
    except Exception:
        _s["error"] = traceback.format_exc()
        _finish()


def start():
    if _s["handle"] is not None:
        return "probe already registered"
    _reset()
    _s["wall_start"] = time.perf_counter()
    try:
        _s["handle"] = unreal.register_slate_post_tick_callback(_tick)
    except Exception as exc:
        return "could not register tick callback: %s" % exc
    editor = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    in_pie = None
    try:
        in_pie = editor.is_in_play_in_editor()
    except Exception:
        in_pie = None
    if in_pie:
        return "PIE already active; probe registered"
    try:
        editor.editor_request_begin_play()
    except Exception as exc:
        return "begin_play failed: %s" % exc
    return "PIE requested; probe registered"


def status():
    elapsed = 0.0
    if _s["t0"]:
        elapsed = time.perf_counter() - _s["t0"]
    return ("probe running=%s done=%s error=%s started=%s elapsed=%.1f s "
            "samples=%d world=%s swap=%s") % (
        _s["handle"] is not None, _s["done"], bool(_s["error"]),
        _s["started"], elapsed, len(_s["samples"]), _s["world_name"],
        _s["swap"])


def _write_status():
    now = time.perf_counter()
    if now - _s["last_status"] < 0.4:
        return
    _s["last_status"] = now
    try:
        with open(_saved_file("aura_retreat_probe_status.txt"), "w") as fh:
            fh.write(status() + "\n")
    except Exception:
        pass


def _fmt_loc(loc):
    if loc is None:
        return "unavailable"
    return "(%.1f, %.1f, %.1f)" % loc


def _build_report():
    lines = ["=== aura_retreat_probe report ==="]
    if _s["error"]:
        lines.append("PROBE ERROR:\n%s" % _s["error"])
    lines.extend(_s["notes"])
    lines.append("loc_sources=%s" % _s["loc_sources"])

    rows = _s["samples"]
    valid = [r for r in rows if r["loc"] is not None]
    lines.append("samples=%d  samples_with_location=%d" % (len(rows), len(valid)))

    if valid:
        start = valid[0]["loc"]
        end = valid[-1]["loc"]
        disp = ((end[0] - start[0]) ** 2 +
                (end[1] - start[1]) ** 2 +
                (end[2] - start[2]) ** 2) ** 0.5
        lines.append("START enemy_loc=%s" % _fmt_loc(start))
        lines.append("END   enemy_loc=%s" % _fmt_loc(end))
        lines.append("enemy_displacement_cm=%.1f" % disp)

    geos = [r["geo"] for r in rows if r["geo"] >= 0.0]
    if geos:
        lines.append("distance_to_player_cm first=%.1f last=%.1f min=%.1f max=%.1f "
                     "change=%+.1f" % (geos[0], geos[-1], min(geos), max(geos),
                                       geos[-1] - geos[0]))
    bbs = [r["bb"] for r in rows if r["bb"] >= 0.0]
    if bbs:
        lines.append("blackboard_distance_cm first=%.1f last=%.1f min=%.1f max=%.1f"
                     % (bbs[0], bbs[-1], min(bbs), max(bbs)))

    statuses = []
    for r in rows:
        if not statuses or statuses[-1] != r["ms"]:
            statuses.append(r["ms"])
    lines.append("move_status_sequence=%s" % statuses)
    lines.append("bt_running_frames=%d/%d" % (
        sum(1 for r in rows if r["run"] == 1), len(rows)))

    # A plateau below the success threshold while the tree still runs is the
    # signature of a navigation failure (path blocked / goal unreachable).
    stalled = 0.0
    stalls = []
    prev = None
    for r in rows:
        if r["geo"] < 0.0:
            continue
        if prev is not None and abs(r["geo"] - prev[1]) < 1.0 and r["run"] == 1:
            stalled += r["t"] - prev[0]
            if stalled >= 1.5:
                stalls.append((prev[0], r["t"], r["geo"]))
        elif prev is not None and abs(r["geo"] - prev[1]) >= 1.0:
            stalled = 0.0
        prev = (r["t"], r["geo"])
    if stalls:
        lines.append("stall_windows (>=1.5 s without distance change while BT runs): %s"
                     % [("t=%.2f..%.2f" % (a, b), "d=%.1f" % d) for a, b, d in stalls])
    else:
        lines.append("stall_windows: none")

    lines.append("")
    lines.append("t      bb_dist  geo_dist  move_status            bt  enemy_loc")
    for r in rows:
        lines.append("%-6.2f %-8.1f %-9.1f %-22s %-3d %s" % (
            r["t"], r["bb"], r["geo"], r["ms"], r["run"], _fmt_loc(r["loc"])))
    return "\n".join(lines)


def _finish():
    try:
        text = _build_report()
    except Exception:
        text = "report build failed:\n%s" % traceback.format_exc()
    try:
        with open(_saved_file("aura_retreat_probe_report.txt"), "w") as fh:
            fh.write(text)
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


def report(force=False):
    if not force and not _s["done"] and not _s["error"]:
        return "PROBE STILL RUNNING - not collecting.\n%s" % status()
    handle = _s["handle"]
    if handle is not None:
        try:
            unreal.unregister_slate_post_tick_callback(handle)
        except Exception:
            pass
        _s["handle"] = None
    text = _build_report()
    try:
        unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).editor_request_end_play()
    except Exception:
        pass
    return text
