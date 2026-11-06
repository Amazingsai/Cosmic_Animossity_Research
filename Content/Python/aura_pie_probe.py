"""Scripted PIE probe for the BT distance-decorator milestone.

Drives one Play-In-Editor session through three distance phases and records,
every editor frame:
  * the enemy Behaviour Tree's blackboard DistanceToTarget value
  * the geometric enemy->player distance
  * the player's CurrentHealth (damage events are derived from its decreases)
  * projectile spawns (each BTTask_EnemyAttack execution calls FireAtTarget,
    which spawns at most one BP_Projectile)
  * whether the enemy's BehaviorTreeComponent is still running

Phases (wall clock seconds from the moment the enemy actor is found):
  A_move_from_3000  10.0 s  player teleported to ~3000 cm and the enemy walks in
  B_in_600           6.0 s  player teleported to 600 cm from the enemy's CURRENT position

Actors are located by CLASS NAME FRAGMENT rather than by loading a class asset:
during PIE, unreal.EditorAssetLibrary asset-registry queries return None, which
made an earlier revision never resolve the enemy.

The module is loaded from disk so its globals survive; inline Aura scripts lose
their namespace once the call returns, which breaks long-lived tick callbacks.

Results are written to Saved/aura_pie_probe_report.txt when the run completes, and
progress to Saved/aura_pie_probe_status.txt while it runs.
"""

import os
import time
import traceback

import unreal

ENEMY_CLASS_FRAGMENT = "BP_BasicEnemyAI"
PROJECTILE_CLASS_FRAGMENT = "BP_Projectile"
BB_KEY = "DistanceToTarget"

# Offsets are added to the enemy's location. Both land inside the 4000x4000 cm
# SM_Floor (x,y in +/-2000) that the enemy stands on at (0, 600, 120).
PHASES = (
    ("A_move_from_3000", 10.0),
    ("B_in_600", 6.0),
)
OFFSET_600 = (0.0, -600.0, 0.0)
OFFSET_3000 = (-1580.0, -2550.0, 0.0)

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
        "t0": 0.0,
        "phase_idx": 0,
        "phase_start": 0.0,
        "last_hp": None,
        "seen_proj": set(),
        "last_alive": 0,
        "alive_max": 0,
        "teleported_seen": set(),
        "samples": [],
        "shots": [],
        "damage": [],
        "teleports": [],
        "notes": [],
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


def _projectiles(world):
    found = []
    for actor in _all_actors(world):
        try:
            if PROJECTILE_CLASS_FRAGMENT in actor.get_class().get_name():
                found.append(actor)
        except Exception:
            continue
    return found


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


def _bt_running(enemy):
    try:
        controller = enemy.get_controller()
        brain = controller.get_editor_property("BrainComponent")
        if brain is None:
            return -1
        return 1 if brain.is_running() else 0
    except Exception:
        return -1


def _begin_session(world):
    _s["world_name"] = world.get_name()
    enemy = _find_by_class_fragment(world, ENEMY_CLASS_FRAGMENT)
    if enemy is None:
        return
    _s["enemy"] = enemy
    _s["bb"] = _blackboard(enemy)
    _s["t0"] = time.perf_counter()
    _s["phase_start"] = _s["t0"]
    _s["last_alive"] = len(_projectiles(world))
    _s["alive_max"] = _s["last_alive"]
    loc = enemy.get_actor_location()
    _s["notes"].append("world=%s enemy=%s class=%s loc=(%.1f, %.1f, %.1f)" % (
        _s["world_name"], enemy.get_actor_label(),
        enemy.get_class().get_name(), loc.x, loc.y, loc.z))
    _s["notes"].append("blackboard_resolved=%s" % (_s["bb"] is not None))

    player = unreal.GameplayStatics.get_player_pawn(world, 0)
    if player is None:
        _s["notes"].append("player pawn missing at session start")
        return
    try:
        health = float(player.get_editor_property("CurrentHealth"))
        _s["notes"].append("player_health_at_start=%.1f" % health)
        if health < 100000.0:
            player.set_editor_property("CurrentHealth", 100000.0)
            _s["notes"].append(
                "player_health_raised_to=100000.0 so a death mid-run cannot travel the level")
    except Exception:
        _s["notes"].append("player health access failed: %s" %
                           traceback.format_exc(limit=1).replace("\n", " "))


