"""Legacy compatibility exports for the neutral location resolver."""
from ats_worker.screening import location as _location

for _name in dir(_location):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_location, _name)

__all__ = [name for name in globals() if not name.startswith("_")] + [
    name for name in dir(_location) if name.startswith("_") and not name.startswith("__")
]
