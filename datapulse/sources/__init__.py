"""Source auto-discovery.

Dropping a new module in this package is enough — it is imported on startup
and its `@register`ed classes join the registry. No central list to update.
"""

from __future__ import annotations

import importlib
import pkgutil

for _mod in pkgutil.iter_modules(__path__):
    if not _mod.name.startswith("_"):
        importlib.import_module(f"{__name__}.{_mod.name}")