def _teleport_for(world, phase, now):
    player = unreal.GameplayStatics.get_player_pawn(world, 0)
    if player is None:
        _s["notes"].append("teleport %s skipped: no player pawn" % phase)
        return
    base = _s["enemy"].get_actor_location()
    offset = OFFSET_3000 if "3000" in phase else OFFSET_600
    target = unreal.Vector(base.x + offset[0], base.y + offset[1], base.z + offset[2])
    try:
        player.modify()
    except Exception:
        pass
    moved = False
    try:
        moved = bool(player.set_actor_location(target, False, True))
    except Exception as exc:
        _s["notes"].append("teleport %s raised %s" % (phase, exc))
    _s["teleports"].append({
        "phase": phase,
        "t": round(now - _s["t0"], 3),
        "target": "(%.0f, %.0f, %.0f)" % (target.x, target.y, target.z),
        "moved": moved,
    })


def _step(world):
    now = time.perf_counter()
    if _s["phase_idx"] >= len(PHASES):
        _s["done"] = True
        return

    current_world = world.get_name()
    if _s["world_name"] is not None and current_world != _s["world_name"]:
        _s["error"] = ("game world changed mid-run: %s -> %s (level travel aborted the session)"
                       % (_s["world_name"], current_world))
        return

    name, duration = PHASES[_s["phase_idx"]]
    if now - _s["phase_start"] >= duration:
        _s["phase_idx"] += 1
        _s["phase_start"] = now
        if _s["phase_idx"] >= len(PHASES):
            _s["done"] = True
            return
        name, duration = PHASES[_s["phase_idx"]]

    if name not in _s["teleported_seen"]:
        _teleport_for(world, name, now)
        _s["teleported_seen"].add(name)

    enemy = _s["enemy"]
    if _s["bb"] is None:
        _s["bb"] = _blackboard(enemy)
    player = unreal.GameplayStatics.get_player_pawn(world, 0)

    distance = -1.0
    if _s["bb"] is not None:
        try:
            distance = float(_s["bb"].get_value_as_float(BB_KEY))
        except Exception:
            distance = -1.0

    health = -1.0
    if player is not None:
        try:
            health = float(player.get_editor_property("CurrentHealth"))
        except Exception:
            health = -1.0

    geometric = -1.0
    if player is not None:
        try:
            geometric = float(enemy.get_distance_to(player))
        except Exception:
            geometric = -1.0

    enemy_loc = (-1.0, -1.0, -1.0)
    if enemy is not None:
        try:
            el = enemy.get_actor_location()
            enemy_loc = (round(el.x, 1), round(el.y, 1), round(el.z, 1))
        except Exception:
            pass

    running = _bt_running(enemy)
    elapsed = round(now - _s["t0"], 3)
    _s["samples"].append((elapsed, name, round(distance, 2), round(health, 2),
                          round(geometric, 2), running, enemy_loc))

    previous = _s["last_hp"]
    if previous is not None and health >= 0.0 and health < previous - 0.001:
        _s["damage"].append({"t": elapsed, "phase": name,
                             "hp": round(health, 2),
                             "delta": round(previous - health, 2)})
    _s["last_hp"] = health

    # Shots are counted as increases in the number of live projectile actors.
    # Unreal recycles actor names, so name-based dedupe silently dropped every
    # projectile that reused a destroyed one's name.
    alive_n = len(_projectiles(world))
    if alive_n > _s["last_alive"]:
        for _unused in range(alive_n - _s["last_alive"]):
            _s["shots"].append({"t": elapsed, "phase": name})
    _s["last_alive"] = alive_n
    if alive_n > _s["alive_max"]:
        _s["alive_max"] = alive_n


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
    if _s["wall_start"]:
        elapsed = time.perf_counter() - _s["wall_start"]
    phase = PHASES[_s["phase_idx"]][0] if _s["phase_idx"] < len(PHASES) else "done"
    return ("probe running=%s done=%s error=%s phase=%s elapsed=%.1f s "
            "samples=%d shots=%d damage=%d world=%s world_null_ticks=%d") % (
        _s["handle"] is not None, _s["done"], bool(_s["error"]), phase, elapsed,
        len(_s["samples"]), len(_s["shots"]), len(_s["damage"]),
        _s["world_name"], _s["world_null_ticks"])


def _write_status():
    now = time.perf_counter()
    if now - _s["last_status"] < 0.4:
        return
    _s["last_status"] = now
    try:
        with open(_saved_file("aura_pie_probe_status.txt"), "w") as fh:
            fh.write(status() + "\n")
    except Exception:
        pass


