"""Alphabetical ordering of tool and plugin menus, including submenus."""
from PySide6.QtCore import QCollator, QLocale, Qt
from core.i18n import localize


def label_tools(menu, entries, translate):
    labels = {}
    for key, (title, abbreviation, _) in entries.items():
        if key == 'native:batch':
            continue
        title = localize(title)
        base = title.split(' · ')[0]
        labels[title] = f'{base} · {abbreviation}'
    labels[translate('Отделение звёзд - StarNet', 'Separate stars - StarNet')] = translate(
        'Отделение звёзд · SN', 'Star separation · SN')
    labels['SCNR'] = translate('Подавление цветового шума · SCNR', 'Chromatic noise reduction · SCNR')
    for ru, en, abbreviation in (
        ('Удаление градиента', 'Background extraction', 'GX-G'),
        ('Шумоподавление', 'Denoising', 'GX-N'),
        ('Деконволюция объекта', 'Object deconvolution', 'GX-O'),
        ('Деконволюция звёзд', 'Stellar deconvolution', 'GX-S'),
    ):
        title = translate(ru, en)
        labels[title] = f'{title} · {abbreviation}'
    for action in menu.actions():
        if action.menu() is not None:
            label_tools(action.menu(), entries, translate)
        elif action.text() in labels:
            action.setText(labels[action.text()])


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
            ordered.extend(sorted(group, key=lambda action: (
                not bool(action.property('astraMenuFirst')),
                collator.sortKey(action.text().replace('&', '')))))
        for action in ordered:
            menu.removeAction(action)
        for action in ordered:
            menu.addAction(action)

    for action in menu.actions():
        if action.menu() is not None:
            alphabetize(action.menu(), language)
    sort_menu()
    menu.aboutToShow.connect(sort_menu)
