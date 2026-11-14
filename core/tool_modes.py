"""Shared extension point for full and quick tool interfaces.

Full mode keeps existing controls and explicit actions. Quick mode can define
its own visible fields and manual-run exceptions without changing full mode.
Add a ToolProfile here as each tool's quick interface is refined.
"""
from dataclasses import dataclass, field
from enum import Enum
from PySide6.QtWidgets import QWidget


class ToolMode(str, Enum):
    FULL = 'full'
    QUICK = 'quick'


@dataclass(frozen=True)
class ToolProfile:
    quick_fields: frozenset | None = None
    variants: dict = field(default_factory=dict)
    manual_when: dict = field(default_factory=dict)

    def visible_fields(self, mode, available, values=None):
        if mode == ToolMode.FULL: return set(available)
        values = values or {}
        allowed = self.quick_fields
        for (key, value), fields in self.variants.items():
            if values.get(key) == value: allowed = fields
        return set(available) if allowed is None else set(available) & set(allowed)

    def needs_apply(self, mode, values=None):
        if mode == ToolMode.FULL: return True
        return bool(self.manual_when and all((values or {}).get(k) == v for k,v in self.manual_when.items()))


PROFILES = {
    'rcastro:bxt':ToolProfile(quick_fields=frozenset()),
    'graxpert:deconv-stellar':ToolProfile(quick_fields=frozenset()),
    'graxpert:deconv-obj':ToolProfile(quick_fields=frozenset()),
    'crop': ToolProfile(quick_fields=frozenset({'preset'})),
    'graxpert:background-extraction': ToolProfile(
        variants={('method','AI'): frozenset({'method','smoothing'})},
        manual_when={'method':'RBF','correction':'Subtraction'}),
}
def profile_for(key):
    if key not in PROFILES:PROFILES[key]=ToolProfile()
    return PROFILES[key]


def mode_for(window):
    panel = getattr(window, 'tool_panel', None)
    return ToolMode.QUICK if panel is not None and panel.property('guidedEmbedded') else ToolMode.FULL


def configure_page(page, key, mode):
    """Give every tool page an explicit mode; new panels can add a mode hook."""
    if page.property('astraToolMode') == mode.value: return
    page.setProperty('astraToolMode', mode.value)
    page.setProperty('astraToolKey', key)
    # A specialized panel may implement set_tool_mode for a distinct quick UI.
    for widget in page.findChildren(QWidget):
        hook = getattr(widget, 'set_tool_mode', None)
        if callable(hook): hook(mode)
