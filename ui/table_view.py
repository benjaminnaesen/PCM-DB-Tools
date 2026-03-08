"""
Table view widget with editing, pagination, and column management.

Main data grid component for viewing and editing database tables
with support for inline editing, sorting, searching, and column visibility.
"""

import tkinter as tk
from tkinter import ttk, messagebox

from core.constants import (
    ROW_CHUNK_SIZE, COL_CHUNK_SIZE, DEFAULT_COLUMN_WIDTH,
    RESIZE_SAVE_DELAY, DEFAULT_WINDOW_WIDTH,
)


class TableView:
    """
    Treeview-based table editor with pagination and inline editing.

    Features:
        - Paginated data loading with prev/next page navigation
        - Inline cell editing with Tab/Arrow navigation
        - Column sorting (click headers)
        - Right-click context menu for row operations
        - Foreign key dropdown editors
        - Column show/hide support
        - Persistent column widths
        - Undo/redo integration
    """

    def __init__(self, parent, app_state, on_change_callback):
        """
        Initialize table view widget.

        Args:
            parent: Parent tkinter widget
            app_state (AppState): Application state manager
            on_change_callback (callable): Called when data is modified
        """
        self.parent = parent
        self.state = app_state
        self.on_change = on_change_callback

        self.db = None
        self.current_table = None
        self.search_term = ""
        self.lookup_mode = False

        self.active_editor = None
        self.editing_data = {}
        self.sort_state = {"column": None, "reverse": False}
        self.page_size = ROW_CHUNK_SIZE
        self.offset = 0
        self.total_rows = 0
        self.loading_data = False
        self.last_saved_widths = {}
        self._resize_timer = None
        self.all_columns = []
        self._configured_columns = []
        self._col_window_end = 0

        self._setup_ui()
        self._create_menu()

    def _setup_ui(self):
        self.tree = ttk.Treeview(self.parent, show="headings", selectmode="extended")
        self.tree.tag_configure('oddrow', background="#f4f4f4")
        self.tree.tag_configure('evenrow', background="#ffffff")

        self.vsb = ttk.Scrollbar(self.parent, command=self.tree.yview)
        self.hsb = ttk.Scrollbar(self.parent, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=self.on_tree_scroll, xscrollcommand=self.on_h_scroll)

        self.tree.grid(row=0, column=0, sticky='nsew')
        self.vsb.grid(row=0, column=1, sticky='ns')
        self.hsb.grid(row=1, column=0, sticky='ew')
        self.parent.grid_columnconfigure(0, weight=1)
        self.parent.grid_rowconfigure(0, weight=1)

        self.tree.bind("<Double-1>", self.on_double_click)
        self.tree.bind("<Button-3>", self.show_context_menu)
        self.tree.bind("<ButtonRelease-1>", self.on_single_click)
        self.tree.bind("<Button-1>", self.on_tree_click)
        self.tree.bind("<ButtonRelease-1>", self.on_column_resize, add='+')
        self.tree.bind("<Control-a>", self.select_all_rows)
        self.tree.bind("<Button-3>", self.on_right_click, add='+')

    def _create_menu(self):
        self.row_menu = tk.Menu(self.parent, tearoff=0)
        self.row_menu.add_command(label="Duplicate Row", command=self.duplicate_row)
        self.row_menu.add_command(label="Delete Row", command=self.delete_row)

        self.column_menu = tk.Menu(self.parent, tearoff=0)
        self.column_menu.add_command(label="Hide Column", command=self.hide_column)

    # ------------------------------------------------------------------
    # Database / table switching
    # ------------------------------------------------------------------

    def set_db(self, db):
        """Set database manager instance."""
        self.db = db
        self.current_table = None
        self._configured_columns = []
        self._col_window_end = 0
        self.tree.delete(*self.tree.get_children())
        self.tree["columns"] = []

    def set_table(self, table_name):
        """Switch to viewing a different table."""
        self.current_table = table_name
        self.sort_state = {"column": None, "reverse": False}
        self._configured_columns = []
        self._col_window_end = 0
        self.load_table_data()

    def set_search_term(self, term):
        """Update the search filter and reload the table."""
        self.search_term = term
        self.load_table_data()

    def set_lookup_mode(self, enabled):
        """Toggle FK lookup mode and reload with display names or raw IDs."""
        self.lookup_mode = enabled
        self._configured_columns = []
        self._col_window_end = 0
        self.load_table_data()

    # ------------------------------------------------------------------
    # Visible column filtering helper
    # ------------------------------------------------------------------

    def _filter_visible(self, columns, rows):
        """Filter columns and rows to only include visible ones.

        Args:
            columns (list[str]): All column names
            rows (list[tuple]): Raw row data

        Returns:
            tuple: (display_columns, visible_indices, filtered_rows)
        """
        visible = self.state.get_visible_columns(self.current_table)
        if visible is not None:
            visible_set = set(visible)
            display_columns = [col for col in columns if col in visible_set]
            indices = [i for i, col in enumerate(columns) if col in visible_set]
        else:
            display_columns = columns
            indices = list(range(len(columns)))

        filtered = [tuple(row[i] for i in indices) for row in rows]
        return display_columns, indices, filtered

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def on_tree_scroll(self, first, last):
        """Handle vertical scroll — load more rows near bottom edge."""
        self.vsb.set(first, last)
        if float(last) > 0.95:
            self.load_more_data()

    def on_h_scroll(self, first, last):
        """Handle horizontal scroll — load more columns near right edge."""
        self.hsb.set(first, last)
        if float(last) > 0.9 and self._col_window_end < len(self._configured_columns):
            self._load_more_columns()

    def sort_column(self, col, reverse):
        """Sort table by column."""
        self.sort_state = {"column": col, "reverse": reverse}
        self.load_table_data()

    def _compute_col_window(self, total_cols):
        """Compute how many columns to show in the initial window.

        Returns:
            int: Number of columns for the display window.
        """
        tree_width = self.tree.winfo_width()
        if tree_width < 100:
            tree_width = DEFAULT_WINDOW_WIDTH
        visible_count = tree_width // DEFAULT_COLUMN_WIDTH
        return min(visible_count + COL_CHUNK_SIZE, total_cols)

    def load_table_data(self, start_offset=0):
        """
        Load and display table data with infinite scroll on rows and columns.

        Args:
            start_offset (int): Row offset for pagination (default: 0)
        """
        if self.active_editor:
            self.cancel_edit()
        if not self.current_table or not self.db:
            return

        self.tree.grid_remove()
        self.offset = start_offset
        self.total_rows = self.db.get_row_count(self.current_table, self.search_term, self.lookup_mode)

        # Set default sort to first column (primary key) if not set
        if self.sort_state["column"] is None:
            temp_columns = self.db.get_columns(self.current_table)
            if temp_columns:
                self.sort_state = {"column": temp_columns[0], "reverse": False}

        columns, row_data = self.db.fetch_data(
            self.current_table, self.search_term, self.lookup_mode,
            self.page_size, self.offset,
            self.sort_state["column"], self.sort_state["reverse"],
        )
        self.offset += len(row_data)

        # Store all columns (including hidden ones)
        self.all_columns = columns

        # Filter to visible columns
        display_columns, _, filtered_rows = self._filter_visible(columns, row_data)

        # Reset displaycolumns before changing columns to avoid TclError
        self.tree["displaycolumns"] = "#all"
        self.tree["columns"] = display_columns
        self._configured_columns = list(display_columns)

        # Compute column window — only configure/show a subset initially
        self._col_window_end = self._compute_col_window(len(display_columns))
        window_cols = display_columns[:self._col_window_end]

        if self._col_window_end < len(display_columns):
            self.tree["displaycolumns"] = window_cols

        # Configure column headings and widths for window columns
        saved_widths = self.state.get_column_widths(self.current_table) if self.current_table else None
        current_widths = {}

        for col in window_cols:
            prefix = ""
            if col == self.sort_state["column"]:
                prefix = "\u25bc " if self.sort_state["reverse"] else "\u25b2 "
            self.tree.heading(
                col, text=prefix + col,
                command=lambda _c=col: self.sort_column(
                    _c,
                    not self.sort_state["reverse"] if _c == self.sort_state["column"] else False,
                ),
            )
            width = saved_widths.get(col, DEFAULT_COLUMN_WIDTH) if saved_widths else DEFAULT_COLUMN_WIDTH
            self.tree.column(col, width=width, stretch=False)
            current_widths[col] = width

        self.last_saved_widths = current_widths.copy()

        # Insert rows
        self.tree.delete(*self.tree.get_children())
        for index, row in enumerate(filtered_rows):
            tag = 'evenrow' if index % 2 == 0 else 'oddrow'
            self.tree.insert("", "end", values=row, tags=(tag,))
        self.tree.grid()

    def load_more_data(self):
        """Load next page of data when scrolling to bottom."""
        if not self.current_table or self.loading_data or self.offset >= self.total_rows:
            return
        self.loading_data = True

        _, row_data = self.db.fetch_data(
            self.current_table, self.search_term, self.lookup_mode,
            self.page_size, self.offset,
            self.sort_state["column"], self.sort_state["reverse"],
        )

        _, _, filtered_rows = self._filter_visible(self.all_columns, row_data)

        start_idx = self.offset
        for index, row in enumerate(filtered_rows):
            tag = 'evenrow' if (start_idx + index) % 2 == 0 else 'oddrow'
            self.tree.insert("", "end", values=row, tags=(tag,))
        self.offset += len(row_data)
        self.loading_data = False

    def _load_more_columns(self):
        """Expand the column display window when scrolling right."""
        if not self._configured_columns or self._col_window_end >= len(self._configured_columns):
            return

        old_end = self._col_window_end
        chunk = self._compute_col_window(len(self._configured_columns))
        new_end = min(old_end + chunk, len(self._configured_columns))
        if new_end == old_end:
            return

        self._col_window_end = new_end

        # Configure widths and headings for newly added columns
        saved_widths = self.state.get_column_widths(self.current_table) if self.current_table else None
        for col in self._configured_columns[old_end:new_end]:
            prefix = ""
            if col == self.sort_state["column"]:
                prefix = "\u25bc " if self.sort_state["reverse"] else "\u25b2 "
            self.tree.heading(
                col, text=prefix + col,
                command=lambda _c=col: self.sort_column(
                    _c,
                    not self.sort_state["reverse"] if _c == self.sort_state["column"] else False,
                ),
            )
            width = saved_widths.get(col, DEFAULT_COLUMN_WIDTH) if saved_widths else DEFAULT_COLUMN_WIDTH
            self.tree.column(col, width=width, stretch=False)
            self.last_saved_widths[col] = width

        # Expand display window (no row re-insertion needed)
        if self._col_window_end >= len(self._configured_columns):
            self.tree["displaycolumns"] = "#all"
        else:
            self.tree["displaycolumns"] = self._configured_columns[:new_end]

    # ------------------------------------------------------------------
    # Click handlers
    # ------------------------------------------------------------------

    def on_double_click(self, event):
        item = self.tree.identify_row(event.y)
        col_id = self.tree.identify_column(event.x)
        self.edit_cell(item, col_id)

    def on_single_click(self, event):
        if not self.lookup_mode:
            return
        try:
            region = self.tree.identify_region(event.x, event.y)
        except Exception:
            region = self.tree.identify("region", event.x, event.y)
        if region == "cell":
            col_id = self.tree.identify_column(event.x)
            item = self.tree.identify_row(event.y)
            if col_id and item:
                index = int(col_id.replace('#', '')) - 1
                if index >= 0 and self.tree["columns"][index].startswith("fkID"):
                    self.edit_cell(item, col_id)

    def on_tree_click(self, event):
        if self.active_editor:
            self.commit_editor()

    def on_column_resize(self, event):
        """Save column widths when user resizes a column (debounced)."""
        if not self.current_table or not self._configured_columns:
            return

        widths = {}
        for col in self._configured_columns[:self._col_window_end]:
            widths[col] = self.tree.column(col, "width")

        if widths != self.last_saved_widths:
            self.last_saved_widths = widths.copy()
            if self._resize_timer:
                self.parent.after_cancel(self._resize_timer)
            self._resize_timer = self.parent.after(
                RESIZE_SAVE_DELAY,
                lambda: self.state.set_column_widths(self.current_table, widths),
            )

    # ------------------------------------------------------------------
    # Inline editing
    # ------------------------------------------------------------------

    def cancel_edit(self, event=None):
        """Discard the active inline editor without saving changes."""
        if self.active_editor:
            self.active_editor.destroy()
            self.active_editor = None
            self.editing_data = {}

    def commit_editor(self, event=None, reload_data=True):
        """Save the active editor value to the database and push an undo entry.

        Args:
            reload_data: If True, fully reload the table. If False, update
                the Treeview row in-place (used during keyboard navigation).
        """
        if not self.active_editor:
            return
        new_val = self.active_editor.get()
        editor = self.active_editor
        self.active_editor = None
        data = self.editing_data
        self.editing_data = {}
        editor.destroy()

        col_name = data['col_name']
        pk_val = data['pk_val']
        old_val = data['old_val']
        fk_options = data['fk_options']

        db_val = new_val
        undo_old_val = old_val

        if fk_options:
            if new_val in fk_options:
                db_val = fk_options[new_val]
            else:
                return
            undo_old_val = fk_options.get(old_val, old_val)

        if str(new_val) != str(old_val):
            self.state.push_undo(self.current_table, col_name, undo_old_val, db_val, pk_val)
            self.on_change()
            self.db.update_cell(self.current_table, col_name, db_val, self.tree["columns"][0], pk_val)
            if reload_data:
                self.load_table_data()
            else:
                new_values = list(data['values'])
                new_values[data['index']] = new_val
                self.tree.item(data['item'], values=tuple(new_values))

    def on_editor_navigate(self, event):
        """Handle Tab/Arrow/Enter navigation while the inline editor is open.

        Commits the current edit and opens the editor in the adjacent cell.
        Tab moves horizontally (wrapping to next/prev row), Arrow keys and
        Enter move vertically.
        """
        if not self.editing_data:
            return
        item = self.editing_data['item']
        index = self.editing_data['index']
        self.commit_editor(reload_data=False)

        next_item = item
        next_col_index = index

        if event.keysym == 'Tab':
            if event.state & 1:  # Shift+Tab
                if index > 1:
                    next_col_index -= 1
                elif (p := self.tree.prev(item)):
                    next_item = p
                    next_col_index = len(self.tree['columns']) - 1
            else:
                if index < len(self.tree['columns']) - 1:
                    next_col_index += 1
                elif (n := self.tree.next(item)):
                    next_item = n
                    next_col_index = 1
        elif event.keysym == 'Up' and (p := self.tree.prev(item)):
            next_item = p
        elif event.keysym in ('Down', 'Return') and (n := self.tree.next(item)):
            next_item = n

        self.tree.selection_set(next_item)
        self.edit_cell(next_item, f"#{next_col_index + 1}")
        return "break"

    def edit_cell(self, item, col_id):
        """Open an inline editor (Entry or Combobox) on the given cell.

        In lookup mode, FK columns get a Combobox with display names mapped
        back to raw IDs on commit.
        """
        if not item or not col_id:
            return
        index = int(col_id.replace('#', '')) - 1
        if index == 0:
            return
        if self.active_editor:
            self.commit_editor()

        col_name = self.tree["columns"][index]
        values = self.tree.item(item, "values")
        pk_val = values[0]
        old_val = values[index]

        fk_options = None
        if self.lookup_mode and col_name.startswith("fkID"):
            fk_options = self.db.get_fk_options(col_name)

        x, y, w, h = self.tree.bbox(item, col_id)
        self.tree.see(item)

        if fk_options:
            self.active_editor = ttk.Combobox(self.parent, values=list(fk_options.keys()))
        else:
            self.active_editor = tk.Entry(self.parent, relief="flat")

        self.active_editor.place(x=x, y=y, width=w, height=h)
        self.active_editor.insert(0, old_val)
        if not isinstance(self.active_editor, ttk.Combobox):
            self.active_editor.select_range(0, tk.END)
        self.active_editor.focus_set()

        self.editing_data = {
            'col_name': col_name, 'pk_val': pk_val, 'old_val': old_val,
            'fk_options': fk_options, 'item': item, 'index': index, 'values': values,
        }

        bindings = {
            "<Return>": self.on_editor_navigate,
            "<FocusOut>": lambda e: self.commit_editor(),
            "<Escape>": self.cancel_edit,
            "<Tab>": self.on_editor_navigate,
            "<Up>": self.on_editor_navigate,
            "<Down>": self.on_editor_navigate,
        }
        for key, handler in bindings.items():
            self.active_editor.bind(key, handler)

    # ------------------------------------------------------------------
    # Row operations
    # ------------------------------------------------------------------

    def add_row(self):
        """Add a new empty row to the current table."""
        if not self.current_table or not self.db:
            return
        try:
            if not self.all_columns:
                return

            new_id = self.db.get_max_id(self.current_table, self.all_columns[0])
            row_values = [new_id] + [""] * (len(self.all_columns) - 1)
            self.db.insert_row(self.current_table, self.all_columns, row_values)

            action = {
                "type": "row_op",
                "mode": "insert",
                "table": self.current_table,
                "pk_col": self.all_columns[0],
                "columns": self.all_columns,
                "rows": [{"pk": new_id, "data": row_values}],
            }
            self.state.push_action(action)
            self.on_change()

            # Jump to bottom if sorting by PK ASC
            start_offset = 0
            if not self.sort_state["column"] or (
                self.sort_state["column"] == self.all_columns[0] and not self.sort_state["reverse"]
            ):
                total_rows = self.db.get_row_count(self.current_table, self.search_term, self.lookup_mode)
                if total_rows > self.page_size:
                    start_offset = total_rows - self.page_size

            self.load_table_data(start_offset=start_offset)

            # Select and edit the new row
            for item in self.tree.get_children():
                vals = self.tree.item(item, "values")
                if vals and str(vals[0]) == str(new_id):
                    self.tree.selection_set(item)
                    self.tree.see(item)
                    self.tree.focus(item)
                    if len(self.tree["columns"]) > 1:
                        self.edit_cell(item, "#2")
                    break
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def duplicate_row(self):
        """Duplicate selected row(s) with new auto-incremented IDs."""
        selection = self.tree.selection()
        if not selection:
            return

        added_rows = []
        try:
            columns = self.db.get_columns(self.current_table)
            pk_col = columns[0]

            # Batch fetch source rows and compute IDs once
            pk_vals = [self.tree.item(item, "values")[0] for item in selection]
            rows_map = self.db.get_rows_data(self.current_table, pk_col, pk_vals)
            next_id = self.db.get_max_id(self.current_table, pk_col)

            for pk_val in pk_vals:
                source_data = rows_map.get(pk_val)
                if not source_data:
                    continue
                row_data = list(source_data)
                row_data[0] = next_id
                self.db.insert_row(self.current_table, columns, row_data)
                added_rows.append({"pk": next_id, "data": row_data})
                next_id += 1

            if added_rows:
                action = {
                    "type": "row_op",
                    "mode": "insert",
                    "table": self.current_table,
                    "pk_col": pk_col,
                    "columns": columns,
                    "rows": added_rows,
                }
                self.state.push_action(action)
                self.on_change()

                # Jump to bottom if sorting by PK ASC
                start_offset = 0
                if not self.sort_state["column"] or (
                    self.sort_state["column"] == pk_col and not self.sort_state["reverse"]
                ):
                    total_rows = self.db.get_row_count(self.current_table, self.search_term, self.lookup_mode)
                    if total_rows > self.page_size:
                        start_offset = total_rows - self.page_size

                self.load_table_data(start_offset=start_offset)

                # Select the last duplicated row
                last_new_id = added_rows[-1]["pk"]
                for item in self.tree.get_children():
                    vals = self.tree.item(item, "values")
                    if vals and str(vals[0]) == str(last_new_id):
                        self.tree.selection_set(item)
                        self.tree.see(item)
                        self.tree.focus(item)
                        break

        except Exception as e:
            messagebox.showerror("Error", str(e))

    def delete_row(self):
        """Delete selected row(s) after confirmation."""
        selection = self.tree.selection()
        if not selection:
            return
        if not messagebox.askyesno("Confirm", f"Delete {len(selection)} row(s)?"):
            return

        columns = self.db.get_columns(self.current_table)
        pk_col = columns[0]
        pk_vals = [self.tree.item(item, "values")[0] for item in selection]

        # Capture data for undo before deleting (batch fetch)
        rows_map = self.db.get_rows_data(self.current_table, pk_col, pk_vals)
        deleted_rows = []
        for pk in pk_vals:
            data = rows_map.get(pk)
            if data:
                deleted_rows.append({"pk": pk, "data": list(data)})

        self.db.delete_rows(self.current_table, pk_col, pk_vals)

        if deleted_rows:
            action = {
                "type": "row_op",
                "mode": "delete",
                "table": self.current_table,
                "pk_col": pk_col,
                "columns": columns,
                "rows": deleted_rows,
            }
            self.state.push_action(action)

        self.on_change()
        self.load_table_data()

    # ------------------------------------------------------------------
    # Context menus
    # ------------------------------------------------------------------

    def show_context_menu(self, event):
        """Show right-click menu with Duplicate/Delete row actions."""
        row_id = self.tree.identify_row(event.y)
        if row_id:
            if row_id not in self.tree.selection():
                self.tree.selection_set(row_id)

            selection_count = len(self.tree.selection())
            self.row_menu.entryconfig(0, label="Duplicate Rows" if selection_count > 1 else "Duplicate Row")
            self.row_menu.entryconfig(1, label="Delete Rows" if selection_count > 1 else "Delete Row")
            self.row_menu.post(event.x_root, event.y_root)

    def on_right_click(self, event):
        """Handle right-click on column headers to show hide menu."""
        region = self.tree.identify_region(event.x, event.y)
        if region == "heading":
            col_id = self.tree.identify_column(event.x)
            if col_id:
                index = int(col_id.replace('#', '')) - 1
                if 0 <= index < len(self.tree["columns"]):
                    self.clicked_column = self.tree["columns"][index]
                    if self.clicked_column != self.all_columns[0]:
                        self.column_menu.post(event.x_root, event.y_root)

    def hide_column(self):
        """Hide the clicked column."""
        if not hasattr(self, 'clicked_column') or not self.current_table:
            return

        visible_columns = self.state.get_visible_columns(self.current_table)
        if visible_columns is None:
            visible_columns = self.all_columns.copy()

        if self.clicked_column in visible_columns:
            visible_columns.remove(self.clicked_column)
            self.state.set_visible_columns(self.current_table, visible_columns)
            self.load_table_data()

    # ------------------------------------------------------------------
    # Column accessors
    # ------------------------------------------------------------------

    def get_all_columns(self):
        """Get all columns for the current table (including hidden ones)."""
        return self.all_columns.copy() if self.all_columns else []

    def get_visible_columns(self):
        """Get currently visible columns."""
        return list(self.tree["columns"]) if self.tree["columns"] else []

    def set_visible_columns(self, columns):
        """Set which columns should be visible."""
        if not self.current_table:
            return
        self.state.set_visible_columns(self.current_table, columns)
        self.load_table_data()

    def select_all_rows(self, event=None):
        """Select all rows in the table."""
        items = self.tree.get_children()
        if items:
            self.tree.selection_set(items)
        return "break"
