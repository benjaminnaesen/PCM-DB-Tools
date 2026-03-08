"""
Main application window and controller.

Coordinates the home screen, database editor, and startlist generator,
manages file operations, and handles application lifecycle.
"""

import gc
import os
import sys
import tkinter as tk
from tkinter import filedialog, ttk, messagebox, simpledialog

from core.db_manager import DatabaseManager
from core.app_state import AppState
from core.constants import APP_NAME, APP_VERSION, SEARCH_DEBOUNCE_DELAY
import core.converter as converter
import core.csv_io as csv_io
from ui.welcome_screen import WelcomeScreen
from ui.ui_utils import run_async
from ui.sidebar import Sidebar
from ui.table_view import TableView
from ui.column_manager_dialog import ColumnManagerDialog
from ui.startlist_view import StartlistView


class PCMDatabaseTools:
    """Main application controller for PCM Database Tools.

    Manages:
        - Home screen with tool launcher tiles
        - Database editor (CDB loading, table editing, CSV import/export)
        - Startlist generator (full-frame view)
        - Undo/redo coordination
        - Application settings persistence
    """

    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_NAME} v{APP_VERSION}")
        self.state = AppState("session_config.json")
        self.normal_geometry = self.state.settings.get("window_size", "1200x800")
        self.root.geometry(self.normal_geometry)

        if self.state.settings.get("is_maximized", False):
            try:
                if sys.platform.startswith('win'):
                    self.root.state('zoomed')
                else:
                    self.root.attributes('-zoomed', True)
            except (tk.TclError, AttributeError):
                pass

        self.root.bind("<Configure>", self.track_window_size)
        self.db = None
        self.temp_path = None
        self.current_table = None
        self.unsaved_changes = False
        self.search_timer = None

        self._setup_ui()
        self.root.bind("<Control-z>", lambda e: self.undo())
        self.root.bind("<Control-y>", lambda e: self.redo())
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def track_window_size(self, event):
        """Track normal (non-maximized) window geometry for session persistence."""
        try:
            if sys.platform.startswith('win'):
                is_maximized = self.root.state() == 'zoomed'
            else:
                is_maximized = self.root.attributes('-zoomed')
            if not is_maximized:
                self.normal_geometry = self.root.geometry()
        except (tk.TclError, AttributeError):
            pass

    # ==================================================================
    # UI Setup
    # ==================================================================

    def _setup_ui(self):
        # -- Home screen frame --
        self.welcome_frame = tk.Frame(self.root, bg="#f0f0f0")
        self.welcome_screen = WelcomeScreen(
            self.welcome_frame, self.state,
            load_callback=self.load_cdb,
            startlist_callback=self.show_startlist,
        )

        # -- Editor frame --
        self.editor_frame = tk.Frame(self.root)
        self._setup_editor_toolbar()
        self._setup_editor_content()

        # -- Startlist frame --
        self.startlist_frame = tk.Frame(self.root)
        self.startlist_view = StartlistView(
            self.startlist_frame, self.root, go_home=self.show_home,
        )

        self.show_home()

    def _setup_editor_toolbar(self):
        toolbar = tk.Frame(self.editor_frame, pady=10, bg="#f0f0f0")
        toolbar.pack(side=tk.TOP, fill=tk.X)

        tk.Button(toolbar, text="\u2190 Close CDB", command=self.close_cdb).pack(side=tk.LEFT, padx=5)
        tk.Button(toolbar, text="Open CDB", command=self.load_cdb, width=10).pack(side=tk.LEFT, padx=5)
        tk.Button(toolbar, text="Save As...", command=self.save_as_cdb, width=10).pack(side=tk.LEFT, padx=5)

        self.tools_btn = tk.Menubutton(toolbar, text="Tools", relief="raised", width=10)
        self.tools_menu = tk.Menu(self.tools_btn, tearoff=0)

        # Career submenu
        self.career_menu = tk.Menu(self.tools_menu, tearoff=0)
        self.career_menu.add_command(label="Change team budget...", command=self.change_team_budget)
        self.tools_menu.add_cascade(label="Career", menu=self.career_menu)

        # Export submenu
        self.export_menu = tk.Menu(self.tools_menu, tearoff=0)
        self.export_menu.add_command(label="Export table to CSV...", command=self.export_csv)
        self.export_menu.add_command(label="Import table from CSV...", command=self.import_csv_table)
        self.export_menu.add_separator()
        self.export_menu.add_command(label="Export all tables to folder...", command=self.export_all_csv)
        self.export_menu.add_command(label="Import all tables from folder...", command=self.import_all_csv)
        self.tools_menu.add_cascade(label="Export", menu=self.export_menu)

        self.tools_btn.config(menu=self.tools_menu)

        self.undo_btn = tk.Button(toolbar, text="↶ Undo", command=self.undo, state="disabled")
        self.undo_btn.pack(side=tk.LEFT, padx=5)
        self.redo_btn = tk.Button(toolbar, text="↷ Redo", command=self.redo, state="disabled")
        self.redo_btn.pack(side=tk.LEFT, padx=5)
        tk.Button(toolbar, text="Add Row", command=lambda: self.table_view.add_row(), width=12).pack(side=tk.LEFT, padx=5)
        tk.Button(toolbar, text="Remove Row", command=lambda: self.table_view.delete_row(), width=12).pack(side=tk.LEFT, padx=5)
        tk.Button(toolbar, text="Clear Table", command=self.clear_table, width=12).pack(side=tk.LEFT, padx=5)

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self.on_search)
        self._create_search_box(toolbar, self.search_var, 40).pack(side=tk.RIGHT, padx=15)
        self.lookup_var = tk.BooleanVar(value=self.state.settings.get("lookup_mode", False))
        self.lookup_btn = tk.Button(
            toolbar,
            text="Lookup: ON" if self.lookup_var.get() else "Lookup: OFF",
            command=self.toggle_lookup, width=12,
        )
        self.lookup_btn.pack(side=tk.RIGHT, padx=5)
        tk.Button(toolbar, text="Columns", command=self.open_column_manager, width=10).pack(side=tk.RIGHT, padx=5)
        self.tools_btn.pack(side=tk.RIGHT, padx=5)

    def _setup_editor_content(self):
        self.pw = tk.PanedWindow(self.editor_frame, orient=tk.HORIZONTAL, sashwidth=4, bg="#ccc")
        self.pw.pack(expand=True, fill=tk.BOTH)

        sidebar_container = tk.Frame(self.pw, bg="#e1e1e1")
        self.pw.add(sidebar_container)
        self.sidebar = Sidebar(sidebar_container, self.state, self.on_table_select)

        self.table_frame = tk.Frame(self.pw)
        self.pw.add(self.table_frame)
        self.table_view = TableView(self.table_frame, self.state, self.on_data_change)

        status_bar = tk.Frame(self.editor_frame, bd=1, relief="sunken")
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        self.status = tk.Label(status_bar, text="Ready", anchor="w")
        self.status.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.selection_label = tk.Label(status_bar, text="", anchor="e", padx=10)
        self.selection_label.pack(side=tk.RIGHT)

        self.table_view.tree.bind("<<TreeviewSelect>>", self._on_selection_change)

    # ==================================================================
    # Navigation
    # ==================================================================

    def show_home(self):
        """Show the home screen, hiding all other views."""
        self.editor_frame.pack_forget()
        self.startlist_frame.pack_forget()
        self.root.title(f"{APP_NAME} v{APP_VERSION}")
        self.welcome_screen.show()

    def show_startlist(self):
        """Show the startlist generator view."""
        self.welcome_screen.hide()
        self.editor_frame.pack_forget()
        self.root.title(f"{APP_NAME} v{APP_VERSION} - Startlist Generator")
        self.startlist_frame.pack(fill=tk.BOTH, expand=True)

    # ==================================================================
    # Search & Lookup
    # ==================================================================

    def on_search(self, *args):
        """Debounced search handler — delays execution until typing stops."""
        if self.search_timer:
            self.root.after_cancel(self.search_timer)
        self.search_timer = self.root.after(SEARCH_DEBOUNCE_DELAY, self._execute_search)

    def _execute_search(self):
        self.table_view.set_search_term(self.search_var.get())
        self.search_timer = None

    def toggle_lookup(self):
        """Toggle FK lookup mode between showing display names and raw IDs."""
        new_state = not self.lookup_var.get()
        self.lookup_var.set(new_state)
        self.lookup_btn.config(text="Lookup: ON" if new_state else "Lookup: OFF")
        self.table_view.set_lookup_mode(new_state)

    # ==================================================================
    # Undo / Redo
    # ==================================================================

    def on_data_change(self):
        """Mark the session as having unsaved changes and refresh undo/redo buttons."""
        self.unsaved_changes = True
        self._update_btns()

    def undo(self):
        """Undo the last edit (cell change or row operation)."""
        action = self.state.undo()
        if not action:
            return

        if action.get("type") == "row_op":
            self._handle_row_op(action, is_undo=True)
        else:
            self.db.update_cell(
                action["table"], action["column"], action["old"],
                self.table_view.tree["columns"][0], action["pk"],
            )
            self.unsaved_changes = True
            self.table_view.load_table_data()
        self._update_btns()

    def redo(self):
        """Redo the last undone edit."""
        action = self.state.redo()
        if not action:
            return

        if action.get("type") == "row_op":
            self._handle_row_op(action, is_undo=False)
        else:
            self.db.update_cell(
                action["table"], action["column"], action["new"],
                self.table_view.tree["columns"][0], action["pk"],
            )
            self.unsaved_changes = True
            self.table_view.load_table_data()
        self._update_btns()

    def _handle_row_op(self, action, is_undo):
        """Apply or reverse a row insert/delete operation for undo/redo."""
        table = action["table"]
        mode = action["mode"]
        rows = action["rows"]
        pk_col = action["pk_col"]
        columns = action["columns"]

        effective_op = (
            "delete"
            if (mode == "insert" and is_undo) or (mode == "delete" and not is_undo)
            else "insert"
        )

        try:
            if effective_op == "delete":
                self.db.delete_rows(table, pk_col, [r["pk"] for r in rows])
            else:
                for r in rows:
                    self.db.insert_row(table, columns, r["data"])

            self.unsaved_changes = True
            self.table_view.load_table_data()
        except Exception as e:
            operation = "undo" if is_undo else "redo"
            messagebox.showerror("Error", f"Failed to {operation} operation: {str(e)}")

    def _update_btns(self):
        self.undo_btn.config(state="normal" if self.state.undo_stack else "disabled")
        self.redo_btn.config(state="normal" if self.state.redo_stack else "disabled")

    # ==================================================================
    # CDB File Operations
    # ==================================================================

    def close_cdb(self):
        """Close the current database and return to the home screen."""
        if self.unsaved_changes:
            if not messagebox.askyesno("Unsaved Changes", "You have unsaved changes. Are you sure you want to close?"):
                return
        if self.db:
            self.db.close()
        self.db = None
        self.current_table = None
        self.unsaved_changes = False
        self.table_view.set_db(None)
        self.tools_menu.entryconfig("Career", state="disabled")
        gc.collect()
        self.show_home()

    def load_cdb(self, path=None):
        """Open a CDB file, convert to SQLite, and show the editor view."""
        if not path:
            path = filedialog.askopenfilename(
                initialdir=self.state.settings.get("last_path", ""),
                filetypes=[("CDB files", "*.cdb")],
            )
        if not path:
            return

        def task():
            gc.collect()
            return converter.export_cdb_to_sqlite(path)

        def on_success(temp_path):
            self.temp_path = temp_path
            self.db = DatabaseManager(self.temp_path)
            self.all_tables = self.db.get_table_list()
            self.sidebar.set_tables(self.all_tables)
            self.state.settings["last_path"] = os.path.dirname(path)
            self.table_view.set_db(self.db)
            self.table_view.set_lookup_mode(self.lookup_var.get())
            self.sidebar.select_first_favorite()
            self.state.add_recent(path)
            self._update_tools_menu_state()
            self.welcome_screen.hide()
            self.startlist_frame.pack_forget()
            self.root.title(f"{APP_NAME} v{APP_VERSION} - {os.path.basename(path)}")
            self.editor_frame.pack(fill=tk.BOTH, expand=True)
            self.status.config(text=f"Loaded: {path}")
            self.unsaved_changes = False

        run_async(self.root, task, on_success, "Opening CDB...")

    def save_as_cdb(self):
        """Export the working SQLite database back to a CDB file."""
        path = filedialog.asksaveasfilename(
            defaultextension=".cdb",
            filetypes=[("CDB files", "*.cdb")],
        )
        if path:
            gc.collect()

            def task():
                converter.import_sqlite_to_cdb(self.temp_path, path)

            def on_complete(_):
                self.unsaved_changes = False
                self.status.config(text=f"Saved: {path}")

            run_async(self.root, task, on_complete, "Saving CDB...")

    # ==================================================================
    # Tools Menu
    # ==================================================================

    def _update_tools_menu_state(self):
        """Enable or disable tool submenus based on available tables."""
        if self.db and "GAM_career_data" in self.all_tables:
            self.tools_menu.entryconfig("Career", state="normal")
        else:
            self.tools_menu.entryconfig("Career", state="disabled")

    def change_team_budget(self):
        """Open dialog to change team budget from GAM_career_data table."""
        if not self.db:
            return

        try:
            cursor = self.db.conn.cursor()

            cursor.execute("PRAGMA table_info([GAM_career_data])")
            columns = [col[1] for col in cursor.fetchall()]

            if "value" not in columns:
                messagebox.showerror("Error", "Column 'value' not found in GAM_career_data table")
                return

            cursor.execute("SELECT value FROM [GAM_career_data] WHERE UID = 1")
            row = cursor.fetchone()

            if not row:
                messagebox.showerror("Error", "No career data found (UID = 1 not found in GAM_career_data)")
                return

            current_value = row[0]

            new_value = simpledialog.askinteger(
                "Change Team Budget",
                "Enter new team budget:",
                initialvalue=current_value,
                minvalue=0,
                parent=self.root,
            )

            if new_value is not None:
                self.db.update_cell("GAM_career_data", "value", new_value, "UID", 1)
                self.unsaved_changes = True

                if self.table_view.current_table == "GAM_career_data":
                    self.table_view.load_table_data()

                self.status.config(text=f"Team budget updated to {new_value}")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to update budget: {str(e)}")

    # ==================================================================
    # CSV Import / Export
    # ==================================================================

    def export_csv(self):
        """Export the current table to a CSV file."""
        if not self.db:
            return
        if not self.table_view.current_table:
            return messagebox.showwarning("Warning", "No table selected.")

        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile=f"{self.table_view.current_table}.csv",
        )
        if path:
            table_name = self.table_view.current_table
            run_async(
                self.root,
                lambda: csv_io.export_table(self.temp_path, table_name, path),
                lambda _: self.status.config(text=f"Exported table '{table_name}' to CSV"),
                "Exporting CSV...",
            )

    def import_csv_table(self):
        """Overwrite the current table's data from a CSV file."""
        if not self.db:
            return
        if not self.table_view.current_table:
            return messagebox.showwarning("Warning", "No table selected.")

        path = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv")])
        if path:
            if not messagebox.askyesno(
                "Confirm Import",
                f"This will overwrite data in '{self.table_view.current_table}' with data from the CSV. Continue?",
            ):
                return

            table_name = self.table_view.current_table

            def on_complete(_):
                self.unsaved_changes = True
                self.table_view.load_table_data()
                self.status.config(text=f"Imported CSV data into table '{table_name}'")

            run_async(
                self.root,
                lambda: csv_io.import_table_from_csv(self.temp_path, table_name, path),
                on_complete, "Importing CSV...",
            )

    def export_all_csv(self):
        """Export all database tables as CSV files into a folder."""
        if not self.db:
            return

        folder = filedialog.askdirectory(title="Select folder to export all tables")
        if folder:
            run_async(
                self.root,
                lambda: csv_io.export_to_csv(self.temp_path, folder),
                lambda _: self.status.config(text="Successfully exported all tables to folder"),
                "Exporting all tables...",
            )

    def import_all_csv(self):
        """Overwrite all matching tables from CSV files in a folder."""
        if not self.db:
            return

        folder = filedialog.askdirectory(title="Select folder containing CSV files")
        if folder:
            if not messagebox.askyesno(
                "Confirm Import",
                "This will overwrite data in ALL matching tables with data from CSV files in the selected folder. Continue?",
            ):
                return

            def on_complete(_):
                self.unsaved_changes = True
                if self.table_view.current_table:
                    self.table_view.load_table_data()
                self.status.config(text="Successfully imported all matching tables from folder")

            run_async(
                self.root,
                lambda: csv_io.import_from_csv(self.temp_path, folder),
                on_complete, "Importing all tables...",
            )

    # ==================================================================
    # Column Manager & Table Operations
    # ==================================================================

    def open_column_manager(self):
        if not self.db or not self.table_view.current_table:
            messagebox.showwarning("No Table", "Please select a table first.")
            return
        ColumnManagerDialog(self.root, self.table_view, self.state)

    def clear_table(self):
        """Delete all rows from the current table (undoable)."""
        if not self.db or not self.table_view.current_table:
            messagebox.showwarning("No Table", "Please select a table first.")
            return

        try:
            table_name = self.table_view.current_table
            total_rows = self.db.get_row_count(table_name)

            if total_rows == 0:
                messagebox.showinfo("Empty Table", "This table is already empty.")
                return

            if not messagebox.askyesno(
                "Confirm Clear Table",
                f"This will delete ALL {total_rows} rows from '{table_name}'.\n\nThis action can be undone.\n\nContinue?",
            ):
                return

            columns = self.db.get_columns(table_name)
            pk_col = columns[0]

            _, all_rows = self.db.fetch_data(table_name, limit=None)

            deleted_rows = [{"pk": row[0], "data": list(row)} for row in all_rows]

            pk_vals = [row[0] for row in all_rows]
            self.db.delete_rows(table_name, pk_col, pk_vals)

            if deleted_rows:
                action = {
                    "type": "row_op",
                    "mode": "delete",
                    "table": table_name,
                    "pk_col": pk_col,
                    "columns": columns,
                    "rows": deleted_rows,
                }
                self.state.push_action(action)

            self.unsaved_changes = True
            self.table_view.load_table_data()
            self._update_btns()
            self.status.config(text=f"Cleared {len(deleted_rows)} rows from '{table_name}'")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to clear table: {str(e)}")

    # ==================================================================
    # Helpers
    # ==================================================================

    def _create_search_box(self, parent, var, width):
        """Create a search entry with a clear button, returns the container frame."""
        frame = tk.Frame(parent, bg="white", highlightbackground="#ccc", highlightthickness=1)
        tk.Entry(frame, textvariable=var, width=width, relief="flat").pack(side="left", padx=5, fill="x", expand=True)
        tk.Button(frame, text="✕", command=lambda: var.set(""), relief="flat", bg="white", bd=0).pack(side="right")
        return frame

    def _on_selection_change(self, event=None):
        count = len(self.table_view.tree.selection())
        self.selection_label.config(text=f"{count} row{'s' if count != 1 else ''} selected" if count else "")

    def on_table_select(self, table_name):
        """Handle sidebar table selection — clear search and load the table."""
        self.search_var.set("")
        self.table_view.set_table(table_name)

    def on_close(self):
        """Save settings and close the application, prompting if unsaved."""
        if self.unsaved_changes:
            if not messagebox.askyesno("Unsaved Changes", "You have unsaved changes. Are you sure you want to exit?"):
                return
        is_maximized = False
        try:
            if sys.platform.startswith('win'):
                is_maximized = self.root.state() == 'zoomed'
            else:
                is_maximized = self.root.attributes('-zoomed')
        except (tk.TclError, AttributeError):
            pass
        self.state.save_settings(self.normal_geometry, is_maximized, self.lookup_var.get())
        if self.db:
            self.db.close()
        self.root.destroy()
