"""
Manages application state including settings, favorites, and undo/redo history.

Persists user preferences to JSON file and maintains undo/redo stacks for edits.
"""

import json
import os

from core.constants import MAX_RECENT_FILES, MAX_UNDO_STACK_SIZE


class AppState:
    """
    Manages application state including settings, favorites, and undo/redo history.

    Persists user preferences to JSON file and maintains undo/redo stacks for edits.
    """

    def __init__(self, settings_file):
        """
        Initialize application state from settings file.

        Args:
            settings_file (str): Path to JSON settings file

        Notes:
            Creates default settings if file doesn't exist.
        """
        self.settings_file = settings_file
        self.undo_stack = []
        self.redo_stack = []
        self.settings = self.load_settings()
        self.favorites = self.settings.get("favorites", [])
        self.recents = self.settings.get("recents", [])
        self.column_widths = self.settings.get("column_widths", {})
        self.column_visibility = self.settings.get("column_visibility", {})
        self.column_presets = self.settings.get("column_presets", {})

    def load_settings(self):
        """
        Load settings from JSON file or return defaults.

        Returns:
            dict: Settings dictionary with keys: favorites, window_size,
                  last_path, is_maximized, lookup_mode, recents

        Notes:
            Returns default settings if file doesn't exist or is invalid.
        """
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, "r") as file:
                    return json.load(file)
            except (json.JSONDecodeError, OSError):
                pass
        return {
            "favorites": [],
            "window_size": "1200x800",
            "last_path": "",
            "is_maximized": False,
            "lookup_mode": False,
            "recents": [],
        }

    def save_partial(self):
        """Write current settings to disk without requiring window state args."""
        with open(self.settings_file, "w") as file:
            json.dump(self.settings, file, indent=4)

    def save_settings(self, window_geometry, is_maximized, lookup_mode):
        """
        Persist current application settings to JSON file.

        Args:
            window_geometry (str): Window size and position (e.g., "1200x800+100+50")
            is_maximized (bool): Whether window is maximized
            lookup_mode (bool): Whether lookup mode is enabled
        """
        self.settings["favorites"] = self.favorites
        self.settings["recents"] = self.recents
        self.settings["column_widths"] = self.column_widths
        self.settings["column_visibility"] = self.column_visibility
        self.settings["column_presets"] = self.column_presets
        self.settings["window_size"] = window_geometry
        self.settings["is_maximized"] = is_maximized
        self.settings["lookup_mode"] = lookup_mode
        with open(self.settings_file, "w") as file:
            json.dump(self.settings, file, indent=4)

    def add_recent(self, path):
        """
        Add file path to recent files list (maximum entries defined by MAX_RECENT_FILES).

        Args:
            path (str): File path to add
        """
        if path in self.recents:
            self.recents.remove(path)
        self.recents.insert(0, path)
        self.recents = self.recents[:MAX_RECENT_FILES]

    # ------------------------------------------------------------------
    # Undo / Redo
    # ------------------------------------------------------------------

    def _trim_undo_stack(self):
        """Trim undo stack to MAX_UNDO_STACK_SIZE, dropping oldest entries."""
        if len(self.undo_stack) > MAX_UNDO_STACK_SIZE:
            self.undo_stack = self.undo_stack[-MAX_UNDO_STACK_SIZE:]

    def push_undo(self, table, col, old, new, pk):
        """
        Add an edit action to the undo stack.

        Args:
            table (str): Table name where edit occurred
            col (str): Column name that was edited
            old: Previous value before edit
            new: New value after edit
            pk: Primary key value identifying the row
        """
        self.undo_stack.append({
            "table": table, "column": col,
            "old": old, "new": new, "pk": pk,
        })
        self.redo_stack.clear()
        self._trim_undo_stack()

    def push_action(self, action):
        """
        Push a generic action dictionary to the undo stack.

        Args:
            action (dict): Dictionary containing action details (type, table, etc.)
        """
        self.undo_stack.append(action)
        self.redo_stack.clear()
        self._trim_undo_stack()

    def undo(self):
        """
        Pop the most recent action from undo stack and add to redo stack.

        Returns:
            dict or None: Action dictionary, or None if undo stack is empty
        """
        if not self.undo_stack:
            return None
        action = self.undo_stack.pop()
        self.redo_stack.append(action)
        return action

    def redo(self):
        """
        Pop the most recent action from redo stack and add back to undo stack.

        Returns:
            dict or None: Action dictionary, or None if redo stack is empty
        """
        if not self.redo_stack:
            return None
        action = self.redo_stack.pop()
        self.undo_stack.append(action)
        return action

    # ------------------------------------------------------------------
    # Column preferences
    # ------------------------------------------------------------------

    def get_column_widths(self, table_name):
        """
        Get saved column widths for a specific table.

        Args:
            table_name (str): Name of the table

        Returns:
            dict or None: Dictionary mapping column names to widths, or None if not saved
        """
        return self.column_widths.get(table_name)

    def set_column_widths(self, table_name, widths):
        """
        Save column widths for a specific table.

        Args:
            table_name (str): Name of the table
            widths (dict): Dictionary mapping column names to widths
        """
        self.column_widths[table_name] = widths

    def get_visible_columns(self, table_name):
        """
        Get list of visible columns for a specific table.

        Args:
            table_name (str): Name of the table

        Returns:
            list or None: List of visible column names, or None if not set (show all)
        """
        return self.column_visibility.get(table_name)

    def set_visible_columns(self, table_name, columns):
        """
        Save visible columns for a specific table.

        Args:
            table_name (str): Name of the table
            columns (list): List of visible column names
        """
        self.column_visibility[table_name] = columns

    def get_column_presets(self, table_name):
        """
        Get saved column presets for a specific table.

        Args:
            table_name (str): Name of the table

        Returns:
            dict: Dictionary mapping preset names to column lists
        """
        return self.column_presets.get(table_name, {})

    def save_column_preset(self, table_name, preset_name, columns):
        """
        Save a column preset for a specific table.

        Args:
            table_name (str): Name of the table
            preset_name (str): Name of the preset
            columns (list): List of column names in this preset
        """
        if table_name not in self.column_presets:
            self.column_presets[table_name] = {}
        self.column_presets[table_name][preset_name] = columns

    def delete_column_preset(self, table_name, preset_name):
        """
        Delete a column preset.

        Args:
            table_name (str): Name of the table
            preset_name (str): Name of the preset to delete
        """
        if table_name in self.column_presets and preset_name in self.column_presets[table_name]:
            del self.column_presets[table_name][preset_name]