def _phase_line(name, duration):
    rows = [r for r in _s["samples"] if r[1] == name]
    if not rows:
        return "%s: NO SAMPLES (duration %.1f s)" % (name, duration)
    distances = [r[2] for r in rows if r[2] >= 0.0]
    geometric = [r[4] for r in rows if r[4] >= 0.0]
    run_flags = [r[5] for r in rows]
    healths = [r[3] for r in rows if r[3] >= 0.0]
    shots = [x for x in _s["shots"] if x["phase"] == name]
    damage = [x for x in _s["damage"] if x["phase"] == name]

    def mean(values):
        return sum(values) / len(values) if values else -1.0

    line = ("%-12s frames=%-4d bb_dist min/mean/max=%7.1f/%7.1f/%7.1f  "
            "geo_dist_mean=%7.1f  bt_running=%d/%d  hp_first/last=%s/%s  "
            "shots=%d  damage_events=%d  damage_total=%.1f  alive_max=%d") % (
        name, len(rows),
        min(distances) if distances else -1.0, mean(distances),
        max(distances) if distances else -1.0,
        mean(geometric),
        sum(1 for f in run_flags if f == 1), len(run_flags),
        ("%.1f" % healths[0]) if healths else "n/a",
        ("%.1f" % healths[-1]) if healths else "n/a",
        len(shots), len(damage), sum(x["delta"] for x in damage),
        _s["alive_max"])
    detail = []
    # Use the first and last rows that actually captured a location: a single
    # failed get_actor_location() on an edge frame must not drop the measurement.
    locs = [r[6] for r in rows if r[6][0] >= 0.0]
    if len(locs) >= 2:
        start_loc = locs[0]
        end_loc = locs[-1]
        displacement = ((end_loc[0] - start_loc[0]) ** 2 +
                        (end_loc[1] - start_loc[1]) ** 2) ** 0.5
        detail.append(
            "      enemy_move from=(%.0f, %.0f) to=(%.0f, %.0f) displacement=%.0f cm (locs=%d/%d)"
            % (start_loc[0], start_loc[1], end_loc[0], end_loc[1], displacement,
               len(locs), len(rows)))
    if shots:
        detail.append("      shot_times=%s" % [x["t"] for x in shots])
    if damage:
        detail.append("      damage_times=%s" % [x["t"] for x in damage])
    return line + ("\n" + "\n".join(detail) if detail else "")


def _build_report():
    lines = ["=== aura_pie_probe report ==="]
    if _s["error"]:
        lines.append("PROBE ERROR:\n%s" % _s["error"])
    lines.extend(_s["notes"])
    for entry in _s["teleports"]:
        lines.append("teleport %-12s at t=%.3f s target=%s moved=%s" % (
            entry["phase"], entry["t"], entry["target"], entry["moved"]))

    for name, duration in PHASES:
        lines.append(_phase_line(name, duration))

    # Response times: teleport -> first/last shot, teleport -> first damage.
    for entry in _s["teleports"]:
        phase = entry["phase"]
        start_t = entry["t"]
        shots = [x["t"] for x in _s["shots"] if x["phase"] == phase]
        damage = [x["t"] for x in _s["damage"] if x["phase"] == phase]
        parts = []
        if shots:
            parts.append("first_shot=+%.3f s" % (min(shots) - start_t))
            parts.append("shots_in_phase=%d" % len(shots))
        else:
            parts.append("no shots")
        if damage:
            parts.append("first_damage=+%.3f s" % (min(damage) - start_t))
            parts.append("last_damage=+%.3f s" % (max(damage) - start_t))
        lines.append("latency %-12s %s" % (phase, "  ".join(parts)))

    # Cadence between consecutive shots across the whole run.
    times = [x["t"] for x in _s["shots"]]
    gaps = [round(times[i + 1] - times[i], 3) for i in range(len(times) - 1)]
    if gaps:
        lines.append("shot_count=%d  gaps=%s" % (len(times), gaps))

    lines.append("total_samples=%d  done=%s" % (len(_s["samples"]), _s["done"]))
    return "\n".join(lines)


def _finish():
    try:
        text = _build_report()
    except Exception:
        text = "report build failed:\n%s" % traceback.format_exc()
    try:
        with open(_saved_file("aura_pie_probe_report.txt"), "w") as fh:
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
