"""Randomness and rezzing. Mixed into Simulator."""

from . import pure
from .limits import INVENTORY_OBJECT
from .values import Key, f32


class MiscMixin(object):
    """Randomness and rezzing."""

    # --- randomness ------------------------------------------------------------

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

    # --- rezzing ---------------------------------------------------------------

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
