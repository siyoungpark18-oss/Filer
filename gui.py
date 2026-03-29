#IMPORTS——————————————————————————————————————————————————————————————————————————————————————————————————
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
from pathlib import Path
import threading
import queue
import sys
import io
import shutil
import webbrowser

#IMPORT FROM MANAGER——————————————————————————————————————————————————————————————————————————————————————
from Manager import (
   load_config, save_config, get_input,
   folders_to_pdf, images_to_pdf, folder_renamer, file_renamer,
   combine_image_sets, image_converter, pdf_splitter, pdf_combiner,
   pdf_to_images, status, find_duplicates, DEFAULTS, SENTINEL
)

#VISUAL THEMES—————————————————————————————————————————————————————————————————————————————————————————————
THEMES = {
    "light": {
        "bg":        "#f0f0f0",
        "fg":        "#000000",
        "log_bg":    "#f8f8f8",
        "log_fg":    "#000000",
        "entry_bg":  "#ffffff",
        "entry_fg":  "#000000",
        "btn_bg":    "#e0e0e0",
        "btn_fg":    "#000000",
        "hint_fg":   "gray",
        "hover":     "#d0d0d0",
        "log_error":   "#bd7e7e",
        "log_warn":    "#c59b79",
        "log_success": "#6cab72",
        "log_dim":     "#999999",
    },
    "dark": {
        "bg":        "#1e1e1e",
        "fg":        "#d4d4d4",
        "log_bg":    "#2d2d2d",
        "log_fg":    "#d4d4d4",
        "entry_bg":  "#3c3c3c",
        "entry_fg":  "#d4d4d4",
        "btn_bg":    "#3c3c3c",
        "btn_fg":    "#d4d4d4",
        "hint_fg":   "#888888",
        "hover":     "#4e4e4e",
        "log_error":   "#f44747",
        "log_warn":    "#ce9178",
        "log_success": "#6cab72",
        "log_dim":     "#666666",
    },
}

#LOG——————————————————————————————————————————————————————————————————————————————————————————————————
class LogRedirect(io.TextIOBase):
    REPEAT_THRESHOLD = 1

    def __init__(self, log_widget, app):
        self.log = log_widget
        self.app = app
        self._last_msg = None
        self._rep_count = 0
        self._active_section = None

    def start_section(self, header):
        self._active_section = None

        tag = f"section_{id(header)}_{self.log.index(tk.END)}"
        hide_tag = f"hide_{tag}"
        expanded = self.app.config.get("log_default_expanded", False)

        self.log.configure(state='normal')
        arrow = "▲" if expanded else "▼"
        line = f"{arrow} {header}\n"

        self.log.tag_configure(tag, foreground=self.app._theme()["log_fg"])
        self.log.insert(tk.END, line, (tag,))
        self.log.tag_configure(hide_tag, elide=not expanded)

        self.log.tag_bind(tag, "<Button-1>", lambda e, t=tag, h=hide_tag: self._toggle(t, h))
        self.log.tag_bind(tag, "<Enter>", lambda e: self.log.configure(cursor="hand2"))
        self.log.tag_bind(tag, "<Leave>", lambda e: self.log.configure(cursor=""))

        self.log.see(tk.END)
        self.log.configure(state='disabled')

        self._active_section = {"tag": tag, "hide_tag": hide_tag, "expanded": expanded}
        return tag

    def end_section(self):
        self._active_section = None

    def _toggle(self, tag, hide_tag):
        self.log.configure(state='normal')
        currently_elided = self.log.tag_cget(hide_tag, "elide")
        is_hidden = str(currently_elided) in ("1", "True", "true")
        new_elide = not is_hidden
        self.log.tag_configure(hide_tag, elide=new_elide)

        ranges = self.log.tag_ranges(tag)
        if ranges:
            start, end = ranges[0], ranges[1]
            text = self.log.get(start, end)
            if text.startswith("▼"):
                self.log.delete(start, f"{start}+1c")
                self.log.insert(start, "▲", (tag,))
            elif text.startswith("▲"):
                self.log.delete(start, f"{start}+1c")
                self.log.insert(start, "▼", (tag,))

        self.log.configure(state='disabled')

    def _style_tag_for(self, msg):
        t = self.app._theme()
        s = msg.strip()

        if s.startswith("✖") or "Failed" in s:
            tag = "log_error"
            cfg = {"foreground": t["log_error"]}
        elif s.startswith("⚠") or "skipped (unsupported type)" in s:
            tag = "log_warn"
            cfg = {"foreground": t["log_warn"]}
        elif s.startswith("Done!") or s.startswith("→") or "Done!" in s:
            tag = "log_success"
            cfg = {"foreground": t["log_success"]}
        elif (s.startswith("Saved:") or s.startswith("converted:") or
              s.startswith("Total:") or s.startswith("PDFs saved:") or
              s.startswith("combined:") or s.startswith("renamed:") or
              s.startswith("copied:") or s.startswith("pages exported:") or
              s.startswith("scanned:")):
            tag = "log_bold"
            cfg = {}
        elif msg.startswith("    ") and self._active_section:
            tag = "log_dim"
            cfg = {"foreground": t["log_dim"]}
        else:
            return None

        self.log.tag_configure(tag, **cfg)
        return tag

    def write(self, msg):
        msg = msg.rstrip('\n')
        if not msg.strip():
            return len(msg)

        self.log.configure(state='normal')

        style_tag = self._style_tag_for(msg)
        hide_tag = self._active_section["hide_tag"] if self._active_section else None
        insert_tags = tuple(t for t in (hide_tag, style_tag) if t)

        if msg == self._last_msg:
            self._rep_count += 1
            if self._rep_count >= self.REPEAT_THRESHOLD:
                self.log.delete("end-2l", "end-1l")
                self.log.insert(tk.END, f"{msg}  ×{self._rep_count}\n", insert_tags)
                self.log.see(tk.END)
                self.log.configure(state='disabled')
                return len(msg)
        else:
            self._last_msg = msg
            self._rep_count = 1

        self.log.insert(tk.END, msg + '\n', insert_tags)
        self.log.see(tk.END)
        self.log.configure(state='disabled')
        return len(msg)

    def flush(self):
        pass


input_queue = queue.Queue()
result_queue = queue.Queue()


def thread_safe_input(prompt=""):
    input_queue.put(prompt)
    return result_queue.get()


def patch_input():
    import builtins
    builtins.input = thread_safe_input


TOOL_LABELS = {
    "Folders to PDF", "Images to PDF", "Folder Renamer", "File Renamer",
    "Combine Image Sets", "Image Converter", "Find Duplicates",
    "PDF Combiner", "PDF Splitter", "PDF to Images",
}


