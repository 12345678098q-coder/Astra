# Не включать в базовые архивы и установщики

`cuda/site-packages` содержит необязательные CuPy и CUDA-библиотеки.
Флаг исключения: `build-support/package-policy.json`,
`base_bundle_include_cuda: false`. Проверка: `build-support/check_package.py`.
Рабочие GPU-пакеты перенесены сюда из `.venv`; это не дубликат окружения.

Для установки с нуля откройте в Astra
**Настройки → Поддержка NVIDIA GPU** и скопируйте актуальную команду.
Для исходников из корня проекта в PowerShell:

    & ".\.venv\Scripts\python.exe" -m pip install --no-deps --target ".\optional\cuda\site-packages" -r ".\requirements-cuda.txt"

Перед установкой закройте Astra. Используйте Python этой Astra.
Не устанавливайте сюда NumPy: он уже находится в базовом окружении.
В `requirements-cuda.txt` перечислены все дополнительные зависимости.
После установки перезапустите приложение. Для работы нужна совместимая
NVIDIA GPU с драйвером. CPU не требует содержимого этой папки.

Каталог подключается через `core/gpu_runtime.py` только для GPU и его
настроек. Короткий путь Windows используется для совместимости NVRTC
с кириллицей в имени проекта. Не перемещайте DLL в System32.
