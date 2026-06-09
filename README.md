# PCM Database Tools

A desktop application bundling modding tools for Pro Cycling Manager (PCM), including a database editor and startlist generator.

## Features

### Database Editor

- **CDB File Support**: Open and edit .cdb files from Pro Cycling Manager games
- **Table Browser**: Browse all database tables with a searchable sidebar
- **Favorites System**: Star frequently-used tables for quick access with drag-and-drop reordering
- **Smart Editing**:
  - Double-click cells to edit
  - Lookup Mode: Display human-readable names for foreign key relationships
  - Keyboard navigation (Tab, Arrow keys)
- **Undo/Redo**: Full undo/redo support for all cell edits (Ctrl+Z / Ctrl+Y)
- **Search & Filter**: Real-time search across table contents
- **Sorting**: Click column headers to sort (ascending/descending)
- **CSV Operations**:
  - Export individual tables to CSV
  - Import CSV data back into tables
  - Export/Import all tables at once
- **Column Management**: Show/hide columns with saveable presets
- **Row Operations**: Multi-select, duplicate, or delete rows via right-click context menu
- **Session Persistence**: Remembers window size, favorites, recent files, and settings
- **Pagination**: Efficiently handles large tables with lazy loading

### Startlist Generator

- **URL-based Fetching**: Paste a ProCyclingStats startlist URL and fetch it directly
- **Auto Race Selection**: Pasting a URL automatically selects the matching race from the dropdown
- **Database Matching**: Match rider/team names to PCM database IDs using CSV databases or an opened CDB file
- **Progress Tracking**: Real-time log output and progress bar during conversion

## Requirements

- **Python**: 3.10 or higher
- **Operating System**: Windows (required for SQLiteExporter.exe)
- **Dependencies**: PySide6, beautifulsoup4, cloudscraper — install with pip (see below)

## Installation

1. **Clone or Download** this repository
2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

### Starting the Application

```bash
python main.py
```

The home screen presents two tools: **Database Editor** and **Startlist Generator**, plus a list of recently opened CDB files. Click a recent file to jump straight into editing.

---

### Database Editor

#### Opening a Database

1. Click the **Database Editor** tile on the home screen, or click a recent file
2. Select a `.cdb` file from the file dialog
3. The app converts it to SQLite internally and loads all tables

#### Browsing Tables

- The **sidebar** lists all tables in the database
- Type in the sidebar search box to filter tables by name
- **Favorites**: Right-click a table and select "Add to Favorites" to pin it at the top. Drag and drop to reorder favorites

#### Editing Data

- **Double-click** any cell (including ID columns) to start editing
- **Enter**: Commit the edit and move to the cell below
- **Tab / Shift+Tab**: Move to the next / previous cell
- **Arrow Up / Down**: Move to the cell above / below
- **Escape**: Cancel the edit
- Type a new value and press Enter to save it to the database

#### Lookup Mode

Toggle **Lookup: ON/OFF** in the toolbar to switch between raw IDs and human-readable names for foreign key columns.

- When **ON**: FK columns display resolved names (e.g. team names, rider names instead of numeric IDs). Searching also matches against these display names.
- When **OFF**: FK columns display raw ID values
- Single-click an FK cell in lookup mode to open a dropdown with all valid options

#### Search

The search box in the toolbar filters the current table in real-time:
- Searches across **all columns** simultaneously
- In lookup mode, also matches FK display values (e.g. search "Jumbo" to find riders by team name)
- Clear the search with the X button

#### Sorting

- Click any **column header** to sort ascending
- Click again to sort **descending**
- Sorting persists until you switch tables

#### Row Operations

- **Add Row**: Click the "Add Row" button in the toolbar to insert a new row
- **Duplicate Row**: Right-click a row (or multi-select rows) and choose "Duplicate Row"
- **Delete Row**: Right-click and choose "Delete Row"
- **Multi-select**: Hold Ctrl or Shift and click rows, or press Ctrl+A to select all

#### Column Management

- **Hide columns**: Right-click a column header and select "Hide Column"
- **Manage columns**: Use the Tools menu > "Manage Columns" to open the column visibility dialog
  - Check/uncheck columns to show or hide them
  - Save column visibility configurations as **presets** for reuse
  - Use "Show All" / "Hide All" for bulk toggling

#### Undo / Redo

- **Ctrl+Z**: Undo the last cell edit
- **Ctrl+Y**: Redo
- The undo/redo buttons in the toolbar also work

#### CSV Import / Export

From the **Tools** menu:
- **Export Table to CSV**: Save the current table as a CSV file
- **Import CSV to Table**: Load data from a CSV file into the current table
- **Export All Tables**: Export every table in the database to individual CSV files in a folder
- **Import All Tables**: Import CSVs from a folder, matching filenames to table names

#### Saving Changes

- Click **Save As...** in the toolbar to convert the modified SQLite database back to a `.cdb` file
- The app will prompt for an output path -- you can overwrite the original or save to a new file
- **Always keep a backup of your original `.cdb` file**

---

### Startlist Generator

The startlist generator has two tabs: **Singleplayer** (HTML to XML) and **Multiplayer** (HTML + CDB to modified CDB).

#### Singleplayer: URL to XML Startlist

Use this to generate a PCM-compatible XML startlist file from a live startlist URL.

**Step-by-step:**