#APP——————————————————————————————————————————————————————————————————————————————————————————————————
class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Tankobon")
        self.root.resizable(True, True)
        self.config = load_config()
        self.cancel_event = threading.Event()
        self._running_jobs = {}
        self._open_accordion = {}
        self._dark = self.config.get("dark_mode", False)
        self._btn_labels = {}
        self._suboption_labels = {}
        self._last_input_count = -1
        patch_input()
        self._build_ui()
        self._apply_theme()
        sys.stdout = LogRedirect(self.log, self)
        sys.stderr = LogRedirect(self.log, self)
        self._poll_input()
        self._status_running = False

    TOOL_OPTIONS = {
        "Folders to PDF":     ["combine", "individual"],
        "Images to PDF":      [],
        "Folder Renamer":     ["prefix", "suffix", "replace", "extract number"],
        "File Renamer":       ["prefix", "suffix", "replace", "sequence"],
        "Combine Image Sets": ["natural", "none"],
        "Image Converter":    ["jpg", "png", "webp", "bmp", "tiff"],
        "Find Duplicates":    ["keep one copy", "delete all"],
        "PDF Combiner":       ["natural", "none"],
        "PDF Splitter":       [],
        "PDF to Images":      ["jpg", "png"],
        "Add Input":          ["files", "folder"],
    }

    TOOL_MODE_CONFIG_KEY = {
        "Folders to PDF":  "default_folders_to_pdf_mode",
        "Folder Renamer":  "default_folder_renamer_mode",
        "File Renamer":    "default_file_renamer_mode",
        "Image Converter": "default_img_fmt",
        "Find Duplicates": "default_dedupe_mode",
        "PDF to Images":   "default_img_fmt",
        "PDF Combiner": "default_sort",
        "Combine Image Sets": "default_sort",
    }

    OPTION_LABELS = {
        "combine":        "Combine all → one PDF",
        "individual":     "One PDF per folder",
        "prefix":         "Prefix",
        "suffix":         "Suffix",
        "replace":        "Find & Replace",
        "extract number": "Extract Number",
        "sequence":       "Sequence",
        "jpg":            "JPG",
        "png":            "PNG",
        "webp":           "WebP",
        "bmp":            "BMP",
        "tiff":           "TIFF",
        "keep one copy":  "Keep one copy",
        "delete all":     "Delete all instances",
        "natural":        "Natural sort",
        "none":           "No sort",
        "files":          "Files",
        "folder":         "Individual Folder",
    }

    def _theme(self):
        return THEMES["dark"] if self._dark else THEMES["light"]

    def _apply_theme(self):
        t = self._theme()
        self.root.configure(bg=t["bg"])
        for widget in [self.root, self._btn_frame, self._right]:
            self._apply_to_widget(widget, t)
        self.log.configure(bg=t["log_bg"], fg=t["log_fg"],
                           insertbackground=t["log_fg"])
        for tag in self.log.tag_names():
            if tag.startswith("section_"):
                self.log.tag_configure(tag, foreground=t["log_fg"])
            elif tag.startswith("log_dim"):
                self.log.tag_configure(tag, foreground=t["log_dim"])
            elif tag.startswith("log_error"):
                self.log.tag_configure(tag, foreground=t["log_error"])
            elif tag.startswith("log_warn"):
                self.log.tag_configure(tag, foreground=t["log_warn"])
            elif tag.startswith("log_success"):
                self.log.tag_configure(tag, foreground=t["log_success"])
        self._update_button_states()

    def _on_scroll(self, first, last):
        self._scrollbar.set(first, last)
        if float(first) <= 0.0 and float(last) >= 1.0:
            self._scrollbar.pack_forget()
        else:
            self._scrollbar.pack(side='right', fill='y')

    def _apply_to_widget(self, widget, t):
        if isinstance(widget, tk.Toplevel):
            return
        cls = widget.winfo_class()
        try:
            if cls in ("Frame",):
                widget.configure(bg=t["bg"])
            elif cls in ("Label",):
                widget.configure(bg=t["bg"], fg=t["fg"])
            elif cls in ("Button",):
                widget.configure(bg=t["btn_bg"], fg=t["btn_fg"],
                                 activebackground=t["bg"], activeforeground=t["fg"])
            elif cls in ("Entry",):
                widget.configure(bg=t["entry_bg"], fg=t["entry_fg"],
                                 insertbackground=t["entry_fg"])
            elif cls in ("Text", "ScrolledText"):
                widget.configure(bg=t["log_bg"], fg=t["log_fg"])
        except tk.TclError:
            pass
        for child in widget.winfo_children():
            self._apply_to_widget(child, t)

    def _toggle_dark(self):
        self._dark = not self._dark
        self.config["dark_mode"] = self._dark
        save_config(self.config)
        self._apply_theme()
        self._dark_btn.configure(text="☀" if self._dark else "🌙")
        new_tip = "Bright Mode" if self._dark else "Dark Mode"
        self._dark_btn.bind("<Enter>", lambda e: (
            self._dark_btn.configure(bg=self._theme()["hover"]),
            self._show_tooltip_popup(self._dark_btn, new_tip)
        ))

    def _get_input_count(self):
        try:
            input_dir = get_input(self.config)
            if not input_dir.exists():
                return 0
            return sum(1 for _ in input_dir.iterdir())
        except Exception:
            return 0

    def _is_configured(self):
        inp = self.config.get("input", "")
        out = self.config.get("output", "")
        return bool(inp and out and Path(inp).exists() and Path(out).exists())

    def _update_button_states(self):
        t = self._theme()
        configured = self._is_configured()

        for label, lbl in self._btn_labels.items():
            try:
                if label == "Add Input":
                    if not configured:
                        current = lbl.cget("text")
                        if not current.startswith("⚠ "):
                            lbl.configure(text="⚠ Add Input")
                    else:
                        lbl.configure(text="Add Input")
            except tk.TclError:
                pass

        if not self.config.get("guide_empty_input", True):
            for label, lbl in self._btn_labels.items():
                try:
                    if not label.startswith("⚠ "):
                        lbl.configure(fg=t["fg"], bg=t["bg"])
                except tk.TclError:
                    pass
            return

        count = self._get_input_count()
        empty = count == 0

        for label, lbl in self._btn_labels.items():
            try:
                bare = label.replace("⚠ ", "")
                if bare == "Add Input":
                    lbl.configure(fg=t["fg"], bg=t["hover"] if empty else t["bg"])
                elif bare in TOOL_LABELS:
                    lbl.configure(fg=t["hint_fg"] if empty else t["fg"], bg=t["bg"])
            except tk.TclError:
                pass

        for tool_label, opt_lbls in self._suboption_labels.items():
            color = t["hint_fg"] if empty else t["fg"]
            for lbl in opt_lbls:
                try:
                    lbl.configure(fg=color)
                except tk.TclError:
                    pass

    def _poll_input(self):
        try:
            prompt = input_queue.get_nowait()
            self._show_inline_input(prompt)
        except queue.Empty:
            pass

        count = self._get_input_count()
        if count != self._last_input_count:
            self._last_input_count = count
            label = f"[{count} item{'s' if count != 1 else ''}]"
            try:
                self._input_status_lbl.configure(text=label)
            except tk.TclError:
                pass
            self._update_button_states()

        self.root.after(50, self._poll_input)

    def _show_inline_input(self, prompt):
        if hasattr(self, '_input_frame') and self._input_frame.winfo_exists():
            return

        t = self._theme()
        self._input_frame = tk.Frame(self._right, bg=t["bg"])
        self._input_frame.pack(fill='x', pady=(4, 0))

        if prompt.strip():
            print(f"{prompt.strip()}")

        is_pick = "Waiting for key" in prompt

        if is_pick:
            hint = "  (Enter = Files  •  Space = Folder  •  Escape = Cancel)"
        else:
            continue_key = self.config.get("hotkey_continue", "Return")
            cancel_key = self.config.get("hotkey_cancel", "Delete")
            hint = f"  ({continue_key} = confirm  •  {cancel_key} = cancel)"

        tk.Label(self._input_frame, text=hint, fg=t["hint_fg"],
                 bg=t["bg"], font=('Courier', 10)).pack(side='left')

        var = tk.StringVar()
        entry = tk.Entry(self._input_frame, textvariable=var, font=('Courier', 11),
                         bg=t["entry_bg"], fg=t["entry_fg"],
                         insertbackground=t["entry_fg"])
        entry.pack(side='left', fill='x', expand=True, padx=4)
        entry.focus_set()

        if is_pick:
            def pick_files(e=None):
                self._input_frame.destroy()
                result_queue.put("FILES")
            def pick_folder(e=None):
                self._input_frame.destroy()
                result_queue.put("FOLDER")
            def cancel(e=None):
                self._input_frame.destroy()
                result_queue.put("CANCEL")
            entry.bind("<Return>", pick_files)
            entry.bind("<space>", pick_folder)
            entry.bind("<Escape>", cancel)
        else:
            continue_key = self.config.get("hotkey_continue", "Return")
            cancel_key = self.config.get("hotkey_cancel", "Delete")

            def confirm(e=None):
                val = var.get()
                self._input_frame.destroy()
                result_queue.put(val)

            def cancel(e=None):
                self._input_frame.destroy()
                result_queue.put(SENTINEL)

            entry.bind(f"<{continue_key}>", confirm)
            entry.bind(f"<{cancel_key}>", cancel)

    def _show_help(self):
        win = tk.Toplevel(self.root)
        win.title("Help")
        win.geometry("600x620")
        win.resizable(False, False)

        text = scrolledtext.ScrolledText(win, wrap='word', font=('Courier', 11),
                                         padx=10, pady=10)
        text.pack(fill='both', expand=True)

        text.tag_configure("h1", font=('Courier', 16, 'bold'))
        text.tag_configure("h2", font=('Courier', 12, 'bold'))
        text.tag_configure("body", font=('Courier', 11))
        text.tag_configure("dim", font=('Courier', 10), foreground="gray")

        def h1(s):  text.insert(tk.END, s + "\n", "h1")
        def h2(s):  text.insert(tk.END, s + "\n", "h2")
        def body(s): text.insert(tk.END, s + "\n", "body")
        def gap():  text.insert(tk.END, "\n")

        h1("Tankobon")
        gap()
        body("Tankobon is a file manager.")
        body("To be more specific, it's specialized for image management en masse. It's meant to manage, convert, and compress folders with images or individual images in the thousands at a time and to do this with speed.")
        gap()
        body("And with this comes its true Niche or intended use. Ultimately, Tankobon is a companion to large scale Manga Piracy. To those who wish to own and obtain manga from third party sources you may find that a multitude of reasons can impede time-efficient management of what could be thousands of manga pages, each stored as an individual image.")
        gap()
        body("Following is the explanation of the use cases for each tool within this Niche. I hope it's useful in these areas at the very least.")
        gap()
        gap()
        h2("The Intended use of each tool")
        gap()
        h2("Folders to PDF")
        body("This is a tool that quite unassumingly turns multiple folders into a PDF. However, this can be quite a feat to do manually when working with a manga.")
        gap()
        body("This tool is meant to be used to combine All or some of the individual chapters of a manga into a single pdf. Since chapters in a manga downloader such as Hakuneko or Mihon are downloaded individually, and a manga can have hundreds of chapters, this is a useful way to compress them into a single PDF if wanted.")
        gap()
        body("The PDF format is generally most useful for reading on monitors, provided were still talking about manga here.")
        gap()
        h2("Images to PDF")
        body("A companion tool to folders to pdf. This tool is comparatively simple and simply requires you to input a folder with multiple images in it. The tool will create an output based on the input.")
        gap()
        h2("Folder Renamer")
        body("The folder renamer renames files based on the number in its file name. If there are multiple numbers, it is no good.")
        gap()
        body("However, its main use case is with Manga chapters. When manga is downloaded its usual format is in an image set form with the images of individual chapters or volumes in a folder.")
        gap()
        body("Provided the naming conventions of the folders is simple and each folder is named by Chapter It can extract the number. This is useful in certain cases where the naming conventions are obscured by different scanlation groups.")
        gap()
        body("This program usually does nothing if there are no numbers available.")
        gap()
        h2("File Renamer")
        body("A similar but different tool that also renames files. This is a general renaming tool which can replace certain parts of file names, add a prefix or suffix to the file name, or use the sequence function to sort by number.")
        gap()
        h2("Combine Image Sets")
        body("This tool combines multiple folders of images into a single folder with all the images, preserving order.")
        gap()
        h2("Image Converter")
        body("Can convert a ton of images to whatever format is on the list.")
        gap()
        h2("Find Duplicates")
        body("Finds exact image duplicates of files by file hash.")
        gap()
        h2("PDF Combiner")
        body("Combines multiple PDFs into one.")
        gap()
        h2("PDF Splitter")
        body("Splits a PDF at page numbers you specify.")
        gap()
        h2("PDF to Images")
        body("Converts a PDF into individual image files. Resource intensive.")
        gap()
        body("DPI settings are for printing, so there's no reason to use a DPI higher than the minimum usually.")
        gap()
        gap()
        h1("Utility")
        gap()
        h2("Add Input")
        body("Adds files or a folder to the input directory for processing.")
        gap()
        h2("Clear Input")
        body("Clears the current input folder. Originals are not affected.")
        gap()
        h2("Status")
        body("Displays what's currently in the input and output folders.")
        gap()
        h2("Clear Log")
        body("Clears the log display.")
        gap()
        h2("Clear Output")
        body("Clears the output folder.")
        gap()
        h2("Cancel Job")
        body("Cancels the currently running job.")
        gap()
        h2("Open Output")
        body("Opens the output folder in Finder/Explorer.")
        gap()
        h2("Preferences (≡)")
        body("Set paths, configure behaviour, defaults, throttles, and visible buttons.")
        gap()
        gap()
        h1("Example Workflow")
        gap()
        text.insert(tk.END, "1. ", "h2")
        body("Click Add Input and add your files or folder.")
        text.insert(tk.END, "2. ", "h2")
        body("Select a tool and run it.")
        text.insert(tk.END, "3. ", "h2")
        body("Take the output from the output folder.")
        text.insert(tk.END, "4. ", "h2")
        body("Clear input when done.")
        gap()

        text.configure(state='disabled')
        tk.Button(win, text="Close", command=win.destroy).pack(pady=8)

    def _show_docs(self):
        win = tk.Toplevel(self.root)
        win.title("Documentation")
        win.geometry("600x620")
        win.resizable(False, False)

        text = scrolledtext.ScrolledText(win, wrap='word', font=('Courier', 11),
                                         padx=10, pady=10)
        text.pack(fill='both', expand=True)

        def insert_link(url):
            tag = f"link_{url}"
            text.tag_configure(tag, foreground="blue", underline=True)
            text.insert(tk.END, url, (tag,))
            text.tag_bind(tag, "<Button-1>", lambda e, u=url: webbrowser.open(u))
            text.tag_bind(tag, "<Enter>", lambda e: text.configure(cursor="hand2"))
            text.tag_bind(tag, "<Leave>", lambda e: text.configure(cursor=""))

        text.configure(state='normal')
        text.insert(tk.END, "Tankobon\n\n")
        text.insert(tk.END,
                    "Tankobon is a file manager. It's an open source project that specializes in managing image files in bulk. Its under the AGPL license\n\n")
        text.insert(tk.END, "Github:\n")
        insert_link("https://github.com/siyoungpark18-oss/Tankobon")
        text.insert(tk.END, "\n\nMacOS .dmg:\n")
        insert_link("https://drive.google.com/drive/u/2/folders/1gjRlr2hV7RjLBTGlGs2SqQgKNaW4T0Il")
        text.insert(tk.END, "\n\nPrevious versions:\n")
        insert_link("https://drive.google.com/drive/u/2/folders/1jT_qMHEpWVczcIwBHTYJt1QkrE6WL8pb")
        text.insert(tk.END, "\n")
        text.configure(state='disabled')

        tk.Button(win, text="Close", command=win.destroy).pack(pady=8)

    def _build_ui(self):
        self._log_font_size = 11

        left = tk.Frame(self.root, width=200)
        left.pack(side='left', fill='y', padx=10, pady=10)
        left.pack_propagate(False)

        title_row = tk.Frame(left)
        title_row.pack(fill='x', pady=(0, 2))
        tk.Label(title_row, text="Tankobon", font=('', 11, 'bold')).pack(side='left')

        def _mini_btn(parent, text_or_var, cmd, side='right', tooltip=None):
            t = self._theme()
            f = tk.Frame(parent, bg=t["fg"], padx=1, pady=1)
            lbl = tk.Label(f, bg=t["bg"], fg=t["fg"], font=('', 10), width=2, cursor="hand2")
            if isinstance(text_or_var, str):
                lbl.configure(text=text_or_var)
            lbl.pack()

            def on_click(e):
                if getattr(self, '_last_click', 0) == id(cmd):
                    return "break"
                self._last_click = id(cmd)
                self.root.after(300, lambda: setattr(self, '_last_click', None))
                cmd()
                return "break"

            lbl.bind("<Button-1>", on_click)
            lbl.bind("<Enter>", lambda e: lbl.configure(bg=self._theme()["hover"]))
            lbl.bind("<Leave>", lambda e: lbl.configure(bg=self._theme()["bg"]))

            if tooltip:
                def show_tip(e):
                    self._show_tooltip_popup(lbl, tooltip)
                def hide_tip(e):
                    if hasattr(self, '_tooltip') and self._tooltip:
                        self._tooltip.destroy()
                        self._tooltip = None
                lbl.bind("<Enter>", lambda e: (lbl.configure(bg=self._theme()["hover"]), show_tip(e)))
                lbl.bind("<Leave>", lambda e: (lbl.configure(bg=self._theme()["bg"]), hide_tip(e)))

            f.pack(side=side, padx=(2, 0))
            return lbl

        _mini_btn(title_row, "?", self._show_help, tooltip="Help")
        _mini_btn(title_row, "i", self._show_docs, tooltip="Documentation")
        _mini_btn(title_row, "≡", self._show_preferences, tooltip="Preferences")
        self._dark_btn = _mini_btn(title_row, "🌙" if not self._dark else "☀", self._toggle_dark,
                                   tooltip="Dark Mode" if not self._dark else "Bright Mode")

        status_row = tk.Frame(left)
        status_row.pack(fill='x', pady=(0, 4))
        t = self._theme()
        self._input_status_lbl = tk.Label(
            status_row, text="[0 items]",
            font=('Courier', 9), fg=t["hint_fg"], bg=t["bg"], anchor='w'
        )
        self._input_status_lbl.pack(side='left')

        self._btn_frame = tk.Frame(left)
        self._btn_frame.pack(fill='both', expand=True)

        self._right = tk.Frame(self.root)
        self._right.pack(side='left', fill='both', expand=True, padx=(0, 10), pady=10)

        log_header = tk.Frame(self._right)
        log_header.pack(fill='x')

        tk.Label(log_header, text="Log", font=('', 11, 'bold')).pack(side='left')
        self._status_lbl = tk.Label(log_header, text="", font=('Courier', 9))
        self._status_lbl.pack(side='left', padx=(8, 0))

        def _change_font(delta):
            self._log_font_size = max(7, min(24, self._log_font_size + delta))
            self.log.configure(font=('Courier', self._log_font_size))

        for symbol, delta in (('+', 1), ('-', -1)):
            btn = tk.Label(log_header, text=symbol, font=('', 10, 'bold'),
                           bg=t["bg"], fg=t["fg"], padx=6, cursor="hand2")
            btn.pack(side='right', padx=(2, 0))
            btn.bind("<Button-1>", lambda e, d=delta: _change_font(d))
            btn.bind("<Enter>", lambda e, b=btn: b.configure(bg=self._theme()["hover"]))
            btn.bind("<Leave>", lambda e, b=btn: b.configure(bg=self._theme()["bg"]))

        log_frame = tk.Frame(self._right)
        log_frame.pack(fill='both', expand=True)

        self._scrollbar = tk.Scrollbar(log_frame)
        self._scrollbar.pack(side='right', fill='y')

        self.log = tk.Text(log_frame, state='disabled', wrap='word',
                           font=('Courier', self._log_font_size),
                           yscrollcommand=self._on_scroll,
                           relief='flat', bd=0, highlightthickness=0)
        self.log.pack(side='left', fill='both', expand=True)
        self._scrollbar.config(command=self.log.yview)
        self._scrollbar.pack_forget()

        self._rebuild_buttons()

    TOGGLEABLE = [
        ("show_folders_to_pdf", "Folder", "Folders to PDF", "run_folders_to_pdf"),
        ("show_images_to_pdf", "Folder", "Images to PDF", "run_images_to_pdf"),
        ("show_folder_renamer", "Folder", "Folder Renamer", "run_folder_renamer"),
        ("show_file_renamer", "Folder", "File Renamer", "run_file_renamer"),
        ("show_combine", "Folder", "Combine Image Sets", "run_combine"),
        ("show_converter", "Folder", "Image Converter", "run_converter"),
        ("show_duplicates", "Folder", "Find Duplicates", "run_duplicates"),
        ("show_pdf_combiner", "Folder", "PDF Combiner", "run_pdf_combiner"),
        ("show_pdf_splitter", "File", "PDF Splitter", "run_pdf_splitter"),
        ("show_pdf_to_images", "File", "PDF to Images", "run_pdf_to_images"),
    ]

    TOOLTIPS = {
        "Folders to PDF": "Combines all folders in Input into a single PDF. Each folder is treated as a chapter.",
        "Images to PDF": "Converts all images in Input into a single PDF.",
        "Folder Renamer": "Renames folders by extracting the number from their name. Useful for sorting chapters.",
        "File Renamer": "Renames files by prefix, suffix, find/replace, or sequence numbering.",
        "Combine Image Sets": "Merges multiple folders of images into one flat folder, preserving order.",
        "Image Converter": "Converts all images in Input to a chosen format (jpg, png, webp, etc).",
        "Find Duplicates": "Finds and optionally deletes exact duplicate images by file hash.",
        "PDF Combiner": "Combines multiple PDFs into one.",
        "PDF Splitter": "Splits a PDF into parts at page numbers you specify.",
        "PDF to Images": "Converts a PDF into individual image files. Resource intensive.",
        "Add Input": "Copies files or a folder into the Input directory for processing.",
        "Clear Input": "Deletes everything in the Input folder. Originals are not affected.",
        "Status": "Shows what is currently in the Input and Output folders.",
        "Clear Log": "Clears the log display.",
        "Clear Output": "Deletes everything in the Output folder.",
        "Cancel Job": "Cancels the currently running job.",
        "Open Input": "Opens the input folder in Finder/Explorer.",
        "Open Output": "Opens the output folder in Finder/Explorer and prints the path to the log.",
    }

    def open_input(self):
        input_dir = get_input(self.config)
        if not self.config.get("input", ""):
            print("  Input folder is not configured. Set it in Preferences (≡).")
            return
        if not input_dir.exists():
            print(f"  Input folder does not exist yet: {input_dir}")
            return
        print(f"  Input: {input_dir}")
        import subprocess, sys as _sys
        if _sys.platform == "darwin":
            subprocess.Popen(["open", str(input_dir)])
        elif _sys.platform == "win32":
            subprocess.Popen(["explorer", str(input_dir)])
        else:
            subprocess.Popen(["xdg-open", str(input_dir)])

    def open_output(self):
        out_dir = Path(self.config.get("output", "")) / "output"
        if not self.config.get("output", ""):
            print("  Output folder is not configured. Set it in Preferences (≡).")
            return
        if not out_dir.exists():
            print(f"  Output folder does not exist yet: {out_dir}")
            return
        print(f"  Output: {out_dir}")
        import subprocess, sys as _sys
        if _sys.platform == "darwin":
            subprocess.Popen(["open", str(out_dir)])
        elif _sys.platform == "win32":
            subprocess.Popen(["explorer", str(out_dir)])
        else:
            subprocess.Popen(["xdg-open", str(out_dir)])

    def _show_tooltip(self, widget, text):
        def on_enter(e):
            x = widget.winfo_rootx() + widget.winfo_width() + 4
            y = widget.winfo_rooty()
            self._tooltip = tk.Toplevel(self.root)
            self._tooltip.wm_overrideredirect(True)
            self._tooltip.wm_geometry(f"+{x}+{y}")
            t = self._theme()
            lbl = tk.Label(self._tooltip, text=text, wraplength=220,
                           justify='left', font=('Courier', 10),
                           bg=t["btn_bg"], fg=t["fg"], padx=6, pady=4)
            lbl.pack()

        def on_leave(e):
            if hasattr(self, '_tooltip') and self._tooltip:
                self._tooltip.destroy()
                self._tooltip = None

        widget.bind("<Enter>", on_enter)
        widget.bind("<Leave>", on_leave)

    def _show_tooltip_popup(self, widget, text):
        if hasattr(self, '_tooltip') and self._tooltip:
            self._tooltip.destroy()
        x = widget.winfo_rootx() + widget.winfo_width() + 4
        y = widget.winfo_rooty()
        self._tooltip = tk.Toplevel(self.root)
        self._tooltip.wm_overrideredirect(True)
        self._tooltip.wm_geometry(f"+{x}+{y}")
        t = self._theme()
        tk.Label(self._tooltip, text=text, font=('Courier', 10),
                 bg=t["btn_bg"], fg=t["fg"], padx=6, pady=4).pack()

    def _make_button(self, parent, text, cmd, tooltip=None):
        t = self._theme()
        row = tk.Frame(parent, bg=t["bg"])
        row.pack(pady=2, fill='x')

        f = tk.Frame(row, bg=t["fg"], padx=1, pady=1)
        lbl = tk.Label(f, text=text, bg=t["bg"], fg=t["fg"],
                       font=('', 10), width=22, cursor="hand2")
        lbl.pack()
        lbl.bind("<Button-1>", lambda e: cmd())
        lbl.bind("<Enter>", lambda e: lbl.configure(bg=self._theme()["hover"]))
        lbl.bind("<Leave>", lambda e: lbl.configure(bg=self._theme()["bg"]))
        f.pack(side='left')

        self._btn_labels[text] = lbl

        if tooltip and self.config.get("show_tooltips", True):
            info = tk.Label(row, text="i", bg=t["bg"], fg=t["hint_fg"],
                            font=('', 9), cursor="hand2", padx=2)
            info.pack(side='left', padx=(3, 0))
            info.bind("<Enter>", lambda e: info.configure(bg=self._theme()["hover"]))
            info.bind("<Leave>", lambda e: info.configure(bg=self._theme()["bg"]))
            self._show_tooltip(info, tooltip)

        return f, lbl

    # ── button rebuilding ─────────────────────────────────────────────────────

    def _rebuild_buttons(self):
        self._btn_labels.clear()
        self._suboption_labels.clear()
        self._open_accordion = {}
        for w in self._btn_frame.winfo_children():
            w.destroy()

        if self.config.get("ui_mode", "classic") == "dropdown":
            self._build_dropdown_buttons()
        else:
            self._build_classic_buttons()

        self._apply_theme()
        self._update_button_states()

    def _build_classic_buttons(self):
        from collections import OrderedDict
        toggleable_sections = OrderedDict()
        for key, section, label, method in self.TOGGLEABLE:
            if self.config.get(key, True):
                toggleable_sections.setdefault(section, []).append(
                    (label, getattr(self, method)))

        fixed_sections = [
            ("Input", [
                ("Add Input",    self.pick_files),
                ("Clear Input",  self.clear_input),
                ("Open Input",   self.open_input),
            ]),
            ("Utility", [
                ("Status",       self.run_status),
                ("Clear Log",    self.clear_log),
                ("Open Output",  self.open_output),
                ("Clear Output", self.clear_output),
                ("Cancel Job",   self.cancel_job),
            ]),
        ]

        all_sections = list(toggleable_sections.items()) + fixed_sections

        for section_label, cmds in all_sections:
            tk.Label(self._btn_frame, text=section_label,
                     font=('', 10, 'bold')).pack(anchor='w', pady=(8, 2))
            for label, cmd in cmds:
                self._make_button(self._btn_frame, label, cmd,
                                  tooltip=self.TOOLTIPS.get(label))

    def _build_dropdown_buttons(self):
        t = self._theme()

        from collections import OrderedDict
        tool_rows = OrderedDict()
        for key, section, label, method in self.TOGGLEABLE:
            if self.config.get(key, True):
                tool_rows.setdefault(section, []).append(
                    (label, getattr(self, method)))

        # ── tool accordion sections ───────────────────────────────────────────
        for section_label, items in tool_rows.items():
            tk.Label(self._btn_frame, text=section_label,
                     font=('', 10, 'bold'), bg=t["bg"], fg=t["fg"]
                     ).pack(anchor='w', pady=(8, 2))
            for label, run_fn in items:
                self._make_tool_accordion(self._btn_frame, label, run_fn)

        # ── Input section ─────────────────────────────────────────────────────
        tk.Label(self._btn_frame, text="Input",
                 font=('', 10, 'bold'), bg=t["bg"], fg=t["fg"]
                 ).pack(anchor='w', pady=(8, 2))
        self._make_tool_accordion(self._btn_frame, "Add Input", self.pick_files)
        for label, cmd in [("Clear Input", self.clear_input), ("Open Input", self.open_input)]:
            self._make_button(self._btn_frame, label, cmd, tooltip=self.TOOLTIPS.get(label))

        # ── Utility section ───────────────────────────────────────────────────
        tk.Label(self._btn_frame, text="Utility",
                 font=('', 10, 'bold'), bg=t["bg"], fg=t["fg"]
                 ).pack(anchor='w', pady=(8, 2))
        for label, cmd in [
            ("Status",       self.run_status),
            ("Clear Log",    self.clear_log),
            ("Open Output",  self.open_output),
            ("Clear Output", self.clear_output),
            ("Cancel Job",   self.cancel_job),
        ]:
            self._make_button(self._btn_frame, label, cmd, tooltip=self.TOOLTIPS.get(label))

    def _make_tool_accordion(self, parent, label, run_fn):
        t = self._theme()
        options = self.TOOL_OPTIONS.get(label, [])

        outer = tk.Frame(parent, bg=t["bg"])
        outer.pack(fill='x', pady=1)

        hdr_row = tk.Frame(outer, bg=t["bg"])
        hdr_row.pack(fill='x')

        hdr_f = tk.Frame(hdr_row, bg=t["fg"], padx=1, pady=1)
        hdr_lbl = tk.Label(hdr_f, text=label, bg=t["bg"], fg=t["fg"],
                           font=('', 10), width=22, cursor="hand2")
        hdr_lbl.pack()
        hdr_f.pack(side='left')

        self._btn_labels[label] = hdr_lbl

        if self.config.get("show_tooltips", True) and label in self.TOOLTIPS:
            info = tk.Label(hdr_row, text="i", bg=t["bg"], fg=t["hint_fg"],
                            font=('', 9), cursor="hand2", padx=2)
            info.pack(side='left', padx=(3, 0))
            info.bind("<Enter>", lambda e: info.configure(bg=self._theme()["hover"]))
            info.bind("<Leave>", lambda e: info.configure(bg=self._theme()["bg"]))
            self._show_tooltip(info, self.TOOLTIPS[label])

        body = tk.Frame(outer, bg=t["bg"])
        state = {"open": False}

        def _update_label(is_open, lbl=hdr_lbl, lbl_text=label):
            prefix = "▼ " if is_open else "▶ "
            lbl.configure(text=prefix + lbl_text)

        _update_label(False)

        def set_open(label=label, state=state, body=body):
            for lbl_key, info in self._open_accordion.items():
                if lbl_key != label and info["open"]:
                    info["close"]()
            if state["open"]:
                body.pack_forget()
                _update_label(False)
                state["open"] = False
                self._open_accordion[label]["open"] = False
            else:
                body.pack(fill='x')
                _update_label(True)
                state["open"] = True
                self._open_accordion[label]["open"] = True

        def close_fn(body=body, state=state):
            body.pack_forget()
            _update_label(False)
            state["open"] = False

        self._open_accordion[label] = {"open": False, "close": close_fn}

        # Check if a default is configured — if so, act like a direct-run button
        config_key = self.TOOL_MODE_CONFIG_KEY.get(label)
        has_default = (
            config_key is not None
            and self.config.get(config_key, "ask") != "ask"
        )

        if not options or has_default:
            # Direct-run: clicking header or ▶ runs the tool immediately
            for w in (hdr_f, hdr_lbl):
                w.bind("<Button-1>", lambda e, fn=run_fn, jn=label:
                       self._inject_and_run(fn, None, jn))
                w.bind("<Enter>", lambda e: hdr_lbl.configure(bg=self._theme()["hover"]))
                w.bind("<Leave>", lambda e: hdr_lbl.configure(bg=self._theme()["bg"]))
            hdr_lbl.configure(text=label)

            # ▶ run button on the right
            rbf = tk.Frame(hdr_row, bg=t["fg"], padx=1, pady=1)
            rbl = tk.Label(rbf, text="▶", bg=t["bg"], fg=t["fg"],
                           font=('', 9), padx=5, cursor="hand2")
            rbl.pack()
            rbf.pack(side='right', padx=(4, 2))
            rbl.bind("<Button-1>", lambda e, fn=run_fn, jn=label:
                     self._inject_and_run(fn, None, jn))
            rbl.bind("<Enter>", lambda e, b=rbl: b.configure(bg=self._theme()["hover"]))
            rbl.bind("<Leave>", lambda e, b=rbl: b.configure(bg=self._theme()["bg"]))

        else:
            # Expandable: clicking header toggles sub-options
            for w in (hdr_f, hdr_lbl):
                w.bind("<Button-1>", lambda e, fn=set_open: fn())
                w.bind("<Enter>", lambda e: hdr_lbl.configure(bg=self._theme()["hover"]))
                w.bind("<Leave>", lambda e: hdr_lbl.configure(bg=self._theme()["bg"]))

        # ── sub-option rows (only shown when expanded, and only if not defaulted) ──
        if options and not has_default:
            for opt in options:
                opt_label = self.OPTION_LABELS.get(opt, opt)
                row = tk.Frame(body, bg=t["bg"])
                row.pack(fill='x', pady=1, padx=(18, 0))

                opt_lbl = tk.Label(row, text=opt_label, bg=t["bg"], fg=t["fg"],
                                   font=('', 9), anchor='w')
                opt_lbl.pack(side='left', fill='x', expand=True)
                self._suboption_labels.setdefault(label, []).append(opt_lbl)

                rbf = tk.Frame(row, bg=t["fg"], padx=1, pady=1)
                rbl = tk.Label(rbf, text="▶", bg=t["bg"], fg=t["fg"],
                               font=('', 9), padx=5, cursor="hand2")
                rbl.pack()
                rbf.pack(side='right', padx=(4, 2))

                rbl.bind("<Button-1>",
                         lambda e, fn=run_fn, o=opt, jn=label:
                         self._inject_and_run(fn, o, jn))
                rbl.bind("<Enter>",
                         lambda e, b=rbl: b.configure(bg=self._theme()["hover"]))
                rbl.bind("<Leave>",
                         lambda e, b=rbl: b.configure(bg=self._theme()["bg"]))
                opt_lbl.bind("<Enter>",
                             lambda e, b=opt_lbl: b.configure(bg=self._theme()["hover"]))
                opt_lbl.bind("<Leave>",
                             lambda e, b=opt_lbl: b.configure(bg=self._theme()["bg"]))

    @property
    def _tool_fns(self):
        return {
            "Folders to PDF":     lambda: folders_to_pdf(self.config, self.cancel_event),
            "Images to PDF":      lambda: images_to_pdf(self.config, self.cancel_event),
            "Folder Renamer":     lambda: folder_renamer(self.config, self.cancel_event),
            "File Renamer":       lambda: file_renamer(self.config, self.cancel_event),
            "Combine Image Sets": lambda: combine_image_sets(self.config, self.cancel_event),
            "Image Converter":    lambda: image_converter(self.config, self.cancel_event),
            "Find Duplicates":    lambda: find_duplicates(self.config, self.cancel_event),
            "PDF Combiner":       lambda: pdf_combiner(self.config, self.cancel_event),
            "PDF Splitter":       lambda: pdf_splitter(self.config, self.cancel_event),
            "PDF to Images":      lambda: pdf_to_images(self.config, self.cancel_event),
            "Add Input":          lambda: self.pick_files(),
        }

    def _inject_and_run(self, run_fn, choice, job_name):
        direct_fn = self._tool_fns.get(job_name)
        if direct_fn is None:
            self._run(run_fn, job_name=job_name)
            return

        # Special case: Add Input routes choice directly to pick_files
        if job_name == "Add Input":
            self._run(lambda c=choice: self.pick_files(c), job_name=job_name)
            return

        config_key = self.TOOL_MODE_CONFIG_KEY.get(job_name) if choice is not None else None

        if config_key:
            original = self.config.get(config_key)
            self.config[config_key] = choice

            fn_snapshot = self._tool_fns[job_name]

            def run_with_restore():
                try:
                    fn_snapshot()
                finally:
                    self.config[config_key] = original

            self._run(run_with_restore, job_name=job_name)
        else:
            self._run(direct_fn, job_name=job_name)

    def _run(self, fn, ignore_lock=False, job_name="Job"):
        if self._running_jobs and not ignore_lock:
            if not self.config.get("allow_concurrent_jobs", False):
                print("  A job is already running. Wait for it to finish or cancel it first.")
                return
            if job_name in self._running_jobs:
                print(f"  {job_name} is already running.")
                return
        self.cancel_event.clear()

        if job_name != "Add Input" and self.config.get("show_timestamps", True):
            from datetime import datetime
            font_size = self._log_font_size
            line_len = max(10, int(55 - (font_size - 7) * 2.5))
            line = "─" * line_len
            timestamp = datetime.now().strftime("%H:%M:%S")

            self.log.configure(state='normal')
            self.log.tag_configure("ts_dim", foreground=self._theme()["log_dim"])
            self.log.insert(tk.END, f"\n{timestamp}\n{line}\n\n", ("ts_dim",))
            self.log.see(tk.END)
            self.log.configure(state='disabled')
        self._running_jobs[job_name] = self._running_jobs.get(job_name, 0) + 1
        self._update_status_label()

        def wrapper():
            try:
                fn()
            finally:
                count = self._running_jobs.get(job_name, 1) - 1
                if count <= 0:
                    self._running_jobs.pop(job_name, None)
                else:
                    self._running_jobs[job_name] = count
                self.root.after(0, self._update_status_label)

        threading.Thread(target=wrapper, daemon=True).start()

    def cancel_job(self):
        if not self._running_jobs:
            print("  No job is running.")
            return
        self.cancel_event.set()
        print("  Cancelling...")

    def _update_status_label(self):
        if not self._running_jobs:
            self._status_lbl.configure(text="")
        else:
            names = []
            for name, count in self._running_jobs.items():
                names.append(f"{name}" if count == 1 else f"{name} ×{count}")
            self._status_lbl.configure(text="● " + "  |  ".join(names))

    def clear_log(self):
        self.log.configure(state='normal')
        self.log.delete('1.0', tk.END)
        self.log.configure(state='disabled')

    def clear_output(self):
        out_dir = Path(self.config["output"]) / "output"
        if not out_dir.exists() or not any(out_dir.iterdir()):
            print("Output folder is already empty.")
            return
        for item in out_dir.iterdir():
            try:
                shutil.rmtree(item) if item.is_dir() else item.unlink()
            except Exception as e:
                print(f"Failed to delete {item.name}: {e}")
        print("Output cleared.")

    def clear_input(self):
        input_dir = get_input(self.config)
        if not input_dir.exists() or not any(input_dir.iterdir()):
            print("Input folder is already empty.")
            return
        for item in input_dir.iterdir():
            try:
                shutil.rmtree(item) if item.is_dir() else item.unlink()
            except Exception as e:
                print(f"Failed to delete {item.name}: {e}")
        print("Input cleared.")

    def _show_preferences(self):
        t = THEMES["light"]
        win = tk.Toplevel(self.root)
        win.title("Preferences")
        win.resizable(True, True)
        win.geometry("640x520")
        win.configure(bg=t["bg"])

        outer = tk.Frame(win, bg=t["bg"])
        outer.pack(fill='both', expand=True)

        sidebar = tk.Frame(outer, width=110, bg=t["btn_bg"])
        sidebar.pack(side='left', fill='y')
        sidebar.pack_propagate(False)

        content_area = tk.Frame(outer, bg=t["bg"])
        content_area.pack(side='left', fill='both', expand=True)

        pages = {}
        for name in ("Paths", "General", "Tools", "Hotkeys", "Throttle", "Buttons"):
            f = tk.Frame(content_area, bg=t["bg"], padx=16, pady=12)
            f.grid(row=0, column=0, sticky='nsew')
            pages[name] = f

        content_area.grid_rowconfigure(0, weight=1)
        content_area.grid_columnconfigure(0, weight=1)

        tab_lbls = {}
        active_tab = {"name": None}

        def show_tab(name):
            active_tab["name"] = name
            pages[name].tkraise()
            for n, lbl in tab_lbls.items():
                lbl.configure(bg=t["hover"] if n == name else t["btn_bg"], fg=t["fg"])
            win.update_idletasks()

        tk.Label(sidebar, text="Preferences", font=('', 8),
                 bg=t["btn_bg"], fg=t["hint_fg"], pady=8).pack(fill='x')

        for name in pages:
            lbl = tk.Label(sidebar, text=name, anchor='w', padx=12,
                           bg=t["btn_bg"], fg=t["fg"], font=('', 10),
                           cursor="hand2")
            lbl.pack(fill='x', ipady=7)
            lbl.bind("<Button-1>", lambda e, n=name: show_tab(n))
            lbl.bind("<Enter>", lambda e, l=lbl, n=name: l.configure(
                bg=t["bg"] if active_tab["name"] == n else t["hover"]))
            lbl.bind("<Leave>", lambda e, l=lbl, n=name: l.configure(
                bg=t["bg"] if active_tab["name"] == n else t["btn_bg"]))
            tab_lbls[name] = lbl

        tk.Frame(sidebar, bg=t["btn_bg"]).pack(fill='both', expand=True)

        paths = {
            "input": tk.StringVar(value=self.config.get("input", "")),
            "output": tk.StringVar(value=self.config.get("output", "")),
        }
        lbl_vals = {}

        def pick(key):
            chosen = filedialog.askdirectory(title=f"Select {key} directory")
            if chosen:
                paths[key].set(chosen)
                refresh()

        def set_both():
            inp = paths["input"].get()
            if not inp:
                pick("input")
                inp = paths["input"].get()
            if inp:
                paths["output"].set(inp)
                refresh()

        def refresh():
            for key in ("input", "output"):
                val = paths[key].get()
                lbl_vals[key].configure(state='normal')
                lbl_vals[key].delete(0, tk.END)
                lbl_vals[key].insert(0, val if val else "")
                lbl_vals[key].configure(state='readonly')

        def _pref_btn(parent, text, cmd):
            lbl = tk.Label(parent, text=text, bg=t["bg"], fg=t["fg"],
                           font=('', 10), padx=6, cursor="hand2")
            lbl.bind("<Button-1>", lambda e: cmd())
            lbl.bind("<Enter>", lambda e: lbl.configure(bg=t["hover"]))
            lbl.bind("<Leave>", lambda e: lbl.configure(bg=t["bg"]))
            return lbl

        # ── PATHS tab ──────────────────────────────────────────────────────────
        p = pages["Paths"]
        r = 0
        tk.Label(p, text="Paths", font=('', 11, 'bold'), bg=t["bg"]).grid(
            row=r, column=0, columnspan=2, sticky='w', pady=(0, 8))
        r += 1

        for key, title in (("input", "Input directory"), ("output", "Output directory")):
            tk.Label(p, text=title, anchor='w', bg=t["bg"]).grid(
                row=r, column=0, columnspan=2, sticky='w', pady=(6, 0))
            r += 1
            e = tk.Entry(p, width=40, readonlybackground=t["entry_bg"])
            e.insert(0, paths[key].get())
            e.configure(state='readonly')
            e.grid(row=r, column=0, sticky='w')
            lbl_vals[key] = e
            _pref_btn(p, "Browse…", lambda k=key: pick(k)).grid(
                row=r, column=1, padx=(6, 0), sticky='w')
            r += 1

        _pref_btn(p, "Set Both", set_both).grid(
            row=r, column=0, sticky='w', pady=(6, 0))
        r += 1

        # ── GENERAL tab ────────────────────────────────────────────────────────
        p = pages["General"]
        tk.Label(p, text="General", font=('', 11, 'bold'), bg=t["bg"]).grid(
            row=0, column=0, columnspan=2, sticky='w', pady=(0, 8))

        general_fields = [
            ("ui_mode",                "UI Mode",                            "combo", ["classic", "dropdown"]),
            ("allow_concurrent_jobs",  "Allow Multiple Jobs at Once",        "check", None),
            ("auto_clear_input",       "Auto Clear Input After Job",         "check", None),
            ("ask_run_name",           "Ask for Run Name",                   "check", None),
            ("replace_output",         "Replace Output Each Run",            "check", None),
            ("sort_output",            "Sort Output by Operation",           "check", None),
            ("guide_empty_input",      "Dim Tools when Input Empty",         "check", None),
            ("show_tooltips",          "Show Tooltip Hints",                 "check", None),
            ("log_default_expanded",   "Log Sections Expanded by Default",   "check", None),
            ("show_timestamps", "Show Timestamps in Log",                    "check", None),
            ("min_free_gb",            "Min Free Space to Start (GB)",       "combo", ["0","1","2","3","5","10"]),
        ]

        tools_fields = [
            ("default_folders_to_pdf_mode", "Folders to PDF: Default Mode",   "combo", ["ask", "combine", "individual"]),
            ("default_sort",               "Default Sort Mode",               "combo", ["ask","natural","none"]),
            ("default_folder_renamer_mode", "Folder Renamer: Default Mode",   "combo", ["ask", "prefix", "suffix", "replace", "extract number"]),
            ("default_file_renamer_mode",  "File Renamer: Default Mode",      "combo", ["ask", "prefix", "suffix", "replace", "sequence"]),
            ("default_img_fmt",            "Default Image Format",            "combo", ["ask", "jpg", "png", "webp", "bmp", "tiff"]),
            ("default_dedupe_mode",        "Find Duplicates: Default Mode",   "combo", ["ask", "keep one copy", "delete all"]),
            ("default_dpi",               "Default DPI (PDF to Images)",      "combo", ["ask","72","96","150","200","300","600"]),
        ]

        hotkey_fields = [
            ("hotkey_continue", "Continue Hotkey", "combo", ["Return","space","Right"]),
            ("hotkey_cancel",   "Cancel Hotkey",   "combo", ["Escape","space","Left"]),
        ]

        throttle_fields = [
            ("throttle_cpu", "Max CPU % (0 = off)", "combo", ["0","50","60","70","80","90"]),
            ("throttle_mem", "Max Memory % (0 = off)", "combo", ["0","50","60","70","80","90"]),
        ]

        vars_ = {}

        def build_fields(page, fields, start_row=1):
            for i, (key, label, typ, opts) in enumerate(fields):
                row = start_row + i
                tk.Label(page, text=label, anchor='w', bg=t["bg"]).grid(
                    row=row, column=0, sticky='w', pady=4, padx=(0, 16))
                if typ == "check":
                    default = True if key in ("guide_empty_input", "show_tooltips") else False
                    v = tk.BooleanVar(value=bool(self.config.get(key, default)))
                    tk.Checkbutton(page, variable=v, bg=t["bg"]).grid(row=row, column=1, sticky='w')
                else:
                    v = tk.StringVar(value=str(self.config.get(key, opts[0])))
                    ttk.Combobox(page, textvariable=v, values=opts,
                                 state='readonly', width=16).grid(row=row, column=1, sticky='w')
                vars_[key] = v

        build_fields(pages["General"], general_fields)

        p = pages["Tools"]
        tk.Label(p, text="Tools", font=('', 11, 'bold'), bg=t["bg"]).grid(
            row=0, column=0, columnspan=2, sticky='w', pady=(0, 8))
        build_fields(p, tools_fields)

        p = pages["Hotkeys"]
        tk.Label(p, text="Hotkeys", font=('', 11, 'bold'), bg=t["bg"]).grid(
            row=0, column=0, columnspan=2, sticky='w', pady=(0, 8))
        build_fields(p, hotkey_fields)

        p = pages["Throttle"]
        tk.Label(p, text="Throttle", font=('', 11, 'bold'), bg=t["bg"]).grid(
            row=0, column=0, columnspan=2, sticky='w', pady=(0, 8))
        tk.Label(p, text="Limit resource usage during jobs.", fg=t["hint_fg"],
                 bg=t["bg"], font=('', 9)).grid(row=1, column=0, columnspan=2, sticky='w', pady=(0, 8))
        build_fields(p, throttle_fields, start_row=2)

        p = pages["Buttons"]
        tk.Label(p, text="Visible Buttons", font=('', 11, 'bold'), bg=t["bg"]).grid(
            row=0, column=0, columnspan=2, sticky='w', pady=(0, 8))

        btn_vars = {}
        for i, (key, section, label, _) in enumerate(self.TOGGLEABLE):
            v = tk.BooleanVar(value=bool(self.config.get(key, True)))
            tk.Label(p, text=f"{label}  ({section})", anchor='w', bg=t["bg"]).grid(
                row=i + 1, column=0, sticky='w', pady=3)
            tk.Checkbutton(p, variable=v, bg=t["bg"]).grid(row=i + 1, column=1, sticky='w')
            btn_vars[key] = v

        def save():
            for key in ("input", "output"):
                val = paths[key].get().strip()
                if val and Path(val).exists():
                    self.config[key] = val
                elif val:
                    messagebox.showwarning("Invalid Path", f"Does not exist: {val}")
                    return
            for key, v in vars_.items():
                val = v.get()
                if key in ("auto_clear_input", "replace_output", "sort_output",
                           "guide_empty_input", "show_tooltips", "allow_concurrent_jobs",
                           "log_default_expanded", "show_timestamps"):
                    self.config[key] = bool(val)
                elif key in ("throttle_cpu", "throttle_mem"):
                    self.config[key] = int(str(val).split()[0])
                elif key == "default_dpi":
                    self.config[key] = val if val == "ask" else int(val)
                elif key == "min_free_gb":
                    self.config[key] = int(str(val).split()[0])
                else:
                    self.config[key] = val
            for key, v in btn_vars.items():
                self.config[key] = bool(v.get())
            save_config(self.config)
            self._update_button_states()
            self._rebuild_buttons()
            win.destroy()

        for text, cmd in (("Cancel", win.destroy), ("Save", save)):
            lbl = tk.Label(sidebar, text=text, anchor='w', padx=12,
                           bg=t["btn_bg"], fg=t["fg"], font=('', 10),
                           cursor="hand2")
            lbl.pack(fill='x', ipady=7, side='bottom')
            lbl.bind("<Button-1>", lambda e, c=cmd: c())
            lbl.bind("<Enter>", lambda e, l=lbl: l.configure(bg=t["hover"]))
            lbl.bind("<Leave>", lambda e, l=lbl: l.configure(bg=t["btn_bg"]))

        show_tab("Paths")

    def pick_files(self, choice=None):
        if not self.config.get("input", ""):
            print("  Input folder is not configured. Set it in Preferences (≡).")
            return

        input_dir = get_input(self.config)
        input_dir.mkdir(parents=True, exist_ok=True)
        dialog_result = queue.Queue()

        def open_dialog(c):
            if c == "files":
                paths = filedialog.askopenfilenames(title="Select files to add to Input")
                dialog_result.put(list(paths))
            elif c == "folder":
                folder = filedialog.askdirectory(title="Select a folder to add to Input")
                dialog_result.put([folder] if folder else [])
            else:
                dialog_result.put([])

        def run():
            if choice is None:
                # Classic mode — key-press flow
                print("Add to Input")
                print("  Enter = Files   Space = Folder   Escape = Cancel")
                raw = thread_safe_input("Waiting for key...").strip()
                if raw == "FILES":
                    c = "files"
                elif raw == "FOLDER":
                    c = "folder"
                else:
                    print("  Cancelled.")
                    return
            else:
                c = choice

            self.root.after(0, lambda: open_dialog(c))
            paths = dialog_result.get()
            if not paths:
                print("  Nothing selected.")
                return
            print(f"  Copying {len(paths)} item(s) to Input...")
            ok, fail = 0, 0
            for p in paths:
                src = Path(p)
                dest = input_dir / src.name
                try:
                    if src.is_dir():
                        shutil.copytree(str(src), str(dest), dirs_exist_ok=True)
                    else:
                        shutil.copy2(str(src), str(dest))
                    ok += 1
                except Exception as e:
                    print(f"  Failed: {src.name}: {e}")
                    fail += 1
            print(f"  Done! {ok} added{f', {fail} failed' if fail else ''} → {input_dir}")

        self._run(run, job_name="Add Input")

    def run_folders_to_pdf(self):
        self._run(lambda: folders_to_pdf(self.config, self.cancel_event), job_name="Folders to PDF")

    def run_images_to_pdf(self):
        self._run(lambda: images_to_pdf(self.config, self.cancel_event), job_name="Images to PDF")

    def run_folder_renamer(self):
        self._run(lambda: folder_renamer(self.config, self.cancel_event), job_name="Folder Renamer")

    def run_file_renamer(self):
        self._run(lambda: file_renamer(self.config, self.cancel_event), job_name="File Renamer")

    def run_combine(self):
        self._run(lambda: combine_image_sets(self.config, self.cancel_event), job_name="Combine Image Sets")

    def run_converter(self):
        self._run(lambda: image_converter(self.config, self.cancel_event), job_name="Image Converter")

    def run_duplicates(self):
        self._run(lambda: find_duplicates(self.config, self.cancel_event), job_name="Find Duplicates")

    def run_pdf_splitter(self):
        self._run(lambda: pdf_splitter(self.config, self.cancel_event), job_name="PDF Splitter")

    def run_pdf_combiner(self):
        self._run(lambda: pdf_combiner(self.config, self.cancel_event), job_name="PDF Combiner")

    def run_pdf_to_images(self):
        self._run(lambda: pdf_to_images(self.config, self.cancel_event), job_name="PDF to Images")

    def run_status(self):
        if self._status_running:
            return

        def _run():
            self._status_running = True
            try:
                status(self.config)
            finally:
                self._status_running = False

        self._run(_run, ignore_lock=True, job_name="Status")


if __name__ == "__main__":
    root = tk.Tk()
    root.geometry("900x600")
    app = App(root)
    root.mainloop()
