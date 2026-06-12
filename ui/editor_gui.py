"""
Main application window and controller.

Coordinates the home screen, database editor, and startlist generator,
manages file operations, and handles application lifecycle.
"""

import gc
import os

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMainWindow, QMenu, QMessageBox, QPushButton, QSplitter,
    QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from core.db_manager import DatabaseManager
from core.app_state import AppState
from core.constants import (
    APP_NAME, APP_VERSION, DEFAULT_WINDOW_HEIGHT, DEFAULT_WINDOW_WIDTH,
    SEARCH_DEBOUNCE_DELAY,
)
import core.converter as converter
import core.csv_io as csv_io
from ui.welcome_screen import WelcomeScreen
from ui.ui_utils import run_async
from ui.sidebar import Sidebar
from ui.table_view import TableView
from ui.column_manager_dialog import ColumnManagerDialog
from ui.startlist_view import StartlistView


class PCMDatabaseTools(QMainWindow):
    """Main application window for PCM Database Tools."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.state = AppState("session_config.json")

        # Window geometry
        size = self.state.settings.get("window_size", "1200x800")
        try:
            w, h = (int(x) for x in size.split("x")[:2])
        except (ValueError, IndexError):
            w, h = DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT
        self.resize(w, h)

        if self.state.settings.get("is_maximized", False):
            self.showMaximized()

        self.db = None
        self.temp_path = None
        self.all_tables = []
        self.current_table = None
        self.unsaved_changes = False

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(SEARCH_DEBOUNCE_DELAY)
        self._search_timer.timeout.connect(self._execute_search)

        self._build_ui()

        QShortcut(QKeySequence.Undo, self, self.undo)
        QShortcut(QKeySequence.Redo, self, self.redo)

    # ==================================================================
    # UI Setup
    # ==================================================================

    def _build_ui(self):
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        # Page 0: Welcome screen
        self.welcome_screen = WelcomeScreen(self.state)
        self.welcome_screen.load_requested.connect(self.load_cdb)
        self.welcome_screen.startlist_requested.connect(self.show_startlist)
        self.stack.addWidget(self.welcome_screen)

        # Page 1: Editor — force light mode regardless of system theme
        editor_page = QWidget()
        editor_page.setStyleSheet(
            "QWidget { background-color: #f0f0f0; color: #212121; }"
            "QPushButton {"
            "  background-color: #e1e1e1; color: #212121;"
            "  border: 1px solid #adadad; border-radius: 2px; padding: 4px 10px;"
            "}"
            "QPushButton:hover { background-color: #e5f1fb; border-color: #0078d4; }"
            "QPushButton:pressed { background-color: #cce4f7; }"
            "QPushButton:checked { background-color: #cce4f7; border-color: #0078d4; }"
            "QPushButton:disabled { color: #a0a0a0; background-color: #f0f0f0; }"
            "QToolButton {"
            "  background-color: #e1e1e1; color: #212121;"
            "  border: 1px solid #adadad; border-radius: 2px; padding: 4px 10px;"
            "}"
            "QToolButton::menu-indicator { image: none; }"
            "QLineEdit {"
            "  background-color: #ffffff; color: #212121;"
            "  border: 1px solid #adadad; border-radius: 2px; padding: 2px 4px;"
            "}"
            "QLabel { background-color: transparent; color: #212121; }"
            "QScrollBar:vertical { background-color: #f0f0f0; width: 14px; border: none; }"
            "QScrollBar::handle:vertical { background-color: #c0c0c0; border-radius: 3px; min-height: 20px; }"
            "QScrollBar:horizontal { background-color: #f0f0f0; height: 14px; border: none; }"
            "QScrollBar::handle:horizontal { background-color: #c0c0c0; border-radius: 3px; min-width: 20px; }"
            "QMenu { background-color: #ffffff; color: #212121; border: 1px solid #ccc; }"
            "QMenu::item:selected { background-color: #0078d4; color: #ffffff; }"
            "QSplitter::handle { background-color: #d0d0d0; }"
        )
        editor_layout = QVBoxLayout(editor_page)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(0)

        self._build_toolbar(editor_layout)

        splitter = QSplitter(Qt.Horizontal)
        self.sidebar = Sidebar(self.state)
        self.sidebar.table_selected.connect(self._on_table_select)
        self.sidebar.setFixedWidth(220)
        splitter.addWidget(self.sidebar)

        self.table_view = TableView(self.state)
        self.table_view.data_changed.connect(self._on_data_change)
        self.table_view.selection_changed.connect(self._on_selection_change)
        splitter.addWidget(self.table_view)
        splitter.setStretchFactor(1, 1)

        editor_layout.addWidget(splitter, 1)
        self.stack.addWidget(editor_page)

        # Page 2: Startlist
        self.startlist_view = StartlistView(app_state=self.state)
        self.startlist_view.go_home.connect(self.show_home)
        self.stack.addWidget(self.startlist_view)

        # Status bar
        self.status_label = QLabel("Ready")
        self.statusBar().addWidget(self.status_label, 1)
        self.selection_label = QLabel("")
        self.statusBar().addPermanentWidget(self.selection_label)

        self.show_home()

    def _build_toolbar(self, parent_layout):
        toolbar = QWidget()
        toolbar.setObjectName("editorToolbar")
        toolbar.setStyleSheet(
            "#editorToolbar { border-bottom: 1px solid #ccc; }"
        )
        tb = QHBoxLayout(toolbar)
        tb.setContentsMargins(8, 8, 8, 8)

        # Left buttons
        close_btn = QPushButton("\u2190 Close CDB")
        close_btn.clicked.connect(self.close_cdb)
        tb.addWidget(close_btn)

        open_btn = QPushButton("Open CDB")
        open_btn.clicked.connect(lambda: self.load_cdb(""))
        tb.addWidget(open_btn)

        save_btn = QPushButton("Save As\u2026")
        save_btn.clicked.connect(self.save_as_cdb)
        tb.addWidget(save_btn)

        # Tools menu button
        self.tools_button = QToolButton()
        self.tools_button.setText("Tools")
        self.tools_button.setPopupMode(QToolButton.InstantPopup)
        self._build_tools_menu()
        tb.addWidget(self.tools_button)

        self.undo_btn = QPushButton("\u21b6 Undo")
        self.undo_btn.setEnabled(False)
        self.undo_btn.clicked.connect(self.undo)
        tb.addWidget(self.undo_btn)

        self.redo_btn = QPushButton("\u21b7 Redo")
        self.redo_btn.setEnabled(False)
        self.redo_btn.clicked.connect(self.redo)
        tb.addWidget(self.redo_btn)

        add_btn = QPushButton("Add Row")
        add_btn.clicked.connect(lambda: self.table_view.add_row())
        tb.addWidget(add_btn)

        del_btn = QPushButton("Remove Row")
        del_btn.clicked.connect(lambda: self.table_view.delete_row())
        tb.addWidget(del_btn)

        clear_btn = QPushButton("Clear Table")
        clear_btn.clicked.connect(self.clear_table)
        tb.addWidget(clear_btn)

        tb.addStretch()

        # Right side: columns, lookup, search
        col_btn = QPushButton("Columns")
        col_btn.clicked.connect(self.open_column_manager)
        tb.addWidget(col_btn)

        self.lookup_btn = QPushButton("Lookup: OFF")
        self.lookup_btn.setCheckable(True)
        self.lookup_btn.setChecked(
            self.state.settings.get("lookup_mode", False))
        if self.lookup_btn.isChecked():
            self.lookup_btn.setText("Lookup: ON")
        self.lookup_btn.toggled.connect(self._on_lookup_toggled)
        tb.addWidget(self.lookup_btn)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search\u2026")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setFixedWidth(300)
        self.search_edit.textChanged.connect(
            lambda: self._search_timer.start())
        tb.addWidget(self.search_edit)

        parent_layout.addWidget(toolbar)

    def _build_tools_menu(self):
        menu = QMenu(self)

        # Career submenu
        self.career_menu = menu.addMenu("Career")
        self.career_menu.addAction(
            "Change team budget\u2026", self.change_team_budget)
        self.career_menu.setEnabled(False)

        # Export submenu
        export_menu = menu.addMenu("Export")
        export_menu.addAction(
            "Export table to CSV\u2026", self.export_csv)
        export_menu.addAction(
            "Import table from CSV\u2026", self.import_csv_table)
        export_menu.addSeparator()
        export_menu.addAction(
            "Export all tables to folder\u2026", self.export_all_csv)
        export_menu.addAction(
            "Import all tables from folder\u2026", self.import_all_csv)

        self.tools_button.setMenu(menu)

    # ==================================================================
    # Navigation
    # ==================================================================

    def show_home(self):
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.welcome_screen.refresh_recents()
        self.stack.setCurrentIndex(0)

    def show_startlist(self):
        self.setWindowTitle(
            f"{APP_NAME} v{APP_VERSION} \u2014 Startlist Generator")
        self.stack.setCurrentIndex(2)

    # ==================================================================
    # Search & Lookup
    # ==================================================================

    def _execute_search(self):
        self.table_view.set_search_term(self.search_edit.text())

    def _on_lookup_toggled(self, checked):
        self.lookup_btn.setText("Lookup: ON" if checked else "Lookup: OFF")
        self.table_view.set_lookup_mode(checked)

    # ==================================================================
    # Undo / Redo
    # ==================================================================

    def _on_data_change(self):
        self.unsaved_changes = True
        self._update_btns()

    def undo(self):
        action = self.state.undo()
        if not action:
            return
        if action.get("type") == "row_op":
            self._handle_row_op(action, is_undo=True)
        else:
            pk_col = self.table_view.model.all_columns()
            if pk_col:
                self.db.update_cell(
                    action["table"], action["column"], action["old"],
                    pk_col[0], action["pk"])
            self.unsaved_changes = True
            self.table_view.load_table_data()
        self._update_btns()

    def redo(self):
        action = self.state.redo()
        if not action:
            return
        if action.get("type") == "row_op":
            self._handle_row_op(action, is_undo=False)
        else:
            pk_col = self.table_view.model.all_columns()
            if pk_col:
                self.db.update_cell(
                    action["table"], action["column"], action["new"],
                    pk_col[0], action["pk"])
            self.unsaved_changes = True
            self.table_view.load_table_data()
        self._update_btns()

    def _handle_row_op(self, action, is_undo):
        table = action["table"]
        mode = action["mode"]
        rows = action["rows"]
        pk_col = action["pk_col"]
        columns = action["columns"]

        effective = (
            "delete"
            if (mode == "insert" and is_undo) or (mode == "delete" and not is_undo)
            else "insert"
        )
        try:
            if effective == "delete":
                self.db.delete_rows(table, pk_col, [r["pk"] for r in rows])
            else:
                for r in rows:
                    self.db.insert_row(table, columns, r["data"])
            self.unsaved_changes = True
            self.table_view.load_table_data()
        except Exception as e:
            op = "undo" if is_undo else "redo"
            QMessageBox.critical(
                self, "Error", f"Failed to {op} operation: {e}")

    def _update_btns(self):
        self.undo_btn.setEnabled(bool(self.state.undo_stack))
        self.redo_btn.setEnabled(bool(self.state.redo_stack))

    # ==================================================================
    # CDB File Operations
    # ==================================================================

    def close_cdb(self):
        if self.unsaved_changes:
            if QMessageBox.question(
                self, "Unsaved Changes",
                "You have unsaved changes. Are you sure you want to close?",
                QMessageBox.Yes | QMessageBox.No,
            ) != QMessageBox.Yes:
                return
        if self.db:
            self.db.close()
        self.db = None
        self.current_table = None
        self.unsaved_changes = False
        self.table_view.set_db(None)
        self.career_menu.setEnabled(False)
        gc.collect()
        self.show_home()

    def load_cdb(self, path=""):
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Open CDB file",
                self.state.settings.get("last_path", ""),
                "CDB files (*.cdb)",
            )
        if not path:
            return

        def task():
            gc.collect()
            return converter.export_cdb_to_sqlite(path)

        def on_success(temp_path):
            self.temp_path = temp_path
            self.db = DatabaseManager(temp_path)
            self.all_tables = self.db.get_table_list()
            self.sidebar.set_tables(self.all_tables)
            self.state.settings["last_path"] = os.path.dirname(path)
            self.table_view.set_db(self.db)
            self.table_view.set_lookup_mode(self.lookup_btn.isChecked())
            self.sidebar.select_first_favorite()
            self.state.add_recent(path)
            self._update_tools_menu_state()
            self.setWindowTitle(
                f"{APP_NAME} v{APP_VERSION} \u2014 {os.path.basename(path)}")
            self.stack.setCurrentIndex(1)
            self.status_label.setText(f"Loaded: {path}")
            self.unsaved_changes = False

        run_async(self, task, on_success, "Opening CDB\u2026")

    def save_as_cdb(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save CDB as", "", "CDB files (*.cdb)")
        if not path:
            return
        gc.collect()

        def task():
            converter.import_sqlite_to_cdb(self.temp_path, path)

        def on_complete(_):
            self.unsaved_changes = False
            self.status_label.setText(f"Saved: {path}")

        run_async(self, task, on_complete, "Saving CDB\u2026")

    # ==================================================================
    # Tools Menu
    # ==================================================================

    def _update_tools_menu_state(self):
        self.career_menu.setEnabled(
            bool(self.db and "GAM_career_data" in self.all_tables))

    def change_team_budget(self):
        if not self.db:
            return
        try:
            cursor = self.db.conn.cursor()
            cursor.execute("PRAGMA table_info([GAM_career_data])")
            columns = [col[1] for col in cursor.fetchall()]

            if "value" not in columns:
                QMessageBox.critical(
                    self, "Error",
                    "Column 'value' not found in GAM_career_data table")
                return

            cursor.execute(
                "SELECT value FROM [GAM_career_data] WHERE UID = 1")
            row = cursor.fetchone()
            if not row:
                QMessageBox.critical(
                    self, "Error",
                    "No career data found (UID = 1 not found)")
                return

            new_value, ok = QInputDialog.getInt(
                self, "Change Team Budget",
                "Enter new team budget:",
                value=int(row[0]), min=0)
            if ok:
                self.db.update_cell(
                    "GAM_career_data", "value", new_value, "UID", 1)
                self.unsaved_changes = True
                if self.table_view.current_table == "GAM_career_data":
                    self.table_view.load_table_data()
                self.status_label.setText(
                    f"Team budget updated to {new_value}")

        except Exception as e:
            QMessageBox.critical(
                self, "Error", f"Failed to update budget: {e}")

    # ==================================================================
    # CSV Import / Export
    # ==================================================================

    def export_csv(self):
        if not self.db or not self.table_view.current_table:
            QMessageBox.warning(
                self, "Warning", "No table selected.")
            return
        table_name = self.table_view.current_table
        path, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", f"{table_name}.csv",
            "CSV files (*.csv)")
        if path:
            run_async(
                self,
                lambda: csv_io.export_table(self.temp_path, table_name, path),
                lambda _: self.status_label.setText(
                    f"Exported table '{table_name}' to CSV"),
                "Exporting CSV\u2026")

    def import_csv_table(self):
        if not self.db or not self.table_view.current_table:
            QMessageBox.warning(
                self, "Warning", "No table selected.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Import CSV", "", "CSV files (*.csv)")
        if not path:
            return
        table_name = self.table_view.current_table
        if QMessageBox.question(
            self, "Confirm Import",
            f"This will overwrite data in '{table_name}' "
            f"with data from the CSV. Continue?",
            QMessageBox.Yes | QMessageBox.No,
        ) != QMessageBox.Yes:
            return

        def on_complete(_):
            self.unsaved_changes = True
            self.table_view.load_table_data()
            self.status_label.setText(
                f"Imported CSV data into table '{table_name}'")

        run_async(
            self,
            lambda: csv_io.import_table_from_csv(
                self.temp_path, table_name, path),
            on_complete, "Importing CSV\u2026")

    def export_all_csv(self):
        if not self.db:
            return
        folder = QFileDialog.getExistingDirectory(
            self, "Select folder to export all tables")
        if folder:
            run_async(
                self,
                lambda: csv_io.export_to_csv(self.temp_path, folder),
                lambda _: self.status_label.setText(
                    "Exported all tables to folder"),
                "Exporting all tables\u2026")

    def import_all_csv(self):
        if not self.db:
            return
        folder = QFileDialog.getExistingDirectory(
            self, "Select folder containing CSV files")
        if not folder:
            return
        if QMessageBox.question(
            self, "Confirm Import",
            "This will overwrite data in ALL matching tables "
            "with CSV files from the selected folder. Continue?",
            QMessageBox.Yes | QMessageBox.No,
        ) != QMessageBox.Yes:
            return

        def on_complete(_):
            self.unsaved_changes = True
            if self.table_view.current_table:
                self.table_view.load_table_data()
            self.status_label.setText(
                "Imported all matching tables from folder")

        run_async(
            self,
            lambda: csv_io.import_from_csv(self.temp_path, folder),
            on_complete, "Importing all tables\u2026")

    # ==================================================================
    # Column Manager & Table Operations
    # ==================================================================

    def open_column_manager(self):
        if not self.db or not self.table_view.current_table:
            QMessageBox.warning(
                self, "No Table", "Please select a table first.")
            return
        dlg = ColumnManagerDialog(self.table_view, self.state, self)
        dlg.exec()

    def clear_table(self):
        if not self.db or not self.table_view.current_table:
            QMessageBox.warning(
                self, "No Table", "Please select a table first.")
            return
        try:
            table_name = self.table_view.current_table
            total_rows = self.db.get_row_count(table_name)
            if total_rows == 0:
                QMessageBox.information(
                    self, "Empty Table", "This table is already empty.")
                return
            if QMessageBox.question(
                self, "Confirm Clear Table",
                f"This will delete ALL {total_rows} rows from "
                f"'{table_name}'.\n\nThis action can be undone.\n\nContinue?",
                QMessageBox.Yes | QMessageBox.No,
            ) != QMessageBox.Yes:
                return

            columns = self.db.get_columns(table_name)
            pk_col = columns[0]
            _, all_rows = self.db.fetch_data(table_name, limit=None)
            deleted_rows = [
                {"pk": row[0], "data": list(row)} for row in all_rows]
            pk_vals = [row[0] for row in all_rows]
            self.db.delete_rows(table_name, pk_col, pk_vals)

            if deleted_rows:
                self.state.push_action({
                    "type": "row_op", "mode": "delete",
                    "table": table_name, "pk_col": pk_col,
                    "columns": columns, "rows": deleted_rows,
                })
            self.unsaved_changes = True
            self.table_view.load_table_data()
            self._update_btns()
            self.status_label.setText(
                f"Cleared {len(deleted_rows)} rows from '{table_name}'")
        except Exception as e:
            QMessageBox.critical(
                self, "Error", f"Failed to clear table: {e}")

    # ==================================================================
    # Helpers
    # ==================================================================

    def _on_table_select(self, table_name):
        self.search_edit.clear()
        self.table_view.set_table(table_name)

    def _on_selection_change(self, count):
        if count:
            self.selection_label.setText(
                f"{count} row{'s' if count != 1 else ''} selected")
        else:
            self.selection_label.setText("")

    def closeEvent(self, event):
        if self.unsaved_changes:
            if QMessageBox.question(
                self, "Unsaved Changes",
                "You have unsaved changes. Are you sure you want to exit?",
                QMessageBox.Yes | QMessageBox.No,
            ) != QMessageBox.Yes:
                event.ignore()
                return

        is_maximized = self.isMaximized()
        geom = f"{self.width()}x{self.height()}"
        self.state.save_settings(
            geom, is_maximized, self.lookup_btn.isChecked())
        if self.db:
            self.db.close()
        event.accept()
