"""Refresh the list of open images when a selector is opened."""
from PySide6.QtWidgets import QComboBox


class ImageSelector(QComboBox):
    def __init__(self, refresh):
        super().__init__()
        self.refresh_sources = refresh

    def showPopup(self):
        self.refresh_sources()
        super().showPopup()
