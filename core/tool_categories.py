"""Group the existing tool actions while retaining a complete tool list."""
def organize(menu, translate):
    original=list(menu.actions())
    for action in original:menu.removeAction(action)
    all_tools=menu.addMenu(translate('Все инструменты','All tools'))
    groups=[
        (('Фон и цвет','Background and color'),('фон','градиент','цвет','палитр','кислород','palette','color','background','oxygen','linearfit','scnr')),
        (('Растяжение и контраст','Stretch and contrast'),('растяж','гистограмм','крив','контраст','stretch','histogram','curve','contrast','lhe','hdr')),
        (('Детали, шум и звёзды','Details, noise and stars'),('шум','звёзд','звезд','смаз','резк','graxpert','rc-astro','starnet','noise','star','detail','sharp','blur','деконвол')),
        (('Геометрия и исправления','Geometry and corrections'),('кадр','пиксел','кисть','штамп','crop','pixel','heal','clone','defect')),
    ]
    categories=[(menu.addMenu(translate(*names)),terms) for names,terms in groups]
    other=menu.addMenu(translate('Маски, анализ и прочее','Masks, analysis and other'))
    for action in original:
        all_tools.addAction(action)
        text=action.text().casefold()
        target=next((category for category,terms in categories if any(term in text for term in terms)),other)
        target.addAction(action)
