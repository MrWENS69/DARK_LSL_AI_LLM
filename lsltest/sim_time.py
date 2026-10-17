"""Timers, the clock and script control: llSetTimerEvent, llSleep, llGetTime, llResetScript, memory. Mixed into Simulator."""

import time as _time

from .errors import ResetSignal
from .limits import MAX_SLEEP, MIN_TIMER
from .values import f32, to_int32
from .world import _slt_offset


class TimeMixin(object):
    """Timers, the clock and script control: llSetTimerEvent, llSleep, llGetTime, llResetScript, memory."""

    # --- timers and time ---------------------------------------------------

    def ll_SetTimerEvent(self, script, seconds):
        if not seconds > 0.0:                 # also NaN
            script.timer_interval = 0.0
            script.timer_due = None
        else:
            script.timer_interval = max(seconds, MIN_TIMER)
            script.timer_due = self.time + script.timer_interval

    def ll_Sleep(self, script, seconds):
        if seconds > 0:
            self.time += min(seconds, MAX_SLEEP)   # due timers fire after the handler, as on the grid

    def ll_GetTime(self, script):
        return script.time_since_start()

    def ll_ResetTime(self, script):
        script.start_time = self.time

    def ll_GetAndResetTime(self, script):
        elapsed = script.time_since_start()
        script.start_time = self.time
        return elapsed

    def ll_GetUnixTime(self, script):
        return to_int32(int(self.epoch + self.time))

    def _utc(self):
        try:
            return _time.gmtime(self.epoch + self.time)
        except (OSError, OverflowError, ValueError):   # the clock was pushed beyond what the platform converts
            return _time.gmtime(0)

    def ll_GetTimestamp(self, script):
        return _time.strftime("%Y-%m-%dT%H:%M:%S", self._utc()) + ".%06dZ" % int((self.time % 1) * 1e6)

    def ll_GetWallclock(self, script):
        return f32(int((self.epoch + self.time + _slt_offset(self.epoch + self.time)) % 86400))

    def ll_GetGMTclock(self, script):
        return f32((self.epoch + self.time) % 86400)

    def ll_GetDate(self, script):
        return _time.strftime("%Y-%m-%d", self._utc())

    # --- script control ----------------------------------------------------

    def ll_ResetScript(self, script):
        raise ResetSignal()

    def ll_ResetOtherScript(self, script, name):
        other = script.obj.script_named(name)
        if other is not None and other is not script:
            other.reset()

    def ll_GetScriptName(self, script):
        return script.name

    def ll_GetScriptState(self, script, name):
        other = script.obj.script_named(name)
        return int(other is not None and other.running and not other.dead)

    def ll_SetScriptState(self, script, name, running):
        other = script.obj.script_named(name)
        if other is not None:
            other.running = bool(running)

    def ll_GetStartParameter(self, script):
        return script.start_param

    def ll_GetFreeMemory(self, script):
        return max(0, script.memory_limit - script.memory_used())

    def ll_GetUsedMemory(self, script):
        return script.memory_used()

    def ll_GetMemoryLimit(self, script):
        return script.memory_limit

    def ll_SetMemoryLimit(self, script, limit):
        if limit < script.memory_used() or limit > 65536:
            return 0
        script.memory_limit = limit
        return 1

    def ll_ScriptProfiler(self, script, flags):
        pass

    def ll_GetSPMaxMemory(self, script):
        return script.memory_used()

    def ll_Die(self, script):
        script.obj.alive = False
        self.record_call(script, "llDie")