1. Click the **Startlist Generator** tile from the home screen
2. **Select a database** for ID matching:
   - Pick a CSV database from the dropdown (databases stored in the `databases/` folder), OR
   - Click **Open CDB...** to load a `.cdb` file directly
3. The database status will confirm how many teams and cyclists were loaded
4. **Paste a startlist URL** from [ProCyclingStats](https://www.procyclingstats.com) into the URL field — the race dropdown will auto-select the matching race
5. **Verify the race** selection in the dropdown (or pick one manually)
6. Click **Fetch** to download the startlist, then **Generate Startlist**
7. A **Save As** dialog will open — choose where to save the output XML file
8. The log will show the matching progress: which teams and riders were matched to database IDs, and which were not found

#### Multiplayer: CDB Startlist Modification

Use this to create a modified CDB where teams are trimmed to their race startlist. Non-startlist riders are moved to the free agent pool (team 119).

**How it works:**
- For teams **with riders in the HTML startlist**: keeps all matched riders.
- Removed riders have their `fkIDteam` set to 119 (free agent) and their contracts deleted

**Step-by-step:**

1. Go to the **Multiplayer** tab in the Startlist Generator
2. Click **Load CDB...** to select and convert your `.cdb` database
3. **Paste the startlist URL** into the URL field
4. Click **Save as...** to choose the output `.cdb` file path
5. Click **Generate CDB Startlist**
6. A backup reminder will appear -- make sure you have a copy of your original CDB
7. The log shows the matching process:
   - `[TEAM] Team Name -> ID 123` for matched teams
   - `[RIDER] Rider Name -> ID 456` for matched riders
   - `-> NOT FOUND` for unmatched entries
8. After matching, the app modifies the database and exports the result as a new `.cdb` file
9. A summary dialog shows how many riders were kept and how many were moved to team 119

**Tip:** The output CDB is a new file -- your original database is never modified.

---

### Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| **Ctrl+Z** | Undo last edit |
| **Ctrl+Y** | Redo |
| **Ctrl+A** | Select all rows |
| **Double-click** | Edit cell |
| **Enter** | Commit edit, move down |
| **Tab** | Commit edit, move to next cell |
| **Shift+Tab** | Commit edit, move to previous cell |
| **Arrow Up/Down** | Commit edit, move up/down |
| **Escape** | Cancel edit |

### File Formats

| Extension | Description |
|---|---|
| `.cdb` | Pro Cycling Manager database file (proprietary format) |
| `.sqlite` | SQLite database (used internally during editing) |
| `.csv` | Comma-separated values (for bulk data import/export) |
| `.xml` | PCM startlist format (output of Singleplayer generator) |
| `.html` | Startlist page fetched from ProCyclingStats (used internally) |

The application automatically handles conversion between CDB and SQLite formats using the bundled SQLiteExporter.exe tool.

## Project Structure

```
PCM-Database-Tools/
├── main.py                          # Application entry point
├── core/                            # Business logic
│   ├── db_manager.py                # Database operations and queries
│   ├── app_state.py                 # Application state and settings
│   ├── constants.py                 # Shared constants
│   ├── converter.py                 # CDB ↔ SQLite conversion
│   ├── csv_io.py                    # CSV import/export
│   └── startlist.py                 # Startlist parsing, matching, and XML writing
├── ui/                              # User interface components
│   ├── editor_gui.py                # Main application window and menu
│   ├── welcome_screen.py            # Home screen with tool tiles
│   ├── sidebar.py                   # Table list and favorites sidebar
│   ├── table_view.py                # Table data display and editing
│   ├── column_manager_dialog.py     # Column visibility and presets dialog
│   ├── startlist_view.py            # Startlist generator view
│   └── ui_utils.py                  # Tooltips and async task helpers
├── databases/                       # CSV database folders for startlist matching
├── SQLiteExporter/                  # External conversion tool
│   └── SQLiteExporter.exe           # CDB ↔ SQLite converter (Windows)
├── tests/                           # Unit tests
│   ├── test_app_state.py            # AppState tests
│   ├── test_db_manager.py           # DatabaseManager tests
│   └── ...
├── requirements.txt                 # Python dependencies
├── session_config.json              # User preferences (auto-generated)
└── README.md
```

## Configuration

The application automatically creates `session_config.json` to store:
- Window size and maximized state
- Favorite tables
- Recent file paths
- Last opened directory
- Lookup mode preference

This file is gitignored and will be created on first run.

## Testing

```bash
# Run all tests
python -m unittest discover tests

# Run a specific test module
python -m unittest tests.test_app_state
```

## Contributing

1. Follow existing code style and patterns
2. Test changes on actual PCM CDB files
3. Add tests for new functionality
4. Update documentation for new features

## Known Limitations

- **Windows Only**: Requires SQLiteExporter.exe which is Windows-specific
- **CDB Format**: Supports PCM game CDB files only
- **Large Files**: Very large databases may take time to convert and load

## Troubleshooting

**"Module PySide6 not found"**
Run `pip install -r requirements.txt` to install all dependencies.

**"SQLiteExporter.exe not found"**
Ensure the `SQLiteExporter/` folder is in the same directory as `main.py`.

**CDB file won't open**
Ensure the file is a valid PCM CDB file and not corrupted.

## Credits

- **SQLiteExporter**: External tool for CDB/SQLite conversion (see SQLiteExporter/Readme.pdf)
- Developed for the Pro Cycling Manager modding community

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

**Always backup your .cdb files before editing!** While this tool has undo/redo support, it's always safer to keep backups of your game files.
