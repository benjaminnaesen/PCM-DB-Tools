"""
Table view widget with editing, pagination, and column management.

Main data grid component using QTableView with a custom model and delegate
for inline editing, sorting, searching, and column visibility.
"""

from PySide6.QtCore import (
    QAbstractTableModel, QModelIndex, QTimer, Qt, Signal,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QLineEdit, QMenu,
    QMessageBox, QStyledItemDelegate, QTableView, QVBoxLayout, QWidget,
)

from core.constants import (
    DEFAULT_COLUMN_WIDTH, RESIZE_SAVE_DELAY, ROW_CHUNK_SIZE,
)


# ======================================================================
# Model
# ======================================================================

class DatabaseTableModel(QAbstractTableModel):
    """Table model with lazy row loading via canFetchMore/fetchMore."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._columns: list[str] = []
        self._visible_indices: list[int] = []
        self._rows: list[tuple] = []
        self._all_columns: list[str] = []
        self._total_rows = 0

        self.db = None
        self.table_name = None
        self.search_term = ""
        self.lookup_mode = False
        self.sort_col = None
        self.sort_reverse = False
        self.page_size = ROW_CHUNK_SIZE

    # -- Qt interface --------------------------------------------------

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self._columns)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        if role in (Qt.DisplayRole, Qt.EditRole):
            row = self._rows[index.row()]
            vi = self._visible_indices[index.column()]
            return "" if row[vi] is None else str(row[vi])
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            col = self._columns[section]
            if col == self.sort_col:
                prefix = "\u25bc " if self.sort_reverse else "\u25b2 "
                return prefix + col
            return col
        return None

    def flags(self, index):
        base = super().flags(index)
        if index.isValid() and index.column() > 0:
            return base | Qt.ItemIsEditable
        return base

    # -- Lazy loading --------------------------------------------------

    def canFetchMore(self, parent=QModelIndex()):
        return len(self._rows) < self._total_rows

    def fetchMore(self, parent=QModelIndex()):
        if not self.db or not self.table_name:
            return
        offset = len(self._rows)
        _, new_rows = self.db.fetch_data(
            self.table_name, self.search_term, self.lookup_mode,
            self.page_size, offset, self.sort_col, self.sort_reverse,
        )
        if not new_rows:
            return
        first = len(self._rows)
        self.beginInsertRows(QModelIndex(), first, first + len(new_rows) - 1)
        self._rows.extend(new_rows)
        self.endInsertRows()

    # -- Public helpers ------------------------------------------------

    def load(self, db, table_name, search_term, lookup_mode,
             sort_col, sort_reverse, visible_set):
        """Full reload: fetch first page and reset model."""
        self.beginResetModel()

        self.db = db
        self.table_name = table_name
        self.search_term = search_term
        self.lookup_mode = lookup_mode
        self.sort_col = sort_col
        self.sort_reverse = sort_reverse

        if not db or not table_name:
            self._columns = []
            self._visible_indices = []
            self._rows = []
            self._all_columns = []
            self._total_rows = 0
            self.endResetModel()
            return

        # Default sort to first column (PK)
        if self.sort_col is None:
            temp = db.get_columns(table_name)
            if temp:
                self.sort_col = temp[0]

        self._total_rows = db.get_row_count(
            table_name, search_term, lookup_mode)

        columns, rows = db.fetch_data(
            table_name, search_term, lookup_mode,
            self.page_size, 0, self.sort_col, self.sort_reverse,
        )
        self._all_columns = columns

        if visible_set is not None:
            vs = set(visible_set)
            self._visible_indices = [
                i for i, c in enumerate(columns) if c in vs]
            self._columns = [columns[i] for i in self._visible_indices]
        else:
            self._visible_indices = list(range(len(columns)))
            self._columns = list(columns)

        self._rows = list(rows)
        self.endResetModel()

    def load_from_offset(self, offset):
        """Reload starting from a specific row offset."""
        if not self.db or not self.table_name:
            return
        self.beginResetModel()
        self._total_rows = self.db.get_row_count(
            self.table_name, self.search_term, self.lookup_mode)
        _, rows = self.db.fetch_data(
            self.table_name, self.search_term, self.lookup_mode,
            self.page_size, offset, self.sort_col, self.sort_reverse,
        )
        self._rows = list(rows)
        self.endResetModel()

    def all_columns(self):
        return list(self._all_columns)

    def visible_columns(self):
        return list(self._columns)

    def raw_row(self, model_row):
        """Return the full raw row tuple for a given model row index."""
        if 0 <= model_row < len(self._rows):
            return self._rows[model_row]
        return None

    def pk_value(self, model_row):
        """Return PK (column 0) for a given model row."""
        row = self.raw_row(model_row)
        return row[0] if row else None

    def column_name(self, visible_col):
        """Return the real column name for a visible column index."""
        if 0 <= visible_col < len(self._columns):
            return self._columns[visible_col]
        return None

    def update_row_in_place(self, model_row, all_col_idx, new_val):
        """Update a single cell value in the cached row data."""
        if 0 <= model_row < len(self._rows):
            row = list(self._rows[model_row])
            row[all_col_idx] = new_val
            self._rows[model_row] = tuple(row)
            vis_col = (self._visible_indices.index(all_col_idx)
                       if all_col_idx in self._visible_indices else -1)
            if vis_col >= 0:
                idx = self.index(model_row, vis_col)
                self.dataChanged.emit(idx, idx)


# ======================================================================
# Delegate
# ======================================================================

class CellDelegate(QStyledItemDelegate):
    """Inline cell editor: QComboBox for FK lookups, QLineEdit otherwise."""

    def __init__(self, table_view_widget, parent=None):
        super().__init__(parent)
        self._tv = table_view_widget

    def createEditor(self, parent, option, index):
        col_name = self._tv.model.column_name(index.column())
        if self._tv.lookup_mode and col_name and col_name.startswith("fkID"):
            fk_opts = self._tv.db.get_fk_options(col_name) if self._tv.db else None
            if fk_opts:
                editor = QComboBox(parent)
                editor.addItems(list(fk_opts.keys()))
                editor.setEditable(True)
                editor._fk_options = fk_opts
                return editor
        editor = QLineEdit(parent)
        return editor

    def setEditorData(self, editor, index):
        value = index.data(Qt.EditRole) or ""
        if isinstance(editor, QComboBox):
            idx = editor.findText(value)
            if idx >= 0:
                editor.setCurrentIndex(idx)
            else:
                editor.setEditText(value)
        else:
            editor.setText(value)
            editor.selectAll()

    def setModelData(self, editor, model, index):
        col_name = self._tv.model.column_name(index.column())
        row = index.row()
        raw = self._tv.model.raw_row(row)
        if not raw:
            return

        pk_val = raw[0]
        all_col_idx = self._tv.model._visible_indices[index.column()]
        old_val = "" if raw[all_col_idx] is None else str(raw[all_col_idx])

        if isinstance(editor, QComboBox):
            new_display = editor.currentText()
            fk_opts = getattr(editor, '_fk_options', None)
            if fk_opts and new_display in fk_opts:
                db_val = fk_opts[new_display]
                undo_old = fk_opts.get(old_val, old_val)
            else:
                return
        else:
            new_display = editor.text()
            db_val = new_display
            undo_old = old_val

        if str(new_display) == str(old_val):
            return

        pk_col = self._tv.model._all_columns[0]
        self._tv.state.push_undo(
            self._tv.current_table, col_name, undo_old, db_val, pk_val)
        self._tv.data_changed.emit()
        self._tv.db.update_cell(
            self._tv.current_table, col_name, db_val, pk_col, pk_val)

        # Update cached row in-place (no full reload)
        self._tv.model.update_row_in_place(row, all_col_idx, new_display)

    def eventFilter(self, editor, event):
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.KeyPress:
            key = event.key()
            view = self._tv.table

            if key == Qt.Key_Escape:
                self.commitData.emit(editor)
                self.closeEditor.emit(
                    editor, QStyledItemDelegate.EndEditHint.NoHint)
                return True

            if key in (Qt.Key_Tab, Qt.Key_Backtab):
                self.commitData.emit(editor)
                cur = view.currentIndex()
                if key == Qt.Key_Backtab:
                    if cur.column() > 1:
                        nxt = cur.sibling(cur.row(), cur.column() - 1)
                    elif cur.row() > 0:
                        nxt = cur.sibling(
                            cur.row() - 1,
                            self._tv.model.columnCount() - 1)
                    else:
                        nxt = cur
                else:
                    if cur.column() < self._tv.model.columnCount() - 1:
                        nxt = cur.sibling(cur.row(), cur.column() + 1)
                    elif cur.row() < self._tv.model.rowCount() - 1:
                        nxt = cur.sibling(cur.row() + 1, 1)
                    else:
                        nxt = cur
                self.closeEditor.emit(
                    editor, QStyledItemDelegate.EndEditHint.NoHint)
                view.setCurrentIndex(nxt)
                view.edit(nxt)
                return True

            if key in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Return):
                self.commitData.emit(editor)
                cur = view.currentIndex()
                if key == Qt.Key_Up and cur.row() > 0:
                    nxt = cur.sibling(cur.row() - 1, cur.column())
                elif key in (Qt.Key_Down, Qt.Key_Return):
                    if cur.row() < self._tv.model.rowCount() - 1:
                        nxt = cur.sibling(cur.row() + 1, cur.column())
                    else:
                        nxt = cur
                else:
                    nxt = cur
                self.closeEditor.emit(
                    editor, QStyledItemDelegate.EndEditHint.NoHint)
                view.setCurrentIndex(nxt)
                view.edit(nxt)
                return True

        return super().eventFilter(editor, event)


# ======================================================================
# View widget
# ======================================================================

class TableView(QWidget):
    """Database table viewer with inline editing, sorting and pagination."""

    data_changed = Signal()
    selection_changed = Signal(int)  # number of selected rows

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.state = app_state
        self.db = None
        self.current_table = None
        self.search_term = ""
        self.lookup_mode = False
        self.sort_state = {"column": None, "reverse": False}
        self._last_saved_widths = {}

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(RESIZE_SAVE_DELAY)
        self._resize_timer.timeout.connect(self._save_column_widths)

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.model = DatabaseTableModel(self)
        self.delegate = CellDelegate(self, self)

        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setItemDelegate(self.delegate)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet(
            "QTableView {"
            "  gridline-color: #ddd;"
            "  background-color: #ffffff;"
            "  alternate-background-color: #f4f4f4;"
            "  color: #212121;"
            "}"
            "QTableView::item:selected {"
            "  background-color: #0078d4;"
            "  color: #ffffff;"
            "}"
        )

        header = self.table.horizontalHeader()
        header.setDefaultSectionSize(DEFAULT_COLUMN_WIDTH)
        header.setStretchLastSection(False)
        header.setSectionsMovable(False)
        header.sectionClicked.connect(self._on_header_clicked)
        header.sectionResized.connect(self._on_section_resized)
        header.setContextMenuPolicy(Qt.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_column_menu)

        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_row_menu)

        self.table.selectionModel().selectionChanged.connect(
            lambda: self.selection_changed.emit(
                len(self.table.selectionModel().selectedRows())))

        layout.addWidget(self.table)

    # ------------------------------------------------------------------
    # Database / table switching
    # ------------------------------------------------------------------

    def set_db(self, db):
        self.db = db
        self.current_table = None
        self.model.load(None, None, "", False, None, False, None)

    def set_table(self, table_name):
        self.current_table = table_name
        self.sort_state = {"column": None, "reverse": False}
        self.load_table_data()

    def set_search_term(self, term):
        self.search_term = term
        self.load_table_data()

    def set_lookup_mode(self, enabled):
        self.lookup_mode = enabled
        self.load_table_data()

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def load_table_data(self, start_offset=0):
        if not self.current_table or not self.db:
            return

        visible = self.state.get_visible_columns(self.current_table)
        self.model.load(
            self.db, self.current_table, self.search_term,
            self.lookup_mode, self.sort_state["column"],
            self.sort_state["reverse"], visible,
        )

        if start_offset > 0:
            self.model.load_from_offset(start_offset)

        self._apply_column_widths()

    def _apply_column_widths(self):
        saved = self.state.get_column_widths(self.current_table)
        header = self.table.horizontalHeader()
        widths = {}
        for i, col in enumerate(self.model.visible_columns()):
            w = (saved.get(col, DEFAULT_COLUMN_WIDTH)
                 if saved else DEFAULT_COLUMN_WIDTH)
            header.resizeSection(i, w)
            widths[col] = w
        self._last_saved_widths = widths

    # ------------------------------------------------------------------
    # Sorting
    # ------------------------------------------------------------------

    def _on_header_clicked(self, logical_index):
        col = self.model.column_name(logical_index)
        if not col:
            return
        if col == self.sort_state["column"]:
            self.sort_state["reverse"] = not self.sort_state["reverse"]
        else:
            self.sort_state = {"column": col, "reverse": False}
        self.load_table_data()

    # ------------------------------------------------------------------
    # Column resize persistence
    # ------------------------------------------------------------------

    def _on_section_resized(self, logical_index, old_size, new_size):
        self._resize_timer.start()

    def _save_column_widths(self):
        if not self.current_table:
            return
        header = self.table.horizontalHeader()
        widths = {}
        for i, col in enumerate(self.model.visible_columns()):
            widths[col] = header.sectionSize(i)
        if widths != self._last_saved_widths:
            self._last_saved_widths = widths.copy()
            self.state.set_column_widths(self.current_table, widths)

    # ------------------------------------------------------------------
    # Row operations
    # ------------------------------------------------------------------

    def add_row(self):
        if not self.current_table or not self.db:
            return
        try:
            all_cols = self.model.all_columns()
            if not all_cols:
                return
            new_id = self.db.get_max_id(self.current_table, all_cols[0])
            row_values = [new_id] + [""] * (len(all_cols) - 1)
            self.db.insert_row(self.current_table, all_cols, row_values)

            self.state.push_action({
                "type": "row_op", "mode": "insert",
                "table": self.current_table, "pk_col": all_cols[0],
                "columns": all_cols,
                "rows": [{"pk": new_id, "data": row_values}],
            })
            self.data_changed.emit()

            start = 0
            sc = self.sort_state["column"]
            if not sc or (sc == all_cols[0] and not self.sort_state["reverse"]):
                total = self.db.get_row_count(
                    self.current_table, self.search_term, self.lookup_mode)
                if total > self.model.page_size:
                    start = total - self.model.page_size
            self.load_table_data(start_offset=start)

            # Select new row and start editing
            for r in range(self.model.rowCount()):
                if str(self.model.pk_value(r)) == str(new_id):
                    idx = self.model.index(r, 1)
                    self.table.setCurrentIndex(idx)
                    self.table.scrollTo(idx)
                    self.table.edit(idx)
                    break
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def duplicate_row(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        try:
            columns = self.db.get_columns(self.current_table)
            pk_col = columns[0]
            pk_vals = [self.model.pk_value(idx.row()) for idx in rows]
            rows_map = self.db.get_rows_data(
                self.current_table, pk_col, pk_vals)
            next_id = self.db.get_max_id(self.current_table, pk_col)

            added = []
            for pk in pk_vals:
                src = rows_map.get(pk)
                if not src:
                    continue
                data = list(src)
                data[0] = next_id
                self.db.insert_row(self.current_table, columns, data)
                added.append({"pk": next_id, "data": data})
                next_id += 1

            if added:
                self.state.push_action({
                    "type": "row_op", "mode": "insert",
                    "table": self.current_table, "pk_col": pk_col,
                    "columns": columns, "rows": added,
                })
                self.data_changed.emit()

                start = 0
                sc = self.sort_state["column"]
                if not sc or (sc == pk_col and not self.sort_state["reverse"]):
                    total = self.db.get_row_count(
                        self.current_table, self.search_term, self.lookup_mode)
                    if total > self.model.page_size:
                        start = total - self.model.page_size
                self.load_table_data(start_offset=start)

                last_pk = added[-1]["pk"]
                for r in range(self.model.rowCount()):
                    if str(self.model.pk_value(r)) == str(last_pk):
                        idx = self.model.index(r, 0)
                        self.table.setCurrentIndex(idx)
                        self.table.scrollTo(idx)
                        break
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def delete_row(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        n = len(rows)
        if QMessageBox.question(
            self, "Confirm", f"Delete {n} row(s)?",
            QMessageBox.Yes | QMessageBox.No,
        ) != QMessageBox.Yes:
            return

        columns = self.db.get_columns(self.current_table)
        pk_col = columns[0]
        pk_vals = [self.model.pk_value(idx.row()) for idx in rows]
        rows_map = self.db.get_rows_data(self.current_table, pk_col, pk_vals)

        deleted = []
        for pk in pk_vals:
            data = rows_map.get(pk)
            if data:
                deleted.append({"pk": pk, "data": list(data)})

        self.db.delete_rows(self.current_table, pk_col, pk_vals)

        if deleted:
            self.state.push_action({
                "type": "row_op", "mode": "delete",
                "table": self.current_table, "pk_col": pk_col,
                "columns": columns, "rows": deleted,
            })
        self.data_changed.emit()
        self.load_table_data()

    # ------------------------------------------------------------------
    # Context menus
    # ------------------------------------------------------------------

    def _show_row_menu(self, pos):
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        if index not in self.table.selectionModel().selectedIndexes():
            self.table.selectRow(index.row())

        n = len(self.table.selectionModel().selectedRows())
        menu = QMenu(self)
        menu.addAction(
            "Duplicate Rows" if n > 1 else "Duplicate Row",
            self.duplicate_row)
        menu.addAction(
            "Delete Rows" if n > 1 else "Delete Row",
            self.delete_row)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _show_column_menu(self, pos):
        logical = self.table.horizontalHeader().logicalIndexAt(pos)
        col = self.model.column_name(logical)
        if not col:
            return
        all_cols = self.model.all_columns()
        if all_cols and col == all_cols[0]:
            return
        menu = QMenu(self)
        menu.addAction("Hide Column", lambda: self._hide_column(col))
        menu.exec(self.table.horizontalHeader().mapToGlobal(pos))

    def _hide_column(self, col_name):
        if not self.current_table:
            return
        visible = self.state.get_visible_columns(self.current_table)
        if visible is None:
            visible = self.model.all_columns()
        if col_name in visible:
            visible.remove(col_name)
            self.state.set_visible_columns(self.current_table, visible)
            self.load_table_data()

    # ------------------------------------------------------------------
    # Column accessors (used by column manager dialog)
    # ------------------------------------------------------------------

    def get_all_columns(self):
        return self.model.all_columns()

    def get_visible_columns(self):
        return self.model.visible_columns()

    def set_visible_columns(self, columns):
        if not self.current_table:
            return
        self.state.set_visible_columns(self.current_table, columns)
        self.load_table_data()

    def select_all_rows(self):
        self.table.selectAll()
