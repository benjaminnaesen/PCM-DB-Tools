"""
Home screen launcher with tool tiles and recent files.

Displays application branding and large tile buttons for each tool
(Database Editor, Startlist Generator), plus a recent CDB files list.
"""

import tkinter as tk
import os
from tkinter import messagebox
from core.constants import APP_NAME, APP_VERSION
from ui.ui_utils import ToolTip


class WelcomeScreen:
    """Landing page / home screen shown when no tool is active.

    Features:
        - Two large tile buttons: Database Editor, Startlist Generator
        - Recent CDB files list with full path tooltips
        - Auto-removes missing files from recent list
    """

    def __init__(self, root_frame, app_state, load_callback, startlist_callback):
        """Initialize home screen.

        Args:
            root_frame: Parent tkinter frame
            app_state (AppState): Application state manager
            load_callback (callable): Function to call when opening a CDB file
            startlist_callback (callable): Function to call when opening startlist generator
        """
        self.frame = root_frame
        self.state = app_state
        self.load_callback = load_callback
        self.startlist_callback = startlist_callback

    def show(self):
        """Display the home screen with tool tiles and recent files."""
        for widget in self.frame.winfo_children():
            widget.destroy()
        self.frame.pack(fill=tk.BOTH, expand=True)

        container = tk.Frame(self.frame, bg="white", padx=40, pady=40,
                             relief="raised", bd=1)
        container.place(relx=0.5, rely=0.5, anchor="center")

        # Title
        tk.Label(
            container, text=APP_NAME,
            font=("Segoe UI", 24, "bold"), bg="white", fg="#333",
        ).pack(pady=(0, 4))
        tk.Label(
            container, text=f"v{APP_VERSION} — Modding tools for Pro Cycling Manager",
            font=("Segoe UI", 10), bg="white", fg="#888",
        ).pack(pady=(0, 24))

        # Tool tiles
        tiles = tk.Frame(container, bg="white")
        tiles.pack(fill=tk.X, pady=(0, 20))
        tiles.columnconfigure(0, weight=1)
        tiles.columnconfigure(1, weight=1)

        self._create_tile(
            tiles, column=0,
            title="Database Editor",
            description="Open and edit CDB database files",
            color="#007acc",
            command=lambda: self.load_callback(),
        )
        self._create_tile(
            tiles, column=1,
            title="Startlist Generator",
            description="Generate startlists from HTML",
            color="#2e8b57",
            command=self.startlist_callback,
        )

        # Recent files
        if self.state.recents:
            tk.Label(
                container, text="Recent Databases",
                font=("Segoe UI", 10, "bold"), bg="white", fg="#777",
                anchor="w",
            ).pack(fill=tk.X, pady=(8, 5))

            for path in self.state.recents:
                display = (f"{os.path.basename(os.path.dirname(path))}"
                           f"/{os.path.basename(path)}"
                           if os.path.dirname(path) else path)
                btn = tk.Button(
                    container, text=display,
                    command=lambda p=path: self.load_recent(p),
                    anchor="w", relief="flat", bg="#f9f9f9", fg="#333",
                    padx=10, pady=5, cursor="hand2",
                )
                btn.pack(fill=tk.X, pady=1)
                ToolTip(btn, path)

    def _create_tile(self, parent, column, title, description, color, command):
        """Create a large clickable tile button."""
        tile = tk.Frame(
            parent, bg=color, cursor="hand2",
            padx=24, pady=20,
        )
        tile.grid(row=0, column=column, padx=8, sticky="nsew")

        title_lbl = tk.Label(
            tile, text=title,
            font=("Segoe UI", 14, "bold"), bg=color, fg="white",
        )
        title_lbl.pack(anchor="w")

        desc_lbl = tk.Label(
            tile, text=description,
            font=("Segoe UI", 9), bg=color, fg="#e0e0e0",
        )
        desc_lbl.pack(anchor="w", pady=(4, 0))

        # Make the whole tile clickable
        for widget in (tile, title_lbl, desc_lbl):
            widget.bind("<Button-1>", lambda e, cmd=command: cmd())

    def load_recent(self, path):
        """Load a recent file, removing it from list if not found."""
        if not os.path.exists(path):
            messagebox.showerror("Error", f"File not found:\n{path}")
            if path in self.state.recents:
                self.state.recents.remove(path)
                self.show()
            return
        self.load_callback(path)

    def hide(self):
        """Hide the home screen."""
        self.frame.pack_forget()
