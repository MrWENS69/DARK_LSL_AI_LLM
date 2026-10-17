"""LSL constants by name, the grid limits and lsltest's own guards.

Every LSL constant comes from builtins.txt through signatures.py: nothing here is a literal of the grid."""

from .signatures import CONSTANTS


def _consts(*names):
    return tuple(CONSTANTS[n] for n in names)


# LSL constants come from builtins.txt through signatures.py: the handlers below name the ones they need.
EOF, NAK, DEBUG_CHANNEL, PUBLIC_CHANNEL = _consts("EOF", "NAK", "DEBUG_CHANNEL", "PUBLIC_CHANNEL")
INVENTORY_NOTECARD, INVENTORY_SCRIPT, INVENTORY_OBJECT, INVENTORY_NONE, INVENTORY_ALL = _consts(
    "INVENTORY_NOTECARD", "INVENTORY_SCRIPT", "INVENTORY_OBJECT", "INVENTORY_NONE", "INVENTORY_ALL")
URL_REQUEST_GRANTED, URL_REQUEST_DENIED = _consts("URL_REQUEST_GRANTED", "URL_REQUEST_DENIED")
HTTP_METHOD, HTTP_CUSTOM_HEADER, HTTP_BODY_MAXLENGTH, HTTP_BODY_TRUNCATED = _consts(
    "HTTP_METHOD", "HTTP_CUSTOM_HEADER", "HTTP_BODY_MAXLENGTH", "HTTP_BODY_TRUNCATED")
AGENT, ACTIVE, PASSIVE, SCRIPTED = _consts("AGENT", "ACTIVE", "PASSIVE", "SCRIPTED")
LINK_SET, LINK_ALL_OTHERS, LINK_ALL_CHILDREN, LINK_THIS = _consts(
    "LINK_SET", "LINK_ALL_OTHERS", "LINK_ALL_CHILDREN", "LINK_THIS")
CHANGED_REGION, CHANGED_REGION_START = _consts("CHANGED_REGION", "CHANGED_REGION_START")
(OBJECT_NAME, OBJECT_DESC, OBJECT_POS, OBJECT_ROT, OBJECT_VELOCITY, OBJECT_OWNER, OBJECT_GROUP, OBJECT_CREATOR,
 OBJECT_ROOT, OBJECT_PRIM_COUNT, OBJECT_TOTAL_SCRIPT_COUNT, OBJECT_RUNNING_SCRIPT_COUNT,
 OBJECT_ATTACHED_POINT) = _consts(
    "OBJECT_NAME", "OBJECT_DESC", "OBJECT_POS", "OBJECT_ROT", "OBJECT_VELOCITY", "OBJECT_OWNER", "OBJECT_GROUP",
    "OBJECT_CREATOR", "OBJECT_ROOT", "OBJECT_PRIM_COUNT", "OBJECT_TOTAL_SCRIPT_COUNT",
    "OBJECT_RUNNING_SCRIPT_COUNT", "OBJECT_ATTACHED_POINT")
DATA_ONLINE, DATA_NAME, DATA_BORN, DATA_PAYINFO = _consts("DATA_ONLINE", "DATA_NAME", "DATA_BORN", "DATA_PAYINFO")
(PARCEL_DETAILS_NAME, PARCEL_DETAILS_DESC, PARCEL_DETAILS_OWNER, PARCEL_DETAILS_GROUP, PARCEL_DETAILS_AREA,
 PARCEL_DETAILS_ID) = _consts("PARCEL_DETAILS_NAME", "PARCEL_DETAILS_DESC", "PARCEL_DETAILS_OWNER",
                              "PARCEL_DETAILS_GROUP", "PARCEL_DETAILS_AREA", "PARCEL_DETAILS_ID")
(LINKSETDATA_OK, LINKSETDATA_EMEMORY, LINKSETDATA_ENOKEY, LINKSETDATA_EPROTECTED, LINKSETDATA_NOTFOUND,
 LINKSETDATA_NOUPDATE) = _consts("LINKSETDATA_OK", "LINKSETDATA_EMEMORY", "LINKSETDATA_ENOKEY",
                                 "LINKSETDATA_EPROTECTED", "LINKSETDATA_NOTFOUND", "LINKSETDATA_NOUPDATE")
LINKSETDATA_RESET, LINKSETDATA_UPDATE, LINKSETDATA_DELETE, LINKSETDATA_MULTIDELETE = _consts(
    "LINKSETDATA_RESET", "LINKSETDATA_UPDATE", "LINKSETDATA_DELETE", "LINKSETDATA_MULTIDELETE")
_CONTENT_TYPES = {CONSTANTS[name]: mime for name, mime in (
    ("CONTENT_TYPE_TEXT", "text/plain"), ("CONTENT_TYPE_HTML", "text/html"), ("CONTENT_TYPE_XML", "application/xml"),
    ("CONTENT_TYPE_XHTML", "application/xhtml+xml"), ("CONTENT_TYPE_ATOM", "application/atom+xml"),
    ("CONTENT_TYPE_JSON", "application/json"), ("CONTENT_TYPE_LLSD", "application/llsd+xml"),
    ("CONTENT_TYPE_FORM", "application/x-www-form-urlencoded"), ("CONTENT_TYPE_RSS", "application/rss+xml"))
    if name in CONSTANTS}

# Grid limits that are not LSL constants.
MAX_LISTENS = 65              # llListen handles per script before "Too Many Listens"
MAX_URLS = 38                 # HTTP-in URLs per script, what llGetFreeURLs counts down from
LINKSET_DATA_SIZE = 131072    # bytes of linkset data per object
HTTP_BODY_DEFAULT = 2048      # bytes of an HTTP response body kept without HTTP_BODY_MAXLENGTH
MIN_TIMER = 0.022             # one simulator frame: shorter timers and sensor rates are rounded up to it
MAX_SLEEP = 31536000.0        # one year: llSleep never moves the clock further in one call
SENSOR_MAX = 32               # results of one sensor scan, nearest first (16 before March 2024)
RECORD_ONLY = frozenset(("llGiveInventory", "llTakeControls", "llReleaseControls", "llStartAnimation",
                         "llStopAnimation"))   # modelled as "record the call", even under strict

# lsltest's own guards, not grid limits.
MAX_RUN_ROUNDS = 10000        # run() rounds before the scripts are declared to be ping-ponging
MAX_TICK_STEPS = 100000       # timer or sensor steps a single tick() may run
MAX_RECORDS = 100000          # chat lines, dialogs, requests... of one kind the simulator keeps
MAX_PATTERN_LEN = 256         # llLinksetDataFindKeys patterns longer than this match nothing...
MAX_MATCH_LEN = 256           # ...and only the first characters of a key are matched
MAX_SCRIPT_BYTES = 1048576    # a .lsl file over 1 MB is refused
