"""Alphabetical ordering of tool and plugin menus, including submenus."""
from PySide6.QtCore import QCollator, QLocale, Qt


def alphabetize(menu, language):
    collator = QCollator(QLocale('en_US' if language == 'en' else 'ru_RU'))
    collator.setCaseSensitivity(Qt.CaseInsensitive)
    collator.setNumericMode(True)

    def sort_menu():
        # Keep separator groups intact if groups are added in the future.
        groups = [[]]
        for action in menu.actions():
            if action.isSeparator():
                groups.append([action])
                groups.append([])
            else:
                groups[-1].append(action)
        ordered = []
        for group in groups:
            ordered.extend(sorted(group, key=lambda action: collator.sortKey(action.text().replace('&', ''))))
        for action in ordered:
            menu.removeAction(action)
        for action in ordered:
            menu.addAction(action)

    for action in menu.actions():
        if action.menu() is not None:
            alphabetize(action.menu(), language)
    sort_menu()
    menu.aboutToShow.connect(sort_menu)
