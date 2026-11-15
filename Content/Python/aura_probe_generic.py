"""Generic behaviour-tree gameplay probe (Phase 7F, candidate #5 follow-up).

Run 1 (`aura_p03_probe`,  P03PROBE_*)  established geometry and reachability.
Run 2 (`aura_p03_probe2`, P03PROBE2_*)  added per-sample BP_Projectile counting and found
zero projectiles in all four phases, including mid_600 and close_200 where the blackboard
CanAttack key read true on every sample.

Per-sample projectile counting at ~3 Hz can in principle miss a short-lived actor, so this
module adds the decisive, *persistent* observable: the weapon's own `LastFireTime`.
`BP_WeaponBase::FireAt` writes `LastFireTime = GetGameTimeInSeconds()` on every shot that
passes `CanFire`, and the value survives between samples. A phase in which the attack task
executed therefore ends with a strictly larger `LastFireTime` than it started with, whether
or not the projectile was ever sampled.

`BTTask_EnemyAttack` only ever prints when its own gate REFUSES, so a silent attack task is
indistinguishable from a non-executing one by log alone. LastFireTime separates them.

Subjects are selected by `configure()`; nothing in any asset is modified.

  configure("/Game/Research/AI/BT_Behavior_P03_G02", "p7p03g2_probe3", "P03PROBE3")

Project rules honoured: level name asserted; PIE never started while PIE is active; player
health raised so no death truncates a phase; damage not bookkept on a teleport tick; no
time.sleep; no reflection helpers; no asset is modified.
"""

import os
import time
import traceback

import unreal

EXPECTED_WORLD = "Lvl_Research_Trial"
ENEMY_FRAGMENT = "BP_BasicEnemyAI"
PROJECTILE_CLASS_PATH = "/Game/FirstPerson/Blueprints/Weapons/BP_Projectile.BP_Projectile_C"

DEFAULT_PHASES = (
    ("far_1500", 8.0, 1500.0),
    ("mid_600", 8.0, 600.0),
    ("close_200", 8.0, 200.0),
    ("far_1500_again", 8.0, 1500.0),
)

WEAPON_FLOAT_FIELDS = ("Damage", "FireRate", "Range", "Accuracy", "BulletSpeed")

CONFIG = {}
_s = {}


def configure(tree_fragment, run_id, output_prefix, phases=None):
    """Select the subject tree and the output identity for the next start()."""
    CONFIG.clear()
    CONFIG["tree_fragment"] = tree_fragment
    CONFIG["run_id"] = run_id
    CONFIG["prefix"] = output_prefix
    CONFIG["phases"] = tuple(phases) if phases else DEFAULT_PHASES
    return "configured run_id=%s tree=%s phases=%d" % (
        run_id, tree_fragment, len(CONFIG["phases"]))


def _phases():
    return CONFIG.get("phases") or DEFAULT_PHASES


