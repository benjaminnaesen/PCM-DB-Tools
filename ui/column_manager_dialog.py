"""
Column visibility management dialog.

Provides UI for showing/hiding columns, saving/loading presets,
and searching through available columns.
"""

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog


class ColumnManagerDialog:
    """
    Modal dialog for managing column visibility with preset support.

    Features:
        - Checkboxes for all columns (primary key always visible)
        - Search/filter columns by name
        - Save/load/delete column visibility presets
        - Show All / Hide All buttons
    """
    def __init__(self, parent, table_view, app_state):
        """
        Initialize column manager dialog.

        Args:
            parent: Parent tkinter window
            table_view (TableView): Table view instance
            app_state (AppState): Application state manager
        """
        self.parent = parent
        self.table_view = table_view
        self.state = app_state
        self.current_table = table_view.current_table

        if not self.current_table:
            messagebox.showwarning("No Table", "Please select a table first.")
            return

        self.dialog = tk.Toplevel(parent)
        self.dialog.title(f"Manage Columns - {self.current_table}")
        self.dialog.geometry("500x600")
        self.dialog.transient(parent)
        self.dialog.grab_set()

        # Get all columns
        self.all_columns = table_view.get_all_columns()
        if not self.all_columns:
            messagebox.showwarning("No Columns", "No columns available.")
            self.dialog.destroy()
            return

        # Current visible columns
        visible_cols = self.state.get_visible_columns(self.current_table)
        self.visible_columns = visible_cols if visible_cols else self.all_columns.copy()

        self._setup_ui()

    def _setup_ui(self):
        # Top frame with presets
        preset_frame = tk.Frame(self.dialog, bg="#f0f0f0", pady=10)
        preset_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)

        tk.Label(preset_frame, text="Presets:", bg="#f0f0f0", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=5)

        self.preset_var = tk.StringVar()
        self.preset_combo = ttk.Combobox(preset_frame, textvariable=self.preset_var, state="readonly", width=20)
        self.preset_combo.pack(side=tk.LEFT, padx=5)
        self.update_preset_list()

        tk.Button(preset_frame, text="Save", command=self.save_preset, width=8).pack(side=tk.LEFT, padx=2)
        tk.Button(preset_frame, text="Load", command=self.load_preset, width=8).pack(side=tk.LEFT, padx=2)
        tk.Button(preset_frame, text="Delete", command=self.delete_preset, width=8).pack(side=tk.LEFT, padx=2)

        # Search box
        search_frame = tk.Frame(self.dialog, bg="#f0f0f0", pady=5)
        search_frame.pack(side=tk.TOP, fill=tk.X, padx=10)

        tk.Label(search_frame, text="Filter:", bg="#f0f0f0").pack(side=tk.LEFT, padx=5)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self.filter_columns)
        tk.Entry(search_frame, textvariable=self.search_var, width=30).pack(side=tk.LEFT, padx=5)

        # Columns list with checkboxes
        list_frame = tk.Frame(self.dialog)
        list_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=10)

        tk.Label(list_frame, text="Columns:", font=("Segoe UI", 9, "bold")).pack(anchor="w")

        # Scrollable frame for checkboxes
        canvas = tk.Canvas(list_frame, bg="white", highlightthickness=1, highlightbackground="#ccc")
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        self.scrollable_frame = tk.Frame(canvas, bg="white")

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Create checkboxes for each column
        self.column_vars = {}
        self.column_checkboxes = {}
        self.create_column_checkboxes()

        # Bottom buttons
        button_frame = tk.Frame(self.dialog, bg="#f0f0f0", pady=10)
        button_frame.pack(side=tk.BOTTOM, fill=tk.X)

        tk.Button(button_frame, text="Show All", command=self.show_all_columns, width=10).pack(side=tk.LEFT, padx=5)
        tk.Button(button_frame, text="Hide All", command=self.hide_all_columns, width=10).pack(side=tk.LEFT, padx=5)
        tk.Button(button_frame, text="Apply", command=self.apply_changes, width=12, bg="#4CAF50", fg="white").pack(side=tk.RIGHT, padx=10)
        tk.Button(button_frame, text="Cancel", command=self.dialog.destroy, width=12).pack(side=tk.RIGHT, padx=5)

    def create_column_checkboxes(self):
        """Create checkboxes for all columns."""
        # Clear existing checkboxes
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()

        self.column_vars = {}
        self.column_checkboxes = {}

        for i, col in enumerate(self.all_columns):
            var = tk.BooleanVar(value=col in self.visible_columns)
            self.column_vars[col] = var

            # Disable first column (primary key) - must always be visible
            state = "disabled" if i == 0 else "normal"
            if i == 0:
                var.set(True)  # Always checked

            cb = tk.Checkbutton(
                self.scrollable_frame,
                text=col,
                variable=var,
                state=state,
                bg="white",
                anchor="w",
                font=("Segoe UI", 9)
            )
            cb.pack(fill=tk.X, padx=10, pady=2)
            self.column_checkboxes[col] = cb

    def filter_columns(self, *args):
        """
        Filter visible checkboxes based on search term.

        Shows/hides checkboxes that match the filter text.
        """
        search_term = self.search_var.get().lower()

        for col, cb in self.column_checkboxes.items():
            if search_term in col.lower():
                cb.pack(fill=tk.X, padx=10, pady=2)
            else:
                cb.pack_forget()

    def show_all_columns(self):
        """Check all column checkboxes (select all for visibility)."""
        for col, var in self.column_vars.items():
            var.set(True)

    def hide_all_columns(self):
        """
        Uncheck all column checkboxes (except primary key).

        Primary key is always kept visible to maintain data integrity.
        """
        for i, (col, var) in enumerate(self.column_vars.items()):
            if i > 0:  # Don't hide primary key
                var.set(False)

    def update_preset_list(self):
        """Refresh preset dropdown with saved presets from app state."""
        presets = self.state.get_column_presets(self.current_table)
        self.preset_combo['values'] = list(presets.keys())

    def save_preset(self):
        """
        Save current column selection as a named preset.

        Prompts user for preset name and stores selected columns.
        """
        preset_name = simpledialog.askstring(
            "Save Preset",
            "Enter preset name:",
            parent=self.dialog
        )

        if preset_name:
            # Get currently selected columns
            selected_columns = [col for col, var in self.column_vars.items() if var.get()]
            self.state.save_column_preset(self.current_table, preset_name, selected_columns)
            self.update_preset_list()
            self.preset_var.set(preset_name)
            messagebox.showinfo("Success", f"Preset '{preset_name}' saved successfully.")

    def load_preset(self):
        """
        Load a saved preset from dropdown.

        Updates checkboxes to match the selected preset's column visibility.
        """
        preset_name = self.preset_var.get()
        if not preset_name:
            messagebox.showwarning("No Preset", "Please select a preset to load.")
            return

        presets = self.state.get_column_presets(self.current_table)
        if preset_name in presets:
            preset_columns = presets[preset_name]
            # Update checkboxes
            for col, var in self.column_vars.items():
                var.set(col in preset_columns)

    def delete_preset(self):
        """
        Delete the currently selected preset.

        Requires confirmation before deletion.
        """
        preset_name = self.preset_var.get()
        if not preset_name:
            messagebox.showwarning("No Preset", "Please select a preset to delete.")
            return

        if messagebox.askyesno("Confirm Delete", f"Delete preset '{preset_name}'?"):
            self.state.delete_column_preset(self.current_table, preset_name)
            self.update_preset_list()
            self.preset_var.set("")

    def apply_changes(self):
        """
        Apply selected column visibility to table view.

        Validates that primary key remains visible before applying.
        """
        selected_columns = [col for col, var in self.column_vars.items() if var.get()]

        # Ensure at least the primary key is selected
        if not selected_columns or self.all_columns[0] not in selected_columns:
            messagebox.showerror("Error", "You must keep at least the primary key column visible.")
            return

        # Update visibility
        self.table_view.set_visible_columns(selected_columns)
        self.dialog.destroy()
