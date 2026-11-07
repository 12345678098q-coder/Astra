"""Expose Astra's language selection to standalone Palette Lab scripts."""
import sys
from pathlib import Path

if not __package__:
    # Training scripts and the standalone launcher import modules from this
    # directory directly, so the project root may be absent from sys.path.
    root = str(Path(__file__).resolve().parent.parent)
    if root not in sys.path:
        sys.path.insert(0, root)

from core.i18n import localize