def _reset():
    _s.clear()
    _s.update({
        "handle": None, "done": False, "error": None,
        "world_name": None, "actor": None, "player": None, "weapon": None,
        "spawn_loc": None, "spawn_rot": None, "player_z": None, "bb": None,
        "proj_class": None, "tree_desc": "", "phase": 0, "phase_start": 0.0,
        "phase_samples": 0, "phase_damage": 0.0, "phase_first_damage": None,
        "phase_last_hp": None, "phase_start_xy": None, "just_teleported": False,
        "phase_rows": [], "sample_rows": [], "events": [], "notes": [],
        "started": False, "started_at": "", "wall_start": 0.0,
        "bb_min": None, "bb_max": None, "can_true": 0, "can_samples": 0,
        "proj_max": None, "proj_hit_samples": 0, "proj_seen_total": 0,
        "fire_start": -1.0, "fire_end": -1.0,
        "enemy_hp_start": None, "enemy_hp_end": None,
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


def _last_fire_time():
    weapon = _s["weapon"]
    if weapon is None:
        return -1.0
    try:
        return float(weapon.get_editor_property("LastFireTime"))
    except Exception:
        return -1.0


def _count_projectiles(world):
    if _s["proj_class"] is None:
        return -1
    try:
        found = unreal.GameplayStatics.get_all_actors_of_class(world, _s["proj_class"])
        return len(list(found))
    except Exception:
        return -1


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
    fragment = CONFIG.get("tree_fragment") or ""
    if fragment and fragment not in _s["tree_desc"]:
        _s["error"] = ("controller is not running %s - reports %r"
                       % (fragment, _s["tree_desc"]))
        return False
    _s["spawn_loc"] = actor.get_actor_location()
    _s["spawn_rot"] = actor.get_actor_rotation()
    _s["bb"] = _blackboard(actor)
    _s["proj_class"] = unreal.load_class(None, PROJECTILE_CLASS_PATH)

    try:
        _s["weapon"] = actor.get_editor_property("Weapon")
    except Exception as exc:
        _s["weapon"] = None
        _s["notes"].append("weapon read failed (%s)" % exc)
    weapon = _s["weapon"]
    _s["notes"].append("enemy_weapon=%s" % (
        weapon.get_class().get_name() if weapon else "None"))
    if weapon is not None:
        for field_name in WEAPON_FLOAT_FIELDS:
            try:
                _s["notes"].append("weapon_%s=%s"
                                   % (field_name, weapon.get_editor_property(field_name)))
            except Exception as exc:
                _s["notes"].append("weapon_%s unreadable (%s)" % (field_name, exc))

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
    _s["notes"].append("projectile_class=%s" % (
        _s["proj_class"].get_name() if _s["proj_class"] else "UNRESOLVED"))
    try:
        _s["enemy_hp_start"] = float(actor.get_editor_property("CurrentHealth"))
        _s["notes"].append("enemy_health_start=%.1f max=%.1f" % (
            _s["enemy_hp_start"], float(actor.get_editor_property("MaxHealth"))))
    except Exception:
        pass
    _enter_phase(world, 0)
    return True


def _enter_phase(world, index):
    name, duration, distance = _phases()[index]
    _s["phase"] = index
    _s["phase_start"] = time.perf_counter()
    _s["phase_samples"] = 0
    _s["phase_damage"] = 0.0
    _s["phase_first_damage"] = None
    _s["just_teleported"] = True
    _s["bb_min"] = None
    _s["bb_max"] = None
    _s["can_true"] = 0
    _s["can_samples"] = 0
    _s["proj_max"] = None
    _s["proj_hit_samples"] = 0
    _s["proj_seen_total"] = 0

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
    _s["fire_start"] = _last_fire_time()
    unreal.log("AURA_PHASE %s start requested=%.0f health=%.1f last_fire=%.3f"
               % (name, distance, health, _s["fire_start"]))


def _close_phase():
    name, duration, distance = _phases()[_s["phase"]]
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
    try:
        _s["enemy_hp_end"] = float(actor.get_editor_property("CurrentHealth"))
    except Exception:
        _s["enemy_hp_end"] = None
    moved = -1.0
    if _s["phase_start_xy"] and end_xy[0] is not None:
        moved = (((end_xy[0] - _s["phase_start_xy"][0]) ** 2
                  + (end_xy[1] - _s["phase_start_xy"][1]) ** 2) ** 0.5)

    _s["fire_end"] = _last_fire_time()
    fired = (1 if (_s["fire_end"] > _s["fire_start"] + 0.0001) else 0)

    events = [e for e in _s["events"] if e["phase"] == name]
    geo = [e["geo"] for e in events if e["geo"] >= 0.0]
    can_rate = ("%.3f" % (_s["can_true"] / _s["can_samples"])
                if _s["can_samples"] else "")

    _s["phase_rows"].append([
        CONFIG.get("run_id", ""), name, "%.0f" % distance, "%.1f" % duration,
        _s["phase_samples"],
        "%.1f" % (_s["phase_samples"] / duration if duration else 0.0),
        len(events), "%.1f" % _s["phase_damage"],
        "%.1f" % (max(geo) if geo else -1.0),
        "%.1f" % (min(geo) if geo else -1.0),
        "%.3f" % (_s["phase_first_damage"]
                  if _s["phase_first_damage"] is not None else -1.0),
        "%.1f" % moved,
        ("%.1f" % _s["phase_start_xy"][1]) if _s["phase_start_xy"] else "",
        ("%.1f" % end_xy[1]) if end_xy[1] is not None else "",
        "%.1f" % end_geo,
        "%.1f" % (_s["bb_min"] if _s["bb_min"] is not None else -1.0),
        "%.1f" % (_s["bb_max"] if _s["bb_max"] is not None else -1.0),
        can_rate,
        _s["proj_max"] if _s["proj_max"] is not None else -1,
        _s["proj_hit_samples"], _s["proj_seen_total"],
        fired, "%.3f" % _s["fire_start"], "%.3f" % _s["fire_end"],
        "%.1f" % (_s["enemy_hp_start"] if _s["enemy_hp_start"] is not None else -1.0),
        "%.1f" % (_s["enemy_hp_end"] if _s["enemy_hp_end"] is not None else -1.0),
    ])
    unreal.log("AURA_PHASE %s end moved=%.1f damage=%.1f end_geo=%.1f proj_max=%s "
               "proj_samples=%d fired=%d fire_start=%.3f fire_end=%.3f"
               % (name, moved, _s["phase_damage"], end_geo,
                  _s["proj_max"], _s["proj_hit_samples"], fired,
                  _s["fire_start"], _s["fire_end"]))


def _step(world):
    now = time.perf_counter()
    name, duration, distance = _phases()[_s["phase"]]

    if now - _s["phase_start"] >= duration:
        _close_phase()
        if _s["phase"] + 1 < len(_phases()):
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
            _s["can_samples"] += 1
            if bb_can == 1:
                _s["can_true"] += 1
        except Exception:
            bb_can = -1
    if bb_dist >= 0.0:
        if _s["bb_min"] is None or bb_dist < _s["bb_min"]:
            _s["bb_min"] = bb_dist
        if _s["bb_max"] is None or bb_dist > _s["bb_max"]:
            _s["bb_max"] = bb_dist

    proj = _count_projectiles(world)
    if proj >= 0:
        _s["proj_seen_total"] += proj
        if proj > 0:
            _s["proj_hit_samples"] += 1
        if _s["proj_max"] is None or proj > _s["proj_max"]:
            _s["proj_max"] = proj

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
        CONFIG.get("run_id", ""), name, "%.3f" % t_in_phase, "%.1f" % geo,
        "%.1f" % bb_dist, "%.3f" % bb_hp, bb_can, proj,
        "%.1f" % health, "%.1f" % enemy_hp, ex, ey, "%.2f" % delta])


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
                _s["error"] = ("subject not resolvable within %.0f s"
                               % SETUP_BUDGET)
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
    prefix = CONFIG.get("prefix", "P03PROBE")
    phase_header = ["run_id", "phase", "requested_cm", "duration_s", "samples",
                    "sample_rate_hz", "damage_events", "damage_total",
                    "max_geo_at_damage_cm", "min_geo_at_damage_cm",
                    "first_damage_s", "enemy_moved_cm", "enemy_start_y",
                    "enemy_end_y", "enemy_end_geo_cm", "bb_dist_min", "bb_dist_max",
                    "bb_can_attack_true_rate", "projectiles_max",
                    "samples_with_projectile", "projectile_samples_total",
                    "weapon_fired", "last_fire_start", "last_fire_end",
                    "enemy_health_start", "enemy_health_end"]
    sample_header = ["run_id", "phase", "t_s", "geo_cm", "bb_cm",
                     "bb_health_percent", "bb_can_attack", "projectiles",
                     "player_hp", "enemy_hp", "enemy_x", "enemy_y", "delta"]
    try:
        _write_csv(os.path.join(out, "%s_phases.csv" % prefix),
                   phase_header, _s["phase_rows"])
        _write_csv(os.path.join(out, "%s_samples.csv" % prefix),
                   sample_header, _s["sample_rows"])
    except Exception:
        pass

    notes = list(_s["notes"])
    if _s["error"]:
        notes.append("ERROR: %s" % _s["error"])
    try:
        with open(os.path.join(out, "%s_session.txt" % prefix), "w") as handle:
            handle.write("run_id=%s\n" % CONFIG.get("run_id", ""))
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


