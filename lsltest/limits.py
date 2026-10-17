"""LSL constants by name (from builtins.txt through signatures.py), the grid limits that builtins.txt
does not carry, and lsltest's own guards, the interpreter's included."""

from .signatures import CONSTANTS


def _consts(*names):
    return tuple(CONSTANTS[n] for n in names)


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
MAX_CALL_DEPTH = 150          # the grid dies with "Stack-Heap Collision" long before this
MAX_QUEUE = 64                # events queued per script; more are dropped silently
MAX_STATEMENTS = 2000000      # statements per event handler: beyond that the script is looping (sim.max_statements)
MAX_HANDLER_SECONDS = 20.0    # wall-clock time per event handler, for builtins that cost more than a statement
                              # (sim.max_handler_seconds)
RECURSION_LIMIT = 2500        # Python frames allowed while a handler runs: enough for MAX_CALL_DEPTH
MAX_NESTING = 120             # nested expressions or blocks the parser accepts (about 15 frames each)
PARSER_RECURSION_LIMIT = 3000 # Python frames the parser may use: MAX_NESTING levels and some margin
MAX_VECTOR_TRY = 4            # nested vector literals whose components get the two-pass parse
