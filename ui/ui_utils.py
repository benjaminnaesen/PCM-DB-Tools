"""
Shared UI utility functions and widgets.

Provides reusable components like tooltips and async task execution
with progress feedback.
"""

import threading
import tkinter as tk
from tkinter import ttk, messagebox


class ToolTip:
    """
    Hover tooltip widget for displaying help text.

    Automatically shows/hides a small yellow popup on mouse enter/leave.
    """

    def __init__(self, widget, text):
        """
        Attach tooltip to a widget.

        Args:
            widget: Tkinter widget to attach tooltip to
            text (str): Text to display in tooltip
        """
        self.widget = widget
        self.text = text
        self.tip_window = None
        self.widget.bind("<Enter>", self.show_tip)
        self.widget.bind("<Leave>", self.hide_tip)

    def show_tip(self, event=None):
        if self.tip_window or not self.text:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tk.Label(
            tw, text=self.text, justify=tk.LEFT,
            bg="#ffffe0", relief=tk.SOLID, bd=1,
            font=("tahoma", "8", "normal"),
        ).pack(ipadx=1)

    def hide_tip(self, event=None):
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None


def run_async(root, task, callback, message):
    """
    Run a task asynchronously with progress dialog.

    Args:
        root: Root tkinter window
        task (callable): Function to execute in background thread
        callback (callable): Function to call with task result on completion
        message (str): Progress message to display

    Notes:
        - Shows modal progress dialog with indeterminate progress bar
        - Executes task in daemon thread to prevent blocking UI
        - Automatically handles errors with messagebox
        - Destroys dialog on completion
    """
    popup = tk.Toplevel(root)
    popup.title("Please wait...")
    popup.geometry("300x100")
    popup.resizable(False, False)
    popup.transient(root)
    popup.grab_set()

    try:
        x = root.winfo_rootx() + (root.winfo_width() // 2) - 150
        y = root.winfo_rooty() + (root.winfo_height() // 2) - 50
        popup.geometry(f"+{x}+{y}")
    except tk.TclError:
        pass

    tk.Label(popup, text=message, pady=10).pack()
    pb = ttk.Progressbar(popup, mode="indeterminate")
    pb.pack(fill=tk.X, padx=20, pady=5)
    pb.start(10)

    def thread_target():
        try:
            res = task()
            root.after(0, lambda: finish(res, None))
        except Exception as e:
            root.after(0, lambda err=e: finish(None, err))

    def finish(res, err):
        popup.destroy()
        if err:
            messagebox.showerror("Error", str(err))
        else:
            try:
                callback(res)
            except Exception as e:
                messagebox.showerror("Error", str(e))

    threading.Thread(target=thread_target, daemon=True).start()
