#!/usr/bin/env python3

import os
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

APP_VERSION = "1.0.3"
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "simbrief_downloader_config.json")
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

        # Flight info display
        self.flight_info_label = ttk.Label(root, text="Flight Info: N/A", font=("Arial", 12, "bold"), foreground="#ffffff")
        self.flight_info_label.grid(row=0, column=0, columnspan=6, sticky='w', padx=5, pady=5)

        # Username
        simbrief_label = ttk.Label(root, text="SimBrief ID:")
        simbrief_label.grid(row=1, column=0, sticky='w', padx=5, pady=5)
        self.username_entry = ttk.Entry(root, width=20)
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
        ttk.Label(root, text="File Formats:").grid(row=2, column=0, sticky='ew', padx=2, pady=2)
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
        formats_per_row = 4
        row_base = 3
        col = 1

        for i, (fmt, var) in enumerate(self.formats.items()):
            r = row_base + (i // formats_per_row)
            c = 1 + (i % formats_per_row)
            check = ttk.Checkbutton(root, text=fmt, variable=var)
            check.grid(row=r, column=c, padx=8, pady=5, sticky='w')
            if fmt in self.format_tooltips:
                ToolTip(check, self.format_tooltips[fmt])

        # Directory variables + Button zum Unterfenster
        self.directory_vars = {fmt: tk.StringVar() for fmt in self.formats}
        target_dirs_label = ttk.Label(root, text="Target Directories:")
        target_dirs_label.grid(row=6, column=0, sticky='w', padx=5, pady=5)
        dir_btn = ttk.Button(root, text="📂 Target Directories…", command=self.open_directories_window)
        dir_btn.grid(row=6, column=1, padx=5, pady=5, sticky='w', columnspan=3)
        auto_update_check = ttk.Checkbutton(root, text="Auto-Update", variable=self.auto_update_var, command=self.toggle_auto_update)
        auto_update_check.grid(row=6, column=4, padx=5, pady=5, sticky='e')
        status_frame = ttk.Frame(root)
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
        self.progress = ttk.Progressbar(root, mode='determinate', length=500)
        self.progress.grid(row=7, column=0, columnspan=6, padx=5, pady=10)
        ToolTip(self.progress, "Shows download progress for the current file.")

        # Console log
        self.console = ScrolledText(root, height=8, bg="#1e1e1e", fg="#ffffff", insertbackground='#ffffff')
        self.console.grid(row=8, column=0, columnspan=6, padx=5, pady=5, sticky="ew")
        ToolTip(
            self.console,
            "Live log of actions and errors. Useful for troubleshooting downloads.",
        )

        # Buttons
        save_btn = ttk.Button(root, text="Save Settings", command=self.save_settings)
        save_btn.grid(row=9, column=0, padx=5, pady=10)
        ToolTip(save_btn, "Save your current selections and paths to the local config file.")

        download_btn = ttk.Button(root, text="🚀 Download Flightplan 🚀", command=self.download_flightplan)
        download_btn.grid(row=9, column=1, padx=5, pady=10, columnspan=2)
        ToolTip(download_btn, "Download the selected formats for the current SimBrief plan.")

        self.cleanup_days_var = tk.StringVar(value="7")
        cleanup_days_label = ttk.Label(root, text="Cleanup days:")
        cleanup_days_label.grid(row=9, column=3, padx=5, pady=10, sticky='e')
        cleanup_days_entry = ttk.Entry(root, width=6, textvariable=self.cleanup_days_var)
        cleanup_days_entry.grid(row=9, column=4, padx=5, pady=10, sticky='w')
        clean_btn = ttk.Button(root, text="🧹 Clean Old Files", command=self.clean_old_files)
        clean_btn.grid(row=9, column=5, padx=5, pady=10, sticky='e')
        ToolTip(cleanup_days_label, "Age threshold in days for cleanup.")
        ToolTip(cleanup_days_entry, "Age threshold in days for cleanup.")
        ToolTip(clean_btn, "Delete files older than the specified number of days.")

        license_btn = ttk.Button(root, text="📄 License (GPL)", command=self.show_license)
        license_btn.grid(row=10, column=0, columnspan=6, padx=5, pady=10)

        # Initial load
        self.last_flight_info = self.load_last_flight_info()
        self.load_settings()
        if self.auto_update_var.get():
            self.schedule_auto_update()
        else:
            self.set_status("Idle")

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

    def save_settings(self, silent=False):
        config = {
            "username": self.username_entry.get(),
            "formats": [fmt for fmt, var in self.formats.items() if var.get()],
            "directories": {fmt: var.get() for fmt, var in self.directory_vars.items()},
            "use_standard_dirs": {fmt: var.get() for fmt, var in self.standard_dir_vars.items()},
            "xplane_root": self.xplane_root_var.get(),
            "auto_update": self.auto_update_var.get(),
            "cleanup_days": self.cleanup_days_var.get(),
            "last_flight_info": self.last_flight_info
        }
        with open(CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=4)
        if not silent:
            messagebox.showinfo("Saved", "Settings have been saved!")

    def load_settings(self):
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r") as f:
                config = json.load(f)
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

    def load_last_flight_info(self):
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r") as f:
                config = json.load(f)
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
