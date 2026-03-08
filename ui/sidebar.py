"""
Sidebar widget for table navigation and favorites management.

Provides a two-section sidebar with favorites at the top and
filterable table list below, supporting drag-and-drop reordering.
"""

import tkinter as tk
from core.constants import FILTER_DEBOUNCE_DELAY

class Sidebar:
    """
    Navigation sidebar for browsing and selecting database tables.

    Features:
        - Favorites section with drag-and-drop reordering
        - Searchable table list with debounced filtering
        - Right-click context menu for adding/removing favorites
        - Alternating row colors for better readability
    """
    def __init__(self, parent, app_state, on_table_select):
        """
        Initialize sidebar with favorites and table list.

        Args:
            parent: Parent tkinter widget
            app_state (AppState): Application state manager
            on_table_select (callable): Callback function when table is selected
        """
        self.parent = parent
        self.state = app_state
        self.on_table_select = on_table_select
        self.all_tables = []
        self.sidebar_even, self.sidebar_odd, self.fav_color = "#e8e8e8", "#fdfdfd", "#fff9c4"
        self.filter_timer = None

        self._setup_ui()
        self._create_menu()

    def _setup_ui(self):
        tk.Label(self.parent, text=" ⭐ FAVORITES", anchor="w", bg="#ffd700", font=("SegoeUI", 8, "bold")).pack(fill=tk.X)
        self.fav_lb = tk.Listbox(self.parent, height=6, relief="flat", bg=self.fav_color, highlightthickness=0)
        self.fav_lb.pack(fill=tk.X, padx=2, pady=2)
        self.fav_lb.bind("<<ListboxSelect>>", lambda e: self.on_select(self.fav_lb))
        self.fav_lb.bind("<Button-3>", lambda e: self.show_menu(e, self.fav_lb))
        self.fav_lb.bind("<Button-1>", self.on_fav_press)
        self.fav_lb.bind("<B1-Motion>", self.on_fav_motion)

        tk.Label(self.parent, text=" 📂 TABLES", anchor="w", bg="#444", fg="white", font=("SegoeUI", 8, "bold")).pack(fill=tk.X, pady=(5,0))
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", self.filter_list)
        
        # Search box
        search_frame = tk.Frame(self.parent, bg="white", highlightbackground="#ccc", highlightthickness=1)
        tk.Entry(search_frame, textvariable=self.filter_var, width=20, relief="flat").pack(side="left", padx=5, fill="x", expand=True)
        tk.Button(search_frame, text="✕", command=lambda: self.filter_var.set(""), relief="flat", bg="white", bd=0).pack(side="right")
        search_frame.pack(fill=tk.X, padx=2, pady=5)

        self.listbox = tk.Listbox(self.parent, width=35, relief="flat", highlightthickness=0)
        self.listbox.pack(expand=True, fill=tk.BOTH)
        self.listbox.bind("<<ListboxSelect>>", lambda e: self.on_select(self.listbox))
        self.listbox.bind("<Button-3>", lambda e: self.show_menu(e, self.listbox))

    def _create_menu(self):
        self.menu = tk.Menu(self.parent, tearoff=0)

    def set_tables(self, tables):
        """
        Update the list of available tables.

        Args:
            tables (list[str]): List of table names to display
        """
        self.all_tables = tables
        self._execute_filter()  # Execute immediately when setting tables, not debounced
        self.refresh_favorites()

    def filter_list(self, *args):
        """Debounced filter handler that delays execution until typing stops."""
        # Cancel previous filter timer if user is still typing
        if self.filter_timer:
            self.parent.winfo_toplevel().after_cancel(self.filter_timer)

        # Schedule new filter after delay (faster than main search since it's in-memory)
        self.filter_timer = self.parent.winfo_toplevel().after(FILTER_DEBOUNCE_DELAY, self._execute_filter)

    def _execute_filter(self):
        """Execute the actual filtering based on search term."""
        term = self.filter_var.get().lower()
        self.listbox.delete(0, "end")
        for index, table in enumerate([t for t in self.all_tables if term in t.lower()]):
            self.listbox.insert("end", table)
            self.listbox.itemconfig(index, {'bg': self.sidebar_even if index % 2 == 0 else self.sidebar_odd})
        self.filter_timer = None

    def refresh_favorites(self):
        """Reload the favorites list from app state."""
        self.fav_lb.delete(0, "end")
        for table in [f for f in self.state.favorites if f in self.all_tables]:
            self.fav_lb.insert("end", table)

    def on_select(self, widget):
        """Handle selection in either the favorites or tables listbox."""
        selection = widget.curselection()
        if selection:
            self.on_table_select(widget.get(selection[0]))

    def show_menu(self, event, widget):
        """Show right-click context menu to add/remove favorites."""
        widget.selection_clear(0, "end")
        index = widget.nearest(event.y)
        widget.selection_set(index)
        table_name = widget.get(index)
        
        self.menu.delete(0, "end")
        if table_name in self.state.favorites:
            self.menu.add_command(label="❌ Remove Favorite", command=self.remove_favorite)
        else:
            self.menu.add_command(label="⭐ Add Favorite", command=self.add_favorite)
        self.menu.post(event.x_root, event.y_root)

    def add_favorite(self):
        """Add the selected table to the favorites list."""
        selection = self.listbox.curselection()
        if selection:
            name = self.listbox.get(selection[0])
            if name not in self.state.favorites:
                self.state.favorites.append(name)
                self.refresh_favorites()

    def remove_favorite(self):
        """Remove the selected table from the favorites list."""
        sel_fav = self.fav_lb.curselection()
        sel_list = self.listbox.curselection()
        name = self.fav_lb.get(sel_fav[0]) if sel_fav else self.listbox.get(sel_list[0]) if sel_list else None
        if name in self.state.favorites:
            self.state.favorites.remove(name)
            self.refresh_favorites()

    def on_fav_press(self, event):
        """Record the drag start index for favorites reordering."""
        self.cur_fav_index = self.fav_lb.nearest(event.y)

    def on_fav_motion(self, event):
        """Drag-and-drop reorder: move the dragged favorite to the hovered position."""
        i = self.fav_lb.nearest(event.y)
        if i < self.fav_lb.size() and i != self.cur_fav_index:
            text = self.fav_lb.get(self.cur_fav_index)
            self.fav_lb.delete(self.cur_fav_index)
            self.fav_lb.insert(i, text)
            self.fav_lb.selection_set(i)
            self.cur_fav_index = i
            
            visible = list(self.fav_lb.get(0, tk.END))
            hidden = [f for f in self.state.favorites if f not in visible]
            self.state.favorites = visible + hidden
    
    def select_first_favorite(self):
        """Auto-select the first favorite table if available."""
        if self.fav_lb.size() > 0:
            self.fav_lb.selection_set(0)
            self.on_select(self.fav_lb)
