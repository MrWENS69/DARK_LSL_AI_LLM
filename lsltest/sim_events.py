"""Builtins that raise events in other scripts or later: link messages, permissions and animations, sensors. Mixed into Simulator."""

from types import SimpleNamespace

from . import pure
from .limits import (ACTIVE, AGENT, LINK_ALL_CHILDREN, LINK_ALL_OTHERS, LINK_SET, LINK_THIS, MIN_TIMER,
                     PASSIVE, SCRIPTED, SENSOR_MAX)
from .values import Key, NULL_KEY, is_valid_key


class EventsMixin(object):

    def _post_prim(self, script, event, args):
        """Post an event to every script of the prim: http_response and dataserver reach them all."""
        for other in script.obj.scripts:
            other.post(event, args)

    def deliver_sensor(self, script, name, id_, kind, range_, arc):
        found = []
        here = script.obj.pos
        if kind & AGENT:
            for av in self.avatars.values():
                if script.obj.wearer is not None and av.key == script.obj.wearer.key:
                    continue          # an attachment never detects its wearer
                if pure.llVecDist(here, av.pos) <= range_:
                    if name and av.name != name:
                        continue
                    if is_valid_key(id_) and id_ != NULL_KEY and av.key != id_:
                        continue
                    found.append(self._detected_record(avatar=av))
        if kind & (ACTIVE | PASSIVE | SCRIPTED):
            for obj in self.objects:
                if obj is script.obj or not obj.alive or obj.attached:
                    continue
                if pure.llVecDist(here, obj.pos) <= range_:
                    if name and obj.name != name:
                        continue
                    found.append(self._detected_record(obj=obj))
        found.sort(key=lambda d: pure.llVecDist(here, d["pos"]))
        found = found[:SENSOR_MAX]
        if found:
            script.post("sensor", [len(found)], found)
        else:
            script.post("no_sensor", [])

    def ll_MessageLinked(self, script, link, num, text, id_):
        """Delivery is by prim: every script of a target prim gets the message, the sender included."""
        sender = self.ll_GetLinkNumber(script)
        self._keep(self.link_messages, SimpleNamespace(script=script, sender=sender, link=link, num=num, str=text,
                                                       id=id_, time=self.time))
        for other in script.obj.scripts:
            target = self.ll_GetLinkNumber(other)
            same_prim = target == sender
            deliver = (
                link == LINK_SET
                or (link == LINK_ALL_OTHERS and not same_prim)
                or (link == LINK_ALL_CHILDREN and target > 1)
                or (link == LINK_THIS and same_prim)
                or (link >= 0 and link == target)
                or (script.obj.prims == 1 and link in (0, 1))      # an unlinked prim answers to 0 and 1
            )
            if deliver:
                other.post("link_message", [sender, num, text, Key(id_)])

    def ll_RequestPermissions(self, script, agent, perms):
        if perms == 0:
            return
        av = self.avatars.get(agent)
        if av is None:
            return
        policy = self.permission_policy
        if callable(policy):
            granted = int(policy(av, perms))
        else:
            granted = perms if policy else 0
        # the answer comes with the run_time_permissions event, never inside the calling handler
        script.pending_permissions = (granted, Key(agent) if granted else NULL_KEY)
        script.post("run_time_permissions", [granted])

    def ll_GetPermissions(self, script):
        return script.permissions

    def ll_GetPermissionsKey(self, script):
        return Key(script.permissions_key)

    def ll_Sensor(self, script, name, id_, kind, range_, arc):
        self.deliver_sensor(script, name, id_, kind, range_, arc)

    def ll_SensorRepeat(self, script, name, id_, kind, range_, arc, rate):
        if not rate > 0:                      # also NaN
            script.sensor_repeat = None
            return
        rate = max(rate, MIN_TIMER)
        script.sensor_repeat = SimpleNamespace(name=name, id=id_, type=kind, range=range_, arc=arc,
                                               rate=rate, due=self.time + rate)

    def ll_SensorRemove(self, script):
        script.sensor_repeat = None
