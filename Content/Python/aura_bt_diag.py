"""Movement diagnostic for Phase 7 candidate #1 (BT_Behavior_P01_G01).

Answers one question the isolation probe could not: at a 1500 cm standoff the
enemy pawn stayed put while the recorded distance collapsed to ~289 cm, so
something moved. This records, every editor frame, the enemy and player world
locations and velocities alongside the live blackboard DistanceToTarget, so the
mover is identified rather than inferred.

It also guards the probe against a silent wrong-level run: PIE must come up in
EXPECTED_WORLD, otherwise the run aborts immediately and says so. An earlier
attempt measured 25 s of Lvl_FirstPerson after begin_play was requested while a
previous end_play was still tearing down, which produced a report that looked
valid but described a level with no enemy in it.

Loaded as a module (not an inline script) so its globals survive the Aura call
that starts it. Report: Saved/aura_bt_diag.txt.
"""

import os
import time
import traceback

import unreal

EXPECTED_WORLD = "Lvl_Research_Trial"
ENEMY_CLASS_FRAGMENT = "BP_BasicEnemyAI"
TARGET_CM = 1500.0
DURATION = 8.0
BUDGET = 90.0

_s = {}


def _reset():
    _s.clear()
    _s.update({
        "handle": None,
        "done": False,
        "error": None,
        "rows": [],
        "notes": [],
        "enemy": None,
        "player": None,
        "bb": None,
        "spawn": None,
        "player_z": None,
        "t0": 0.0,
        "wall_start": 0.0,
        "started": False,
        "world_name": None,
    })


_reset()


def _saved_file(name):
    base = unreal.Paths.convert_relative_path_to_full(
        unreal.Paths.project_saved_dir().replace("\\", "/")).replace("\\", "/")
    if not base.endswith("/"):
        base = base + "/"
    return os.path.join(base, name)


def _game_world():
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


def _setup(world):
    enemy = _find_by_class_fragment(world, ENEMY_CLASS_FRAGMENT)
    if enemy is None:
        return False
    player = unreal.GameplayStatics.get_player_pawn(world, 0)
    if player is None:
        return False

    _s["enemy"] = enemy
    _s["player"] = player
    try:
        _s["bb"] = unreal.AIBlueprintHelperLibrary.get_blackboard(enemy)
    except Exception:
        _s["bb"] = None

    _s["spawn"] = enemy.get_actor_location()
    ploc = player.get_actor_location()
    _s["player_z"] = ploc.z

    _s["notes"].append(
        "blackboard_resolved=%s enemy=%s player_pawn=%s" % (
            _s["bb"] is not None,
            enemy.get_class().get_name(),
            player.get_class().get_name()))
    _s["notes"].append(
        "enemy_spawn=(%.1f,%.1f,%.1f) player_spawn=(%.1f,%.1f,%.1f)" % (
            _s["spawn"].x, _s["spawn"].y, _s["spawn"].z,
            ploc.x, ploc.y, ploc.z))

    try:
        player.set_editor_property("CurrentHealth", 100000.0)
        _s["notes"].append("player health raised to 100000")
    except Exception:
        _s["notes"].append("player health raise FAILED")

    target = unreal.Vector(_s["spawn"].x, _s["spawn"].y - TARGET_CM, _s["player_z"])
    try:
        player.modify()
        player.set_actor_location(target, False, True)
    except Exception as exc:
        _s["notes"].append("teleport raised %s" % exc)
    after = player.get_actor_location()
    _s["notes"].append(
        "teleport_requested=(%.1f,%.1f,%.1f) actual_after=(%.1f,%.1f,%.1f)" % (
            target.x, target.y, target.z, after.x, after.y, after.z))
    _s["notes"].append(
        "initial_blackboard_or_geo_distance=%.1f" % float(enemy.get_distance_to(player)))
    return True


def _sample():
    enemy = _s["enemy"]
    player = _s["player"]

    bb_dist = -1.0
    if _s["bb"] is not None:
        try:
            bb_dist = float(_s["bb"].get_value_as_float("DistanceToTarget"))
        except Exception:
            bb_dist = -1.0

    el = enemy.get_actor_location()
    pl = player.get_actor_location()
    pv = player.get_velocity()
    ev = enemy.get_velocity()
    geo = float(enemy.get_distance_to(player))

    health = -1.0
    try:
        health = float(player.get_editor_property("CurrentHealth"))
    except Exception:
        health = -1.0

    elapsed = round(time.perf_counter() - _s["t0"], 3)
    _s["rows"].append((
        elapsed, round(bb_dist, 1), round(geo, 1), round(health, 1),
        round(el.x, 1), round(el.y, 1),
        round(pl.x, 1), round(pl.y, 1),
        round(pv.x, 1), round(pv.y, 1),
        round(ev.x, 1), round(ev.y, 1)))


