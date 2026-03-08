"""
PCM Database Tools - Main entry point.

A desktop application bundling modding tools for Pro Cycling Manager,
including a database editor and startlist generator.
"""

import tkinter as tk

from core.constants import APP_VERSION
from ui.editor_gui import PCMDatabaseTools

__version__ = APP_VERSION

if __name__ == "__main__":
    root = tk.Tk()
    app = PCMDatabaseTools(root)
    root.mainloop()
