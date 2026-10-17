"""One version for the whole distribution: the installed package's, or the source tree's."""

try:
    from importlib.metadata import version as _dist_version
    __version__ = _dist_version("lslcheck")
except Exception:  # not installed: running from a checkout
    __version__ = "1.2.0"