SETUP_BUDGET = 60.0


def start():
    if not CONFIG:
        return "REFUSED: call configure(...) first"
    if _s.get("handle") is not None:
        return "a probe session is already registered"
    editor = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if editor.is_in_play_in_editor():
        return "REFUSED: PIE already active"
    _reset()
    _s["started_at"] = time.strftime("%Y.%m.%d-%H.%M.%S")
    _s["wall_start"] = time.perf_counter()
    print("probe started_at=%s run_id=%s" % (_s["started_at"], CONFIG.get("run_id")))
    try:
        _s["handle"] = unreal.register_slate_post_tick_callback(_tick)
    except Exception as exc:
        return "could not register tick callback: %s" % exc
    try:
        editor.editor_request_begin_play()
    except Exception as exc:
        return "begin_play failed: %s" % exc
    return "probe started phases=%d total_s=%.0f tree=%s" % (
        len(_phases()), sum(p[1] for p in _phases()),
        CONFIG.get("tree_fragment"))


def status():
    index = _s.get("phase", 0)
    names = [p[0] for p in _phases()]
    if not isinstance(index, int) or index < 0 or index >= len(names):
        label = "done" if _s.get("done") else "idle"
    else:
        label = names[index]
    return ("running=%s done=%s error=%s phase=%s world=%s phase_rows=%d samples=%d"
            % (_s.get("handle") is not None, bool(_s.get("done")),
               bool(_s.get("error")), label, _s.get("world_name"),
               len(_s.get("phase_rows") or []), len(_s.get("sample_rows") or [])))
