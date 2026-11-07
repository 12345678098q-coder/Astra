"""Official download links and read-only detection of the required GraXpert version."""
import re
from pathlib import Path
from PySide6.QtWidgets import QWidget,QVBoxLayout,QLabel
from .tool_updates import find_tool,GRA_VERSION

GRAXPERT_URL='https://github.com/Steffenhir/GraXpert/releases/tag/'+GRA_VERSION
STARNET_URL='https://starnetastro.com/cli-tools/starnet/'


def graxpert_version(executable):
    if executable is None:return None
    home=Path(executable).parent
    for relative in ('lib/graxpert/version.pyc','graxpert/version.py','lib/graxpert/version.py'):
        path=home/relative
        try:
            if path.stat().st_size>65536:continue
            found=re.search(rb'\d+\.\d+\.\d+(?:rc\d+|b\d+)?',path.read_bytes())
            if found:return found[0].decode('ascii')
        except OSError:continue
    return None


class DownloadLinks(QWidget):
    def __init__(self,owner,path=None):
        super().__init__();self.owner=owner;layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.graxpert=QLabel();self.graxpert.setWordWrap(True);self.graxpert.setOpenExternalLinks(True);layout.addWidget(self.graxpert)
        self.starnet=QLabel('<a href="'+STARNET_URL+'">'+owner.trtext('Скачать StarNet CLI с официального сайта','Download StarNet CLI from the official website')+'</a><br>'+owner.trtext('ZIP распакуйте в tools/starnet внутри папки Astra. Также доступна установка из окна инструмента StarNet.','Extract the ZIP into tools/starnet inside Astra. Installation is also available in the StarNet tool panel.'))
        self.starnet.setWordWrap(True);self.starnet.setOpenExternalLinks(True);layout.addWidget(self.starnet)
        self.set_graxpert_path(path if path is not None else str(owner.settings.value('external/graxpert','')))
    def set_graxpert_path(self,path):
        exe=find_tool('graxpert',str(path));version=graxpert_version(exe);tr=self.owner.trtext
        if exe is None:status=tr('GraXpert не установлен. Нужна версия ','GraXpert is not installed. Required version: ')+GRA_VERSION
        elif version is None:status=tr('Версию GraXpert определить не удалось. Нужна ','Could not detect the GraXpert version. Required: ')+GRA_VERSION
        elif version!=GRA_VERSION:status=tr('Установлен GraXpert {version}, нужна версия {required}.','GraXpert {version} is installed; {required} is required.').format(version=version,required=GRA_VERSION)
        else:status=tr('Установлена нужная версия GraXpert: ','Required GraXpert version is installed: ')+version
        if version!=GRA_VERSION:status+='<br><a href="'+GRAXPERT_URL+'">'+tr('Скачать GraXpert ','Download GraXpert ')+GRA_VERSION+'</a>'
        self.graxpert.setText(status)
