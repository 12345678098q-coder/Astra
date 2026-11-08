"""Language shared by the interface and its processing workers."""

if __package__:
    from .translations_en import ENGLISH
else:  # cuda_support.py can run directly under the isolated installer Python.
    from translations_en import ENGLISH

LANGUAGES = {'ru': 'Русский', 'en': 'English'}
_language = 'ru'


def set_language(code):
    global _language
    _language = code if code in LANGUAGES else 'ru'
    return _language


def localize(source, english=None):
    if _language == 'en':
        return english if english is not None else ENGLISH.get(source, source)
    return source


def configure_interface(settings):
    """Select the saved language before constructing any widgets."""
    from PySide6.QtCore import QCoreApplication, QLibraryInfo, QLocale, Qt, QTranslator

    code = set_language(settings.value('language', 'ru'))
    app = QCoreApplication.instance()
    if getattr(app, '_astra_language', None) == code:
        return code
    locale = QLocale(code)
    QLocale.setDefault(locale)
    # Keep native Windows open/save dialogs for both interface languages.
    app.setAttribute(Qt.AA_DontUseNativeDialogs, False)
    previous = getattr(app, '_astra_translator', None)
    if previous is not None:
        app.removeTranslator(previous)
        previous.deleteLater()
        app._astra_translator = None
    if code != 'en':
        translator = QTranslator(app)
        if translator.load(locale, 'qtbase', '_', QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
            app.installTranslator(translator)
            app._astra_translator = translator
    app._astra_language = code
    return code
