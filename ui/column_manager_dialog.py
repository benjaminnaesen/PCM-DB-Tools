"""
Column visibility management dialog.

Provides UI for showing/hiding columns, saving/loading presets,
and searching through available columns.
"""

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)


class ColumnManagerDialog(QDialog):
    """Modal dialog for managing column visibility with preset support."""

    def __init__(self, table_view, app_state, parent=None):
        super().__init__(parent)
        self.table_view = table_view
        self.state = app_state
        self.current_table = table_view.current_table

        if not self.current_table:
            QMessageBox.warning(self, "No Table", "Please select a table first.")
            self.reject()
            return

        self.all_columns = table_view.get_all_columns()
        if not self.all_columns:
            QMessageBox.warning(self, "No Columns", "No columns available.")
            self.reject()
            return

        visible_cols = self.state.get_visible_columns(self.current_table)
        self.visible_columns = visible_cols if visible_cols else self.all_columns.copy()

        self.setWindowTitle(f"Manage Columns \u2014 {self.current_table}")
        self.resize(500, 600)
        self.setModal(True)

        self._checkboxes: dict[str, QCheckBox] = {}
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Presets row
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Presets:"))
        self._preset_combo = QComboBox()
        self._preset_combo.setMinimumWidth(160)
        self._update_preset_list()
        preset_row.addWidget(self._preset_combo, 1)

        for text, handler in [("Save", self._save_preset),
                              ("Load", self._load_preset),
                              ("Delete", self._delete_preset)]:
            btn = QPushButton(text)
            btn.setFixedWidth(70)
            btn.clicked.connect(handler)
            preset_row.addWidget(btn)
        layout.addLayout(preset_row)

        # Filter
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filter:"))
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Search columns\u2026")
        self._filter_edit.setClearButtonEnabled(True)
        self._filter_edit.textChanged.connect(self._filter_columns)
        filter_row.addWidget(self._filter_edit, 1)
        layout.addLayout(filter_row)

        # Column label
        layout.addWidget(QLabel("Columns:"))

        # Scrollable checkbox area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: 1px solid #ccc; }")

        container = QWidget()
        self._cb_layout = QVBoxLayout(container)
        self._cb_layout.setContentsMargins(10, 6, 10, 6)
        self._cb_layout.setSpacing(4)

        for i, col in enumerate(self.all_columns):
            cb = QCheckBox(col)
            cb.setChecked(col in self.visible_columns)
            if i == 0:
                cb.setChecked(True)
                cb.setEnabled(False)
            self._cb_layout.addWidget(cb)
            self._checkboxes[col] = cb

        self._cb_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

        # Bottom buttons
        btn_row = QHBoxLayout()
        show_all = QPushButton("Show All")
        show_all.clicked.connect(self._show_all)
        btn_row.addWidget(show_all)

        hide_all = QPushButton("Hide All")
        hide_all.clicked.connect(self._hide_all)
        btn_row.addWidget(hide_all)

        btn_row.addStretch()

        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)

        apply_btn = QPushButton("Apply")
        apply_btn.setStyleSheet(
            "QPushButton { background: #4CAF50; color: white; padding: 6px 16px; }"
            "QPushButton:hover { background: #43a047; }"
        )
        apply_btn.clicked.connect(self._apply)
        btn_row.addWidget(apply_btn)

        layout.addLayout(btn_row)

    # ------------------------------------------------------------------

    def _filter_columns(self, text):
        term = text.lower()
        for col, cb in self._checkboxes.items():
            cb.setVisible(term in col.lower())

    def _show_all(self):
        for cb in self._checkboxes.values():
            cb.setChecked(True)

    def _hide_all(self):
        for i, cb in enumerate(self._checkboxes.values()):
            if i > 0:
                cb.setChecked(False)

    # -- Presets -------------------------------------------------------

    def _update_preset_list(self):
        self._preset_combo.clear()
        presets = self.state.get_column_presets(self.current_table)
        self._preset_combo.addItems(list(presets.keys()))

    def _save_preset(self):
        name, ok = QInputDialog.getText(self, "Save Preset", "Enter preset name:")
        if ok and name:
            selected = [c for c, cb in self._checkboxes.items() if cb.isChecked()]
            self.state.save_column_preset(self.current_table, name, selected)
            self._update_preset_list()
            idx = self._preset_combo.findText(name)
            if idx >= 0:
                self._preset_combo.setCurrentIndex(idx)

    def _load_preset(self):
        name = self._preset_combo.currentText()
        if not name:
            QMessageBox.warning(self, "No Preset", "Please select a preset to load.")
            return
        presets = self.state.get_column_presets(self.current_table)
        if name in presets:
            cols = presets[name]
            for col, cb in self._checkboxes.items():
                cb.setChecked(col in cols)

    def _delete_preset(self):
        name = self._preset_combo.currentText()
        if not name:
            QMessageBox.warning(self, "No Preset", "Please select a preset to delete.")
            return
        if QMessageBox.question(
            self, "Confirm", f"Delete preset '{name}'?",
            QMessageBox.Yes | QMessageBox.No,
        ) == QMessageBox.Yes:
            self.state.delete_column_preset(self.current_table, name)
            self._update_preset_list()

    # -- Apply ---------------------------------------------------------

    def _apply(self):
        selected = [c for c, cb in self._checkboxes.items() if cb.isChecked()]
        if not selected or self.all_columns[0] not in selected:
            QMessageBox.critical(
                self, "Error",
                "You must keep at least the primary key column visible.")
            return
        self.table_view.set_visible_columns(selected)
        self.accept()
