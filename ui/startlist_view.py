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
import tkinter as tk
from tkinter import END, filedialog, messagebox, scrolledtext, ttk

import core.converter as converter
from core.startlist import (
    StartlistDatabase, StartlistParser, PCMXmlWriter,
    apply_multiplayer_startlist,
)
from ui.ui_utils import run_async


# databases/ folder next to main.py
DATABASES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'databases',
)


class StartlistView:
    """Full-frame startlist generator with database selector."""

    def __init__(self, parent_frame, root, go_home):
        """
        Args:
            parent_frame: tk.Frame to build the view inside
            root: The tk.Tk root window (for dialogs / update_idletasks)
            go_home: Callback to return to the home screen
        """
        self.frame = parent_frame
        self.root = root
        self.go_home = go_home
        self.parser = StartlistParser()
        self.writer = PCMXmlWriter()
        self.db = None
        self.temp_path = None

        # Multiplayer state
        self.mp_db = None
        self.mp_temp_path = None

        self._build_ui()
        self._load_selected_db()

    def _build_ui(self):
        # Toolbar
        toolbar = tk.Frame(self.frame, pady=10, bg="#f0f0f0")
        toolbar.pack(side=tk.TOP, fill=tk.X)

        tk.Button(
            toolbar, text="\u2190 Back", command=self._on_home,
            bg="#b0b0b0",
        ).pack(side=tk.LEFT, padx=5)

        # Shared content area
        content = tk.Frame(self.frame, padx=16, pady=12)
        content.pack(fill='both', expand=True)

        # Notebook (tabs)
        self.notebook = ttk.Notebook(content)
        self.notebook.pack(fill='both', expand=True)

        self._build_singleplayer_tab()
        self._build_multiplayer_tab()

        # Status bar
        self.status = tk.Label(
            self.frame, text="Ready", bd=1, relief="sunken", anchor="w",
        )
        self.status.pack(side=tk.BOTTOM, fill=tk.X)

    # -- Tab builders -------------------------------------------------------

    def _build_singleplayer_tab(self):
        tab = tk.Frame(self.notebook, padx=8, pady=8)
        self.notebook.add(tab, text="Singleplayer")

        # Database section
        db_frame = tk.LabelFrame(tab, text="Database", padx=8, pady=8)
        db_frame.pack(fill='x', pady=(0, 8))
        db_row = tk.Frame(db_frame)
        db_row.pack(fill='x')

        tk.Label(db_row, text="Select database:").pack(side='left')

        # Scan databases/ folder for subfolders
        self._db_names = []
        if os.path.isdir(DATABASES_DIR):
            self._db_names = sorted(
                d for d in os.listdir(DATABASES_DIR)
                if os.path.isdir(os.path.join(DATABASES_DIR, d))
            )

        self.db_var = tk.StringVar()
        self.db_combo = ttk.Combobox(
            db_row, textvariable=self.db_var, values=self._db_names,
            state='readonly', width=30,
        )
        self.db_combo.pack(side='left', padx=(6, 0))
        self.db_combo.bind(
            '<<ComboboxSelected>>', lambda e: self._load_selected_db())

        if self._db_names:
            self.db_combo.current(0)

        tk.Label(db_row, text="or").pack(side='left', padx=8)
        tk.Button(
            db_row, text="Open CDB...", command=self._load_cdb,
        ).pack(side='left')

        self.db_status = tk.Label(
            db_frame, text="", fg="#888", font=("Segoe UI", 9), anchor='w',
        )
        self.db_status.pack(fill='x', pady=(4, 0))

        # HTML file input
        file_frame = tk.LabelFrame(tab, text="HTML startlist file",
                                   padx=8, pady=8)
        file_frame.pack(fill='x', pady=(0, 8))
        row = tk.Frame(file_frame)
        row.pack(fill='x')

        self.file_var = tk.StringVar()
        tk.Entry(row, textvariable=self.file_var, width=60).pack(
            side='left', fill='x', expand=True)
        tk.Button(row, text="Browse...", command=self._browse_file).pack(
            side='left', padx=(6, 0))

        # Race selection (determines output filename)
        race_frame = tk.LabelFrame(tab, text="Race", padx=8, pady=8)
        race_frame.pack(fill='x', pady=(0, 8))
        race_row = tk.Frame(race_frame)
        race_row.pack(fill='x')

        tk.Label(race_row, text="Select race:").pack(side='left')
        self._race_map = {}        # display_name -> filename
        self.race_combo = ttk.Combobox(race_row, state='readonly', width=50)
        self.race_combo.pack(side='left', padx=(6, 0), fill='x', expand=True)

        self.out_var = tk.StringVar()
        self.race_filename_label = tk.Label(
            race_frame, textvariable=self.out_var,
            fg="#888", font=("Segoe UI", 9), anchor='w',
        )
        self.race_filename_label.pack(fill='x', pady=(4, 0))
        self.race_combo.bind(
            '<<ComboboxSelected>>', self._on_race_selected)

        # Convert button
        btn_frame = tk.Frame(tab)
        btn_frame.pack(fill='x', pady=(0, 8))
        tk.Button(
            btn_frame, text="Generate Startlist", command=self._convert,
            bg="#2e8b57", fg="white",
        ).pack(side='left')

        # Progress bar
        self.progress_var = tk.DoubleVar()
        ttk.Progressbar(
            tab, variable=self.progress_var, maximum=100,
        ).pack(fill='x', pady=(0, 4))

        # Log area
        tk.Label(tab, text="Log:", font=("Segoe UI", 9)).pack(anchor='w')
        self.log_widget = scrolledtext.ScrolledText(
            tab, height=14, state='disabled',
            font=("Consolas", 9), bg="#1e1e1e", fg="#cccccc",
        )
        self.log_widget.pack(fill='both', expand=True, pady=(2, 0))

    def _build_multiplayer_tab(self):
        tab = tk.Frame(self.notebook, padx=8, pady=8)
        self.notebook.add(tab, text="Multiplayer")

        # CDB file input
        cdb_frame = tk.LabelFrame(tab, text="CDB database file", padx=8, pady=8)
        cdb_frame.pack(fill='x', pady=(0, 8))
        cdb_row = tk.Frame(cdb_frame)
        cdb_row.pack(fill='x')

        self.mp_cdb_var = tk.StringVar()
        tk.Entry(cdb_row, textvariable=self.mp_cdb_var, width=60,
                 state='readonly').pack(side='left', fill='x', expand=True)
        tk.Button(cdb_row, text="Load CDB...",
                  command=self._mp_browse_cdb).pack(side='left', padx=(6, 0))

        self.mp_cdb_status = tk.Label(
            cdb_frame, text="No CDB loaded", fg="#888",
            font=("Segoe UI", 9), anchor='w',
        )
        self.mp_cdb_status.pack(fill='x', pady=(4, 0))

        # HTML startlist input
        html_frame = tk.LabelFrame(tab, text="HTML startlist file",
                                   padx=8, pady=8)
        html_frame.pack(fill='x', pady=(0, 8))
        html_row = tk.Frame(html_frame)
        html_row.pack(fill='x')

        self.mp_html_var = tk.StringVar()
        tk.Entry(html_row, textvariable=self.mp_html_var, width=60).pack(
            side='left', fill='x', expand=True)
        tk.Button(html_row, text="Browse...",
                  command=self._mp_browse_html).pack(side='left', padx=(6, 0))

        # Output CDB file
        out_frame = tk.LabelFrame(tab, text="Output CDB file", padx=8, pady=8)
        out_frame.pack(fill='x', pady=(0, 8))
        out_row = tk.Frame(out_frame)
        out_row.pack(fill='x')

        self.mp_out_var = tk.StringVar()
        tk.Entry(out_row, textvariable=self.mp_out_var, width=60).pack(
            side='left', fill='x', expand=True)
        tk.Button(out_row, text="Save as...",
                  command=self._mp_browse_output).pack(side='left', padx=(6, 0))

        # Process button
        btn_frame = tk.Frame(tab)
        btn_frame.pack(fill='x', pady=(0, 8))
        tk.Button(
            btn_frame, text="Generate CDB Startlist", command=self._mp_process,
            bg="#2e8b57", fg="white",
        ).pack(side='left')

        # Progress bar
        self.mp_progress_var = tk.DoubleVar()
        ttk.Progressbar(
            tab, variable=self.mp_progress_var, maximum=100,
        ).pack(fill='x', pady=(0, 4))

        # Log area
        tk.Label(tab, text="Log:", font=("Segoe UI", 9)).pack(anchor='w')
        self.mp_log_widget = scrolledtext.ScrolledText(
            tab, height=14, state='disabled',
            font=("Consolas", 9), bg="#1e1e1e", fg="#cccccc",
        )
        self.mp_log_widget.pack(fill='both', expand=True, pady=(2, 0))

    # ======================================================================
    # Singleplayer: Database loading
    # ======================================================================

    def _load_selected_db(self):
        """Load database from the selected CSV folder."""
        name = self.db_var.get()
        if not name:
            self.db = None
            self.db_status.config(text="No database selected")
            self._populate_races()
            return

        db_path = os.path.join(DATABASES_DIR, name)
        self.db = StartlistDatabase.from_csv_folder(db_path)
        self._populate_races()

        if self.db.loaded:
            msg = (f"Database '{name}' loaded: {len(self.db.teams)} teams, "
                   f"{len(self.db.cyclists)} cyclists")
            self.db_status.config(text=msg, fg="#333")
            self._log(msg)
        else:
            self.db_status.config(
                text=f"WARNING: '{name}' missing CSV files", fg="#c00")
            self._log(f"WARNING: Database '{name}' missing CSV files.")

    def _load_cdb(self):
        """Load database from a CDB file (converted to SQLite)."""
        path = filedialog.askopenfilename(
            filetypes=[("CDB files", "*.cdb")],
        )
        if not path:
            return

        def task():
            gc.collect()
            return converter.export_cdb_to_sqlite(path)

        def on_success(temp_path):
            self.temp_path = temp_path
            self.db = StartlistDatabase.from_sqlite(temp_path)
            # Clear dropdown selection to show CDB is active
            self.db_combo.set('')
            self._populate_races()
            if self.db.loaded:
                msg = (f"CDB loaded: {len(self.db.teams)} teams, "
                       f"{len(self.db.cyclists)} cyclists")
                self.db_status.config(text=msg, fg="#333")
                self._log(msg)
                self.status.config(text=f"Loaded: {path}")
            else:
                self.db_status.config(
                    text="WARNING: DYN_team or DYN_cyclist tables missing",
                    fg="#c00")
                self._log("WARNING: DYN_team or DYN_cyclist tables missing. "
                          "ID matching unavailable.")

        run_async(self.root, task, on_success, "Loading CDB...")

    # ======================================================================
    # Singleplayer: Logging helpers
    # ======================================================================

    def _log(self, msg):
        """Append a message to the singleplayer log widget."""
        self.log_widget.config(state='normal')
        self.log_widget.insert('end', msg + "\n")
        self.log_widget.see('end')
        self.log_widget.config(state='disabled')
        self.root.update_idletasks()

    def _clear_log(self):
        """Clear the singleplayer log and reset the progress bar."""
        self.log_widget.config(state='normal')
        self.log_widget.delete('1.0', 'end')
        self.log_widget.config(state='disabled')
        self.progress_var.set(0)

    def _update_progress(self, current, total):
        """Update the singleplayer progress bar percentage."""
        self.progress_var.set((current / total) * 100 if total else 0)
        self.root.update_idletasks()

    # ======================================================================
    # Singleplayer: File dialogs
    # ======================================================================

    def _browse_file(self):
        """Open a file dialog to select an HTML startlist file."""
        path = filedialog.askopenfilename(
            title="Select HTML startlist file",
            filetypes=[("HTML files", "*.html *.htm"), ("All files", "*.*")],
        )
        if path:
            self.file_var.set(path)

    def _populate_races(self):
        """Fill the race dropdown from the current database."""
        self._race_map = {}
        if self.db and self.db.races:
            for r in self.db.races:
                name = r.get('gene_sz_race_name', '')
                filename = r.get('gene_sz_filename', '')
                if name and filename:
                    self._race_map[name] = filename

        names = sorted(self._race_map.keys())
        self.race_combo['values'] = names
        self.race_combo.set('')
        self.out_var.set('')

    def _on_race_selected(self, event=None):
        """Update the output filename when a race is selected."""
        selected = self.race_combo.get()
        filename = self._race_map.get(selected, '')
        self.out_var.set(f"{filename}.xml" if filename else '')

    # ======================================================================
    # Singleplayer: Conversion
    # ======================================================================

    def _convert(self):
        """Parse the HTML startlist, match IDs, and write the XML output file."""
        filepath = self.file_var.get().strip()
        if not filepath:
            messagebox.showwarning("No file",
                                   "Please select an HTML file first.")
            return

        output = self.out_var.get().strip()
        if not output:
            messagebox.showwarning("No race",
                                   "Please select a race first.")
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
            self.progress_var.set(100)
            self._log(f"\nSaved to: {output}")
            self.status.config(
                text=f"Saved {output}  --  {total_teams} teams, "
                     f"{total_riders} riders"
            )
            messagebox.showinfo(
                "Success",
                f"Startlist saved to {output}\n\n"
                f"Teams: {total_teams}\nRiders: {total_riders}",
            )
        else:
            self.progress_var.set(0)
            self.status.config(text="Error: no data parsed")
            self._log("ERROR: Could not parse any startlist data "
                      "from the input.")
            messagebox.showerror(
                "Error",
                "Could not parse any startlist data.\n"
                "Make sure the file contains a valid startlist.",
            )

    # ======================================================================
    # Multiplayer: File dialogs
    # ======================================================================

    def _mp_browse_cdb(self):
        """Open a file dialog to select and load a CDB for multiplayer."""
        path = filedialog.askopenfilename(
            title="Select CDB database file",
            filetypes=[("CDB files", "*.cdb")],
        )
        if not path:
            return
        self.mp_cdb_var.set(path)
        self._mp_load_cdb(path)

    def _mp_load_cdb(self, path):
        """Convert CDB to SQLite and load for matching."""
        def task():
            gc.collect()
            return converter.export_cdb_to_sqlite(path)

        def on_success(temp_path):
            self.mp_temp_path = temp_path
            self.mp_db = StartlistDatabase.from_sqlite(temp_path)
            if self.mp_db.loaded:
                msg = (f"CDB loaded: {len(self.mp_db.teams)} teams, "
                       f"{len(self.mp_db.cyclists)} cyclists")
                self.mp_cdb_status.config(text=msg, fg="#333")
                self._mp_log(msg)
            else:
                self.mp_cdb_status.config(
                    text="WARNING: DYN_team or DYN_cyclist tables missing",
                    fg="#c00")
                self._mp_log("WARNING: tables missing in CDB.")

        run_async(self.root, task, on_success, "Loading CDB...")

    def _mp_browse_html(self):
        """Open a file dialog to select an HTML startlist for multiplayer."""
        path = filedialog.askopenfilename(
            title="Select HTML startlist file",
            filetypes=[("HTML files", "*.html *.htm"), ("All files", "*.*")],
        )
        if path:
            self.mp_html_var.set(path)

    def _mp_browse_output(self):
        """Open a save dialog to set the multiplayer output CDB path."""
        path = filedialog.asksaveasfilename(
            title="Save modified CDB as",
            defaultextension=".cdb",
            filetypes=[("CDB files", "*.cdb"), ("All files", "*.*")],
        )
        if path:
            self.mp_out_var.set(path)

    # ======================================================================
    # Multiplayer: Logging helpers
    # ======================================================================

    def _mp_log(self, msg):
        """Append a message to the multiplayer log widget."""
        self.mp_log_widget.config(state='normal')
        self.mp_log_widget.insert('end', msg + "\n")
        self.mp_log_widget.see('end')
        self.mp_log_widget.config(state='disabled')
        self.root.update_idletasks()

    def _mp_clear_log(self):
        """Clear the multiplayer log and reset the progress bar."""
        self.mp_log_widget.config(state='normal')
        self.mp_log_widget.delete('1.0', 'end')
        self.mp_log_widget.config(state='disabled')
        self.mp_progress_var.set(0)

    def _mp_update_progress(self, current, total):
        """Update the multiplayer progress bar percentage."""
        self.mp_progress_var.set((current / total) * 100 if total else 0)
        self.root.update_idletasks()

    # ======================================================================
    # Multiplayer: Processing
    # ======================================================================

    def _mp_process(self):
        """Run the full multiplayer pipeline: parse HTML, match IDs, modify CDB."""
        # Validate inputs
        if not self.mp_db or not self.mp_db.loaded:
            messagebox.showwarning("No CDB", "Please load a CDB file first.")
            return

        html_path = self.mp_html_var.get().strip()
        if not html_path:
            messagebox.showwarning("No startlist",
                                   "Please select an HTML startlist file.")
            return

        output = self.mp_out_var.get().strip()
        if not output:
            messagebox.showwarning("No output",
                                   "Please set an output CDB file path.")
            return

        # Warn user to back up their CDB
        proceed = messagebox.askokcancel(
            "Backup reminder",
            "Make sure you have a backup of your CDB file before proceeding.\n\n"
            "This will create a modified CDB where non-startlist riders on "
            "participating teams are moved to the free agent pool (team 119) "
            "and their contracts are removed.\n\n"
            "Continue?",
        )
        if not proceed:
            return

        self._mp_clear_log()
        self._mp_log(f"Reading startlist: {html_path}")

        # 1. Parse HTML
        data = self.parser.parse_file(html_path)
        if not data:
            self._mp_log("ERROR: Could not parse startlist data.")
            messagebox.showerror("Error", "Could not parse startlist data.")
            return

        total_teams = len(data)
        total_riders = sum(len(r) for r in data.values())
        self._mp_log(f"Parsed {total_teams} teams, {total_riders} riders\n")

        # 2. Match teams and riders
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
                rider_id, matched = self.mp_db.match_rider(
                    rider_name, team_id)
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
            self._mp_log(f"[!] {len(unmatched_riders)} rider(s) not matched")

        if not matched_team_ids:
            self._mp_log("ERROR: No teams matched. Cannot proceed.")
            messagebox.showerror("Error", "No teams matched the database.")
            return

        # 3. Modify database: move non-startlist riders to team 119
        self._mp_log("\nMoving non-startlist riders to team 119...")

        working_path, moved, contracts = apply_multiplayer_startlist(
            self.mp_temp_path, matched_team_ids, matched_rider_ids,
        )
        self._mp_log(f"Moved {moved} rider(s) to team 119")
        self._mp_log(f"Removed {contracts} contract(s)")

        # 4. Export to CDB
        self._mp_log(f"Saving to: {output}")

        def task():
            return converter.import_sqlite_to_cdb(working_path, output)

        def on_success(_result):
            self.mp_progress_var.set(100)
            self._mp_log(f"\nDone! Saved to: {output}")
            self.status.config(
                text=f"Saved {output}  --  {len(matched_rider_ids)} on "
                     f"startlist, {moved} moved to team 119"
            )
            messagebox.showinfo(
                "Success",
                f"Multiplayer CDB saved to:\n{output}\n\n"
                f"Teams on startlist: {len(matched_team_ids)}\n"
                f"Riders on startlist: {len(matched_rider_ids)}\n"
                f"Riders moved to team 119: {moved}",
            )

        run_async(self.root, task, on_success, "Saving CDB...")

    # ======================================================================
    # Navigation
    # ======================================================================

    def _on_home(self):
        """Reset all state and navigate back to the home screen."""
        # Reset singleplayer fields
        self.temp_path = None
        self.db = None
        self.file_var.set('')
        self.out_var.set('')
        self._race_map = {}
        self.race_combo['values'] = []
        self.race_combo.set('')
        self.db_status.config(text='', fg='#888')
        self.progress_var.set(0)
        self._clear_log()
        if self._db_names:
            self.db_combo.current(0)
        else:
            self.db_combo.set('')

        # Reset multiplayer fields
        self.mp_temp_path = None
        self.mp_db = None
        self.mp_cdb_var.set('')
        self.mp_html_var.set('')
        self.mp_out_var.set('')
        self.mp_cdb_status.config(text='No CDB loaded', fg='#888')
        self.mp_progress_var.set(0)
        self._mp_clear_log()

        # Reset to first tab
        self.notebook.select(0)

        self.status.config(text='Ready')
        gc.collect()
        self.go_home()
