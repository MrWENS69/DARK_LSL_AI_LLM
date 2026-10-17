"""Object and avatar getters, llDetected*, inventory and notecards, randomness, rezzing. Mixed into Simulator."""

import uuid

from . import pure
from .limits import (DATA_BORN, DATA_NAME, DATA_ONLINE, DATA_PAYINFO, EOF, INVENTORY_ALL, INVENTORY_NONE,
                     INVENTORY_NOTECARD, INVENTORY_OBJECT, NAK, OBJECT_ATTACHED_POINT, OBJECT_CREATOR,
                     OBJECT_DESC, OBJECT_GROUP, OBJECT_NAME, OBJECT_OWNER, OBJECT_POS, OBJECT_PRIM_COUNT,
                     OBJECT_ROOT, OBJECT_ROT, OBJECT_RUNNING_SCRIPT_COUNT, OBJECT_TOTAL_SCRIPT_COUNT,
                     OBJECT_VELOCITY, PARCEL_DETAILS_AREA, PARCEL_DETAILS_DESC, PARCEL_DETAILS_GROUP,
                     PARCEL_DETAILS_ID, PARCEL_DETAILS_NAME, PARCEL_DETAILS_OWNER)
from .values import Key, Vector, f32, ZERO_VECTOR, ZERO_ROTATION, NULL_KEY
from .world import clip_text


