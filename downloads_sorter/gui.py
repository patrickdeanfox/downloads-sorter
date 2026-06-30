#!/usr/bin/env python3
"""A small Tkinter control panel for downloads-sorter.

It is a *front-end*, not the engine: the watcher runs as a systemd --user
service, and this window starts/stops it, runs one-shot sorts, shows the move
history (with undo), and edits the config file. Run with::

    python3 -m downloads_sorter.gui
"""

from __future__ import annotations

import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .config import Config, CONFIG_PATH, load_config, save_config
from .core import read_moves, undo_rows

SERVICE = "downloads-sorter.service"

# ── palette ────────────────────────────────────────────────────────────────────
BG, BG2, BG3, BORDER = "#0f0f13", "#17171f", "#1e1e28", "#2a2a38"
ACCENT, ACCENT2 = "#7c6af7", "#4ecdc4"
WARN, DANGER, SUCCESS = "#f4a261", "#e05c5c", "#56c97d"
FG, FG2, FG3 = "#e8e8f0", "#9090a8", "#5a5a72"
FONT_HEAD = ("Ubuntu", 13, "bold")
FONT_SUB = ("Ubuntu", 10)
FONT_BODY = ("Ubuntu", 10)
FONT_MONO = ("Ubuntu Mono", 9)
FONT_BADGE = ("Ubuntu", 8, "bold")
FONT_MED = ("Ubuntu", 15, "bold")


# ── systemd helpers ─────────────────────────────────────────────────────────────

def _systemctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", "--user", *args],
                          capture_output=True, text=True)


def service_installed() -> bool:
    unit = Path.home() / ".config" / "systemd" / "user" / SERVICE
    return unit.exists()


def service_active() -> bool:
    return _systemctl("is-active", SERVICE).stdout.strip() == "active"


def service_enabled() -> bool:
    return _systemctl("is-enabled", SERVICE).stdout.strip() == "enabled"


# ── small styled widgets ────────────────────────────────────────────────────────

def _lighten(hexc: str, amt: int = 30) -> str:
    hexc = hexc.lstrip("#")
    r, g, b = (int(hexc[i:i + 2], 16) for i in (0, 2, 4))
    return f"#{min(255, r+amt):02x}{min(255, g+amt):02x}{min(255, b+amt):02x}"


def _btn(parent, text, command, color=ACCENT, fg=FG, font=FONT_BODY):
    b = tk.Button(parent, text=text, command=command, bg=color, fg=fg,
                  activebackground=color, activeforeground=fg, relief="flat",
                  bd=0, font=font, cursor="hand2", padx=14, pady=7)
    b.bind("<Enter>", lambda e: b.config(bg=_lighten(color)))
    b.bind("<Leave>", lambda e: b.config(bg=color))
    return b


def _label(parent, text, font=FONT_BODY, fg=FG, bg=BG, **kw):
    return tk.Label(parent, text=text, font=font, fg=fg, bg=bg, **kw)


def _card(parent, **kw):
    return tk.Frame(parent, bg=BG2, relief="flat", bd=0, **kw)


def _sep(parent):
    return tk.Frame(parent, bg=BORDER, height=1)


class StatusDot(tk.Canvas):
    def __init__(self, parent, size=12, bg=BG2):
        super().__init__(parent, width=size, height=size, bg=bg, highlightthickness=0)
        self._dot = self.create_oval(2, 2, size - 2, size - 2, fill=FG3, outline="")

    def set(self, color):
        self.itemconfig(self._dot, fill=color)


