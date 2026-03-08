"""
PCM Database Tools - Main entry point.

A desktop application bundling modding tools for Pro Cycling Manager,
including a database editor and startlist generator.
"""

import sys

from PySide6.QtWidgets import QApplication

from core.constants import APP_VERSION
from ui.editor_gui import PCMDatabaseTools

__version__ = APP_VERSION

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = PCMDatabaseTools()
    window.show()
    sys.exit(app.exec())
