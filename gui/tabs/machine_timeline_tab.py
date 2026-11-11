"""
machine_timeline_tab.py
"Machine Timeline": an OrgaTEX-style Gantt of the dyeing machines.

  * one row per machine, one rectangle per colour, text "codice - colore - bagno";
  * the rectangle takes the colour of the batch (Produzione, column ``Color RGB``);
  * the RED LINE is "now" and never moves on screen: the time scrolls under it, to
    the left.  Everything left of it is finished (faded + check mark), what is
    running has a green frame, everything to the right is still to come;
  * hovering a rectangle shows all its data (no click needed);
  * clicking a machine name opens that machine's table (same window as the
    Overview's "Copertura macchine" cards);
  * the page only works once BOTH files are uploaded (the PRODUZIONE and COPERTURA
    buttons): Copertura gives every colour's machine, start and length, Produzione
    its dye colour;
  * the search box finds a colour, scrolls to it if needed, flashes it and puts the
    mouse pointer on it -- nothing is opened or hidden.  Not found -> a message.

Drag with the mouse (or the wheel / arrow keys) to look at another time, the
"Now" button goes back; Ctrl+wheel zooms.
"""
from __future__ import annotations

import threading
import tkinter as tk
from bisect import bisect_right
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

import pandas as pd

import calculate.situazione as business_logic
from calculate import machine_timeline as timeline
from utility.ui_thread import post_to_ui
from utility.utils import logger

# Order and wording of the fields shown in the hover card.
_FIELD_LABELS = {
    "cliente": "Cliente", "articolo": "Articolo", "titolo": "Titolo", "codice": "Codice",
    "colore": "Colore", "ordine": "Ordine", "riga": "Riga", "partita": "Partita",
    "rocche": "Rocche", "mc": "M/C", "data": "Data", "consegna": "Consegna",
    "delivery_date": "Delivery Date", "bagno": "Bagno", "cq": "C.Q", "tinto": "Tinto",
    "planedate": "PlaneDate", "data_qualita": "Data Qualità", "data_uscita": "Data Uscita",
    "prezzo": "Prezzo Ord.", "prezzo_lisini": "Prezzo Listini", "comment": "Commento",
    "raw_yarn_match": "Filato Disponibile", "days_to_delivery": "Giorni alla consegna",
}
_STATUS_TEXT = {"done": "Finished", "running": "On the machine now", "queued": "Queued"}
_MAX_ROWS_IN_TIP = 4


