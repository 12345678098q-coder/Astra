"""Group the existing tool actions while retaining a complete tool list."""
from PySide6.QtWidgets import QMenu
def organize(menu, translate):
    original=list(menu.actions())
    for action in original:menu.removeAction(action)
    all_tools=menu.addMenu(translate('Все инструменты','All tools'))
    all_tools.menuAction().setProperty('astraMenuFirst', True)
    groups = [
        (('Фон и градиенты', 'Background and gradients'),
         ('фон', 'градиент', 'background', 'gradient')),
        (('Цвет и палитры', 'Color and palettes'),
         ('цвет', 'палитр', 'кислород', 'узкополос', 'narrowband', 'palette', 'color',
          'oxygen', 'linearfit', 'согласование яркости', 'brightness matching', 'linear fit', 'scnr')),
        (('Растяжение и контраст', 'Stretch and contrast'),
         ('растяж', 'гистограмм', 'крив', 'контраст', 'stretch', 'histogram', 'curve', 'contrast', 'lhe', 'hdr')),
        (('Шум и дефекты', 'Noise and defects'),
         ('шум', 'полос', 'горячие', 'холодные', 'пиксел', 'кисть', 'штамп',
          'nois', 'banding', 'hot', 'cold', 'heal', 'clone', 'defect')),
        (('Резкость и восстановление', 'Sharpness and restoration'),
         ('смаз', 'резк', 'коррекция краёв', 'деконвол', 'deconvol', 'sharp', 'blur',
          'edge correction', 'signal booster')),
        (('Звёзды', 'Stars'),
         ('звёзд', 'звезд', 'star', 'stellar')),
        (('Геометрия и совмещение', 'Geometry and alignment'),
         ('кадрирован', 'crop', 'advanced calibration', 'расширенная калибровка', 'alignment', 'совмещ', 'выравнивание по')),
        (('Маски и PixelMath', 'Masks and PixelMath'),
         ('маск', 'mask', 'pixelmath')),
        (('Анализ и автоматизация', 'Analysis and automation'),
         ('анализ', 'analysis', 'астрометр', 'astrometr', 'пакет', 'batch', 'автомат',
          'automat', 'sequence', 'последователь')),
    ]
    categories = [(menu.addMenu(translate(*names)), terms) for names, terms in groups]
    other = menu.addMenu(translate('Другие инструменты', 'Other tools'))
    def category_for(action):
        text = action.text().casefold()
        # Alignment mentions stars, but belongs with geometric operations.
        if 'global star alignment' in text or 'глобальное выравнивание' in text:
            return categories[6][0]
        if 'pixelmath' in text:
            return categories[7][0]
        return next((category for category, terms in categories
                     if any(term in text for term in terms)), other)
    def distribute(actions):
        distributed={}
        for action in actions:
            submenu=action.menu()
            if action.isSeparator():continue
            if submenu is None:
                distributed.setdefault(category_for(action),[]).append(action)
                continue
            for category,children in distribute(submenu.actions()).items():
                # Reuse the processing actions, but show only the relevant
                # operations of a provider in each category.
                filtered=QMenu(action.text(),category)
                for child in children:filtered.addAction(child)
                distributed.setdefault(category,[]).append(filtered.menuAction())
        return distributed
    for action in original:all_tools.addAction(action)
    for category,actions in distribute(original).items():
        for action in actions:category.addAction(action)
    for category, _ in categories:
        category.menuAction().setVisible(bool(category.actions()))
    other.menuAction().setVisible(bool(other.actions()))
