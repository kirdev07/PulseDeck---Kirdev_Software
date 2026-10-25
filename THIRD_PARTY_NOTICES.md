# Сторонние компоненты Pulse-PC

Pulse-PC использует следующие библиотеки с открытым исходным кодом. Версии — те, с которыми
собирается текущая версия; актуальный список установленных компонентов показан в программе:
«Настройки → Лицензия и компоненты».

| Компонент | Версия | Лицензия | Проект |
|---|---|---|---|
| PySide6 | 6.12.0 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | https://pyside.org |
| aiogram | 3.31.0 | MIT | https://aiogram.dev/ |
| aiohttp | 3.14.5 | Apache-2.0 AND MIT | https://github.com/aio-libs/aiohttp |
| python-dotenv | 1.2.4 | BSD-3-Clause | https://github.com/theskumar/python-dotenv |
| psutil | 7.2.2 | BSD-3-Clause | https://github.com/giampaolo/psutil |
| PyAutoGUI | 0.9.54 | BSD | https://github.com/asweigart/pyautogui |
| pywin32 | 312 | PSF | https://github.com/mhammond/pywin32 |
| mss | 10.2.0 | MIT License | https://github.com/BoboTiG/python-mss |
| pillow | 13.0.0 | MIT-CMU | https://pillow.readthedocs.io/en/stable/releasenotes/index.html |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause | https://github.com/pyca/cryptography |
| pycaw | 20260927 | MIT | https://github.com/AndreMiras/pycaw |
| winrt-runtime | 4.0.3 | MIT | https://pywinrt.readthedocs.io |
| winrt-Windows.Media.Control | 4!10.0.28000.2705 | MIT | https://pywinrt.readthedocs.io |
| Python | 3.x | PSF License | https://www.python.org |

Плюс зависимости перечисленных библиотек (например, `cffi` для `cryptography`, `comtypes` для
`pycaw`), каждая под своей лицензией.

## Qt и PySide6 (LGPLv3)

Интерфейс построен на Qt for Python (PySide6) и Qt, распространяемых по GNU Lesser General Public
License v3. Pulse-PC подключает их динамически: библиотеки Qt лежат в папке программы отдельными
файлами, и вы вправе заменить их совместимой версией. Исходный код Qt и PySide6:
https://code.qt.io и https://download.qt.io/official_releases/QtForPython/ .
Текст лицензии: https://www.gnu.org/licenses/lgpl-3.0.html

Лицензия Pulse-PC (см. `LICENSE`) относится только к собственному коду Pulse-PC и не ограничивает
ваши права на сторонние компоненты по их лицензиям.

## Иконки

Иконки интерфейса нарисованы для Pulse-PC и распространяются вместе с программой.