def _tick(_delta_seconds):
    if _s["done"] or _s["error"]:
        return
    try:
        now = time.perf_counter()
        world = _game_world()
        if world is None:
            if now - _s["wall_start"] > BUDGET:
                _s["error"] = "no game world within %.0f s - PIE never started" % BUDGET
                _finish()
            return

        name = world.get_name()
        if not _s["started"]:
            if name != EXPECTED_WORLD:
                _s["error"] = (
                    "PIE came up in %r but this diagnostic requires %r. "
                    "Refusing to measure a level that has no %s actor."
                    % (name, EXPECTED_WORLD, ENEMY_CLASS_FRAGMENT))
                _finish()
                return
            if not _setup(world):
                if now - _s["wall_start"] > BUDGET:
                    _s["error"] = "enemy or player pawn not found in %s" % name
                    _finish()
                return
            _s["world_name"] = name
            _s["started"] = True
            _s["t0"] = now
            return

        if now - _s["t0"] >= DURATION:
            _s["done"] = True
            _finish()
            return

        _sample()
    except Exception:
        _s["error"] = traceback.format_exc()
        _finish()


def _write_report():
    rows = _s["rows"]
    lines = ["=== aura_bt_diag: who moves at %.0f cm ===" % TARGET_CM]
    lines.append("world=%s expected=%s" % (_s["world_name"], EXPECTED_WORLD))
    lines.extend(_s["notes"])
    if _s["error"]:
        lines.append("PROBE ERROR:")
        lines.append(_s["error"])
    lines.append("samples=%d" % len(rows))
    if not rows:
        return "\n".join(lines)

    first = rows[0]
    last = rows[-1]
    enemy_moved = ((last[4] - first[4]) ** 2 + (last[5] - first[5]) ** 2) ** 0.5
    player_moved = ((last[6] - first[6]) ** 2 + (last[7] - first[7]) ** 2) ** 0.5
    span = last[0] - first[0]
    lines.append("")
    lines.append("enemy_moved=%.1f cm   player_moved=%.1f cm" % (enemy_moved, player_moved))
    lines.append("t_span=%.2f s   sample_rate=%.1f Hz" % (span, len(rows) / max(0.001, span)))
    lines.append("bb_min=%.1f bb_max=%.1f   geo_min=%.1f geo_max=%.1f" % (
        min(r[1] for r in rows), max(r[1] for r in rows),
        min(r[2] for r in rows), max(r[2] for r in rows)))
    lines.append("")
    lines.append("--- every 10th sample ---")
    lines.append("   t     bb     geo     hp  | enemy_x enemy_y | player_x player_y | pvel_x pvel_y | evel_x evel_y")
    step = max(1, len(rows) // 10)
    for r in rows[::step]:
        lines.append("%7.3f %7.1f %7.1f %7.1f | %8.1f %8.1f | %8.1f %8.1f | %6.1f %6.1f | %6.1f %6.1f" % (
            r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9], r[10], r[11]))
    return "\n".join(lines)


def _finish():
    try:
        text = _write_report()
    except Exception:
        text = "report build failed:\n%s" % traceback.format_exc()
    try:
        with open(_saved_file("aura_bt_diag.txt"), "w") as handle:
            handle.write(text)
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
    if _s["handle"] is not None:
        return "diag already running"
    _reset()
    _s["wall_start"] = time.perf_counter()
    editor = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if editor.is_in_play_in_editor():
        return "REFUSED: PIE already active; stop it first so the run cannot inherit the wrong level"
    try:
        _s["handle"] = unreal.register_slate_post_tick_callback(_tick)
    except Exception as exc:
        return "could not register tick callback: %s" % exc
    try:
        editor.editor_request_begin_play()
    except Exception as exc:
        return "begin_play failed: %s" % exc
    return "PIE requested; diag registered"


def status():
    return ("running=%s done=%s error=%s world=%s samples=%d" % (
        _s["handle"] is not None, _s["done"], bool(_s["error"]),
        _s["world_name"], len(_s["rows"])))
