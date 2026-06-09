"""
Application-wide constants for PCM Database Tools.

This module contains all magic numbers and configuration values
used throughout the application, centralized for easy maintenance.
"""

# App metadata
APP_NAME = "PCM Database Tools"
APP_VERSION = "1.2.0"

# Pagination settings
ROW_CHUNK_SIZE = 50  # Number of rows loaded per scroll chunk
COL_CHUNK_SIZE = 15  # Number of columns loaded per scroll chunk

# Database operations
DB_CHUNK_SIZE = 900  # SQLite parameter limit safety margin for bulk operations

# UI delays (milliseconds)
SEARCH_DEBOUNCE_DELAY = 300  # Delay before executing database search
FILTER_DEBOUNCE_DELAY = 200  # Delay before filtering sidebar table list

# Recent files
MAX_RECENT_FILES = 10  # Maximum number of recent files to track

# Table view
DEFAULT_COLUMN_WIDTH = 140  # Default pixel width for table columns
RESIZE_SAVE_DELAY = 500  # Delay in ms before saving column width changes

# Undo/Redo
MAX_UNDO_STACK_SIZE = 100  # Maximum number of undo operations to track

# Window defaults
DEFAULT_WINDOW_WIDTH = 1200
DEFAULT_WINDOW_HEIGHT = 800
