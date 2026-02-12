#!/usr/bin/env python3

import os
import sys
import shutil
import tempfile
import zipfile
import re
import xml.etree.ElementTree as ET
import json
import requests
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
import time
from datetime import datetime, timedelta

try:
    from plyer import notification
except Exception:
    notification = None

APP_VERSION = "1.0.4"
def get_app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(__file__)

CONFIG_PATH = os.path.join(get_app_dir(), "simbrief_downloader_config.json")
SIMBRIEF_API_URL = "https://simbrief.com/api/xml.fetcher.php?userid={username}&json=1"
FLIGHTPLAN_BASE_URL = "https://www.simbrief.com/ofp/flightplans/"
FLIGHTPLAN_XML_URL = "https://www.simbrief.com/ofp/flightplans/xml/"

class ToolTip:
    def __init__(self, widget, text, delay_ms=500):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self._after_id = None
        self._tip = None
        widget.bind("<Enter>", self._schedule)
        widget.bind("<Leave>", self._hide)
        widget.bind("<ButtonPress>", self._hide)

    def _schedule(self, _event=None):
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _show(self):
        if self._tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        self._tip = tk.Toplevel(self.widget)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            self._tip,
            text=self.text,
            justify="left",
            background="#1e1e1e",
            foreground="#ffffff",
            relief="solid",
            borderwidth=1,
            font=("Arial", 9),
        )
        label.pack(ipadx=6, ipady=4)

    def _hide(self, _event=None):
        if self._after_id:
            self.widget.after_cancel(self._after_id)
            self._after_id = None
        if self._tip:
            self._tip.destroy()
            self._tip = None


