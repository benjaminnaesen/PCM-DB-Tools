"""
Startlist generator view.

Full-frame view for converting saved HTML startlists from FirstCycling
or ProCyclingStats into PCM-compatible XML files.  Supports loading
team/cyclist data from CSV database folders or from an opened CDB file.

Two tabs:
    - Singleplayer: HTML -> XML conversion with ID matching
    - Multiplayer:  HTML + CDB -> modified CDB with non-startlist riders
                    on participating teams moved to team 119
"""

import gc
import os

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QProgressBar, QPushButton, QTabWidget,
    QTextEdit, QVBoxLayout, QWidget,
)

import core.converter as converter
from core.startlist import (
    StartlistDatabase, StartlistParser, PCMXmlWriter,
    apply_multiplayer_startlist, fetch_startlist_url,
)
from ui.ui_utils import run_async


# databases/ folder next to main.py
DATABASES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'databases',
)


class StartlistView(QWidget):
    """Full-frame startlist generator with database selector."""

    go_home = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parser = StartlistParser()
        self.writer = PCMXmlWriter()
        self.db = None
        self.temp_path = None

        # Multiplayer state
        self.mp_db = None
        self.mp_temp_path = None

        self._build_ui()
        self._load_selected_db()

    # ==================================================================
    # UI construction
    # ==================================================================

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(8, 8, 8, 8)
        back_btn = QPushButton("\u2190 Back")
        back_btn.setStyleSheet("background: #b0b0b0;")
        back_btn.clicked.connect(self._on_home)
        toolbar.addWidget(back_btn)
        toolbar.addStretch()
        outer.addLayout(toolbar)

        # Tabs
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)

        self._build_singleplayer_tab()
        self._build_multiplayer_tab()

        # Status bar
        self.status = QLabel("Ready")
        self.status.setStyleSheet(
            "padding: 4px; border-top: 1px solid #ccc; color: #555;")
        outer.addWidget(self.status)

    # -- Singleplayer tab ----------------------------------------------

    def _build_singleplayer_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 8, 12, 8)

        # Database section
        db_group = QGroupBox("Database")
        db_lay = QVBoxLayout(db_group)
        db_row = QHBoxLayout()
        db_row.addWidget(QLabel("Select database:"))

        self._db_names = []
        if os.path.isdir(DATABASES_DIR):
            self._db_names = sorted(
                d for d in os.listdir(DATABASES_DIR)
                if os.path.isdir(os.path.join(DATABASES_DIR, d))
            )

        self.db_combo = QComboBox()
        self.db_combo.addItems(self._db_names)
        self.db_combo.currentIndexChanged.connect(
            lambda: self._load_selected_db())
        db_row.addWidget(self.db_combo, 1)

        db_row.addWidget(QLabel("or"))
        cdb_btn = QPushButton("Open CDB\u2026")
        cdb_btn.clicked.connect(self._load_cdb)
        db_row.addWidget(cdb_btn)
        db_lay.addLayout(db_row)

        self.db_status = QLabel("")
        self.db_status.setStyleSheet("color: #888; font-size: 9pt;")
        db_lay.addWidget(self.db_status)
        layout.addWidget(db_group)

        # HTML file input
        file_group = QGroupBox("HTML startlist file")
        file_lay = QVBoxLayout(file_group)
        file_row = QHBoxLayout()
        self.file_edit = QLineEdit()
        file_row.addWidget(self.file_edit, 1)
        browse_btn = QPushButton("Browse\u2026")
        browse_btn.clicked.connect(self._browse_file)
        file_row.addWidget(browse_btn)
        file_lay.addLayout(file_row)

        url_row = QHBoxLayout()
        url_row.addWidget(QLabel("or URL:"))
        self.url_edit = QLineEdit()
        url_row.addWidget(self.url_edit, 1)
        fetch_btn = QPushButton("Fetch")
        fetch_btn.clicked.connect(self._fetch_url)
        url_row.addWidget(fetch_btn)
        file_lay.addLayout(url_row)
        layout.addWidget(file_group)

        # Race selection
        race_group = QGroupBox("Race")
        race_lay = QVBoxLayout(race_group)
        race_row = QHBoxLayout()
        race_row.addWidget(QLabel("Select race:"))
        self._race_map = {}
        self.race_combo = QComboBox()
        self.race_combo.currentIndexChanged.connect(self._on_race_selected)
        race_row.addWidget(self.race_combo, 1)
        race_lay.addLayout(race_row)

        self.out_label = QLabel("")
        self.out_label.setStyleSheet("color: #888; font-size: 9pt;")
        race_lay.addWidget(self.out_label)
        layout.addWidget(race_group)

        # Generate button
        gen_btn = QPushButton("Generate Startlist")
        gen_btn.setStyleSheet(
            "QPushButton { background: #2e8b57; color: white; padding: 6px 16px; }"
            "QPushButton:hover { background: #267349; }")
        gen_btn.clicked.connect(self._convert)
        layout.addWidget(gen_btn)

        # Progress bar
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        # Log
        layout.addWidget(QLabel("Log:"))
        self.log_widget = QTextEdit()
        self.log_widget.setReadOnly(True)
        self.log_widget.setStyleSheet(
            "background: #1e1e1e; color: #cccccc;"
            "font-family: Consolas; font-size: 9pt;")
        layout.addWidget(self.log_widget, 1)

        self.tabs.addTab(tab, "Singleplayer")

    # -- Multiplayer tab -----------------------------------------------

    def _build_multiplayer_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 8, 12, 8)

        # CDB file input
        cdb_group = QGroupBox("CDB database file")
        cdb_lay = QVBoxLayout(cdb_group)
        cdb_row = QHBoxLayout()
        self.mp_cdb_edit = QLineEdit()
        self.mp_cdb_edit.setReadOnly(True)
        cdb_row.addWidget(self.mp_cdb_edit, 1)
        load_btn = QPushButton("Load CDB\u2026")
        load_btn.clicked.connect(self._mp_browse_cdb)
        cdb_row.addWidget(load_btn)
        cdb_lay.addLayout(cdb_row)

        self.mp_cdb_status = QLabel("No CDB loaded")
        self.mp_cdb_status.setStyleSheet("color: #888; font-size: 9pt;")
        cdb_lay.addWidget(self.mp_cdb_status)
        layout.addWidget(cdb_group)

        # HTML startlist input
        html_group = QGroupBox("HTML startlist file")
        html_lay = QVBoxLayout(html_group)
        html_row = QHBoxLayout()
        self.mp_html_edit = QLineEdit()
        html_row.addWidget(self.mp_html_edit, 1)
        html_btn = QPushButton("Browse\u2026")
        html_btn.clicked.connect(self._mp_browse_html)
        html_row.addWidget(html_btn)
        html_lay.addLayout(html_row)

        mp_url_row = QHBoxLayout()
        mp_url_row.addWidget(QLabel("or URL:"))
        self.mp_url_edit = QLineEdit()
        mp_url_row.addWidget(self.mp_url_edit, 1)
        mp_fetch_btn = QPushButton("Fetch")
        mp_fetch_btn.clicked.connect(self._mp_fetch_url)
        mp_url_row.addWidget(mp_fetch_btn)
        html_lay.addLayout(mp_url_row)
        layout.addWidget(html_group)

        # Output CDB file
        out_group = QGroupBox("Output CDB file")
        out_lay = QVBoxLayout(out_group)
        out_row = QHBoxLayout()
        self.mp_out_edit = QLineEdit()
        out_row.addWidget(self.mp_out_edit, 1)
        save_btn = QPushButton("Save as\u2026")
        save_btn.clicked.connect(self._mp_browse_output)
        out_row.addWidget(save_btn)
        out_lay.addLayout(out_row)
        layout.addWidget(out_group)

        # Process button
        proc_btn = QPushButton("Generate CDB Startlist")
        proc_btn.setStyleSheet(
            "QPushButton { background: #2e8b57; color: white; padding: 6px 16px; }"
            "QPushButton:hover { background: #267349; }")
        proc_btn.clicked.connect(self._mp_process)
        layout.addWidget(proc_btn)

        # Progress bar
        self.mp_progress = QProgressBar()
        self.mp_progress.setRange(0, 100)
        self.mp_progress.setValue(0)
        layout.addWidget(self.mp_progress)

        # Log
        layout.addWidget(QLabel("Log:"))
        self.mp_log_widget = QTextEdit()
        self.mp_log_widget.setReadOnly(True)
        self.mp_log_widget.setStyleSheet(
            "background: #1e1e1e; color: #cccccc;"
            "font-family: Consolas; font-size: 9pt;")
        layout.addWidget(self.mp_log_widget, 1)

        self.tabs.addTab(tab, "Multiplayer")

    # ==================================================================
    # Singleplayer: Database loading
    # ==================================================================

    def _load_selected_db(self):
        name = self.db_combo.currentText()
        if not name:
            self.db = None
            self.db_status.setText("No database selected")
            self._populate_races()
            return

        db_path = os.path.join(DATABASES_DIR, name)
        self.db = StartlistDatabase.from_csv_folder(db_path)
        self._populate_races()

        if self.db.loaded:
            msg = (f"Database '{name}' loaded: {len(self.db.teams)} teams, "
                   f"{len(self.db.cyclists)} cyclists")
            self.db_status.setText(msg)
            self.db_status.setStyleSheet("color: #333; font-size: 9pt;")
            self._log(msg)
        else:
            self.db_status.setText(f"WARNING: '{name}' missing CSV files")
            self.db_status.setStyleSheet("color: #c00; font-size: 9pt;")
            self._log(f"WARNING: Database '{name}' missing CSV files.")

    def _load_cdb(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select CDB file", "", "CDB files (*.cdb)")
        if not path:
            return

        def task():
            gc.collect()
            return converter.export_cdb_to_sqlite(path)

        def on_success(temp_path):
            self.temp_path = temp_path
            self.db = StartlistDatabase.from_sqlite(temp_path)
            self.db_combo.setCurrentIndex(-1)
            self._populate_races()
            if self.db.loaded:
                msg = (f"CDB loaded: {len(self.db.teams)} teams, "
                       f"{len(self.db.cyclists)} cyclists")
                self.db_status.setText(msg)
                self.db_status.setStyleSheet("color: #333; font-size: 9pt;")
                self._log(msg)
                self.status.setText(f"Loaded: {path}")
            else:
                self.db_status.setText(
                    "WARNING: DYN_team or DYN_cyclist tables missing")
                self.db_status.setStyleSheet("color: #c00; font-size: 9pt;")
                self._log("WARNING: DYN_team or DYN_cyclist tables missing. "
                          "ID matching unavailable.")

        run_async(self, task, on_success, "Loading CDB\u2026")

    # ==================================================================
    # Singleplayer: Logging helpers
    # ==================================================================

    def _log(self, msg):
        self.log_widget.append(msg)
        QApplication.processEvents()

    def _clear_log(self):
        self.log_widget.clear()
        self.progress.setValue(0)

    def _update_progress(self, current, total):
        self.progress.setValue(int((current / total) * 100) if total else 0)
        QApplication.processEvents()

    # ==================================================================
    # Singleplayer: File dialogs
    # ==================================================================

    def _browse_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select HTML startlist file", "",
            "HTML files (*.html *.htm);;All files (*.*)")
        if path:
            self.file_edit.setText(path)

    def _fetch_url(self):
        url = self.url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, "No URL", "Please enter a URL first.")
            return
        self._log(f"Fetching: {url}")

        def task():
            return fetch_startlist_url(url)

        def on_success(temp_path):
            self.file_edit.setText(temp_path)
            self._log(f"Fetched startlist from {url}")
            self.status.setText(f"Fetched: {url}")

        run_async(self, task, on_success, "Fetching startlist\u2026")

    def _populate_races(self):
        self._race_map = {}
        if self.db and self.db.races:
            for r in self.db.races:
                name = r.get('gene_sz_race_name', '')
                filename = r.get('gene_sz_filename', '')
                if name and filename:
                    self._race_map[name] = filename

        self.race_combo.blockSignals(True)
        self.race_combo.clear()
        self.race_combo.addItems(sorted(self._race_map.keys()))
        self.race_combo.setCurrentIndex(-1)
        self.race_combo.blockSignals(False)
        self.out_label.setText("")

    def _on_race_selected(self):
        selected = self.race_combo.currentText()
        filename = self._race_map.get(selected, '')
        self.out_label.setText(f"{filename}.xml" if filename else "")

    # ==================================================================
    # Singleplayer: Conversion
    # ==================================================================

    def _convert(self):
        filepath = self.file_edit.text().strip()
        url = self.url_edit.text().strip()

        # Auto-fetch URL if no file is selected but a URL is provided
        if not filepath and url:
            self._clear_log()
            self._log(f"Fetching: {url}")

            def task():
                return fetch_startlist_url(url)

            def on_success(temp_path):
                self.file_edit.setText(temp_path)
                self._log(f"Fetched startlist from {url}")
                self._convert()

            run_async(self, task, on_success, "Fetching startlist\u2026")
            return

        if not filepath:
            QMessageBox.warning(
                self, "No file",
                "Please select an HTML file or enter a URL.")
            return

        output = self.out_label.text().strip()
        if not output:
            QMessageBox.warning(
                self, "No race", "Please select a race first.")
            return

        self._clear_log()
        self._log(f"Reading: {filepath}")

        data = self.parser.parse_file(filepath)

        if data:
            total_teams = len(data)
            total_riders = sum(len(r) for r in data.values())
            self._log(f"Parsed {total_teams} teams, {total_riders} riders")
            self._log("Matching IDs...")

            db = self.db if self.db and self.db.loaded else None
            self.writer.write(
                data, output, db=db, log=self._log,
                on_progress=self._update_progress,
            )
            self.progress.setValue(100)
            self._log(f"\nSaved to: {output}")
            self.status.setText(
                f"Saved {output}  \u2014  {total_teams} teams, "
                f"{total_riders} riders")
            QMessageBox.information(
                self, "Success",
                f"Startlist saved to {output}\n\n"
                f"Teams: {total_teams}\nRiders: {total_riders}")
        else:
            self.progress.setValue(0)
            self.status.setText("Error: no data parsed")
            self._log("ERROR: Could not parse any startlist data "
                      "from the input.")
            QMessageBox.critical(
                self, "Error",
                "Could not parse any startlist data.\n"
                "Make sure the file contains a valid startlist.")

    # ==================================================================
    # Multiplayer: File dialogs
    # ==================================================================

    def _mp_browse_cdb(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select CDB database file", "", "CDB files (*.cdb)")
        if not path:
            return
        self.mp_cdb_edit.setText(path)
        self._mp_load_cdb(path)

    def _mp_load_cdb(self, path):
        def task():
            gc.collect()
            return converter.export_cdb_to_sqlite(path)

        def on_success(temp_path):
            self.mp_temp_path = temp_path
            self.mp_db = StartlistDatabase.from_sqlite(temp_path)
            if self.mp_db.loaded:
                msg = (f"CDB loaded: {len(self.mp_db.teams)} teams, "
                       f"{len(self.mp_db.cyclists)} cyclists")
                self.mp_cdb_status.setText(msg)
                self.mp_cdb_status.setStyleSheet(
                    "color: #333; font-size: 9pt;")
                self._mp_log(msg)
            else:
                self.mp_cdb_status.setText(
                    "WARNING: DYN_team or DYN_cyclist tables missing")
                self.mp_cdb_status.setStyleSheet(
                    "color: #c00; font-size: 9pt;")
                self._mp_log("WARNING: tables missing in CDB.")

        run_async(self, task, on_success, "Loading CDB\u2026")

    def _mp_browse_html(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select HTML startlist file", "",
            "HTML files (*.html *.htm);;All files (*.*)")
        if path:
            self.mp_html_edit.setText(path)

    def _mp_fetch_url(self):
        url = self.mp_url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, "No URL", "Please enter a URL first.")
            return
        self._mp_log(f"Fetching: {url}")

        def task():
            return fetch_startlist_url(url)

        def on_success(temp_path):
            self.mp_html_edit.setText(temp_path)
            self._mp_log(f"Fetched startlist from {url}")
            self.status.setText(f"Fetched: {url}")

        run_async(self, task, on_success, "Fetching startlist\u2026")

    def _mp_browse_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save modified CDB as", "",
            "CDB files (*.cdb);;All files (*.*)")
        if path:
            self.mp_out_edit.setText(path)

    # ==================================================================
    # Multiplayer: Logging helpers
    # ==================================================================

    def _mp_log(self, msg):
        self.mp_log_widget.append(msg)
        QApplication.processEvents()

    def _mp_clear_log(self):
        self.mp_log_widget.clear()
        self.mp_progress.setValue(0)

    def _mp_update_progress(self, current, total):
        self.mp_progress.setValue(
            int((current / total) * 100) if total else 0)
        QApplication.processEvents()

    # ==================================================================
    # Multiplayer: Processing
    # ==================================================================

    def _mp_process(self):
        if not self.mp_db or not self.mp_db.loaded:
            QMessageBox.warning(
                self, "No CDB", "Please load a CDB file first.")
            return

        html_path = self.mp_html_edit.text().strip()
        mp_url = self.mp_url_edit.text().strip()

        # Auto-fetch URL if no file is selected but a URL is provided
        if not html_path and mp_url:
            self._mp_clear_log()
            self._mp_log(f"Fetching: {mp_url}")

            def fetch_task():
                return fetch_startlist_url(mp_url)

            def on_fetch_success(temp_path):
                self.mp_html_edit.setText(temp_path)
                self._mp_log(f"Fetched startlist from {mp_url}")
                self._mp_process()

            run_async(self, fetch_task, on_fetch_success,
                      "Fetching startlist\u2026")
            return

        if not html_path:
            QMessageBox.warning(
                self, "No startlist",
                "Please select an HTML file or enter a URL.")
            return

        output = self.mp_out_edit.text().strip()
        if not output:
            QMessageBox.warning(
                self, "No output",
                "Please set an output CDB file path.")
            return

        proceed = QMessageBox.question(
            self, "Backup reminder",
            "Make sure you have a backup of your CDB file before proceeding.\n\n"
            "This will create a modified CDB where non-startlist riders on "
            "participating teams are moved to the free agent pool (team 119) "
            "and their contracts are removed.\n\nContinue?",
            QMessageBox.Ok | QMessageBox.Cancel,
        )
        if proceed != QMessageBox.Ok:
            return

        self._mp_clear_log()
        self._mp_log(f"Reading startlist: {html_path}")

        data = self.parser.parse_file(html_path)
        if not data:
            self._mp_log("ERROR: Could not parse startlist data.")
            QMessageBox.critical(
                self, "Error", "Could not parse startlist data.")
            return

        total_teams = len(data)
        total_riders = sum(len(r) for r in data.values())
        self._mp_log(f"Parsed {total_teams} teams, {total_riders} riders\n")

        matched_team_ids = set()
        matched_rider_ids = set()
        unmatched_teams = []
        unmatched_riders = []
        processed = 0

        for team_name, riders in data.items():
            team_id, _ = self.mp_db.match_team(team_name)
            if team_id:
                matched_team_ids.add(str(team_id))
                self._mp_log(f"  [TEAM]  {team_name} -> ID {team_id}")
            else:
                unmatched_teams.append(team_name)
                self._mp_log(f"  [TEAM]  {team_name} -> NOT FOUND")

            for rider_name in riders:
                rider_id, _ = self.mp_db.match_rider(rider_name, team_id)
                if rider_id:
                    matched_rider_ids.add(str(rider_id))
                    self._mp_log(
                        f"    [RIDER] {rider_name} -> ID {rider_id}")
                else:
                    unmatched_riders.append(rider_name)
                    self._mp_log(
                        f"    [RIDER] {rider_name} -> NOT FOUND")

                processed += 1
                self._mp_update_progress(processed, total_riders)

        self._mp_log(f"\nMatched {len(matched_team_ids)} teams, "
                     f"{len(matched_rider_ids)} riders")
        if unmatched_teams:
            self._mp_log(f"[!] {len(unmatched_teams)} team(s) not matched")
        if unmatched_riders:
            self._mp_log(
                f"[!] {len(unmatched_riders)} rider(s) not matched")

        if not matched_team_ids:
            self._mp_log("ERROR: No teams matched. Cannot proceed.")
            QMessageBox.critical(
                self, "Error", "No teams matched the database.")
            return

        self._mp_log("\nMoving non-startlist riders to team 119...")

        working_path, moved, contracts = apply_multiplayer_startlist(
            self.mp_temp_path, matched_team_ids, matched_rider_ids)
        self._mp_log(f"Moved {moved} rider(s) to team 119")
        self._mp_log(f"Removed {contracts} contract(s)")

        self._mp_log(f"Saving to: {output}")

        def task():
            return converter.import_sqlite_to_cdb(working_path, output)

        def on_success(_result):
            self.mp_progress.setValue(100)
            self._mp_log(f"\nDone! Saved to: {output}")
            self.status.setText(
                f"Saved {output}  \u2014  {len(matched_rider_ids)} on "
                f"startlist, {moved} moved to team 119")
            QMessageBox.information(
                self, "Success",
                f"Multiplayer CDB saved to:\n{output}\n\n"
                f"Teams on startlist: {len(matched_team_ids)}\n"
                f"Riders on startlist: {len(matched_rider_ids)}\n"
                f"Riders moved to team 119: {moved}")

        run_async(self, task, on_success, "Saving CDB\u2026")

    # ==================================================================
    # Navigation
    # ==================================================================

    def _on_home(self):
        # Reset singleplayer
        self.temp_path = None
        self.db = None
        self.file_edit.clear()
        self.url_edit.clear()
        self.out_label.setText("")
        self._race_map = {}
        self.race_combo.clear()
        self.db_status.setText("")
        self.db_status.setStyleSheet("color: #888; font-size: 9pt;")
        self.progress.setValue(0)
        self._clear_log()
        if self._db_names:
            self.db_combo.setCurrentIndex(0)
        else:
            self.db_combo.setCurrentIndex(-1)

        # Reset multiplayer
        self.mp_temp_path = None
        self.mp_db = None
        self.mp_cdb_edit.clear()
        self.mp_html_edit.clear()
        self.mp_url_edit.clear()
        self.mp_out_edit.clear()
        self.mp_cdb_status.setText("No CDB loaded")
        self.mp_cdb_status.setStyleSheet("color: #888; font-size: 9pt;")
        self.mp_progress.setValue(0)
        self._mp_clear_log()

        self.tabs.setCurrentIndex(0)
        self.status.setText("Ready")
        gc.collect()
        self.go_home.emit()
