"""
Sidebar widget for table navigation and favorites management.

Provides a two-section sidebar with favorites at the top and
filterable table list below, supporting drag-and-drop reordering.
"""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QLabel, QLineEdit, QListWidget,
    QMenu, QVBoxLayout, QWidget,
)

from core.constants import FILTER_DEBOUNCE_DELAY


class Sidebar(QWidget):
    """Navigation sidebar for browsing and selecting database tables."""

    table_selected = Signal(str)

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.state = app_state
        self.all_tables: list[str] = []
        self._cur_fav_index = 0

        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(FILTER_DEBOUNCE_DELAY)
        self._filter_timer.timeout.connect(self._execute_filter)

        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Favorites header
        fav_header = QLabel(" \u2b50 FAVORITES")
        fav_header.setStyleSheet(
            "background: #e0e0e0; font-size: 8pt; font-weight: bold;"
            "padding: 4px; color: #333;"
        )
        layout.addWidget(fav_header)

        # Favorites list (drag-drop reorder)
        self.fav_list = QListWidget()
        self.fav_list.setMaximumHeight(130)
        self.fav_list.setStyleSheet(
            "QListWidget { background: #f5f5f5; border: none; }"
            "QListWidget::item { padding: 3px 6px; }"
            "QListWidget::item:selected { background: #cce5ff; color: #000; }"
        )
        self.fav_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.fav_list.setDefaultDropAction(Qt.MoveAction)
        self.fav_list.itemClicked.connect(
            lambda item: self.table_selected.emit(item.text()))
        self.fav_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.fav_list.customContextMenuRequested.connect(
            lambda pos: self._show_menu(self.fav_list, pos))
        self.fav_list.model().rowsMoved.connect(self._on_fav_reordered)
        layout.addWidget(self.fav_list)

        # Tables header
        tbl_header = QLabel(" TABLES")
        tbl_header.setStyleSheet(
            "background: #e0e0e0; font-size: 8pt;"
            "font-weight: bold; padding: 4px; color: #333;"
        )
        layout.addWidget(tbl_header)

        # Filter search box
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Filter tables\u2026")
        self._filter_edit.setClearButtonEnabled(True)
        self._filter_edit.textChanged.connect(lambda: self._filter_timer.start())
        self._filter_edit.setStyleSheet("margin: 4px; padding: 3px;")
        layout.addWidget(self._filter_edit)

        # Tables list
        self.table_list = QListWidget()
        self.table_list.setAlternatingRowColors(True)
        self.table_list.setStyleSheet(
            "QListWidget { border: none; }"
            "QListWidget::item { padding: 3px 6px; }"
            "QListWidget::item:alternate { background: #f4f4f4; }"
            "QListWidget::item:selected { background: #cce5ff; color: #000; }"
        )
        self.table_list.itemClicked.connect(
            lambda item: self.table_selected.emit(item.text()))
        self.table_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table_list.customContextMenuRequested.connect(
            lambda pos: self._show_menu(self.table_list, pos))
        layout.addWidget(self.table_list, 1)  # stretch

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_tables(self, tables):
        """Populate the sidebar with table names."""
        self.all_tables = tables
        self._execute_filter()
        self.refresh_favorites()

    def refresh_favorites(self):
        """Reload the favorites list from app state."""
        self.fav_list.clear()
        for name in self.state.favorites:
            if name in self.all_tables:
                self.fav_list.addItem(name)

    def select_first_favorite(self):
        """Auto-select the first favourite if available."""
        if self.fav_list.count() > 0:
            self.fav_list.setCurrentRow(0)
            self.table_selected.emit(self.fav_list.item(0).text())

    # ------------------------------------------------------------------
    # Filter
    # ------------------------------------------------------------------

    def _execute_filter(self):
        term = self._filter_edit.text().lower()
        self.table_list.clear()
        for name in self.all_tables:
            if term in name.lower():
                self.table_list.addItem(name)

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def _show_menu(self, widget, pos):
        item = widget.itemAt(pos)
        if not item:
            return
        name = item.text()

        menu = QMenu(self)
        if name in self.state.favorites:
            menu.addAction("\u274c Remove Favorite",
                           lambda: self._remove_favorite(name))
        else:
            menu.addAction("\u2b50 Add Favorite",
                           lambda: self._add_favorite(name))
        menu.exec(widget.mapToGlobal(pos))

    def _add_favorite(self, name):
        if name not in self.state.favorites:
            self.state.favorites.append(name)
            self.refresh_favorites()

    def _remove_favorite(self, name):
        if name in self.state.favorites:
            self.state.favorites.remove(name)
            self.refresh_favorites()

    # ------------------------------------------------------------------
    # Drag-drop reorder callback
    # ------------------------------------------------------------------

    def _on_fav_reordered(self):
        visible = [self.fav_list.item(i).text()
                   for i in range(self.fav_list.count())]
        hidden = [f for f in self.state.favorites if f not in visible]
        self.state.favorites = visible + hidden
