"""
Home screen launcher with tool tiles and recent files.

Displays application branding and large tile buttons for each tool
(Database Editor, Startlist Generator), plus a recent CDB files list.
"""

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout,
    QWidget,
)

from core.constants import APP_NAME, APP_VERSION


class _Tile(QFrame):
    """Clickable coloured tile used on the home screen."""

    clicked = Signal()

    def __init__(self, title, description, color, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            f"_Tile {{ background: {color}; border-radius: 6px; }}"
            f"_Tile:hover {{ background: {_darken(color)}; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            "color: white; font-size: 14pt; font-weight: bold;"
            "background: transparent;"
        )
        layout.addWidget(title_lbl)

        desc_lbl = QLabel(description)
        desc_lbl.setStyleSheet(
            "color: #e0e0e0; font-size: 9pt; background: transparent;"
        )
        layout.addWidget(desc_lbl)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


def _darken(hex_color, factor=0.8):
    """Darken a hex colour by *factor* (0–1)."""
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    r, g, b = int(r * factor), int(g * factor), int(b * factor)
    return f"#{r:02x}{g:02x}{b:02x}"


class WelcomeScreen(QWidget):
    """Landing page / home screen shown when no tool is active."""

    load_requested = Signal(str)       # path (empty → file dialog)
    startlist_requested = Signal()

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.state = app_state
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # Centre the card vertically / horizontally
        outer.addStretch(1)
        h_center = QHBoxLayout()
        h_center.addStretch(1)

        card = QFrame()
        card.setStyleSheet(
            "QFrame { background: white; border: 1px solid #ddd;"
            "         border-radius: 8px; }"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(40, 40, 40, 40)

        # Title
        title = QLabel(APP_NAME)
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            "font-size: 24pt; font-weight: bold; color: #333;"
            "border: none; background: transparent;"
        )
        card_layout.addWidget(title)

        subtitle = QLabel(
            f"v{APP_VERSION} \u2014 Modding tools for Pro Cycling Manager"
        )
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet(
            "font-size: 10pt; color: #888; border: none;"
            "background: transparent; margin-bottom: 20px;"
        )
        card_layout.addWidget(subtitle)

        # Tiles
        tiles = QHBoxLayout()
        tiles.setSpacing(16)

        db_tile = _Tile("Database Editor",
                        "Open and edit CDB database files", "#007acc")
        db_tile.clicked.connect(lambda: self.load_requested.emit(""))
        tiles.addWidget(db_tile)

        sl_tile = _Tile("Startlist Generator",
                        "Generate startlists from HTML", "#2e8b57")
        sl_tile.clicked.connect(self.startlist_requested.emit)
        tiles.addWidget(sl_tile)

        card_layout.addLayout(tiles)

        # Recent files (populated dynamically)
        self._recents_container = QVBoxLayout()
        self._recents_container.setContentsMargins(0, 0, 0, 0)
        card_layout.addLayout(self._recents_container)

        h_center.addWidget(card)
        h_center.addStretch(1)
        outer.addLayout(h_center)
        outer.addStretch(1)

    # ------------------------------------------------------------------

    def refresh_recents(self):
        """Rebuild the recent-files section from current state."""
        # Clear previous items
        while self._recents_container.count():
            item = self._recents_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self.state.recents:
            return

        header = QLabel("Recent Databases")
        header.setStyleSheet(
            "font-size: 10pt; font-weight: bold; color: #777;"
            "border: none; background: transparent;"
            "margin-top: 16px; margin-bottom: 6px;"
        )
        self._recents_container.addWidget(header)

        for path in self.state.recents:
            display = (
                f"{os.path.basename(os.path.dirname(path))}"
                f"/{os.path.basename(path)}"
                if os.path.dirname(path) else path
            )
            btn = QPushButton(display)
            btn.setToolTip(path)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(
                "QPushButton { text-align: left; border: none;"
                "  background: #f9f9f9; color: #333; padding: 6px 10px; }"
                "QPushButton:hover { background: #eee; }"
            )
            btn.clicked.connect(lambda checked=False, p=path: self._load_recent(p))
            self._recents_container.addWidget(btn)

    def _load_recent(self, path):
        if not os.path.exists(path):
            QMessageBox.critical(self, "Error", f"File not found:\n{path}")
            if path in self.state.recents:
                self.state.recents.remove(path)
                self.refresh_recents()
            return
        self.load_requested.emit(path)
