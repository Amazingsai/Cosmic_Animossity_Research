"""Verify that BP_BasicEnemyAI's own damage event can be invoked from Python.

set_editor_property is refused for CurrentHealth ("cannot be edited on instances"),
import_text is not exposed, and the console `set` command has no effect, so the only
remaining route to the pawn's health is the pawn's own blueprint logic.  This session
calls SendDamage / ReduceHealth through Unreal reflection and reads CurrentHealth and
the blackboard HealthPercent back after the controller's 0.1 s timer has had time to
propagate the change.

Runs in a throwaway PIE world; nothing in the level is modified.
"""

import time
import traceback

import unreal

ENEMY_FRAGMENT = "BP_BasicEnemyAI"
_s = {}


def _reset():
    _s.clear()
    _s.update({"handle": None, "done": False, "notes": [], "wall_start": 0.0,
               "enemy": None, "stage": 0, "stage_time": 0.0})


def _world():
    return unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()


def _find(world):
    for actor in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor):
        try:
            if ENEMY_FRAGMENT in actor.get_class().get_name():
                return actor
        except Exception:
            continue
    return None


def _health(actor):
    try:
        return float(actor.get_editor_property("CurrentHealth"))
    except Exception as exc:
        return "unreadable (%s)" % exc


def _bb_hp(actor):
    try:
        controller = actor.get_controller()
        bb = controller.get_editor_property("Blackboard") if controller else None
        if bb is None:
            return "no blackboard"
        return float(bb.get_value_as_float("HealthPercent"))
    except Exception as exc:
        return "unreadable (%s)" % exc


def _report(tag):
    actor = _s["enemy"]
    _s["notes"].append("%s health=%s health_percent=%s" % (tag, _health(actor), _bb_hp(actor)))


def _call(name, *args):
    actor = _s["enemy"]
    try:
        result = actor.call_method(name, tuple(args))
        return "ok(%r)" % (result,)
    except Exception as exc:
        return "raised(%s)" % exc


def _tick(_delta):
    if _s["done"]:
        return
    try:
        world = _world()
        if world is None:
            if time.perf_counter() - _s["wall_start"] > 30.0:
                _s["done"] = True
                _finish()
            return
        if time.perf_counter() - _s["wall_start"] < 1.5:
            return

        if _s["enemy"] is None:
            _s["enemy"] = _find(world)
            if _s["enemy"] is None:
                _s["notes"].append("enemy not found in %s" % world.get_name())
                _s["done"] = True
                _finish()
                return
            _report("baseline")
            _s["stage_time"] = time.perf_counter()
            return

        elapsed = time.perf_counter() - _s["stage_time"]
        if _s["stage"] == 0 and elapsed > 0.4:
            _s["notes"].append("call SendDamage(400) -> %s" % _call("SendDamage", 400.0))
            _s["stage"] = 1
            _s["stage_time"] = time.perf_counter()
            return
        if _s["stage"] == 1 and elapsed > 0.6:
            _report("after SendDamage(400)")
            _s["notes"].append("call ReduceHealth(50) -> %s" % _call("ReduceHealth", 50.0))
            _s["stage"] = 2
            _s["stage_time"] = time.perf_counter()
            return
        if _s["stage"] == 2 and elapsed > 0.6:
            _report("after ReduceHealth(50)")
            _s["notes"].append("call SendDamage(-450) -> %s" % _call("SendDamage", -450.0))
            _s["stage"] = 3
            _s["stage_time"] = time.perf_counter()
            return
        if _s["stage"] == 3 and elapsed > 0.6:
            _report("after SendDamage(-450)")
            _s["done"] = True
            _finish()
    except Exception:
        _s["notes"].append("ERROR: %s" % traceback.format_exc())
        _s["done"] = True
        _finish()


def _finish():
    for note in _s["notes"]:
        print(note)
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
    editor = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if editor.is_in_play_in_editor():
        return "REFUSED: PIE already active"
    _reset()
    _s["wall_start"] = time.perf_counter()
    _s["handle"] = unreal.register_slate_post_tick_callback(_tick)
    editor.editor_request_begin_play()
    return "reflection damage-call session started"