class ObjectsMixin(object):

    def ll_GetOwner(self, script):
        return Key(script.obj.owner)

    def ll_GetKey(self, script):
        return Key(script.obj.key)

    def ll_GetObjectName(self, script):
        return script.obj.name

    def ll_SetObjectName(self, script, name):
        script.obj.name = name[:63]

    def ll_GetObjectDesc(self, script):
        return script.obj.desc

    def ll_SetObjectDesc(self, script, desc):
        script.obj.desc = desc[:127]

    def ll_GetPos(self, script):
        return script.obj.pos

    def ll_SetPos(self, script, pos):
        script.obj.pos = pos
        self.time += 0.2

    ll_GetLocalPos = ll_GetRootPosition = ll_GetPos

    def ll_GetRot(self, script):
        return script.obj.rot

    def ll_SetRot(self, script, rot):
        script.obj.rot = rot
        self.time += 0.2

    ll_GetLocalRot = ll_GetRootRotation = ll_GetRot

    ll_SetLocalRot = ll_SetRot

    def ll_GetRegionName(self, script):
        return self.region_name

    def ll_GetRegionCorner(self, script):
        return Vector(256000.0, 256000.0, 0.0)

    def ll_GetEnv(self, script, name):
        return {"sim_version": self.sim_version, "sim_channel": "lsltest", "region_idle": "0",
                "simulator_hostname": "sim.invalid", "estate_name": "lsltest", "region_max_prims": "15000"}.get(name, "")

    def ll_GetLinkNumber(self, script):
        return script.link if script.obj.prims > 1 else 0

    def ll_GetNumberOfPrims(self, script):
        return script.obj.prims

    def ll_GetLinkName(self, script, link):
        return script.obj.name

    def ll_GetLinkKey(self, script, link):
        return Key(script.obj.key)

    def ll_GetAttached(self, script):
        return script.obj.attached

    def ll_SetText(self, script, text, color, alpha):
        script.obj.text = clip_text(text, 254)

    def ll_GetObjectDetails(self, script, key, params):
        obj = next((o for o in self.objects if o.key == key), None)
        av = self.avatars.get(key)
        if obj is not None:
            details = {OBJECT_NAME: obj.name, OBJECT_DESC: obj.desc, OBJECT_POS: obj.pos, OBJECT_ROT: obj.rot,
                       OBJECT_VELOCITY: ZERO_VECTOR, OBJECT_OWNER: Key(obj.owner), OBJECT_GROUP: Key(obj.group),
                       OBJECT_CREATOR: Key(obj.owner), OBJECT_ROOT: Key(obj.key), OBJECT_PRIM_COUNT: obj.prims,
                       OBJECT_TOTAL_SCRIPT_COUNT: len(obj.scripts),
                       OBJECT_RUNNING_SCRIPT_COUNT: sum(1 for s in obj.scripts if s.running and not s.dead),
                       OBJECT_ATTACHED_POINT: obj.attached}
        elif av is not None:
            details = {OBJECT_NAME: av.name, OBJECT_DESC: "", OBJECT_POS: av.pos, OBJECT_ROT: ZERO_ROTATION,
                       OBJECT_VELOCITY: ZERO_VECTOR, OBJECT_OWNER: Key(av.key), OBJECT_GROUP: Key(av.group),
                       OBJECT_CREATOR: Key(av.key), OBJECT_ROOT: Key(av.key), OBJECT_ATTACHED_POINT: 0}
        else:
            return []
        return [details.get(p, "") for p in params]

    def ll_Key2Name(self, script, key):
        av = self.avatars.get(key)
        if av is not None:
            return av.name
        obj = next((o for o in self.objects if o.key == key), None)
        return obj.name if obj is not None else ""

    def _avatar_attr(self, key, attr):
        av = self.avatars.get(key)
        return getattr(av, attr) if av is not None else ""

    def _dataserver(self, script, value):
        """The grid answers asynchronous lookups with a dataserver event in every script of the prim."""
        query = self.new_key()
        self._post_prim(script, "dataserver", [query, value])
        self.time += 0.1
        return query

    def ll_GetDisplayName(self, script, key):
        return self._avatar_attr(key, "display_name")

    def ll_GetUsername(self, script, key):
        return self._avatar_attr(key, "username")

    def ll_RequestDisplayName(self, script, key):
        return self._dataserver(script, self._avatar_attr(key, "display_name"))

    def ll_RequestUsername(self, script, key):
        return self._dataserver(script, self._avatar_attr(key, "username"))

    def ll_RequestAgentData(self, script, key, data):
        av = self.avatars.get(key)
        value = ""
        if av is not None:
            value = {DATA_ONLINE: "1" if av.online else "0", DATA_NAME: av.name, DATA_BORN: "2010-01-01",
                     DATA_PAYINFO: "0"}.get(data, "")
        return self._dataserver(script, value)

    def ll_Name2Key(self, script, name):
        for av in self.avatars.values():
            if av.name == name or av.username == name:
                return Key(av.key)
        return NULL_KEY

    def ll_SameGroup(self, script, key):
        av = self.avatars.get(key)
        if av is None:
            return 0
        return int(av.group == script.obj.group)

    def ll_GetAgentSize(self, script, key):
        return Vector(0.45, 0.6, 1.9) if key in self.avatars else ZERO_VECTOR

    def ll_GetAgentInfo(self, script, key):
        return 0

    def ll_GetAgentList(self, script, scope, options):
        return [Key(k) for k in self.avatars]

    def ll_GetRegionAgentCount(self, script):
        return len(self.avatars)

    def ll_OverMyLand(self, script, key):
        return 1

    def ll_GetParcelDetails(self, script, pos, params):
        details = {PARCEL_DETAILS_NAME: "Test Parcel", PARCEL_DETAILS_DESC: "", PARCEL_DETAILS_OWNER: Key(self.owner.key),
                   PARCEL_DETAILS_GROUP: NULL_KEY, PARCEL_DETAILS_AREA: 65536, PARCEL_DETAILS_ID: Key("")}
        return [details.get(p, "") for p in params]

    def _detected(self, script, index, field, fallback):
        if index < 0 or index >= len(script.detected):
            return fallback
        return script.detected[index].get(field, fallback)

    def ll_DetectedKey(self, script, index):
        return Key(self._detected(script, index, "key", NULL_KEY))

    def ll_DetectedName(self, script, index):
        return self._detected(script, index, "name", "")

    def ll_DetectedOwner(self, script, index):
        return Key(self._detected(script, index, "owner", NULL_KEY))

    def ll_DetectedPos(self, script, index):
        return self._detected(script, index, "pos", ZERO_VECTOR)

    def ll_DetectedRot(self, script, index):
        return self._detected(script, index, "rot", ZERO_ROTATION)

    def ll_DetectedGroup(self, script, index):
        return int(self._detected(script, index, "group", NULL_KEY) == script.obj.group)

    def ll_DetectedType(self, script, index):
        return self._detected(script, index, "type", 0)

    def ll_DetectedVel(self, script, index):
        return self._detected(script, index, "vel", ZERO_VECTOR)

    def ll_DetectedLinkNumber(self, script, index):
        return 1 if script.detected else 0

    def ll_DetectedTouchFace(self, script, index):
        return 0 if script.detected else -1

    def ll_GetInventoryType(self, script, name):
        item = script.obj.inventory.get(name)
        return item[0] if item else INVENTORY_NONE

    def ll_GetInventoryNumber(self, script, kind):
        return sum(1 for t, _ in script.obj.inventory.values() if kind == INVENTORY_ALL or t == kind)

    def ll_GetInventoryName(self, script, kind, index):
        names = sorted(n for n, (t, _) in script.obj.inventory.items() if kind == INVENTORY_ALL or t == kind)
        return names[index] if 0 <= index < len(names) else ""

    def ll_GetInventoryKey(self, script, name):
        return Key(str(uuid.UUID(int=pure.llHash(name) & 0xFFFFFFFF))) if name in script.obj.inventory else NULL_KEY

    def ll_GetInventoryCreator(self, script, name):
        return Key(self.owner.key) if name in script.obj.inventory else NULL_KEY

    def _notecard_lines(self, script, name):
        item = script.obj.inventory.get(name)
        if item is None or item[0] != INVENTORY_NOTECARD:
            return None
        return item[1].split("\n")

    def ll_GetNotecardLine(self, script, name, line):
        lines = self._notecard_lines(script, name)
        if lines is None:
            self._debug(script, "Couldn't find notecard %s" % name)
            return NULL_KEY
        script.obj.cached.add(name)           # an asynchronous read puts the notecard in the grid's cache
        return self._dataserver(script, clip_text(lines[line] if 0 <= line < len(lines) else EOF, 1024))

    def ll_GetNumberOfNotecardLines(self, script, name):
        lines = self._notecard_lines(script, name)
        if lines is None:
            return NULL_KEY
        script.obj.cached.add(name)
        return self._dataserver(script, str(len(lines)))

    def ll_GetNotecardLineSync(self, script, name, line):
        lines = self._notecard_lines(script, name)
        if lines is None or name not in script.obj.cached:
            return NAK                        # not cached yet: the script must fall back to llGetNotecardLine
        return lines[line] if 0 <= line < len(lines) else EOF

    def ll_RemoveInventory(self, script, name):
        script.obj.inventory.pop(name, None)

    def ll_Frand(self, script, mag):
        return f32(self.rng.random() * mag)

    def ll_GenerateKey(self, script):
        return self.new_key()

    def ll_ListRandomize(self, script, src, stride):
        pieces = pure.chunks(src, stride)
        if pieces is None:
            return list(src)
        self.rng.shuffle(pieces)
        return [v for c in pieces for v in c]

    def ll_RezObject(self, script, inventory, pos, vel, rot, param):
        self.record_call(script, "llRezObject", inventory, pos, vel, rot, param)
        if inventory in script.obj.inventory and script.obj.inventory[inventory][0] == INVENTORY_OBJECT:
            child = self.rez(inventory, owner=self.avatars.get(script.obj.owner))
            child.pos = pos
            child.rot = rot
            child.start_param = param
            script.post("object_rez", [Key(child.key)])
        self.time += 0.1

    ll_RezAtRoot = ll_RezObject
