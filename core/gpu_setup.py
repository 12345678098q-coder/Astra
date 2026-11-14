"""Installation guidance targets the exact interpreter running Astra."""
from core.responsive import fit_screen
from core.i18n import localize
import json
import sys
from pathlib import Path
from PySide6.QtWidgets import QDialog,QVBoxLayout,QLabel,QPushButton,QProgressBar,QMessageBox
from PySide6.QtCore import QThread,Signal,QProcess,QProcessEnvironment
from .gpu_runtime import runtime_path
from .cuda_support import CUDA_ARCHIVE_URL

def installation_details():
 exe=Path(sys.executable)
 if exe.name.lower()=='pythonw.exe':exe=exe.with_name('python.exe')
 requirements=Path(__file__).resolve().parent.parent/'requirements-cuda.txt'
 if not requirements.is_file():requirements=requirements.parent/'build-support'/requirements.name
 command=f'& "{exe}" -m pip install --no-deps --target "{runtime_path()}" -r "{requirements}"'
 return exe,requirements,command

class GpuCheck(QThread):
    result=Signal(object)
    def run(self):
        from .cuda_support import detect_driver,verify_runtime
        info=detect_driver();info['installed']=False
        if info['compatible'] and (runtime_path()/'cupy').is_dir():
            try:verify_runtime(runtime_path());info['installed']=True
            except Exception as error:info['runtime_error']=str(error)
        self.result.emit(info)

class GpuSetupDialog(QDialog):
    def __init__(self,owner,parent=None):
        super().__init__(parent if parent is not None else owner);self.owner=owner;self.tr=owner.trtext;self.info={};self.process=None;self.output=''
        self.setWindowTitle(self.tr('Поддержка NVIDIA GPU','NVIDIA GPU support'));fit_screen(self,0.5,0.289)
        layout=QVBoxLayout(self);self.status=QLabel(self.tr('Проверка видеокарты и драйвера…','Checking GPU and driver…'));self.status.setWordWrap(True);layout.addWidget(self.status)
        hint=QLabel(self.tr('Для CUDA нужна совместимая видеокарта NVIDIA и драйвер. Библиотеки устанавливаются в отдельную папку Astra.','CUDA requires a compatible NVIDIA GPU and driver. Libraries are installed in a separate Astra folder.'));hint.setWordWrap(True);layout.addWidget(hint)
        path=QLabel(self.tr('Папка установки: ','Installation folder: ')+str(runtime_path()));path.setWordWrap(True);layout.addWidget(path)
        source=QLabel(f'<a href="{CUDA_ARCHIVE_URL}">Astra-CUDA.zip</a>');source.setOpenExternalLinks(True);layout.addWidget(source)
        self.progress=QProgressBar();self.progress.setRange(0,0);layout.addWidget(self.progress)
        self.install_button=QPushButton(self.tr('Скачать и установить CUDA с GitHub','Download and install CUDA from GitHub'));self.install_button.setEnabled(False);self.install_button.clicked.connect(self.install);layout.addWidget(self.install_button)
        self.close_button=QPushButton(self.tr('Закрыть','Close'));self.close_button.clicked.connect(self.reject);layout.addWidget(self.close_button)
        self.check=GpuCheck(self);self.check.result.connect(self.checked);self.check.finished.connect(self.check_finished);self.check.start()
    def checked(self,info):
        self.info=info;self.progress.hide()
        if not info['compatible']:
            self.status.setText(self.tr('Установка CUDA недоступна. ','CUDA installation unavailable. ')+info.get('reason',localize('Нужна NVIDIA и драйвер.')))
            self.install_button.setEnabled(False)
        elif info['installed']:
            self.status.setText(info['name']+'\n'+self.tr('CUDA установлена, вычисления проверены.','CUDA is installed and computation verified.'));self.install_button.setText(self.tr('CUDA уже установлена','CUDA already installed'))
        else:
            self.status.setText(info['name']+'\n'+self.tr('Можно установить CUDA.','CUDA can be installed.'));self.install_button.setEnabled(True)
            if info.get('runtime_error'):self.status.setText(self.status.text()+'\n'+self.tr('Текущая библиотека не прошла проверку. Требуется переустановка.','The current runtime failed verification and needs reinstalling.'))
    def check_finished(self):
        if getattr(self,'close_when_ready',False):super().reject()
    def install(self):
        from .resources import heavy_job_running
        if not self.info.get('compatible') or heavy_job_running(self.owner):return
        if 'cupy' in sys.modules:
            QMessageBox.information(self,'CUDA',self.tr('Перезапустите Astra и откройте установку до запуска инструментов на GPU.','Restart Astra and open setup before using GPU tools.'));return
        exe,requirements,_=installation_details()
        process=QProcess(self);self.process=process;self.owner.cuda_install_process=process
        environment=QProcessEnvironment.systemEnvironment();environment.insert('ASTRA_LANGUAGE',self.owner.lang);environment.insert('PYTHONUTF8','1');environment.insert('PYTHONUNBUFFERED','1');process.setProcessEnvironment(environment)
        process.setProcessChannelMode(QProcess.MergedChannels)
        self.output=''
        def read_output():self.output=(self.output+bytes(process.readAllStandardOutput()).decode('utf-8',errors='replace'))[-8000:]
        process.readyReadStandardOutput.connect(read_output)
        self.install_button.setEnabled(False);self.close_button.setEnabled(False);self.progress.show();self.status.setText(self.tr('Загрузка, установка и проверка CUDA…','Downloading, installing and verifying CUDA…'))
        def finished(code,status):
            read_output()
            self.progress.hide();self.close_button.setEnabled(True)
            if code==0 and status==QProcess.NormalExit:
                self.owner.stack_options['device'] = 'auto'
                self.owner.settings.setValue('stack_options', json.dumps(self.owner.stack_options))
                self.status.setText(self.tr(
                    'CUDA установлена. Для сложения включён режим «Авто: CUDA / CPU».',
                    'CUDA is installed. Stacking now uses Auto: CUDA / CPU.'))
                self.install_button.setText(self.tr('Установлено','Installed'))
            else:
                self.status.setText(self.tr('Установка не завершена. Можно повторить попытку.','Installation failed. You can retry.'));self.install_button.setEnabled(True)
                lines=[line.strip() for line in self.output.splitlines() if line.strip()]
                if lines:QMessageBox.warning(self,'CUDA',lines[-1][-500:])
        process.finished.connect(finished)
        def failed(error):
            if error==QProcess.FailedToStart:
                self.output=process.errorString();finished(-1,QProcess.CrashExit)
        process.errorOccurred.connect(failed)
        process.start(str(exe),['-u','-B',str(Path(__file__).with_name('cuda_support.py')),str(runtime_path()),'--github'])
    def reject(self):
        if self.process is not None and self.process.state()!=QProcess.NotRunning:return
        if self.check.isRunning():self.close_when_ready=True;return
        super().reject()
    def closeEvent(self,event):
        if (self.process is not None and self.process.state()!=QProcess.NotRunning) or self.check.isRunning():self.reject();event.ignore()
        else:super().closeEvent(event)

def show_gpu_setup(owner, parent=None):
    GpuSetupDialog(owner, parent).exec()
