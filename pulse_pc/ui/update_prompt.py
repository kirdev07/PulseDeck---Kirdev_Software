"""«Обновление готово» — asked once the new installer has been downloaded in the background."""
from PySide6.QtWidgets import QMessageBox

from pulse_pc import __version__


def ask_to_install(window, updater):
    release = updater.release
    if release is None:
        return
    window.showNormal()
    window.raise_()
    window.activateWindow()
    box = QMessageBox(window)
    box.setWindowTitle("Обновление PulseDeck")
    box.setIcon(QMessageBox.Icon.Information)
    box.setText(f"Скачана новая версия {release.version} (у вас {__version__}).")
    notes = release.notes[:700]
    box.setInformativeText((notes + "\n\n" if notes else "") +
                           "PulseDeck закроется, установит её и запустится снова. Настройки, токен и телефоны сохранятся.")
    install = box.addButton("Установить сейчас", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Позже", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(install)
    box.exec()
    if box.clickedButton() is install:
        updater.install()
