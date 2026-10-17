"""Linkset data: llLinksetData* with the 128 KiB quota and the restricted regex matcher. Mixed into Simulator."""

import re

from .limits import (LINKSETDATA_DELETE, LINKSETDATA_EMEMORY, LINKSETDATA_ENOKEY, LINKSETDATA_EPROTECTED,
                     LINKSETDATA_MULTIDELETE, LINKSETDATA_NOTFOUND, LINKSETDATA_NOUPDATE, LINKSETDATA_OK,
                     LINKSETDATA_RESET, LINKSETDATA_UPDATE, LINKSET_DATA_SIZE, MAX_MATCH_LEN,
                     MAX_PATTERN_LEN)


def safe_pattern(pattern):
    """A compiled regex for llLinksetDataFindKeys, or None when the pattern is refused.

    Python's backtracking engine takes exponential time on nested quantifiers and polynomial time on
    several unbounded ones, so groups, backreferences and more than one unbounded quantifier are
    refused; keys are matched on their first MAX_MATCH_LEN characters."""
    if len(pattern) > MAX_PATTERN_LEN or "(" in pattern or re.search(r"\\\d", pattern):
        return None
    if len(re.findall(r"[*+]|\{\d+,\}", pattern)) > 1:
        return None
    try:
        return re.compile(pattern)
    except re.error:
        return None


class LinksetDataMixin(object):

    def _linkset_used(self, obj):
        used = sum(len(k.encode("utf-8")) + len(v.encode("utf-8")) for k, v in obj.linkset_data.items())
        used += sum(len(k.encode("utf-8")) + len(v[0].encode("utf-8")) + 32 for k, v in obj.linkset_protected.items())
        return used

    def _linkset_event(self, obj, action, name, value):
        for script in obj.scripts:
            script.post("linkset_data", [action, name, value])

    def _linkset_fits(self, obj, name, value, old, protected=False):
        """Whether writing value under name (replacing old, "" when new) stays within LINKSET_DATA_SIZE."""
        used = self._linkset_used(obj)
        if old:
            used -= len(name.encode("utf-8")) + len(old.encode("utf-8"))
        elif protected:
            used += 32                                   # the password's share, counted by _linkset_used
        return used + len(name.encode("utf-8")) + len(value.encode("utf-8")) <= LINKSET_DATA_SIZE

    def _linkset_keys(self, obj, pattern=None):
        """The keys, sorted, optionally those a (restricted) regex matches."""
        keys = list(obj.linkset_data) + list(obj.linkset_protected)
        if pattern is not None:
            rx = safe_pattern(pattern)
            if rx is None:
                return []
            keys = [k for k in keys if rx.search(k[:MAX_MATCH_LEN])]
        return sorted(keys)

    @staticmethod
    def _page(keys, start, count):
        return keys[start:start + count] if count > 0 else keys[start:]

    def ll_LinksetDataWrite(self, script, name, value):
        obj = script.obj
        if name == "":
            return LINKSETDATA_ENOKEY
        if name in obj.linkset_protected:
            return LINKSETDATA_EPROTECTED
        old = obj.linkset_data.get(name)
        if value == "":
            if old is None:
                return LINKSETDATA_NOTFOUND
            del obj.linkset_data[name]
            self._linkset_event(obj, LINKSETDATA_DELETE, name, "")
            return LINKSETDATA_OK
        if old == value:
            return LINKSETDATA_NOUPDATE
        if not self._linkset_fits(obj, name, value, old or ""):
            return LINKSETDATA_EMEMORY
        obj.linkset_data[name] = value
        self._linkset_event(obj, LINKSETDATA_UPDATE, name, value)
        return LINKSETDATA_OK

    def ll_LinksetDataWriteProtected(self, script, name, value, password):
        obj = script.obj
        if name == "":
            return LINKSETDATA_ENOKEY
        if name in obj.linkset_data:
            return LINKSETDATA_EPROTECTED
        existing = obj.linkset_protected.get(name)
        if existing is not None and existing[1] != password:
            return LINKSETDATA_EPROTECTED
        if value == "":
            if existing is None:
                return LINKSETDATA_NOTFOUND
            del obj.linkset_protected[name]
            self._linkset_event(obj, LINKSETDATA_DELETE, name, "")
            return LINKSETDATA_OK
        if existing is not None and existing[0] == value:
            return LINKSETDATA_NOUPDATE
        if not self._linkset_fits(obj, name, value, existing[0] if existing else "", protected=True):
            return LINKSETDATA_EMEMORY
        obj.linkset_protected[name] = (value, password)
        self._linkset_event(obj, LINKSETDATA_UPDATE, name, "")
        return LINKSETDATA_OK

    def ll_LinksetDataRead(self, script, name):
        return script.obj.linkset_data.get(name, "")

    def ll_LinksetDataReadProtected(self, script, name, password):
        item = script.obj.linkset_protected.get(name)
        if item is None or item[1] != password:
            return ""
        return item[0]

    def ll_LinksetDataDelete(self, script, name):
        return self.ll_LinksetDataWrite(script, name, "")

    def ll_LinksetDataDeleteProtected(self, script, name, password):
        return self.ll_LinksetDataWriteProtected(script, name, "", password)

    def ll_LinksetDataReset(self, script):
        script.obj.linkset_data = {}
        script.obj.linkset_protected = {}
        self._linkset_event(script.obj, LINKSETDATA_RESET, "", "")

    def ll_LinksetDataAvailable(self, script):
        return LINKSET_DATA_SIZE - self._linkset_used(script.obj)

    def ll_LinksetDataCountKeys(self, script):
        return len(self._linkset_keys(script.obj))

    def ll_LinksetDataListKeys(self, script, start, count):
        return self._page(self._linkset_keys(script.obj), start, count)

    def ll_LinksetDataFindKeys(self, script, pattern, start, count):
        return self._page(self._linkset_keys(script.obj, pattern), start, count)

    def ll_LinksetDataCountFound(self, script, pattern):
        return len(self._linkset_keys(script.obj, pattern))

    def ll_LinksetDataDeleteFound(self, script, pattern, password):
        obj = script.obj
        deleted = refused = 0
        for name in self._linkset_keys(obj, pattern):
            if name in obj.linkset_data:
                del obj.linkset_data[name]
                deleted += 1
            elif obj.linkset_protected[name][1] == password:
                del obj.linkset_protected[name]
                deleted += 1
            else:
                refused += 1
        if deleted:
            self._linkset_event(obj, LINKSETDATA_MULTIDELETE, "", "")
        return [deleted, refused]
