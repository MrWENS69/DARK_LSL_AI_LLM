"""Chat, listens and dialogs: llSay and friends, llListen, llDialog, llTextBox. Mixed into Simulator."""

from types import SimpleNamespace

from .errors import ScriptError
from .limits import MAX_LISTENS, PUBLIC_CHANNEL
from .values import Key, type_of, NULL_KEY, is_valid_key
from .world import Chat, _clip


class ChatMixin(object):
    """Chat, listens and dialogs: llSay and friends, llListen, llDialog, llTextBox."""

    # --- chat ----------------------------------------------------------------

    def _speak(self, script, channel, text, kind, target=None):
        obj = script.obj
        text = _clip(text, 1024)
        self._keep(self.chat, Chat(channel, obj.key, obj.name, text, kind, target, self.time))
        if kind == "ownersay" or (kind == "regionsayto" and channel == PUBLIC_CHANNEL):
            return
        self.deliver_chat(channel, obj.key, obj.name, text, source_obj=obj, target=target)

    def ll_Say(self, script, channel, text):
        self._speak(script, channel, text, "say")

    def ll_Whisper(self, script, channel, text):
        self._speak(script, channel, text, "whisper")

    def ll_Shout(self, script, channel, text):
        self._speak(script, channel, text, "shout")

    def ll_RegionSay(self, script, channel, text):
        if channel == 0:
            return
        self._speak(script, channel, text, "regionsay")

    def ll_RegionSayTo(self, script, target, channel, text):
        self._speak(script, channel, text, "regionsayto", target=Key(target))

    def ll_OwnerSay(self, script, text):
        self._speak(script, PUBLIC_CHANNEL, text, "ownersay")

    def ll_InstantMessage(self, script, user, text):
        self._keep(self.chat, Chat(PUBLIC_CHANNEL, script.obj.key, script.obj.name, _clip(text, 1023), "im",
                                   Key(user), self.time))
        self.time += 2.0

    def ll_Email(self, script, address, subject, message):
        self._keep(self.emails, SimpleNamespace(to=address, subject=subject, body=message, object=script.obj.key))
        self.time += 20.0

    # --- listens ---------------------------------------------------------------

    def ll_Listen(self, script, channel, name, id_, msg):
        wanted = (channel, name, id_ if is_valid_key(id_) and id_ != NULL_KEY else "", msg)
        for handle, listen in script.listens.items():
            if (listen.channel, listen.name, listen.id, listen.msg) == wanted:
                return handle                 # the same filter again: the existing handle, no new listen
        if len(script.listens) >= MAX_LISTENS:
            raise ScriptError("Too Many Listens")
        handle = script.next_listen
        script.next_listen += 1
        script.listens[handle] = SimpleNamespace(channel=wanted[0], name=wanted[1], id=wanted[2], msg=wanted[3], active=True)
        return handle

    def ll_ListenRemove(self, script, handle):
        script.listens.pop(handle, None)

    def ll_ListenControl(self, script, handle, active):
        if handle in script.listens:
            script.listens[handle].active = bool(active)

    # --- dialogs -------------------------------------------------------------

    def ll_Dialog(self, script, avatar, message, buttons, channel):
        # every llDialog error is shouted on DEBUG_CHANNEL and no dialog is shown; the script goes on (wiki)
        if message == "" or len(message.encode("utf-8")) >= 512:
            self._debug(script, "llDialog: must supply a message" if message == ""
                        else "llDialog: message too long, must be less than 512 characters")
            return
        if any(type_of(b) != "string" for b in buttons):
            self._debug(script, "llDialog: all buttons must be strings")
            return
        labels = list(buttons) or ["OK"]
        if len(labels) > 12:
            self._debug(script, "llDialog: too many buttons [%d]" % len(labels))
            return
        if any(label == "" or len(label.encode("utf-8")) > 24 for label in labels):
            self._debug(script, "llDialog: button labels must be between 1 and 24 bytes")
            return
        self._keep(self.dialogs, SimpleNamespace(avatar=avatar, text=message, buttons=labels, channel=channel,
                                                 object=script.obj.key, script=script, time=self.time))
        self.time += 1.0

    def ll_TextBox(self, script, avatar, message, channel):
        self._keep(self.textboxes, SimpleNamespace(avatar=avatar, text=message, channel=channel,
                                                   object=script.obj.key, script=script, time=self.time))
        self.time += 1.0