class SimBriefPyDownloader:
    def __init__(self, root):
        self.root = root
        self.root.title(f"SimBriefPyDownloader (v{APP_VERSION})")

        # Fenster-Icon setzen (unterstützt .ico oder .png)
        icon_path = os.path.join(os.path.dirname(__file__), "simbrief.png")  # oder .ico
        if os.path.exists(icon_path):
            try:
                self.root.iconphoto(False, tk.PhotoImage(file=icon_path))
            except Exception as e:
                print(f"Icon konnte nicht geladen werden: {e}")

        # Dark Theme
        self.root.configure(bg="#2b2b2b")
        style = ttk.Style()
        style.theme_use('default')
        style.configure("TLabel", background="#2b2b2b", foreground="#ffffff", font=('Arial', 10))
        style.configure("TButton", background="#3c3f41", foreground="#ffffff", font=('Arial', 10, 'bold'))
        style.configure("TCheckbutton", background="#2b2b2b", foreground="#ffffff")
        style.configure("Horizontal.TProgressbar", troughcolor="#3c3f41", background="#61892f")

        self.notebook = ttk.Notebook(root)
        self.notebook.grid(row=0, column=0, sticky="nsew")
        root.rowconfigure(0, weight=1)
        root.columnconfigure(0, weight=1)

        self.flightplans_frame = tk.Frame(root, bg="#2b2b2b")
        self.airac_frame = tk.Frame(root, bg="#2b2b2b")
        self.notebook.add(self.flightplans_frame, text="Flightplans")
        self.notebook.add(self.airac_frame, text="AIRAC")

        # Flight info display
        self.flight_info_label = ttk.Label(self.flightplans_frame, text="Flight Info: N/A", font=("Arial", 12, "bold"), foreground="#ffffff")
        self.flight_info_label.grid(row=0, column=0, columnspan=6, sticky='w', padx=5, pady=5)

        # Username
        simbrief_label = ttk.Label(self.flightplans_frame, text="SimBrief ID:")
        simbrief_label.grid(row=1, column=0, sticky='w', padx=5, pady=5)
        self.username_entry = ttk.Entry(self.flightplans_frame, width=20)
        self.username_entry.grid(row=1, column=1, padx=5, pady=5, columnspan=2)
        ToolTip(
            simbrief_label,
            "Numeric SimBrief User ID from your account (not your display name). "
            "Find it in your SimBrief profile or in the URL after \"userid=\".",
        )
        ToolTip(
            self.username_entry,
            "Numeric SimBrief User ID from your account (not your display name). "
            "Find it in your SimBrief profile or in the URL after \"userid=\".",
        )

        # Formats
        ttk.Label(self.flightplans_frame, text="File Formats:").grid(row=2, column=0, sticky='ew', padx=2, pady=2)
        self.formats = {
            "PDF": tk.BooleanVar(),
            "FMS": tk.BooleanVar(),
            "FF757": tk.BooleanVar(),
            "STSFF": tk.BooleanVar(),
            "XPE": tk.BooleanVar(),
            "TDS": tk.BooleanVar(),
            "Zibo": tk.BooleanVar(),
            "XML": tk.BooleanVar(),
            "MD11": tk.BooleanVar(),
        }
        self.format_tooltips = {
            "PDF": "SimBrief flightplan as PDF, e.g. for AviTab.",
            "FMS": "X-Plane 11/12 (no SID/STAR).",
            "FF757": "FlightFactor 757 V2.",
            "STSFF": "FlightFactor 757, 767, 777 V2.",
            "XPE": "X-Plane 11/12 including SID/STAR.",
            "TDS": "TDS GTNXi.",
            "Zibo": "Zibo Mod B737 XML.",
            "XML": "XML data file.",
            "MD11": "Rotate MD-11.",
        }
        self.standard_paths = {
            "PDF": "Resources/plugins/AviTab/charts",
            "FMS": "Output/FMS plans",
            "XPE": "Output/FMS plans",
            "Zibo": "Output/FMS plans",
            "XML": "Output/FMS plans",
            "FF757": "Aircraft/FlightFactor & StepToSky/Boeing 757-Full/co-routes",
            "STSFF": "Custom Data/STSFF/co-routes",
            "MD11": "Aircraft/Rotate-MD-11/user-data/saved-routes",
        }
        self.xplane_root_var = tk.StringVar(value=os.path.expanduser("~/Games/X-Plane 12"))
        self.standard_dir_vars = {
            fmt: tk.BooleanVar(value=fmt in self.standard_paths) for fmt in self.formats
        }
        self.manual_dir_cache = {fmt: "" for fmt in self.formats}
        self.xplane_root_var.trace_add("write", lambda *_: self.refresh_standard_paths())
        self.auto_update_var = tk.BooleanVar(value=False)
        self._auto_update_job = None
        self._auto_update_running = False
        self._auto_update_error_ts = 0
        self._auto_update_failed = False
        self.airac_targets = {
            "124th ATC": {"path": "Resources/plugins/124thATC64/navdata", "rooted": True},
            "World Traffic 2.0+": {"path": "ClassicJetSimUtils/navigraph", "rooted": True},
            "FlightFactor 777v2": {"path": "Custom Data/STSFF/nav-data/ndbl/data", "rooted": True},
            "X-Plane 12 native": {"path": "Custom Data", "rooted": True},
            "X-Plane GNS430": {"path": "Custom Data/GNS430", "rooted": True},
            "SSG (UFMC)": {"path": "Custom Data/UFMC", "rooted": True},
            "IXEG 737 Classic Plus": {"path": "Aircraft/X-Aviation/IXEG 737 Classic Plus", "rooted": True},
            "Rotate MD-11 Passenger": {"path": "Aircraft/Rotate-MD-11P-x12b", "rooted": True},
            "Rotate MD-11 Freighter": {"path": "Aircraft/Rotate-MD-11F", "rooted": True},
            "Rotate MD-80": {"path": "Aircraft/Rotate-MD-80", "rooted": True},
            "SimToolkitPro": {"path": os.path.expanduser("~/Documents/SimToolkitPro"), "rooted": False},
            "Little Navmap": {"path": os.path.expanduser("~/.config/ABarthel"), "rooted": False},
        }
        self.airac_addon_name_patterns = {
            "X-Plane 12 native": ["x-plane 12"],
            "X-Plane GNS430": ["x-plane gns430", "ff757/767/777"],
            "FlightFactor 777v2": ["flightfactor boeing 777v2"],
            "SSG (UFMC)": ["ssg"],
            "IXEG 737 Classic Plus": ["ixeg 737 classic plus", "ixeg 737 classic"],
            "Rotate MD-11 Passenger": ["rotate md-11"],
            "Rotate MD-11 Freighter": ["rotate md-11"],
            "Rotate MD-80": ["rotate md-80"],
            "Little Navmap": ["little navmap", "little_navmap"],
        }
        self.airac_zip_prefixes = {
            "124th ATC": ["124thatcv2_native_"],
            "World Traffic 2.0+": ["worldtraffic_native_"],
            "FlightFactor 777v2": ["ffb777v2_native_"],
            "X-Plane 12 native": ["xplane12_native_"],
            "X-Plane GNS430": ["xplane_customdata_native_"],
            "SSG (UFMC)": ["ssg_native_"],
            "IXEG 737 Classic Plus": ["ixeg737classicplus_native_"],
            "Rotate MD-11 Passenger": ["rotate_md11_native_"],
            "Rotate MD-11 Freighter": ["rotate_md11_native_"],
            "Rotate MD-80": ["rotate_md80_native_"],
            "SimToolkitPro": ["simtoolkitpro_native_"],
            "Little Navmap": ["lnm_native_"],
        }
        self.airac_target_var = tk.StringVar(value="X-Plane 12 native")
        self.airac_directory_vars = {name: tk.StringVar() for name in self.airac_targets}
        self.airac_use_default_vars = {name: tk.BooleanVar(value=True) for name in self.airac_targets}
        self.airac_enabled_vars = {name: tk.BooleanVar(value=True) for name in self.airac_targets}
        formats_per_row = 4
        row_base = 3
        col = 1

        for i, (fmt, var) in enumerate(self.formats.items()):
            r = row_base + (i // formats_per_row)
            c = 1 + (i % formats_per_row)
            check = ttk.Checkbutton(self.flightplans_frame, text=fmt, variable=var)
            check.grid(row=r, column=c, padx=8, pady=5, sticky='w')
            if fmt in self.format_tooltips:
                ToolTip(check, self.format_tooltips[fmt])

        # Directory variables + Button zum Unterfenster
        self.directory_vars = {fmt: tk.StringVar() for fmt in self.formats}
        target_dirs_label = ttk.Label(self.flightplans_frame, text="Target Directories:")
        target_dirs_label.grid(row=6, column=0, sticky='w', padx=5, pady=5)
        dir_btn = ttk.Button(self.flightplans_frame, text="📂 Target Directories…", command=self.open_directories_window)
        dir_btn.grid(row=6, column=1, padx=5, pady=5, sticky='w', columnspan=3)
        auto_update_check = ttk.Checkbutton(self.flightplans_frame, text="Auto-Update", variable=self.auto_update_var, command=self.toggle_auto_update)
        auto_update_check.grid(row=6, column=4, padx=5, pady=5, sticky='e')
        status_frame = ttk.Frame(self.flightplans_frame)
        status_frame.grid(row=6, column=5, padx=5, pady=5, sticky='w')
        self.status_lamp = tk.Canvas(status_frame, width=12, height=12, highlightthickness=0, bg="#2b2b2b")
        self.status_lamp.pack(side="left")
        self._lamp_id = self.status_lamp.create_oval(2, 2, 10, 10, fill="#777777", outline="#777777")
        self.status_label = ttk.Label(status_frame, text="Status: Idle")
        self.status_label.pack(side="left", padx=6)
        ToolTip(
            target_dirs_label,
            "Choose where each format is saved. You can use X-Plane standard folders or set custom paths per format.",
        )
        ToolTip(
            dir_btn,
            "Choose where each format is saved. You can use X-Plane standard folders or set custom paths per format.",
        )
        ToolTip(auto_update_check, "Poll SimBrief every 30 seconds and prompt when a new plan is detected.")

        # Progressbar
        self.progress = ttk.Progressbar(self.flightplans_frame, mode='determinate', length=500)
        self.progress.grid(row=7, column=0, columnspan=6, padx=5, pady=10)
        ToolTip(self.progress, "Shows download progress for the current file.")

        # Console log
        self.console = ScrolledText(self.flightplans_frame, height=8, bg="#1e1e1e", fg="#ffffff", insertbackground='#ffffff')
        self.console.grid(row=8, column=0, columnspan=6, padx=5, pady=5, sticky="ew")
        ToolTip(
            self.console,
            "Live log of actions and errors. Useful for troubleshooting downloads.",
        )

        # Buttons
        save_btn = ttk.Button(self.flightplans_frame, text="Save Settings", command=self.save_settings)
        save_btn.grid(row=9, column=0, padx=5, pady=10)
        ToolTip(save_btn, "Save your current selections and paths to the local config file.")

        download_btn = ttk.Button(self.flightplans_frame, text="🚀 Download Flightplan 🚀", command=self.download_flightplan)
        download_btn.grid(row=9, column=1, padx=5, pady=10, columnspan=2)
        ToolTip(download_btn, "Download the selected formats for the current SimBrief plan.")

        self.cleanup_days_var = tk.StringVar(value="7")
        cleanup_days_label = ttk.Label(self.flightplans_frame, text="Cleanup days:")
        cleanup_days_label.grid(row=9, column=3, padx=5, pady=10, sticky='e')
        cleanup_days_entry = ttk.Entry(self.flightplans_frame, width=6, textvariable=self.cleanup_days_var)
        cleanup_days_entry.grid(row=9, column=4, padx=5, pady=10, sticky='w')
        clean_btn = ttk.Button(self.flightplans_frame, text="🧹 Clean Old Files", command=self.clean_old_files)
        clean_btn.grid(row=9, column=5, padx=5, pady=10, sticky='e')
        ToolTip(cleanup_days_label, "Age threshold in days for cleanup.")
        ToolTip(cleanup_days_entry, "Age threshold in days for cleanup.")
        ToolTip(clean_btn, "Delete files older than the specified number of days.")

        help_btn = ttk.Button(self.flightplans_frame, text="❓ Help", command=self.show_help)
        help_btn.grid(row=10, column=0, padx=5, pady=10, sticky='w')
        ToolTip(help_btn, "Open a short usage guide.")

        license_btn = ttk.Button(self.flightplans_frame, text="📄 License (GPL)", command=self.show_license)
        license_btn.grid(row=11, column=0, columnspan=6, padx=5, pady=10)

        # AIRAC tab UI (placeholder until Navigraph API is configured)
        self.airac_status_var = tk.StringVar(value="Status: Not configured")
        self.airac_installed_var = tk.StringVar(value="")
        self.airac_installed_revision_var = tk.StringVar(value="")
        self.airac_latest_var = tk.StringVar(value="")
        self.airac_latest_revision_var = tk.StringVar(value="0")
        self.airac_latest_initialized = False
        self.airac_path_var = tk.StringVar(value="")
        self.airac_source_var = tk.StringVar(value="")
        self._airac_dirs_win = None

        airac_title = ttk.Label(self.airac_frame, text="AIRAC (Navigraph)", font=("Arial", 12, "bold"))
        airac_title.grid(row=0, column=0, columnspan=3, sticky="w", padx=10, pady=10)

        ttk.Label(self.airac_frame, textvariable=self.airac_status_var).grid(row=1, column=0, columnspan=3, sticky="w", padx=10, pady=5)
        self.airac_installed_label = ttk.Label(self.airac_frame, text="Installed cycle: Unknown")
        self.airac_installed_label.grid(row=2, column=0, columnspan=3, sticky="w", padx=10, pady=5)
        self.airac_latest_label = ttk.Label(self.airac_frame, text="Latest cycle: Unknown")
        self.airac_latest_label.grid(row=3, column=0, columnspan=3, sticky="w", padx=10, pady=5)

        airac_dirs_btn = ttk.Button(self.airac_frame, text="📂 Target Directories…", command=self.open_airac_directories_window)
        airac_dirs_btn.grid(row=4, column=0, padx=10, pady=5, sticky="w")

        ttk.Label(self.airac_frame, text="Source directory:").grid(row=5, column=0, sticky="w", padx=10, pady=5)
        airac_source_entry = ttk.Entry(self.airac_frame, width=60, textvariable=self.airac_source_var)
        airac_source_entry.grid(row=5, column=1, padx=5, pady=5, sticky="ew")
        airac_source_btn = ttk.Button(self.airac_frame, text="Browse", command=self.select_airac_source)
        airac_source_btn.grid(row=5, column=2, padx=10, pady=5, sticky="e")

        airac_check_btn = ttk.Button(self.airac_frame, text="Check for Updates", command=self.check_airac_update)
        airac_check_btn.grid(row=6, column=0, padx=10, pady=10, sticky="w")
        airac_update_btn = ttk.Button(self.airac_frame, text="Update AIRAC", command=self.update_airac)
        airac_update_btn.grid(row=6, column=1, padx=5, pady=10, sticky="w")
        airac_read_btn = ttk.Button(self.airac_frame, text="Read Installed AIRAC", command=self.update_installed_cycle)
        airac_read_btn.grid(row=6, column=2, padx=10, pady=10, sticky="e")

        self.airac_console = ScrolledText(self.airac_frame, height=8, bg="#1e1e1e", fg="#ffffff", insertbackground='#ffffff')
        self.airac_console.grid(row=7, column=0, columnspan=3, padx=10, pady=5, sticky="ew")
        ToolTip(
            self.airac_console,
            "Live log of AIRAC actions and errors. Useful for troubleshooting updates.",
        )

        airac_save_btn = ttk.Button(self.airac_frame, text="Save Settings", command=self.save_settings)
        airac_save_btn.grid(row=8, column=0, padx=10, pady=10, sticky="w")
        ToolTip(airac_save_btn, "Save your current selections and paths to the local config file.")

        self.airac_frame.columnconfigure(1, weight=1)

        # Initial load
        self.last_flight_info = self.load_last_flight_info()
        self.load_settings()
        if self.auto_update_var.get():
            self.schedule_auto_update()
        else:
            self.set_status("Idle")
        self.update_installed_cycle(initialize_latest=True)

        # Keep a reference to the directories window
        self._dirs_win = None

    def show_license(self):
        license_text = """
SimBriefPyDownloader - Flightplan Downloader

Author: Nicolei Rademacher
Copyright (C) 2025

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
 the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
        license_window = tk.Toplevel(self.root)
        license_window.title("License - GPL v3+")
        license_window.configure(bg="#2b2b2b")
        text_area = ScrolledText(license_window, wrap=tk.WORD, bg="#1e1e1e", fg="#ffffff", insertbackground='#ffffff')
        text_area.pack(expand=True, fill='both')
        text_area.insert(tk.END, license_text)
        text_area.config(state='disabled')

    def show_help(self):
        help_text = (
            "Flightplans\n"
            "- Enter your SimBrief ID and select formats.\n"
            "- Configure Target Directories or use standard paths.\n"
            "- Click Download Flightplan to fetch the latest plan.\n"
            "- Enable Auto-Update to poll every 30 seconds.\n\n"
            "AIRAC\n"
            "- Set X-Plane root and open Target Directories to enable targets.\n"
            "- Choose a Source directory containing Navigraph ZIPs.\n"
            "- Use Update AIRAC to install all enabled targets or per-target Download.\n"
            "- Installed cycle and revision are read from .index/cycle.json files."
        )
        messagebox.showinfo("Help", help_text)

    # ---------- Neues Unterfenster für Zielverzeichnisse ----------
    def open_directories_window(self):
        if self._dirs_win and tk.Toplevel.winfo_exists(self._dirs_win):
            self._dirs_win.lift()
            return

        win = tk.Toplevel(self.root)
        self._dirs_win = win
        win.title("Target Directories")
        win.configure(bg="#2b2b2b")
        win.grab_set()  # modal fühlen

        # Überschrift
        ttk.Label(win, text="Set target directory per format").grid(row=0, column=0, columnspan=4, sticky='w', padx=10, pady=10)

        # X-Plane root
        ttk.Label(win, text="X-Plane root:").grid(row=1, column=0, sticky='w', padx=10, pady=4)
        root_entry = ttk.Entry(win, width=70, textvariable=self.xplane_root_var)
        root_entry.grid(row=1, column=1, padx=5, pady=4, sticky="ew", columnspan=2)
        root_browse_btn = ttk.Button(win, text="Browse", command=self.select_xplane_root)
        root_browse_btn.grid(row=1, column=3, padx=10, pady=4, sticky='e')

        # Grid mit Labels / Entry / Browse
        row = 2
        self._dir_entries = {}
        self._dir_browse_buttons = {}
        self._dir_standard_checks = {}
        entry_style = ttk.Style()
        entry_style.configure("Standard.TEntry", foreground="#a0a0a0")
        for fmt in self.formats:
            ttk.Label(win, text=f"{fmt}:").grid(row=row, column=0, sticky='w', padx=10, pady=4)
            entry = ttk.Entry(win, width=58, textvariable=self.directory_vars[fmt])
            entry.grid(row=row, column=1, padx=5, pady=4, sticky="ew")
            browse_btn = ttk.Button(win, text="Browse", command=lambda f=fmt: self.select_directory(f))
            browse_btn.grid(row=row, column=3, padx=10, pady=4, sticky='e')

            std_var = self.standard_dir_vars[fmt]
            std_btn = ttk.Checkbutton(
                win,
                text="Use standard",
                variable=std_var,
                command=lambda f=fmt: self.update_directory_mode(f),
            )
            std_btn.grid(row=row, column=2, padx=5, pady=4, sticky='w')

            self._dir_entries[fmt] = entry
            self._dir_browse_buttons[fmt] = browse_btn
            self._dir_standard_checks[fmt] = std_btn
            row += 1

        # Buttons unten
        close_btn = ttk.Button(win, text="Close", command=win.destroy)
        close_btn.grid(row=row, column=3, padx=10, pady=10, sticky='e')

        # Spalten dehnbar
        win.columnconfigure(1, weight=1)
        self.sync_standard_controls()

    # -------------------------------------------------------------

    def log(self, message):
        self.console.insert(tk.END, message + "\n")
        self.console.see(tk.END)

    def log_airac(self, message):
        if hasattr(self, "airac_console") and self.airac_console:
            self.airac_console.insert(tk.END, message + "\n")
            self.airac_console.see(tk.END)
        self.log(message)

    def select_directory(self, fmt):
        directory = filedialog.askdirectory(title=f"Select target directory for {fmt}")
        if directory:
            self.directory_vars[fmt].set(directory)
            self.manual_dir_cache[fmt] = directory

    def select_xplane_root(self):
        directory = filedialog.askdirectory(title="Select X-Plane root folder")
        if directory:
            self.xplane_root_var.set(directory)

    def get_standard_path(self, fmt):
        standard_rel = self.standard_paths.get(fmt)
        if not standard_rel:
            return ""
        xplane_root = self.xplane_root_var.get().strip()
        if not xplane_root:
            return standard_rel
        return os.path.join(xplane_root, standard_rel)

    def refresh_standard_paths(self):
        if not hasattr(self, "_dir_entries"):
            return
        for fmt, var in self.standard_dir_vars.items():
            if var.get():
                self.directory_vars[fmt].set(self.get_standard_path(fmt))
        self.sync_airac_path()

    def sync_standard_controls(self):
        for fmt, check in self._dir_standard_checks.items():
            if fmt not in self.standard_paths:
                check.state(["disabled"])
                self.standard_dir_vars[fmt].set(False)
            self.update_directory_mode(fmt)

    def update_directory_mode(self, fmt):
        use_standard = self.standard_dir_vars[fmt].get()
        entry = self._dir_entries.get(fmt)
        browse_btn = self._dir_browse_buttons.get(fmt)
        if entry and browse_btn:
            if use_standard and fmt in self.standard_paths:
                if not self.manual_dir_cache[fmt]:
                    self.manual_dir_cache[fmt] = self.directory_vars[fmt].get()
                self.directory_vars[fmt].set(self.get_standard_path(fmt))
                entry.configure(style="Standard.TEntry")
                entry.state(["readonly"])
                browse_btn.state(["disabled"])
            else:
                if self.manual_dir_cache[fmt]:
                    self.directory_vars[fmt].set(self.manual_dir_cache[fmt])
                entry.configure(style="TEntry")
                entry.state(["!readonly"])
                browse_btn.state(["!disabled"])

    def select_airac_path(self):
        directory = filedialog.askdirectory(title="Select AIRAC install folder")
        if directory:
            target = self.airac_target_var.get()
            if target in self.airac_use_default_vars:
                self.airac_use_default_vars[target].set(False)
                self.airac_directory_vars[target].set(directory)
            self.airac_path_var.set(directory)
            self.update_installed_cycle()

    def select_airac_source(self):
        directory = filedialog.askdirectory(title="Select AIRAC ZIP source directory")
        if directory:
            self.airac_source_var.set(directory)

    def sync_airac_path(self):
        target = self.airac_target_var.get()
        target_info = self.airac_targets.get(target)
        if not target_info:
            return
        if self.airac_use_default_vars.get(target, tk.BooleanVar(value=True)).get():
            target_path = self.get_airac_default_path(target)
            self.airac_directory_vars[target].set(target_path)
        else:
            target_path = self.airac_directory_vars.get(target, tk.StringVar(value="")).get()
        if target_path:
            self.airac_path_var.set(target_path)
        self.update_installed_cycle()

    def get_airac_default_path(self, target):
        target_info = self.airac_targets.get(target)
        if not target_info:
            return ""
        target_path = target_info["path"]
        if target_info.get("rooted", True):
            xplane_root = self.xplane_root_var.get().strip()
            if not xplane_root:
                return ""
            target_path = os.path.join(xplane_root, target_path)
        return target_path

    def open_airac_directories_window(self):
        if self._airac_dirs_win and tk.Toplevel.winfo_exists(self._airac_dirs_win):
            self._airac_dirs_win.lift()
            return

        win = tk.Toplevel(self.root)
        self._airac_dirs_win = win
        win.title("AIRAC Target Directories")
        win.configure(bg="#2b2b2b")
        win.grab_set()

        ttk.Label(win, text="Set target directory per AIRAC type").grid(row=0, column=0, columnspan=4, sticky='w', padx=10, pady=10)

        self._airac_dir_entries = {}
        self._airac_dir_browse_buttons = {}
        self._airac_dir_checks = {}
        self._airac_dir_enabled = {}
        self._airac_dir_status = {}
        self._airac_dir_download = {}

        row = 1
        for name in self.airac_targets:
            enabled_var = self.airac_enabled_vars[name]
            enabled_btn = ttk.Checkbutton(win, variable=enabled_var)
            enabled_btn.grid(row=row, column=0, padx=10, pady=4, sticky='w')

            ttk.Label(win, text=f"{name}:").grid(row=row, column=1, sticky='w', padx=10, pady=4)
            entry = ttk.Entry(win, width=58, textvariable=self.airac_directory_vars[name])
            entry.grid(row=row, column=2, padx=5, pady=4, sticky="ew")
            browse_btn = ttk.Button(win, text="Browse", command=lambda n=name: self.select_airac_directory(n))
            browse_btn.grid(row=row, column=4, padx=10, pady=4, sticky='e')

            status_label = tk.Label(win, text="Cycle: Unknown", bg="#2b2b2b", fg="#ffffff")
            status_label.grid(row=row, column=5, padx=10, pady=4, sticky='w')

            std_var = self.airac_use_default_vars[name]
            std_btn = ttk.Checkbutton(
                win,
                text="Use default",
                variable=std_var,
                command=lambda n=name: self.update_airac_directory_mode(n),
            )
            std_btn.grid(row=row, column=3, padx=5, pady=4, sticky='w')

            download_btn = ttk.Button(win, text="Download", command=lambda n=name: self.update_airac_target(n))
            download_btn.grid(row=row, column=6, padx=10, pady=4, sticky='e')

            self._airac_dir_entries[name] = entry
            self._airac_dir_browse_buttons[name] = browse_btn
            self._airac_dir_checks[name] = std_btn
            self._airac_dir_enabled[name] = enabled_btn
            self._airac_dir_status[name] = status_label
            self._airac_dir_download[name] = download_btn
            row += 1

        close_btn = ttk.Button(win, text="Close", command=win.destroy)
        close_btn.grid(row=row, column=6, padx=10, pady=10, sticky='e')

        win.columnconfigure(2, weight=1)
        self.sync_airac_directory_controls()
        self.update_airac_directory_statuses()

    def select_airac_directory(self, name):
        directory = filedialog.askdirectory(title=f"Select AIRAC folder for {name}")
        if directory:
            self.airac_use_default_vars[name].set(False)
            self.airac_directory_vars[name].set(directory)
            self.update_airac_directory_mode(name)
            if self.airac_target_var.get() == name:
                self.sync_airac_path()

    def sync_airac_directory_controls(self):
        for name in self.airac_targets:
            self.update_airac_directory_mode(name)

    def update_airac_directory_mode(self, name):
        entry = self._airac_dir_entries.get(name)
        browse_btn = self._airac_dir_browse_buttons.get(name)
        use_default = self.airac_use_default_vars[name].get()
        if entry and browse_btn:
            if use_default:
                self.airac_directory_vars[name].set(self.get_airac_default_path(name))
                entry.state(["readonly"])
                browse_btn.state(["disabled"])
            else:
                entry.state(["!readonly"])
                browse_btn.state(["!disabled"])
        if self.airac_target_var.get() == name:
            self.sync_airac_path()
        self.update_airac_directory_statuses()

    def parse_cycle_number(self, text):
        if not text:
            return None
        match = re.search(r"(\d{4})", text)
        if match:
            return int(match.group(1))
        return None

    def parse_revision_number(self, text):
        if not text:
            return None
        match = re.search(r"(\d+)", str(text))
        if match:
            return int(match.group(1))
        return None

    def get_latest_cycle_number(self):
        return self.parse_cycle_number(self.airac_latest_var.get())

    def update_airac_latest_label(self):
        latest_cycle = self.airac_latest_var.get().strip()
        latest_revision = self.airac_latest_revision_var.get().strip()
        if latest_cycle:
            revision_text = latest_revision if latest_revision else "0"
            self.airac_latest_label.config(text=f"Latest cycle: {latest_cycle}  Rev. {revision_text}")
        else:
            self.airac_latest_label.config(text="Latest cycle: Unknown")
        self.update_airac_main_colors()

    def update_airac_installed_label(self):
        installed_cycle = self.airac_installed_var.get().strip()
        installed_revision = self.airac_installed_revision_var.get().strip()
        if installed_cycle:
            revision_text = installed_revision if installed_revision else "0"
            self.airac_installed_label.config(text=f"Installed cycle: {installed_cycle}  Rev. {revision_text}")
        else:
            self.airac_installed_label.config(text="Installed cycle: Unknown")
        self.update_airac_main_colors()

    def update_airac_main_colors(self):
        installed_cycle = self.parse_cycle_number(self.airac_installed_var.get())
        latest_cycle = self.get_latest_cycle_number()
        installed_revision = self.parse_revision_number(self.airac_installed_revision_var.get())
        latest_revision = self.parse_revision_number(self.airac_latest_revision_var.get())
        if installed_cycle is None or latest_cycle is None:
            self.airac_installed_label.config(foreground="#ffffff")
            return
        if installed_cycle == latest_cycle:
            if installed_revision is None or latest_revision is None:
                color = "#4CAF50"
            elif installed_revision == latest_revision:
                color = "#4CAF50"
            elif installed_revision < latest_revision:
                color = "#f0c24b"
            else:
                color = "#4aa3ff"
        elif installed_cycle < latest_cycle:
            color = "#f0c24b"
        else:
            color = "#4aa3ff"
        self.airac_installed_label.config(foreground=color)

    def get_airac_installed_cycle_for_target(self, name):
        target_dir = self.get_airac_target_path(name)
        if not target_dir or not os.path.isdir(target_dir):
            return None
        cycle, _revision = self.get_airac_installed_info_for_target_path(target_dir, name)
        return cycle

    def get_airac_installed_info_for_target(self, name):
        target_dir = self.get_airac_target_path(name)
        if not target_dir or not os.path.isdir(target_dir):
            return None, None
        return self.get_airac_installed_info_for_target_path(target_dir, name)

    def get_airac_installed_info_for_target_path(self, target_dir, name_hint):
        if name_hint in ("IXEG 737 Classic Plus", "Rotate MD-11 Passenger", "Rotate MD-11 Freighter", "Rotate MD-80"):
            cycle_json = os.path.join(target_dir, "cycle.json")
            if os.path.exists(cycle_json):
                try:
                    with open(cycle_json, "r") as f:
                        data = json.load(f)
                    cycle_num = self.parse_cycle_number(data.get("cycle"))
                    revision_num = self.parse_revision_number(data.get("revision"))
                    if cycle_num:
                        return cycle_num, revision_num
                except Exception:
                    return None, None
        try:
            files = os.listdir(target_dir)
        except Exception:
            return None, None
        index_files = [f for f in files if f.lower().endswith(".index")]
        for filename in index_files:
            file_path = os.path.join(target_dir, filename)
            try:
                tree = ET.parse(file_path)
                root = tree.getroot()
                addon_name = ""
                addon_cycle = None
                addon_revision = None
                for node in root.iter("addon"):
                    addon_name = node.attrib.get("name", "").lower()
                    addon_cycle = node.attrib.get("cycle")
                    addon_revision = node.attrib.get("revision")
                    break

                if self.match_airac_addon_name(name_hint, addon_name):
                    cycle_num = self.parse_cycle_number(addon_cycle)
                    revision_num = self.parse_revision_number(addon_revision)
                    if cycle_num:
                        return cycle_num, revision_num
                self.log_airac(f"AIRAC: {name_hint} index '{filename}' addon '{addon_name}' cycle '{addon_cycle}'")

                for node in root.iter():
                    for key, value in node.attrib.items():
                        if key.lower() == "cycle":
                            cycle_num = self.parse_cycle_number(value)
                            if cycle_num:
                                revision_num = self.parse_revision_number(node.attrib.get("revision"))
                                return cycle_num, revision_num
            except Exception:
                continue
        return None, None

    def match_airac_addon_name(self, name, addon_name):
        patterns = self.airac_addon_name_patterns.get(name, [])
        if not patterns and name:
            patterns = [name.lower()]
        for pattern in patterns:
            if pattern in addon_name:
                return True
        return False

    def update_airac_directory_statuses(self):
        if not hasattr(self, "_airac_dir_status"):
            return
        if not self._airac_dirs_win or not tk.Toplevel.winfo_exists(self._airac_dirs_win):
            return
        latest_cycle = self.get_latest_cycle_number()
        latest_revision = self.parse_revision_number(self.airac_latest_revision_var.get())
        for name, label in self._airac_dir_status.items():
            try:
                if not label.winfo_exists():
                    continue
            except Exception:
                continue
            target_dir = self.get_airac_target_path(name)
            installed_cycle, installed_revision = self.get_airac_installed_info_for_target(name)
            if not installed_cycle:
                label.config(text="Cycle: Unknown", fg="#ffffff")
                continue
            label_text = f"Cycle: {installed_cycle}"
            if installed_revision is not None:
                label_text += f" r{installed_revision}"
            label.config(text=label_text)
            if latest_cycle is None:
                label.config(fg="#ffffff")
            elif installed_cycle == latest_cycle:
                if installed_revision is None or latest_revision is None:
                    label.config(fg="#4CAF50")
                elif installed_revision == latest_revision:
                    label.config(fg="#4CAF50")
                elif installed_revision < latest_revision:
                    label.config(fg="#f0c24b")
                else:
                    label.config(fg="#4aa3ff")
            elif installed_cycle < latest_cycle:
                label.config(fg="#f0c24b")
            else:
                label.config(fg="#4aa3ff")

    def update_airac_target(self, name):
        source_dir = self.airac_source_var.get().strip()
        if not source_dir or not os.path.isdir(source_dir):
            messagebox.showwarning("AIRAC", "Please select a valid source directory for AIRAC ZIPs.")
            self.log_airac("AIRAC: invalid source directory.")
            return
        if not self.airac_enabled_vars[name].get():
            messagebox.showwarning("AIRAC", f"{name} is disabled in target directories.")
            self.log_airac(f"AIRAC: skipped (disabled) -> {name}")
            return

        zip_path = self.find_airac_zip(source_dir, name)
        if not zip_path:
            self.log_airac(f"AIRAC: missing ZIP -> {name}")
            messagebox.showwarning("AIRAC", f"No ZIP found for {name}.")
            return

        target_dir = self.get_airac_target_path(name)
        if not target_dir:
            self.log_airac(f"AIRAC: target path missing -> {name}")
            messagebox.showwarning("AIRAC", f"No target path set for {name}.")
            return

        try:
            self.extract_airac_zip(zip_path, target_dir)
            self.log_airac(f"AIRAC: installed -> {name} ({os.path.basename(zip_path)})")
            self.update_airac_directory_statuses()
            installed_cycle, installed_revision = self.get_airac_installed_info_for_target(name)
            latest_cycle = self.get_latest_cycle_number()
            latest_revision = self.parse_revision_number(self.airac_latest_revision_var.get())
            if installed_cycle and latest_cycle:
                if installed_cycle == latest_cycle:
                    if installed_revision is None or latest_revision is None or installed_revision == latest_revision:
                        self.log_airac(f"AIRAC: {name} is up to date.")
                    elif installed_revision < latest_revision:
                        self.log_airac(f"AIRAC: {name} is behind the latest revision.")
                    else:
                        self.log_airac(f"AIRAC: {name} is ahead of the latest revision.")
                elif installed_cycle < latest_cycle:
                    self.log_airac(f"AIRAC: {name} is behind the latest cycle.")
                else:
                    self.log_airac(f"AIRAC: {name} is ahead of the latest cycle.")
            messagebox.showinfo("AIRAC", f"{name} installed successfully.")
        except Exception as e:
            self.log_airac(f"AIRAC: install failed -> {name}: {e}")
            messagebox.showerror("AIRAC", f"Failed to install {name}: {e}")

    def update_installed_cycle(self, initialize_latest=False):
        xplane_root = self.xplane_root_var.get().strip()
        if not xplane_root:
            self.airac_installed_var.set("")
            self.airac_installed_revision_var.set("")
            self.update_airac_installed_label()
            self.log_airac("AIRAC: X-Plane root not set.")
            return
        target_dir = os.path.join(xplane_root, "Custom Data")
        cycle_num, revision_num = self.get_airac_installed_info_for_target_path(target_dir, "X-Plane 12 native")
        if cycle_num:
            self.airac_installed_var.set(str(cycle_num))
            self.airac_installed_revision_var.set("" if revision_num is None else str(revision_num))
            self.update_airac_installed_label()
            self.log_airac(f"AIRAC: installed cycle -> {cycle_num}")
            if initialize_latest and not self.airac_latest_initialized:
                self.airac_latest_var.set(str(cycle_num))
                self.airac_latest_revision_var.set("0" if revision_num is None else str(revision_num))
                self.update_airac_latest_label()
                self.save_settings(silent=True)
                self.airac_latest_initialized = True
        else:
            self.airac_installed_var.set("")
            self.airac_installed_revision_var.set("")
            self.update_airac_installed_label()
            self.log_airac("AIRAC: installed cycle not found in .index file.")

    def install_airac_zip(self):
        target_dir = self.airac_path_var.get().strip()
        if not target_dir:
            messagebox.showwarning("AIRAC", "Please select an install path first.")
            return
        zip_path = filedialog.askopenfilename(
            title="Select Navigraph AIRAC ZIP",
            filetypes=[("ZIP files", "*.zip"), ("All files", "*.*")],
        )
        if not zip_path:
            return
        try:
            self.extract_airac_zip(zip_path, target_dir)
            self.update_installed_cycle()
            messagebox.showinfo("AIRAC", "AIRAC package installed successfully.")
        except Exception as e:
            messagebox.showerror("AIRAC", f"Failed to install AIRAC: {e}")

    def extract_airac_zip(self, zip_path, target_dir):
        with tempfile.TemporaryDirectory() as temp_dir:
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(temp_dir)

            source_dir = self.pick_airac_source_dir(temp_dir, target_dir)
            if not source_dir:
                raise RuntimeError("Could not determine AIRAC content folder.")

            os.makedirs(target_dir, exist_ok=True)
            self.copy_tree(source_dir, target_dir)

    def pick_airac_source_dir(self, temp_dir, target_dir):
        custom_data_root = os.path.join(temp_dir, "Custom Data")
        target_lower = target_dir.lower()
        target_leaf = os.path.basename(target_dir.rstrip("/\\"))

        if "gns430" in target_lower:
            for candidate in (
                os.path.join(custom_data_root, "GNS430"),
                os.path.join(temp_dir, "GNS430"),
            ):
                if os.path.isdir(candidate):
                    return candidate
        if "ufmc" in target_lower:
            for candidate in (
                os.path.join(custom_data_root, "UFMC"),
                os.path.join(temp_dir, "UFMC"),
            ):
                if os.path.isdir(candidate):
                    return candidate
        if "stsff" in target_lower:
            for candidate in (
                os.path.join(custom_data_root, "STSFF"),
                os.path.join(temp_dir, "STSFF"),
            ):
                if os.path.isdir(candidate):
                    return candidate

        if target_leaf:
            for root_dir, dirs, _files in os.walk(temp_dir):
                for dir_name in dirs:
                    if dir_name.lower() == target_leaf.lower():
                        return os.path.join(root_dir, dir_name)

        if os.path.isdir(custom_data_root):
            if target_dir.replace("\\", "/").endswith("/Custom Data"):
                return custom_data_root
            return custom_data_root
        return temp_dir if os.path.isdir(temp_dir) else ""

    def copy_tree(self, source_dir, target_dir):
        for root_dir, dirs, files in os.walk(source_dir):
            rel_dir = os.path.relpath(root_dir, source_dir)
            dest_dir = target_dir if rel_dir == "." else os.path.join(target_dir, rel_dir)
            os.makedirs(dest_dir, exist_ok=True)
            for filename in files:
                src_path = os.path.join(root_dir, filename)
                dst_path = os.path.join(dest_dir, filename)
                shutil.copy2(src_path, dst_path)

    def get_airac_target_path(self, name):
        if self.airac_use_default_vars.get(name, tk.BooleanVar(value=True)).get():
            return self.get_airac_default_path(name)
        return self.airac_directory_vars.get(name, tk.StringVar(value="")).get().strip()

    def find_airac_zip(self, source_dir, name):
        prefixes = self.airac_zip_prefixes.get(name, [])
        if not prefixes:
            return ""
        matches = []
        for entry in os.scandir(source_dir):
            if not entry.is_file():
                continue
            filename = entry.name
            lower = filename.lower()
            if not lower.endswith(".zip"):
                continue
            if any(lower.startswith(prefix) for prefix in prefixes):
                matches.append(entry.path)
        if not matches:
            return ""
        if len(matches) == 1:
            return matches[0]
        return self.pick_latest_cycle_zip(matches)

    def pick_latest_cycle_zip(self, paths):
        best_path = ""
        best_cycle = -1
        for path in paths:
            match = re.search(r"_(\d+)\.zip$", os.path.basename(path))
            if match:
                cycle = int(match.group(1))
                if cycle > best_cycle:
                    best_cycle = cycle
                    best_path = path
        return best_path or paths[0]

    def check_airac_update(self):
        self.log_airac("AIRAC: Navigraph API is not configured yet.")
        messagebox.showinfo("AIRAC", "Navigraph API is not configured yet.")

    def update_airac(self):
        source_dir = self.airac_source_var.get().strip()
        if not source_dir or not os.path.isdir(source_dir):
            messagebox.showwarning("AIRAC", "Please select a valid source directory for AIRAC ZIPs.")
            self.log_airac("AIRAC: invalid source directory.")
            return

        self.log_airac(f"AIRAC: scanning source directory -> {source_dir}")
        installed_any = False
        for name in self.airac_targets:
            if not self.airac_enabled_vars[name].get():
                self.log_airac(f"AIRAC: skipped (disabled) -> {name}")
                continue

            zip_path = self.find_airac_zip(source_dir, name)
            if not zip_path:
                self.log_airac(f"AIRAC: missing ZIP -> {name}")
                continue

            target_dir = self.get_airac_target_path(name)
            if not target_dir:
                self.log_airac(f"AIRAC: target path missing -> {name}")
                continue

            try:
                self.extract_airac_zip(zip_path, target_dir)
                self.log_airac(f"AIRAC: installed -> {name} ({os.path.basename(zip_path)})")
                installed_any = True
            except Exception as e:
                self.log_airac(f"AIRAC: install failed -> {name}: {e}")

        self.update_installed_cycle()
        if installed_any:
            self.log_airac("AIRAC: installation completed.")
            messagebox.showinfo("AIRAC", "AIRAC installation completed.")
        else:
            self.log_airac("AIRAC: no packages installed.")
            messagebox.showwarning("AIRAC", "No AIRAC packages were installed.")
        self.update_airac_directory_statuses()

    def save_settings(self, silent=False):
        config = {
            "username": self.username_entry.get(),
            "formats": [fmt for fmt, var in self.formats.items() if var.get()],
            "directories": {fmt: var.get() for fmt, var in self.directory_vars.items()},
            "use_standard_dirs": {fmt: var.get() for fmt, var in self.standard_dir_vars.items()},
            "xplane_root": self.xplane_root_var.get(),
            "auto_update": self.auto_update_var.get(),
            "cleanup_days": self.cleanup_days_var.get(),
            "last_flight_info": self.last_flight_info,
            "airac_path": self.airac_path_var.get(),
            "airac_target": self.airac_target_var.get(),
            "airac_directories": {name: var.get() for name, var in self.airac_directory_vars.items()},
            "airac_use_default": {name: var.get() for name, var in self.airac_use_default_vars.items()},
            "airac_enabled": {name: var.get() for name, var in self.airac_enabled_vars.items()},
            "airac_source": self.airac_source_var.get(),
            "airac_latest": self.airac_latest_var.get(),
            "airac_latest_revision": self.airac_latest_revision_var.get()
        }
        with open(CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=4)
        if not silent:
            messagebox.showinfo("Saved", "Settings have been saved!")

    def load_settings(self):
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r") as f:
                    config = json.load(f)
            except Exception as e:
                self.log(f"Config load error: {e}")
                return
            self.username_entry.delete(0, tk.END)
            self.username_entry.insert(0, config.get("username", ""))
            for fmt, var in self.formats.items():
                var.set(fmt in config.get("formats", []))
            for fmt, var in self.directory_vars.items():
                var.set(config.get("directories", {}).get(fmt, ""))
            if "use_standard_dirs" in config:
                for fmt, var in self.standard_dir_vars.items():
                    var.set(config.get("use_standard_dirs", {}).get(fmt, False))
            if "xplane_root" in config:
                self.xplane_root_var.set(config.get("xplane_root", self.xplane_root_var.get()))
            if "cleanup_days" in config:
                self.cleanup_days_var.set(str(config.get("cleanup_days", self.cleanup_days_var.get())))
            if "auto_update" in config:
                self.auto_update_var.set(bool(config.get("auto_update")))
            if "airac_path" in config:
                self.airac_path_var.set(config.get("airac_path", ""))
            if "airac_target" in config:
                self.airac_target_var.set(config.get("airac_target", self.airac_target_var.get()))
            if "airac_directories" in config:
                for name, var in self.airac_directory_vars.items():
                    var.set(config.get("airac_directories", {}).get(name, ""))
            if "airac_use_default" in config:
                for name, var in self.airac_use_default_vars.items():
                    var.set(config.get("airac_use_default", {}).get(name, True))
            if "airac_enabled" in config:
                for name, var in self.airac_enabled_vars.items():
                    var.set(config.get("airac_enabled", {}).get(name, True))
            if "airac_source" in config:
                self.airac_source_var.set(config.get("airac_source", ""))
            if "airac_latest" in config:
                self.airac_latest_var.set(config.get("airac_latest", ""))
                self.airac_latest_initialized = True
            if "airac_latest_revision" in config:
                self.airac_latest_revision_var.set(str(config.get("airac_latest_revision", "0")))
            if not self.airac_latest_revision_var.get():
                self.airac_latest_revision_var.set("0")
            self.update_airac_latest_label()
            self.sync_airac_path()

    def load_last_flight_info(self):
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r") as f:
                    config = json.load(f)
            except Exception as e:
                self.log(f"Config load error: {e}")
                return {}
            return config.get("last_flight_info", {})
        return {}

    def toggle_auto_update(self):
        if self.auto_update_var.get():
            self.set_status("Idle")
            self.schedule_auto_update()
        else:
            self.cancel_auto_update()
            self.set_status("Idle")

    def set_status(self, state):
        if state == "Polling":
            color = "#f0c24b"
        elif state == "Online":
            color = "#4CAF50"
        elif state == "Offline":
            color = "#e57373"
        else:
            color = "#777777"
        self.status_lamp.itemconfig(self._lamp_id, fill=color, outline=color)
        self.status_label.config(text=f"Status: {state}")

    def schedule_auto_update(self):
        self.cancel_auto_update()
        self._auto_update_job = self.root.after(30000, self.auto_update_tick)

    def cancel_auto_update(self):
        if self._auto_update_job:
            self.root.after_cancel(self._auto_update_job)
            self._auto_update_job = None

    def auto_update_tick(self):
        if not self.auto_update_var.get():
            return
        if self._auto_update_running:
            self.schedule_auto_update()
            return
        self._auto_update_running = True
        try:
            self.set_status("Polling")
            self.check_for_new_plan()
        finally:
            self._auto_update_running = False
            self.schedule_auto_update()

    def check_for_new_plan(self):
        username = self.username_entry.get().strip()
        if not username:
            return

        try:
            url = SIMBRIEF_API_URL.format(username=username)
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            now = time.time()
            if now - self._auto_update_error_ts > 300:
                self.log(f"Auto-update error: {e}")
                self._auto_update_error_ts = now
            self._auto_update_failed = True
            self.set_status("Offline")
            return
        self._auto_update_failed = False
        self.set_status("Online")

        params = data.get("params", {})
        timecode = params.get("time_generated")
        if not timecode:
            return
        last_timecode = self.last_flight_info.get("timecode") if self.last_flight_info else None
        if not last_timecode:
            self.last_flight_info = {"timecode": timecode}
            self.save_settings(silent=True)
            return
        if timecode == last_timecode:
            return

        self.last_flight_info["timecode"] = timecode
        self.save_settings(silent=True)
        self.send_notification("New Flightplan", "New SimBrief flightplan detected.")
        prompt = messagebox.askyesno("New Flightplan", "New SimBrief flightplan detected. Download now?")
        if prompt:
            self.download_flightplan()

    def send_notification(self, title, message):
        if not notification:
            self.log("Notifications are unavailable. Install 'plyer' to enable them.")
            return
        try:
            notification.notify(title=title, message=message, app_name="SimBriefPyDownloader")
        except Exception as e:
            self.log(f"Notification error: {e}")

    def save_last_flight_info(self, flight_info):
        self.last_flight_info = flight_info
        self.save_settings(silent=True)

    def update_flight_info_display(self, icao_airline, flight_number, aircraft, origin, destination, is_new, origin_name, destination_name):
        display_text = f"Flight {icao_airline} {flight_number} | Aircraft: {aircraft} | {origin} ➔ {destination} | {origin_name} ➔ {destination_name}"
        color = "#4CAF50" if is_new else "#ffffff"
        self.flight_info_label.config(text=display_text, foreground=color)

    def get_next_filename(self, directory, base_name, extension):
        os.makedirs(directory, exist_ok=True)
        existing_files = set(os.listdir(directory))
        counter = 1
        while True:
            filename = f"{base_name}{counter:02}.{extension}"
            if base_name == "b738x":
                # Zibo: feste Namenskonvention möglich
                self.log(f"File {base_name}")
                return f"{base_name}.{extension}"
            elif filename not in existing_files:
                return filename
 #           elif filename == "b738x":
 #               # Zibo: feste Namenskonvention möglich
 #               self.log(f"File {base_name}")
 #               return f"{base_name}.{extension}"
            counter += 1

    def download_file(self, url, save_directory, filename):
        os.makedirs(save_directory, exist_ok=True)
        file_path = os.path.join(save_directory, filename)
        response = requests.get(url, stream=True)
        response.raise_for_status()
        total_length = response.headers.get('content-length')
        dl = 0
        total_length = int(total_length) if total_length is not None else None

        with open(file_path, 'wb') as file:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    file.write(chunk)
                    dl += len(chunk)
                    if total_length:
                        self.progress['value'] = (dl / total_length) * 100
                        self.root.update_idletasks()

        self.progress['value'] = 100
        self.root.update_idletasks()

    def clean_old_files(self):
        try:
            cleanup_days = int(self.cleanup_days_var.get())
        except ValueError:
            messagebox.showwarning("Warning", "Cleanup days must be a whole number.")
            return
        if cleanup_days <= 0:
            messagebox.showwarning("Warning", "Cleanup days must be greater than zero.")
            return
        confirm = messagebox.askyesno(
            "Confirm",
            f"Do you really want to delete all flightplan files older than {cleanup_days} days in the target directories?",
        )
        if not confirm:
            return

        now = time.time()
        cutoff = now - (cleanup_days * 86400)

        for fmt, var in self.directory_vars.items():
            directory = var.get()
            if not directory or not os.path.isdir(directory):
                continue
            for filename in os.listdir(directory):
                file_path = os.path.join(directory, filename)
                if os.path.isfile(file_path):
                    if os.path.getmtime(file_path) < cutoff:
                        try:
                            os.remove(file_path)
                            self.log(f"Deleted old file: {file_path}")
                        except Exception as e:
                            self.log(f"Error deleting file {file_path}: {e}")
        messagebox.showinfo("Cleanup", "Old files cleanup completed!")

    def download_flightplan(self):
        username = self.username_entry.get().strip()
        if not username:
            messagebox.showerror("Error", "Please enter your SimBrief username!")
            return

        try:
            url = SIMBRIEF_API_URL.format(username=username)
            self.log(f"Fetching SimBrief data from: {url}")
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()

            fetch = data.get("fetch", {})
            general = data.get("general", {})
            params = data.get("params", {})
            origin = data.get("origin", {})
            destination = data.get("destination", {})
            aircraft = data.get("aircraft", {})

            if not all([fetch, params, origin, destination, aircraft]):
                messagebox.showwarning("Warning", "Incomplete data received from SimBrief. Check your flightplan.")
                return

            origin_icao = origin.get("icao_code")
            destination_icao = destination.get("icao_code")
            timecode = params.get("time_generated")
            icao_airline = general.get("icao_airline", "Private Charter")
            flight_number = general.get("flight_number", "N/A")
            aircraft_type = aircraft.get("icao_code", "N/A")
            origin_name = origin.get("name", "N/A")
            destination_name = destination.get("name", "N/A")

            current_flight_info = {
                "icao_airline": icao_airline,
                "flight_number": flight_number,
                "aircraft": aircraft_type,
                "origin": origin_icao,
                "destination": destination_icao,
                "timecode": timecode,
                "origin_name": origin_name,
                "destination_name": destination_name
            }

            is_new_route = current_flight_info != self.last_flight_info
            self.update_flight_info_display(icao_airline, flight_number, aircraft_type, origin_icao, destination_icao, is_new_route, origin_name, destination_name)

            if is_new_route:
                self.log("New route detected!")
                self.save_last_flight_info(current_flight_info)
            else:
                self.log("No new route detected.")

            downloaded_any = False

            for fmt, var in self.formats.items():
                if var.get():
                    if self.standard_dir_vars[fmt].get() and fmt in self.standard_paths:
                        xplane_root = self.xplane_root_var.get().strip()
                        if not xplane_root:
                            messagebox.showwarning("Warning", "X-Plane root folder is not set.")
                            continue
                        target_dir = os.path.join(xplane_root, self.standard_paths[fmt])
                    else:
                        target_dir = self.directory_vars[fmt].get()
                    if not target_dir:
                        messagebox.showwarning("Warning", f"No target directory set for {fmt}.")
                        continue

                    base_pair = f"{origin_icao}{destination_icao}"
                    if fmt == "PDF":
                        base_filename = f"{base_pair}_PDF_{timecode}"
                        file_url = f"{FLIGHTPLAN_BASE_URL}{base_filename}.pdf"
                        extension = "pdf"
                        base_name = base_pair
                    elif fmt == "FMS":
                        base_filename = f"{base_pair}_XPN_{timecode}"
                        file_url = f"{FLIGHTPLAN_BASE_URL}{base_filename}.fms"
                        extension = "fms"
                        base_name = base_pair
                    elif fmt == "XPE":
                        base_filename = f"{base_pair}_XPE_{timecode}"
                        file_url = f"{FLIGHTPLAN_BASE_URL}{base_filename}.fms"
                        extension = "fms"
                        base_name = base_pair
                    elif fmt in ("FF757", "STSFF"):
                        base_filename = f"{base_pair}_VMX_{timecode}"
                        file_url = f"{FLIGHTPLAN_BASE_URL}{base_filename}.flp--VM5"
                        extension = "flp"
                        base_name = base_pair
                    elif fmt == "TDS":
                        base_filename = f"{base_pair}_GTN_{timecode}"
                        file_url = f"{FLIGHTPLAN_BASE_URL}{base_filename}.gfp--VM5"
                        extension = "gfp"
                        base_name = base_pair
                    elif fmt == "MD11":
                        base_filename = f"{base_pair}_JAR_{timecode}"
                        file_url = f"{FLIGHTPLAN_BASE_URL}{base_filename}.txt--RMD"
                        extension = "txt"
                        base_name = base_pair
                    elif fmt == "Zibo":
                        base_filename = f"{base_pair}_XML_{timecode}"
                        file_url = f"{FLIGHTPLAN_XML_URL}{base_filename}.xml--ZBO"
                        extension = "xml"
                        base_name = "b738x"
                    elif fmt == "XML":
                        base_filename = f"{base_pair}_XML_{timecode}"
                        file_url = f"{FLIGHTPLAN_XML_URL}{base_filename}.xml"
                        extension = "xml"
                        base_name = base_pair
                    else:
                        continue

                    filename = self.get_next_filename(target_dir, base_name, extension)

                    try:
                        self.log(f"Downloading {fmt} to {target_dir}/{filename}")
                        self.progress['value'] = 0
                        self.download_file(file_url, target_dir, filename)
                        downloaded_any = True
                        self.log(f"Saved: {filename}")
                    except Exception as e:
                        self.log(f"Failed to download {fmt}: {e}")

            if downloaded_any:
                messagebox.showinfo("Success", "Selected flightplan files have been downloaded successfully!")
            else:
                messagebox.showwarning("Notice", "No files were downloaded. Check your selection and SimBrief plan.")

        except Exception as e:
            messagebox.showerror("Error", f"Error while fetching data: {e}")
            self.log(f"Error while fetching data: {e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = SimBriefPyDownloader(root)
    root.mainloop()