# ── main window ─────────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Downloads Sorter")
        self.configure(bg=BG)
        self.minsize(900, 620)
        self.geometry("1000x700")
        self.cfg: Config = load_config()
        self._vars: dict[str, tk.Variable] = {}
        self._build()
        self._refresh_service()
        self._refresh_data()
        self.after(5000, self._tick)

    # ── layout ──────────────────────────────────────────────────────────────────

    def _build(self):
        header = tk.Frame(self, bg=BG2, pady=12, padx=20)
        header.pack(fill="x")
        _label(header, "Downloads Sorter", font=FONT_HEAD, bg=BG2).pack(side="left")
        _label(header, "  sorts new downloads by file type", font=FONT_BADGE,
               fg=FG3, bg=BG2).pack(side="left", pady=(4, 0))
        self._svc_dot = StatusDot(header)
        self._svc_dot.pack(side="right", padx=(0, 6))
        self._svc_lbl = _label(header, "—", font=FONT_BADGE, fg=FG3, bg=BG2)
        self._svc_lbl.pack(side="right")
        _sep(self).pack(fill="x")

        self._stats = self._build_stats()
        _sep(self).pack(fill="x")

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Dark.TNotebook", background=BG, borderwidth=0)
        style.configure("Dark.TNotebook.Tab", background=BG2, foreground=FG3,
                        padding=[18, 8], font=FONT_BADGE)
        style.map("Dark.TNotebook.Tab", background=[("selected", BG)],
                  foreground=[("selected", FG)])
        nb = ttk.Notebook(self, style="Dark.TNotebook")
        nb.pack(fill="both", expand=True)

        ctrl = tk.Frame(nb, bg=BG); nb.add(ctrl, text="  Control  ")
        self._build_control(ctrl)
        hist = tk.Frame(nb, bg=BG); nb.add(hist, text="  History  ")
        self._build_history(hist)
        sett = tk.Frame(nb, bg=BG); nb.add(sett, text="  Settings  ")
        self._build_settings(sett)
        nb.bind("<<NotebookTabChanged>>", lambda e: self._refresh_data())

    def _build_stats(self):
        bar = tk.Frame(self, bg=BG2)
        bar.pack(fill="x")
        self._stat_lbls = {}
        for key, label, color in [("total", "Total Sorted", ACCENT),
                                  ("today", "Today", ACCENT2),
                                  ("dupes", "Duplicates", WARN)]:
            c = _card(bar, padx=20, pady=14)
            c.pack(side="left", expand=True, fill="both", padx=(0, 1))
            self._stat_lbls[key] = _label(c, "—", font=FONT_MED, fg=color, bg=BG2)
            self._stat_lbls[key].pack()
            _label(c, label, font=FONT_BADGE, fg=FG3, bg=BG2).pack()
        return bar

    def _build_control(self, parent):
        left = tk.Frame(parent, bg=BG, width=300)
        right = tk.Frame(parent, bg=BG)
        left.pack(side="left", fill="y", padx=(16, 0), pady=14)
        right.pack(side="left", fill="both", expand=True, padx=16, pady=14)
        left.pack_propagate(False)

        # Service card
        c1 = _card(left, padx=16, pady=14); c1.pack(fill="x", pady=(0, 10))
        _label(c1, "BACKGROUND SERVICE", font=FONT_BADGE, fg=FG3, bg=BG2).pack(anchor="w")
        _sep(c1).pack(fill="x", pady=8)
        self._start_btn = _btn(c1, "▶  Start", self._start, color=SUCCESS, fg="#000")
        self._start_btn.pack(fill="x", pady=(0, 6))
        self._stop_btn = _btn(c1, "■  Stop", self._stop, color=BG3, fg=FG2)
        self._stop_btn.pack(fill="x")
        self._vars["enabled"] = tk.BooleanVar()
        tk.Checkbutton(c1, text="Start automatically on login",
                       variable=self._vars["enabled"], command=self._toggle_enabled,
                       bg=BG2, fg=FG2, activebackground=BG2, selectcolor=BG3,
                       font=FONT_BADGE).pack(anchor="w", pady=(10, 0))
        self._install_hint = _label(c1, "", font=FONT_BADGE, fg=WARN, bg=BG2,
                                    wraplength=240, justify="left")
        self._install_hint.pack(anchor="w", pady=(6, 0))

        # One-shot card
        c2 = _card(left, padx=16, pady=14); c2.pack(fill="x", pady=(0, 10))
        _label(c2, "MANUAL SORT", font=FONT_BADGE, fg=FG3, bg=BG2).pack(anchor="w")
        _sep(c2).pack(fill="x", pady=8)
        _label(c2, "Sort whatever is loose in\nyour Downloads folder now.",
               font=FONT_SUB, fg=FG2, bg=BG2, justify="left").pack(anchor="w", pady=(0, 8))
        self._vars["dry_run"] = tk.BooleanVar(value=self.cfg.dry_run)
        tk.Checkbutton(c2, text="Dry-run (preview only)", variable=self._vars["dry_run"],
                       bg=BG2, fg=FG2, activebackground=BG2, selectcolor=BG3,
                       font=FONT_BADGE).pack(anchor="w", pady=(0, 6))
        _btn(c2, "Sort Existing Now", self._sort_once, color=ACCENT).pack(fill="x")

        # Folders card
        c3 = _card(left, padx=16, pady=14); c3.pack(fill="x")
        _label(c3, "OPEN", font=FONT_BADGE, fg=FG3, bg=BG2).pack(anchor="w")
        _sep(c3).pack(fill="x", pady=8)
        _btn(c3, "📁  Downloads", lambda: self._open(self.cfg.downloads_dir),
             color=BG3, fg=FG2).pack(fill="x", pady=(0, 6))
        _btn(c3, "📋  Service Log", self._show_log, color=BG3, fg=FG2).pack(fill="x")

        # Log panel
        _label(right, "ACTIVITY", font=FONT_BADGE, fg=FG3).pack(anchor="w", pady=(0, 4))
        wrap = tk.Frame(right, bg=BORDER, padx=1, pady=1); wrap.pack(fill="both", expand=True)
        self._log = tk.Text(wrap, bg=BG3, fg=FG2, font=FONT_MONO, relief="flat",
                            bd=0, wrap="word", padx=10, pady=8, state="disabled")
        sb = tk.Scrollbar(wrap, command=self._log.yview, width=8)
        self._log.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y"); self._log.pack(fill="both", expand=True)

    def _build_history(self, parent):
        frame = tk.Frame(parent, bg=BG); frame.pack(fill="both", expand=True, padx=16, pady=14)
        hdr = tk.Frame(frame, bg=BG); hdr.pack(fill="x", pady=(0, 6))
        _label(hdr, "MOVE HISTORY", font=FONT_BADGE, fg=FG3).pack(side="left")
        _btn(hdr, "↻ Refresh", self._refresh_data, color=BG3, fg=FG2,
             font=FONT_BADGE).pack(side="right", padx=(4, 0))
        _btn(hdr, "↩ Undo Selected", self._undo_selected, color=WARN, fg="#000",
             font=FONT_BADGE).pack(side="right")

        style = ttk.Style()
        style.configure("Dark.Treeview", background=BG3, foreground=FG2,
                        fieldbackground=BG3, rowheight=24, font=FONT_MONO, borderwidth=0)
        style.configure("Dark.Treeview.Heading", background=BG2, foreground=FG3,
                        font=FONT_BADGE, relief="flat")
        style.map("Dark.Treeview", background=[("selected", ACCENT)],
                  foreground=[("selected", FG)])
        wrap = tk.Frame(frame, bg=BORDER, padx=1, pady=1); wrap.pack(fill="both", expand=True)
        cols = ("time", "type", "name", "to")
        self._tree = ttk.Treeview(wrap, columns=cols, show="headings",
                                  style="Dark.Treeview", selectmode="extended")
        for c, t, w in [("time", "Time", 150), ("type", "Type", 80),
                        ("name", "File", 240), ("to", "Sorted to", 300)]:
            self._tree.heading(c, text=t); self._tree.column(c, width=w)
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side="left", fill="both", expand=True); vsb.pack(side="right", fill="y")
        self._rows: list[list[str]] = []

    def _build_settings(self, parent):
        wrap = tk.Frame(parent, bg=BG, padx=30, pady=24); wrap.pack(fill="both", expand=True)
        _label(wrap, "SETTINGS", font=FONT_BADGE, fg=FG3).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))

        def add_path(r, label, attr):
            _label(wrap, label, fg=FG2).grid(row=r, column=0, sticky="w", pady=4, padx=(0, 12))
            var = tk.StringVar(value=getattr(self.cfg, attr)); self._vars[attr] = var
            e = tk.Entry(wrap, textvariable=var, bg=BG3, fg=FG, insertbackground=FG,
                         relief="flat", bd=0, font=FONT_BODY, width=40,
                         highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT)
            e.grid(row=r, column=1, sticky="ew", pady=4)
            _btn(wrap, "Browse", lambda: self._browse(var), color=BG3, fg=FG2,
                 font=FONT_BADGE).grid(row=r, column=2, padx=(6, 0))

        add_path(1, "Downloads folder", "downloads_dir")
        add_path(2, "Home folder", "home_dir")

        _label(wrap, "Sorted subfolder (blank = directly in Downloads)", fg=FG2).grid(
            row=3, column=0, sticky="w", pady=4, padx=(0, 12))
        self._vars["sorted_subfolder"] = tk.StringVar(value=self.cfg.sorted_subfolder)
        tk.Entry(wrap, textvariable=self._vars["sorted_subfolder"], bg=BG3, fg=FG,
                 insertbackground=FG, relief="flat", bd=0, font=FONT_BODY, width=40,
                 highlightthickness=1, highlightbackground=BORDER).grid(
            row=3, column=1, sticky="ew", pady=4)

        checks = [("watch_home", "Watch home folder for new downloads"),
                  ("notifications", "Show desktop notifications"),
                  ("sort_existing_on_start", "Sort existing Downloads when service starts")]
        for i, (attr, text) in enumerate(checks, start=4):
            self._vars[attr] = tk.BooleanVar(value=getattr(self.cfg, attr))
            tk.Checkbutton(wrap, text=text, variable=self._vars[attr], bg=BG, fg=FG2,
                           activebackground=BG, selectcolor=BG3, font=FONT_BODY).grid(
                row=i, column=0, columnspan=3, sticky="w", pady=3)

        _label(wrap, "On duplicate", fg=FG2).grid(row=7, column=0, sticky="w", pady=4)
        self._vars["on_duplicate"] = tk.StringVar(value=self.cfg.on_duplicate)
        ttk.Combobox(wrap, textvariable=self._vars["on_duplicate"], state="readonly",
                     values=["move", "skip", "delete"], width=12).grid(
            row=7, column=1, sticky="w", pady=4)

        _btn(wrap, "Save Settings", self._save_settings, color=SUCCESS, fg="#000").grid(
            row=8, column=0, columnspan=3, sticky="w", pady=(16, 0))
        _label(wrap, f"Config: {CONFIG_PATH}", font=FONT_BADGE, fg=FG3).grid(
            row=9, column=0, columnspan=3, sticky="w", pady=(10, 0))
        wrap.columnconfigure(1, weight=1)

    # ── actions ─────────────────────────────────────────────────────────────────

    def _log_msg(self, msg: str):
        self._log.config(state="normal")
        self._log.insert("end", f"[{datetime.now():%H:%M:%S}] {msg}\n")
        self._log.see("end"); self._log.config(state="disabled")

    def _start(self):
        if not service_installed():
            self._log_msg("Service not installed — run packaging/install.sh first.")
            return
        r = _systemctl("start", SERVICE)
        self._log_msg("Service started." if r.returncode == 0 else f"Start failed: {r.stderr.strip()}")
        self._refresh_service()

    def _stop(self):
        r = _systemctl("stop", SERVICE)
        self._log_msg("Service stopped." if r.returncode == 0 else f"Stop failed: {r.stderr.strip()}")
        self._refresh_service()

    def _toggle_enabled(self):
        want = self._vars["enabled"].get()
        r = _systemctl("enable" if want else "disable", SERVICE)
        self._log_msg(("Enabled on login." if want else "Disabled on login.")
                      if r.returncode == 0 else f"Failed: {r.stderr.strip()}")
        self._refresh_service()

    def _sort_once(self):
        self._log_msg("Sorting existing Downloads…")
        args = [sys.executable, "-m", "downloads_sorter", "--once"]
        if self._vars["dry_run"].get():
            args.append("--dry-run")

        def run():
            try:
                proc = subprocess.Popen(args, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True, bufsize=1)
                for line in proc.stdout:
                    self.after(0, self._log_msg, line.rstrip())
                proc.wait()
                self.after(0, self._refresh_data)
            except Exception as e:  # noqa: BLE001 - surface any failure in the log
                self.after(0, self._log_msg, f"Error: {e}")
        threading.Thread(target=run, daemon=True).start()

    def _show_log(self):
        r = subprocess.run(["journalctl", "--user", "-u", SERVICE, "-n", "40",
                            "--no-pager"], capture_output=True, text=True)
        for line in (r.stdout or "No service log yet.").splitlines()[-40:]:
            self._log_msg(line)

    def _open(self, path: str):
        try:
            subprocess.Popen(["xdg-open", path])
        except OSError as e:
            self._log_msg(f"Cannot open: {e}")

    def _browse(self, var: tk.StringVar):
        path = filedialog.askdirectory(initialdir=var.get() or str(Path.home()))
        if path:
            var.set(path)

    def _save_settings(self):
        for attr in ("downloads_dir", "home_dir", "sorted_subfolder", "on_duplicate"):
            setattr(self.cfg, attr, self._vars[attr].get())
        for attr in ("watch_home", "notifications", "sort_existing_on_start"):
            setattr(self.cfg, attr, bool(self._vars[attr].get()))
        save_config(self.cfg)
        self._log_msg(f"Saved to {CONFIG_PATH}")
        if service_active():
            _systemctl("restart", SERVICE)
            self._log_msg("Service restarted to apply changes.")

    def _undo_selected(self):
        sel = self._tree.selection()
        if not sel:
            messagebox.showinfo("Undo", "Select one or more rows first.")
            return
        # Tree iids are indices into reversed(self._rows); map back to log rows.
        n = len(self._rows)
        targets = [self._rows[n - 1 - int(iid)] for iid in sel]
        targets = [r for r in targets if r[1] == "MOVED"]
        if not targets:
            messagebox.showinfo("Undo", "Only MOVED rows can be undone.")
            return
        if not messagebox.askyesno("Confirm", f"Restore {len(targets)} file(s)?"):
            return
        for line in undo_rows(targets):
            self._log_msg(line)
        self._refresh_data()

    # ── refresh ─────────────────────────────────────────────────────────────────

    def _refresh_service(self):
        installed = service_installed()
        active = service_active() if installed else False
        self._svc_dot.set(SUCCESS if active else (WARN if installed else DANGER))
        self._svc_lbl.config(
            text="Service running" if active else
            ("Service stopped" if installed else "Service not installed"),
            fg=SUCCESS if active else (FG3 if installed else DANGER))
        self._start_btn.config(state="disabled" if active else "normal")
        self._stop_btn.config(state="normal" if active else "disabled")
        if installed:
            self._vars["enabled"].set(service_enabled())
            self._install_hint.config(text="")
        else:
            self._install_hint.config(text="Run packaging/install.sh to enable the service.")

    def _refresh_data(self):
        self._rows = read_moves()
        # stats
        today = datetime.now().strftime("%Y-%m-%d")
        total = sum(1 for r in self._rows if r[1] == "MOVED")
        td = sum(1 for r in self._rows if r[1] == "MOVED" and r[0].startswith(today))
        dupes = sum(1 for r in self._rows if "Duplicates" in r[3])
        self._stat_lbls["total"].config(text=str(total))
        self._stat_lbls["today"].config(text=str(td))
        self._stat_lbls["dupes"].config(text=str(dupes))
        # history table (newest first)
        if hasattr(self, "_tree"):
            self._tree.delete(*self._tree.get_children())
            home = str(Path.home())
            for i, (ts, mode, src, dst) in enumerate(reversed(self._rows)):
                self._tree.insert("", "end", iid=str(i), values=(
                    ts, mode, Path(src).name, dst.replace(home, "~")))

    def _tick(self):
        self._refresh_service()
        self.after(5000, self._tick)


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