def _fmt(value) -> str:
    """Cell text for the hover card: blank for missing values, dates as dd/mm/yyyy."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.strftime("%d/%m/%Y") if (value.hour, value.minute) == (0, 0) else value.strftime("%d/%m/%Y %H:%M")
    text = str(value).strip()
    return text[:-2] if text.endswith(".0") and text[:-2].isdigit() else text


class MachineTimelineTab(ttk.Frame):
    LABEL_W = 150            # machine-name column
    ROW_H = 54
    HEADER_H = 58
    RED_FRACTION = 0.30      # where the red line sits, as a share of the chart width
    ZOOMS = {"25%": 15, "50%": 30, "75%": 45, "100%": 60, "150%": 90}   # pixels per hour
    TICK_MS = 20_000         # redraw (time moves) / look for new data

    def __init__(self, parent, situazione_tab, open_machine_schedule=None):
        super().__init__(parent)
        self.situazione_tab = situazione_tab
        self._open_machine_schedule = open_machine_schedule
        self._machines = timeline.all_machines()
        self._machine_state: dict[int, tuple[str, int]] = {}      # machine -> (state, colours still to dye)
        self._label_state = None
        self._row_height = self.ROW_H
        self._blocks = pd.DataFrame(columns=timeline.BLOCK_COLUMNS)
        self._rects: list[tuple[float, float, float, float, int]] = []
        self._pinned_left: datetime | None = None       # None = live (red line fixed)
        self._pph = self.ZOOMS["50%"]
        self._tip: tk.Toplevel | None = None
        self._tip_label: tk.Text | None = None
        self._hover_pos: int | None = None
        self._pointer: tuple[int, int] | None = None
        self._drag: tuple[int, datetime] | None = None
        self._highlight: int | None = None
        self._flash_on = False
        self._last_term = ""
        self._hit_index = -1
        self._colors_df: pd.DataFrame | None = None
        self._colors_key = None
        self._colors_error = ""
        self._signature = None
        self._tick_id = None
        self._machine_rows = {machine: row for row, machine in enumerate(self._machines)}
        self._block_index = {}
        self._sorted_starts: list[datetime] = []
        self._sorted_ends: list[datetime] = []

        self._font = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self._font_bold = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self._build_ui()
        self.bind("<Destroy>", self._on_destroy, add="+")
        self._schedule_tick()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        self.columnconfigure(1, weight=1)
        self.rowconfigure(2, weight=1)

        bar = ttk.Frame(self, padding=(8, 4))
        bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        # Search / Zoom / Refresh on the left, the files frame beside them on the right, all on one row.
        # _fit_top_row() measures both and squeezes the buttons until they fit the window; only when even
        # the tightest sizes do not fit does the files frame drop under the buttons (nothing is ever cut).
        bar.columnconfigure(1, weight=1)
        self._bar = bar
        self._fit_job = None
        self._fit_width = None
        controls = ttk.Frame(bar)
        controls.grid(row=0, column=0, sticky="w")
        self._controls = controls
        self._search_label = ttk.Label(controls, text="Search:")
        self._search_label.grid(row=0, column=0, padx=(0, 3))
        self._search_var = tk.StringVar()
        entry = ttk.Entry(controls, textvariable=self._search_var, width=18)
        self._search_entry = entry
        entry.grid(row=0, column=1, padx=(0, 4))
        entry.bind("<Return>", lambda _e: self._search())
        ttk.Button(controls, text="🔍 Find", command=self._search).grid(row=0, column=2, padx=2)
        ttk.Button(controls, text="Clear", command=self._clear_search).grid(row=0, column=3, padx=2)
        ttk.Button(controls, text="⟲ Now", command=self._go_now).grid(row=0, column=4, padx=2)
        self._zoom_label = ttk.Label(controls, text="Zoom:")
        self._zoom_label.grid(row=0, column=5, padx=(6, 2))
        self._zoom_var = tk.StringVar(value="50%")
        zoom = ttk.Combobox(controls, textvariable=self._zoom_var, values=list(self.ZOOMS), width=5, state="readonly")
        zoom.grid(row=0, column=6, padx=(0, 5))
        zoom.bind("<<ComboboxSelected>>", lambda _e: self._set_zoom(self._zoom_var.get()))
        self._refresh_button = ttk.Button(controls, text="↻ Refresh", command=lambda: self.refresh_data(force=True))
        self._refresh_button.grid(row=0, column=8, padx=(4, 0))

        self._file_area = ttk.Frame(bar)
        self._place_files_beside()
        self._file_frame = ttk.LabelFrame(self._file_area, text="Timeline files", padding=(4, 1))
        self._file_frame.grid(row=0, column=0, sticky="w")
        self._file_buttons = ttk.Frame(self._file_frame)
        self._file_buttons.pack(side="left")
        ttk.Button(self._file_buttons, text="PRODUZIONE", command=self._choose_produzione).pack(side="left", padx=(0, 2))
        self._prod_state = ttk.Label(self._file_buttons, text="✖", foreground="#dc2626", font=("Segoe UI", 10, "bold"))
        self._prod_state.pack(side="left")
        ttk.Button(self._file_buttons, text="COPERTURA", command=self._choose_copertura).pack(side="left", padx=(8, 2))
        self._cop_state = ttk.Label(self._file_buttons, text="✖", foreground="#dc2626", font=("Segoe UI", 10, "bold"))
        self._cop_state.pack(side="left")
        bar.bind("<Configure>", self._schedule_fit, add="+")

        corner = tk.Canvas(self, width=self.LABEL_W, height=self.HEADER_H, bg="#e9eef5", highlightthickness=0)
        corner.grid(row=1, column=0, sticky="nsew")
        corner.create_text(self.LABEL_W / 2, self.HEADER_H / 2, text="Machine", font=self._font_bold, fill="#25364d")
        self._header = tk.Canvas(self, height=self.HEADER_H, bg="#e9eef5", highlightthickness=0)
        self._header.grid(row=1, column=1, sticky="ew")

        self._labels = tk.Canvas(self, width=self.LABEL_W, bg="#f8fafc", highlightthickness=0)
        self._labels.grid(row=2, column=0, sticky="ns")
        self._main = tk.Canvas(self, bg="#ffffff", highlightthickness=0, cursor="arrow")
        self._main.grid(row=2, column=1, sticky="nsew")

        status_row = ttk.Frame(self)
        status_row.grid(row=3, column=0, columnspan=2, sticky="ew")
        status_row.columnconfigure(0, weight=1)
        self._status = ttk.Label(status_row, text="", anchor="w", justify="left", padding=(8, 3))
        self._status.grid(row=0, column=0, sticky="ew")
        self._legend = ttk.Label(status_row, text="✔ done   ▶ running   red = no colours   grey = colour not in Produzione",
                                 foreground="#475467", padding=(8, 3))
        self._legend.grid(row=0, column=1, sticky="e")
        # a long message wraps onto a second line instead of running under the legend
        status_row.bind("<Configure>", lambda e: self._status.configure(
            wraplength=max(220, e.width - self._legend.winfo_reqwidth() - 24)), add="+")

        self._main.bind("<Configure>", lambda _e: self._draw())
        self._main.bind("<Motion>", self._on_motion)
        self._main.bind("<Leave>", lambda _e: self._hide_tip())
        self._main.bind("<ButtonPress-1>", self._on_press)
        self._main.bind("<B1-Motion>", self._on_drag)
        self._main.bind("<ButtonRelease-1>", lambda _e: setattr(self, "_drag", None))
        self._main.bind("<MouseWheel>", self._on_wheel)
        self._main.bind("<Left>", lambda _e: self._shift_hours(-3))
        self._main.bind("<Right>", lambda _e: self._shift_hours(3))
        self._main.bind("<Enter>", lambda _e: self._main.focus_set())
        self._draw_labels()

    def _compute_machine_state(self, now: datetime) -> dict[int, tuple[str, int]]:
        """'finished' = everything queued on the machine is already dyed; 'working' = something left;
        'empty' = nothing on the machine in Copertura."""
        state = {machine: ("empty", 0) for machine in self._machines}
        for machine, (entries, _starts, _prefix_ends, sorted_ends) in self._block_index.items():
            left = len(entries) - bisect_right(sorted_ends, now)
            state[machine] = ("working" if left else "finished", left)
        return state

    def _index_blocks(self) -> None:
        """Index sorted intervals once so each redraw visits only visible batches."""
        grouped = {}
        starts, ends = [], []
        for position, block in enumerate(self._blocks.itertuples(index=False)):
            grouped.setdefault(int(block.machine), []).append((position, block))
            starts.append(block.start)
            ends.append(block.end)

        self._block_index = {}
        for machine, entries in grouped.items():
            entries.sort(key=lambda item: item[1].start)
            block_starts = [block.start for _position, block in entries]
            prefix_ends = []
            furthest_end = None
            for _position, block in entries:
                furthest_end = block.end if furthest_end is None else max(furthest_end, block.end)
                prefix_ends.append(furthest_end)
            self._block_index[machine] = (
                entries, block_starts, prefix_ends, sorted(block.end for _position, block in entries),
            )
        self._sorted_starts = sorted(starts)
        self._sorted_ends = sorted(ends)

    def _draw_labels(self) -> None:
        """Machine names as raised buttons; a machine that has dyed everything on it turns red."""
        canvas = self._labels
        canvas.delete("all")
        row_height = self._row_height
        for index, machine in enumerate(self._machines):
            y1, y2 = index * row_height, (index + 1) * row_height
            state, left = self._machine_state.get(machine, ("empty", 0))
            if state == "empty":
                fill, edge, text, sub_text, sub = "#dc2626", "#7f1d1d", "#ffffff", "#ffe4e6", "no colours"
            elif state == "working":
                fill, edge, text, sub_text, sub = "#dbeafe", "#1e3a8a", "#16324f", "#334155", f"{left} to dye"
            else:
                fill, edge, text, sub_text, sub = "#e2e8f0", "#64748b", "#334155", "#475467", "✔ finished"
            tag = f"machine{machine}"
            padding = max(2, min(6, row_height // 9))
            x1, x2, top, bottom = 5, self.LABEL_W - 7, y1 + padding, y2 - padding
            canvas.create_rectangle(x1 + 3, top + 3, x2 + 3, bottom + 3, fill="#c4c9d2", outline="", tags=(tag,))
            canvas.create_rectangle(x1, top, x2, bottom, fill=fill, outline=edge, width=2, tags=(tag, f"{tag}bg"))
            canvas.create_line(x1 + 2, top + 2, x2 - 2, top + 2, fill="#ffffff" if state != "empty" else "#f87171", tags=(tag,))
            center = (top + bottom) / 2
            main_size = max(8, min(11, round(row_height * 0.24)))
            sub_size = max(7, min(9, round(row_height * 0.20)))
            canvas.create_text(x1 + 9, center - row_height * 0.21, text=timeline.machine_row_label(machine), anchor="w",
                               font=("Segoe UI", main_size, "bold"), fill=text, tags=(tag,))
            canvas.create_text(x1 + 9, center + row_height * 0.21, text=sub, anchor="w",
                               font=("Segoe UI", sub_size, "bold"), fill=sub_text, tags=(tag,))
            canvas.create_text(x2 - 8, (top + bottom) / 2, text="▸", anchor="e", fill=sub_text, tags=(tag,))
            canvas.tag_bind(tag, "<Button-1>", lambda _e, m=machine: self._open_machine(m))
            canvas.tag_bind(tag, "<Enter>", lambda _e: canvas.configure(cursor="hand2"))
            canvas.tag_bind(tag, "<Leave>", lambda _e: canvas.configure(cursor=""))

    @classmethod
    def _fit_row_height(cls, available_height: int, machine_count: int) -> int:
        if machine_count <= 0 or available_height < 50:      # not laid out yet (height 1): keep the normal rows
            return cls.ROW_H
        return max(1, min(cls.ROW_H, available_height // machine_count))

    # ------------------------------------------------------------- time <-> x
    def _width(self) -> int:
        return max(self._main.winfo_width(), 200)

    def _left_time(self, now: datetime, width: int) -> datetime:
        """Time at the left edge. Live: the red line stays at RED_FRACTION of the width."""
        if self._pinned_left is not None:
            return self._pinned_left
        return now - timedelta(hours=self.RED_FRACTION * width / self._pph)

    def _x(self, moment: datetime, left: datetime) -> float:
        return (moment - left).total_seconds() / 3600.0 * self._pph

    # --------------------------------------------------------------- drawing
    def _draw(self) -> None:
        if not self.winfo_exists():
            return
        now = datetime.now()
        width = self._width()
        available_height = self._main.winfo_height()
        row_height = self._fit_row_height(available_height, len(self._machines))
        if row_height != self._row_height:
            self._row_height = row_height
            self._label_state = None
        height = len(self._machines) * row_height
        self._labels.configure(height=max(height, 1))
        left = self._left_time(now, width)
        main, header = self._main, self._header
        main.delete("all")
        header.delete("all")
        main.configure(scrollregion=(0, 0, width, height))
        self._rects = []
        self._update_file_states()
        if not self._ready():
            self._draw_waiting(width, height)
            self._update_status(now)
            return

        state = self._compute_machine_state(now)
        if state != self._machine_state or self._label_state is None:
            self._machine_state = state
            self._label_state = True
            self._draw_labels()

        x_now = self._x(now, left)
        if x_now > 0:                                                    # the past, slightly tinted
            main.create_rectangle(0, 0, min(x_now, width), height, fill="#f3f4f6", outline="")
        for index, machine in enumerate(self._machines):             # red row: no colours; grey row: all dyed
            kind = self._machine_state.get(machine, ("", 0))[0]
            if kind in ("empty", "finished"):
                main.create_rectangle(0, index * row_height, width, (index + 1) * row_height,
                                      fill="#fee2e2" if kind == "empty" else "#e5e7eb", outline="")
        for index in range(len(self._machines) + 1):
            main.create_line(0, index * row_height, width, index * row_height, fill="#d0d5dd")

        # grid + time scale: a label every `step` hours, a date at each midnight
        step = next((s for s in (1, 2, 3, 4, 6, 12, 24) if s * self._pph >= 58), 24)
        first = left.replace(minute=0, second=0, microsecond=0)
        first -= timedelta(hours=first.hour % step)
        moment = first
        end_view = left + timedelta(hours=width / self._pph)
        while moment <= end_view:
            x = self._x(moment, left)
            midnight = moment.hour == 0
            main.create_line(x, 0, x, height, fill="#98a2b3" if midnight else "#e4e7ec")
            header.create_line(x, self.HEADER_H - 12, x, self.HEADER_H, fill="#667085")
            header.create_text(x + 3, self.HEADER_H - 14, text=moment.strftime("%H:%M"), anchor="sw",
                               font=self._font, fill="#25364d")
            if midnight or moment == first:
                header.create_text(x + 3, 3, text=moment.strftime("%a %d.%m"), anchor="nw",
                                   font=self._font_bold, fill="#16324f")
            moment += timedelta(hours=step)

        # the colours
        view_start = left - timedelta(hours=5 / self._pph)
        view_end = end_view + timedelta(hours=5 / self._pph)
        for machine, (entries, starts, prefix_ends, _sorted_ends) in self._block_index.items():
            row = self._machine_rows.get(machine)
            if row is None:
                continue
            first = bisect_right(prefix_ends, view_start)
            last = bisect_right(starts, view_end)
            for pos, block in entries[first:last]:
                if block.end < view_start:
                    continue
                x1, x2 = self._x(block.start, left), self._x(block.end, left)
                self._draw_block(pos, block, row, x1, x2, width, now)

        # the red line: always "now"
        if 0 <= x_now <= width:
            main.create_line(x_now, 0, x_now, height, fill="#dc2626", width=2, tags="redline")
            header.create_line(x_now, 0, x_now, self.HEADER_H, fill="#dc2626", width=2)
        self._update_status(now)
        self._refresh_hover()

    def _draw_block(self, pos: int, block, row: int, x1: float, x2: float, width: int, now: datetime) -> None:
        """One colour as a raised tile: a small gap on both sides (neighbours never merge), a dark
        outline, a light top edge and a drop shadow, so even two nearly identical colours stay apart."""
        main = self._main
        row_height = self._row_height
        top, bottom = row * row_height + max(3, row_height // 10), (row + 1) * row_height - max(4, row_height // 7)
        x1, x2 = x1 + 2, x2 - 2                                          # the gap between neighbours
        if x2 - x1 < 3:
            x2 = x1 + 3
        status = timeline.block_status(block.start, block.end, now)
        fill, text_color = block.rgb, timeline.text_color_for(block.rgb)
        outline, outline_w, dash, prefix = timeline.darker(block.rgb, 0.5), 2, None, ""
        if status == "done":
            fill = timeline.blend(block.rgb, "#ffffff", 0.55)
            text_color, outline, outline_w, dash, prefix = "#475467", "#667085", 1, (4, 2), "✔ "
        elif status == "running":
            outline, outline_w, prefix = "#15803d", 3, "▶ "
        is_late = bool(block.late)
        if is_late:
            outline, outline_w, dash = "#dc2626", 3, None
        if pos == self._highlight:
            outline, outline_w, dash = ("#f97316" if self._flash_on else "#c2410c"), 4, None
        if status != "done":
            main.create_rectangle(x1 + 3, top + 3, x2 + 3, bottom + 3, fill="#c4c9d2", outline="")   # shadow
        main.create_rectangle(x1, top, x2, bottom, fill=fill, outline=outline, width=outline_w, dash=dash)
        warning_badge = is_late and x2 - x1 >= 18
        if warning_badge:
            badge_x, badge_y = x2 - 8, top + 8
            main.create_oval(badge_x - 6, badge_y - 6, badge_x + 6, badge_y + 6,
                             fill="#dc2626", outline="#ffffff", width=1)
            main.create_text(badge_x, badge_y, text="!", fill="#ffffff", font=("Segoe UI", 8, "bold"))
        if status != "done" and x2 - x1 > 8:
            main.create_line(x1 + 2, top + 2, x2 - 2, top + 2, fill=timeline.blend(block.rgb, "#ffffff", 0.6))
            main.create_line(x1 + 2, bottom - 2, x2 - 2, bottom - 2, fill=timeline.darker(block.rgb, 0.25))
        text_x = max(x1, 0) + 7
        room = min(x2, width) - text_x - 5
        if warning_badge:
            room -= 14
        if room > 28:
            main.create_text(text_x, (top + bottom) / 2, anchor="w",
                             font=self._font_bold,
                             text=self._fit(prefix + (block.label or block.bagno), room), fill=text_color)
        self._rects.append((x1, top, x2, bottom, pos))

    def _draw_waiting(self, width: int, height: int) -> None:
        """Nothing is drawn until both files are in: say which one is missing."""
        prod_ok = self._colors_df is not None and not self._colors_df.empty
        cop_ok = self._copertura_ok()
        lines = ["Upload both files to build the timeline",
                 "",
                 f"{'✔' if prod_ok else '✖'}  PRODUZIONE   (dye colours)",
                 f"{'✔' if cop_ok else '✖'}  COPERTURA   (machine, start, length of every colour)"]
        if self._colors_error:
            lines += ["", self._colors_error]
        self._main.create_text(width / 2, max(height, 220) / 2 - 10, text="\n".join(lines), justify="center",
                               font=("Segoe UI", 13, "bold"), fill="#475467")

    def _fit(self, text: str, room: float) -> str:
        """Cut *text* with an ellipsis so it fits in *room* pixels."""
        if self._font.measure(text) <= room:
            return text
        while text and self._font.measure(text + "…") > room:
            text = text[:-1]
        return text + "…" if text else ""

    def _copertura_ok(self) -> bool:
        frame = getattr(self.situazione_tab, "loaded_frames", {}).get("copertura")
        return isinstance(frame, pd.DataFrame) and not frame.empty

    def _ready(self) -> bool:
        """The page is built only from COPERTURA + PRODUZIONE together."""
        return self._copertura_ok() and self._colors_df is not None and not self._colors_df.empty

    def _update_file_states(self) -> None:
        for label, ok in ((self._prod_state, self._colors_df is not None and not self._colors_df.empty),
                          (self._cop_state, self._copertura_ok())):
            label.configure(text="✔" if ok else "✖", foreground="#16a34a" if ok else "#dc2626")

    def _update_status(self, now: datetime) -> None:
        blocks = self._blocks
        if not self._ready():
            message = "Waiting for the PRODUZIONE and COPERTURA files (both are needed)."
            if self._colors_error:
                message += "  " + self._colors_error
        elif blocks.empty:
            message = "Copertura has no colour with a machine and a start time."
        else:
            finished = bisect_right(self._sorted_ends, now)
            started = bisect_right(self._sorted_starts, now)
            missing = int((~blocks["has_color"]).sum())
            message = (f"{len(blocks)} colours: {finished} finished, "
                       f"{started - finished} on machines, {len(blocks) - started} queued")
            if missing:
                message += f"  |  {missing} without a Produzione colour (grey)"
            if self._colors_error:
                message += f"  |  {self._colors_error}"
            if self._pinned_left is not None:
                message += "  |  free view — press “Now” to go back"
            unknown = int((~blocks["end_known"]).sum())
            if unknown:
                message += f"  |  {unknown} without a length in Copertura (estimated)"
        self._status.configure(text=message)

    def set_source_bar(self, bar) -> None:
        """Use the program's shared source bar (Copertura, Produzione, Wincoint, DFM) instead of the two own buttons."""
        self._file_frame.grid_remove()
        bar.grid(row=0, column=0, sticky="e")
        self._fit_width = None
        self.after_idle(self._fit_top_row)

    # --------------------------------------------------------- top row fitting
    # (padding added to the text of every button | width of the Search box | show the "Search:" / "Zoom:" captions)
    _DENSITIES = ((None, 18, True), (24, 12, True), (14, 8, False))

    def _place_files_beside(self) -> None:
        self._file_area.grid(row=0, column=1, sticky="e", padx=(12, 0), pady=0)

    def _place_files_below(self) -> None:
        self._file_area.grid(row=1, column=0, columnspan=2, sticky="w", padx=0, pady=(3, 0))

    @staticmethod
    def _squeezable(widget) -> list:
        found = []
        for child in widget.winfo_children():
            if hasattr(child, "set_density"):
                found.append(child)
            found.extend(MachineTimelineTab._squeezable(child))
        return found

    def _apply_density(self, level: int) -> None:
        padding, search_width, captions = self._DENSITIES[level]
        for button in self._squeezable(self._controls) + self._squeezable(self._file_area):
            button.set_density(padding)
        self._search_entry.configure(width=search_width)
        for label in (self._search_label, self._zoom_label):
            if captions:
                label.grid()
            else:
                label.grid_remove()

    def _schedule_fit(self, event=None) -> None:
        if event is not None and (event.widget is not self._bar or event.width == self._fit_width):
            return
        if self._fit_job is not None:
            self.after_cancel(self._fit_job)
        self._fit_job = self.after(30, self._fit_top_row)

    def _fit_top_row(self) -> None:
        """Put the buttons and the files frame on one row, as roomy as the window allows."""
        self._fit_job = None
        available = self._bar.winfo_width()
        if available <= 1 or not self.winfo_exists():
            return
        self._fit_width = available
        self._place_files_beside()
        for level in range(len(self._DENSITIES)):
            self._apply_density(level)
            self._bar.update_idletasks()
            needed = self._controls.winfo_reqwidth() + self._file_area.winfo_reqwidth() + 40
            if needed <= available:
                return
        self._place_files_below()        # even the tightest sizes do not fit: stack them, never cut them

    # ----------------------------------------------------------------- hover
    def _hit(self, x: float, y: float) -> int | None:
        for x1, y1, x2, y2, pos in reversed(self._rects):
            if x1 <= x <= x2 and y1 <= y <= y2:
                return pos
        return None

    def _on_motion(self, event) -> None:
        self._pointer = (event.x, event.y)
        if self._drag is not None:
            return
        pos = self._hit(event.x, event.y)
        if pos is None:
            self._hide_tip()
            return
        if pos != self._hover_pos:
            self._hover_pos = pos
            self._show_tip(pos)
        self._move_tip(event.x_root, event.y_root)

    def _refresh_hover(self) -> None:
        """After a redraw keep the card only if the pointer is still over a colour."""
        if self._pointer is None or self._drag is not None:
            return
        pos = self._hit(*self._pointer)
        if pos is None:
            self._hide_tip()
        elif pos != self._hover_pos:
            self._hover_pos = pos
            self._show_tip(pos)

    def _tooltip_text(self, pos: int) -> str:
        block = self._blocks.iloc[pos]
        now = datetime.now()
        status = timeline.block_status(block["start"], block["end"], now)
        lines = [
            block["label"] or block["bagno"],
            "─" * 34,
            f"Machine : {timeline.machine_row_label(block['machine'])}",
            f"Status  : {_STATUS_TEXT[status]}",
            f"Start   : {block['start']:%d/%m/%Y %H:%M}",
            f"End     : {block['end']:%d/%m/%Y %H:%M}" + ("" if block["end_known"] else "  (estimated)"),
            f"Bagno   : {block['bagno']}",
            f"Colour  : {block['rgb'].upper()}" + ("" if block["has_color"] else "  (not in Produzione)"),
        ]
        rows = block["rows"]
        for index, row in enumerate(rows[:_MAX_ROWS_IN_TIP]):
            lines.append("─" * 34 if index == 0 else "· · ·")
            lines.append(timeline.delivery_delay_text(block.get("planedate"), row))
            for key, label in _FIELD_LABELS.items():
                value = _fmt(row.get(key))
                if key == "planedate":
                    value = _fmt(block.get("planedate")) or value
                if value:
                    lines.append(f"{label:<19}: {value}")
        if len(rows) > _MAX_ROWS_IN_TIP:
            lines.append(f"… +{len(rows) - _MAX_ROWS_IN_TIP} more order rows")
        if not rows:
            lines.append("(this Bagno is not in Situazione Generale)")
            lines.append("RITARDO: unavailable (no matched customer/order details)")
        return "\n".join(lines)

    def _show_tip(self, pos: int) -> None:
        if self._tip is None or not self._tip.winfo_exists():
            self._tip = tk.Toplevel(self)
            self._tip.wm_overrideredirect(True)
            self._tip.attributes("-topmost", True)
            self._tip_label = tk.Text(
                self._tip, wrap="word", bg="#fffbe6", fg="#1f2937", relief="solid",
                borderwidth=1, padx=8, pady=6, font=("Consolas", 9), cursor="arrow",
                takefocus=False, height=1,
            )
            self._tip_label.pack()
            self._tip_label.tag_configure("late", foreground="#dc2626", font=("Consolas", 9, "bold"))
        text = self._tooltip_text(pos)
        self._tip_label.configure(state="normal")
        self._tip_label.delete("1.0", "end")
        self._tip_label.insert("1.0", text)
        for line_number, line in enumerate(text.splitlines(), start=1):
            if line.startswith("RITARDO: late"):
                self._tip_label.tag_add("late", f"{line_number}.0", f"{line_number}.end")
        self._tip_label.configure(height=max(1, len(text.splitlines())), state="disabled")
        self._tip.update_idletasks()
        self._tip.deiconify()

    def _move_tip(self, x_root: int, y_root: int) -> None:
        if self._tip is None or not self._tip.winfo_exists():
            return
        width, height = self._tip.winfo_reqwidth(), self._tip.winfo_reqheight()
        x, y = x_root + 16, y_root + 18
        if x + width > self.winfo_screenwidth():
            x = max(0, x_root - width - 16)
        if y + height > self.winfo_screenheight():
            y = max(0, self.winfo_screenheight() - height - 8)
        self._tip.geometry(f"+{x}+{y}")

    def _hide_tip(self) -> None:
        self._hover_pos = None
        if self._tip is not None and self._tip.winfo_exists():
            self._tip.withdraw()

    # ------------------------------------------------------------ navigation
    def _on_press(self, event) -> None:
        now = datetime.now()
        self._drag = (event.x, self._left_time(now, self._width()))
        self._hide_tip()

    def _on_drag(self, event) -> None:
        if self._drag is None:
            return
        x0, left0 = self._drag
        self._pinned_left = left0 - timedelta(hours=(event.x - x0) / self._pph)
        self._main.configure(cursor="fleur")
        self._draw()

    def _on_wheel(self, event) -> None:
        if event.state & 0x0004:                                         # Ctrl + wheel = zoom
            names = list(self.ZOOMS)
            current = names.index(self._zoom_var.get())
            current = min(len(names) - 1, max(0, current + (1 if event.delta > 0 else -1)))
            self._zoom_var.set(names[current])
            self._set_zoom(names[current])
        else:
            self._shift_hours(-6 if event.delta > 0 else 6)

    def _shift_hours(self, hours: float) -> None:
        self._pinned_left = self._left_time(datetime.now(), self._width()) + timedelta(hours=hours)
        self._draw()

    def _set_zoom(self, name: str) -> None:
        now = datetime.now()
        width = self._width()
        if self._pinned_left is not None:                                # keep the centre of a free view
            centre = self._pinned_left + timedelta(hours=width / self._pph / 2)
        self._pph = self.ZOOMS.get(name, self._pph)
        if self._pinned_left is not None:
            self._pinned_left = centre - timedelta(hours=width / self._pph / 2)
        self._draw()

    def _go_now(self) -> None:
        self._pinned_left = None
        self._main.configure(cursor="arrow")
        self._draw()

    # ---------------------------------------------------------------- search
    def _clear_search(self) -> None:
        self._search_var.set("")
        self._highlight = None
        self._last_term = ""
        self._hit_index = -1
        self._draw()

    def _search(self) -> None:
        term = self._search_var.get().strip()
        if not term:
            return
        if not self._ready() or self._blocks.empty:
            messagebox.showinfo("Search", "Upload the PRODUZIONE and COPERTURA files first.", parent=self)
            return
        hits = timeline.search_blocks(self._blocks, term)
        if not hits:
            self._highlight = None
            self._draw()
            messagebox.showinfo("Search", f"“{term}” was not found on the machines.", parent=self)
            return
        same = term.casefold() == self._last_term
        self._hit_index = (self._hit_index + 1) % len(hits) if same else 0
        self._last_term = term.casefold()
        pos = hits[self._hit_index]
        self._highlight = pos
        self._reveal(pos)
        self._status.configure(text=f"Found {len(hits)} match(es) — showing {self._hit_index + 1}/{len(hits)}. "
                                    "Press Find again for the next one.")
        self._flash(6)

    def _reveal(self, pos: int) -> None:
        """Scroll sideways only when the colour is not already fully on screen, then put the pointer on it."""
        block = self._blocks.iloc[pos]
        now = datetime.now()
        width = self._width()
        left = self._left_time(now, width)
        x1, x2 = self._x(block["start"], left), self._x(block["end"], left)
        if x1 < 10 or x2 > width - 10:
            centre = block["start"] + (block["end"] - block["start"]) / 2
            self._pinned_left = centre - timedelta(hours=width / self._pph / 2)
        self._draw()
        self.after(60, lambda: self._point_at(pos))

    def _point_at(self, pos: int) -> None:
        """Move the real mouse pointer onto the colour (Tk 'warp'), which also opens its hover card."""
        for x1, y1, x2, y2, rect_pos in self._rects:
            if rect_pos == pos:
                width = self._width()
                x = (max(x1, 0) + min(x2, width)) / 2
                y = (y1 + y2) / 2
                try:
                    self._main.event_generate("<Motion>", warp=True, x=int(x), y=int(y))
                except tk.TclError:
                    pass
                return

    def _flash(self, times: int) -> None:
        if times <= 0 or self._highlight is None:
            self._flash_on = False
            self._draw()
            return
        self._flash_on = not self._flash_on
        self._draw()
        self.after(220, lambda: self._flash(times - 1))

    # ------------------------------------------------------------------ data
    def on_shown(self) -> None:
        """Called when the operator opens the page."""
        if not self.refresh_data():
            self._draw()

    def _current_signature(self):
        tab = self.situazione_tab
        return (getattr(tab, "_data_revision", 0), getattr(tab, "_copertura_revision", 0), self._colors_key)

    def refresh_data(self, force: bool = False) -> bool:
        signature = self._current_signature()
        if not force and signature == self._signature:
            return False
        self._ensure_colors(force)
        signature = self._current_signature()
        if not force and signature == self._signature:
            return False
        self._signature = signature
        if not self._ready():
            self._blocks = pd.DataFrame(columns=timeline.BLOCK_COLUMNS)
            self._index_blocks()
            self._hide_tip()
            self._draw()
            return True
        situation = getattr(self.situazione_tab, "current_df", None)
        copertura = getattr(self.situazione_tab, "loaded_frames", {}).get("copertura")
        try:
            self._blocks = timeline.build_blocks(situation, copertura, self._colors_df, datetime.now())
        except Exception:  # noqa: BLE001 -- a bad row must not take the page down
            logger.exception("Machine timeline: could not build the blocks")
            self._blocks = pd.DataFrame(columns=timeline.BLOCK_COLUMNS)
        self._index_blocks()
        extra = sorted(int(m) for m in set(self._blocks["machine"]) if int(m) not in self._machines)
        if extra:                                            # a machine missing from the Master Data table
            self._machines = sorted(self._machines + extra)
            self._machine_rows = {machine: row for row, machine in enumerate(self._machines)}
            self._draw_labels()
        self._highlight = None
        self._hide_tip()
        self._draw()
        return True

    def _ensure_colors(self, force: bool = False) -> None:
        """Load the Color RGB column of the Produzione file the operator uploaded (in a worker thread)."""
        try:
            from utility import source_hub
            path = source_hub.stored_path("produzione")
        except Exception:  # noqa: BLE001
            path = ""
        self._load_colors_from(path, force)

    def _load_colors_from(self, path: str, force: bool = False) -> None:
        if not path or not Path(path).is_file():
            return
        try:
            stamp = Path(path).stat().st_mtime_ns
        except OSError:
            return
        key = (path, stamp)
        if key == self._colors_key and not force:
            return
        if getattr(self, "_colors_loading", None) == key:
            return
        self._colors_loading = key

        def worker():
            from parsers import situazione_loaders
            try:
                from utility import disk_cache
                # cached on disk by (path, mtime, size): the 6k-row workbook is parsed only when it changes
                df, errors = disk_cache.cached_load(
                    "produzione_colors", Path(path),
                    lambda: situazione_loaders.load_produzione_colors(path),
                    is_valid=lambda result: result[0] is not None and not result[0].empty,
                )
            except Exception as exc:  # noqa: BLE001
                df, errors = None, [str(exc)]

            def apply():
                self._colors_loading = None
                if errors or df is None:
                    self._colors_error = "Produzione: " + ("; ".join(errors) if errors else "no colours")
                    logger.warning("Machine timeline: %s", self._colors_error)
                    self._colors_key = key
                else:
                    self._colors_error = "" if not df.empty else "Produzione file has no readable “Color RGB” values"
                    self._colors_df = df
                    self._colors_key = key
                self._signature = None
                self.refresh_data()

            post_to_ui(self, apply)

        threading.Thread(target=worker, daemon=True).start()

    def _choose_produzione(self) -> None:
        """Upload the Produzione export (same slot as Situazione's "Data prod.")."""
        path = filedialog.askopenfilename(
            parent=self, title="PRODUZIONE file",
            filetypes=[("Excel files", "*.xlsx *.xlsm *.xls"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            self.situazione_tab._queue_handle_upload("data_prod", path)   # also remembers the file for the other pages
        except Exception:  # noqa: BLE001
            logger.exception("Machine timeline: Situazione could not take the Produzione file")
            from parsers.prod_lookup import save_prod_cache
            save_prod_cache(path)
        self._load_colors_from(path, force=True)
        self._poll_after_upload()

    def _choose_copertura(self) -> None:
        """Upload the Copertura export (same slot as Situazione's "Copertura")."""
        path = filedialog.askopenfilename(
            parent=self, title="COPERTURA file",
            filetypes=[("Excel files", "*.xlsx *.xlsm *.xls"), ("All files", "*.*")],
        )
        if not path:
            return
        self.situazione_tab._queue_handle_upload("copertura", path)
        self._poll_after_upload()

    def _poll_after_upload(self) -> None:
        """The upload finishes in a background thread: look again a few times until it has landed."""
        for delay in (800, 2000, 4000, 8000):
            self.after(delay, self.refresh_data)

    # -------------------------------------------------------------- machines
    def _open_machine(self, machine: int) -> None:
        """Same table as the Overview's machine cards."""
        if self._open_machine_schedule is None:
            return
        situation = getattr(self.situazione_tab, "current_df", None)
        copertura = getattr(self.situazione_tab, "loaded_frames", {}).get("copertura")
        schedule = business_logic.build_machine_schedule(situation, copertura)
        self._open_machine_schedule(machine, schedule)

    # ---------------------------------------------------------------- timer
    def _schedule_tick(self) -> None:
        self._tick_id = self.after(self.TICK_MS, self._tick)

    def _tick(self) -> None:
        self._tick_id = None
        if not self.winfo_exists():
            return
        if self.winfo_ismapped():
            if not self.refresh_data():
                self._draw()                 # the time has moved: the colours slide left under the red line
        self._schedule_tick()

    def _on_destroy(self, event) -> None:
        if event.widget is self:
            if self._tick_id is not None:
                try:
                    self.after_cancel(self._tick_id)
                except tk.TclError:
                    pass
            if self._tip is not None and self._tip.winfo_exists():
                self._tip.destroy()
