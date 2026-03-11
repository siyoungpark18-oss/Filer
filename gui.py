import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
from pathlib import Path
import threading
import queue
import sys
import io
import shutil




from Manager import (
  load_config, save_config, get_input,
  folders_to_pdf, images_to_pdf, folder_renamer, file_renamer,
  combine_image_sets, image_converter, pdf_splitter, pdf_combiner,
  pdf_to_images, status, find_duplicates, DEFAULTS, SENTINEL
)




THEMES = {
   "light": {
       "bg":        "#f0f0f0",
       "fg":        "#000000",
       "log_bg":    "#ffffff",
       "log_fg":    "#000000",
       "entry_bg":  "#ffffff",
       "entry_fg":  "#000000",
       "btn_bg":    "#e0e0e0",
       "btn_fg":    "#000000",
       "hint_fg":   "gray",
       "hover":     "#d0d0d0",
   },
   "dark": {
       "bg":        "#1e1e1e",
       "fg":        "#d4d4d4",
       "log_bg":    "#252526",
       "log_fg":    "#d4d4d4",
       "entry_bg":  "#3c3c3c",
       "entry_fg":  "#d4d4d4",
       "btn_bg":    "#3c3c3c",
       "btn_fg":    "#d4d4d4",
       "hint_fg":   "#888888",
       "hover":     "#4e4e4e",
   },
}




class LogRedirect(io.TextIOBase):
  def __init__(self, log_widget):
      self.log = log_widget


  def write(self, msg):
      if msg.strip():
          self.log.configure(state='normal')
          self.log.insert(tk.END, msg if msg.endswith('\n') else msg + '\n')
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




class App:
  def __init__(self, root):
      self.root = root
      self.root.title("File & Folder Manager")
      self.root.resizable(True, True)
      self.config = load_config()
      self.cancel_event = threading.Event()
      self._dark = self.config.get("dark_mode", False)
      patch_input()
      self._build_ui()
      self._apply_theme()
      sys.stdout = LogRedirect(self.log)
      sys.stderr = LogRedirect(self.log)
      self._poll_input()


  def _theme(self):
      return THEMES["dark"] if self._dark else THEMES["light"]


  def _apply_theme(self):
      t = self._theme()
      self.root.configure(bg=t["bg"])
      for widget in [self.root, self._btn_frame, self._right]:
          self._apply_to_widget(widget, t)
      self.log.configure(bg=t["log_bg"], fg=t["log_fg"],
                         insertbackground=t["log_fg"])


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


  def _poll_input(self):
      try:
          prompt = input_queue.get_nowait()
          self._show_inline_input(prompt)
      except queue.Empty:
          pass
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
          cancel_key   = self.config.get("hotkey_cancel",   "Delete")
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
          entry.bind("<space>",  pick_folder)
          entry.bind("<Escape>", cancel)
      else:
          continue_key = self.config.get("hotkey_continue", "Return")
          cancel_key   = self.config.get("hotkey_cancel",   "Delete")


          def confirm(e=None):
              val = var.get()
              self._input_frame.destroy()
              result_queue.put(val)


          def cancel(e=None):
              self._input_frame.destroy()
              result_queue.put(SENTINEL)


          entry.bind(f"<{continue_key}>", confirm)
          entry.bind(f"<{cancel_key}>",   cancel)


  def _show_help(self):
      win = tk.Toplevel(self.root)
      win.title("Help")
      win.geometry("600x620")
      win.resizable(False, False)


      text = scrolledtext.ScrolledText(win, wrap='word', font=('Courier', 11),
                                       padx=10, pady=10)
      text.pack(fill='both', expand=True)


      help_text = """FILE & FOLDER MANAGER — HELP




All commands read from the Input folder.
Use "Add to Input" to copy files/folders in.
Use "Clear Input" to empty it when done.




━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FILE & FOLDER COMMANDS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━




Folders to PDF
Converts folders of images into a single PDF.




Images to PDF
Converts loose images into a single PDF.




Sort Folders
Copies files/folders into numbered subfolders
based on the number found in their name.




Mass Rename
Bulk rename files. Modes: Prefix, Suffix,
Replace, Sequence. Originals not modified.




Combine Image Sets
Merges image folders into one output folder,
renumbering images sequentially.




Image Converter
Converts all images to a target format.
Supported: jpg, png, webp, bmp, tiff




Find Duplicates
Finds exact duplicate images by MD5 hash.
Optionally deletes them.




PDF Splitter
Splits a PDF into parts at page boundaries.




PDF Combiner
Merges multiple PDFs into one.




PDF to Images
Converts PDF pages to image files.
Requires poppler (brew install poppler).




━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OTHER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━




Status     — show Input and Output contents
Config     — set input/output directories
Settings   — hotkeys and defaults
Add to Input — copy files or a folder into Input
Clear Input  — wipe Input folder




━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOTES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Everything runs locally. Nothing is uploaded.
• All operations work on copies.
• Natural sort used throughout (1, 2, 10...).
• Prompts appear in the log — respond in the
  input bar that appears at the bottom.
"""
      text.insert('1.0', help_text)
      text.configure(state='disabled')
      tk.Button(win, text="Close", command=win.destroy).pack(pady=8)


  def _build_ui(self):
      left = tk.Frame(self.root, width=200)
      left.pack(side='left', fill='y', padx=10, pady=10)
      left.pack_propagate(False)


      title_row = tk.Frame(left)
      title_row.pack(fill='x', pady=(0, 4))
      tk.Label(title_row, text="File & Folder Manager", font=('', 11, 'bold')).pack(side='left')


      def _mini_btn(parent, text_or_var, cmd, side='right'):
          t = self._theme()
          f = tk.Frame(parent, bg=t["fg"], padx=1, pady=1)
          lbl = tk.Label(f, bg=t["bg"], fg=t["fg"], font=('', 10), width=2, cursor="hand2")
          if isinstance(text_or_var, str):
              lbl.configure(text=text_or_var)
          lbl.pack()
          lbl.bind("<Button-1>", lambda e: cmd())
          lbl.bind("<Enter>",    lambda e: lbl.configure(bg=self._theme()["hover"]))
          lbl.bind("<Leave>",    lambda e: lbl.configure(bg=self._theme()["bg"]))
          f.pack(side=side, padx=(2, 0))
          return lbl


      _mini_btn(title_row, "?", self._show_help)
      self._dark_btn = _mini_btn(title_row, "🌙" if not self._dark else "☀", self._toggle_dark)


      self._btn_frame = tk.Frame(left)
      self._btn_frame.pack(fill='both', expand=True)


      self._right = tk.Frame(self.root)
      self._right.pack(side='left', fill='both', expand=True, padx=(0, 10), pady=10)
      tk.Label(self._right, text="Log", font=('', 11, 'bold')).pack(anchor='w')


      log_frame = tk.Frame(self._right)
      log_frame.pack(fill='both', expand=True)


      self._scrollbar = tk.Scrollbar(log_frame)
      self._scrollbar.pack(side='right', fill='y')


      self.log = tk.Text(log_frame, state='disabled', wrap='word', font=('Courier', 11),
                         yscrollcommand=self._on_scroll)
      self.log.pack(side='left', fill='both', expand=True)
      self._scrollbar.config(command=self.log.yview)
      self._scrollbar.pack_forget()


      self._rebuild_buttons()


  TOGGLEABLE = [
      ("show_folders_to_pdf",     "Folder", "Folders to PDF",     "run_folders_to_pdf"),
      ("show_images_to_pdf",      "Folder", "Images to PDF",      "run_images_to_pdf"),
      ("show_folder_renamer",     "Folder", "Folder Renamer",     "run_folder_renamer"),
      ("show_file_renamer",       "Folder", "File Renamer",       "run_file_renamer"),
      ("show_combine",            "Folder", "Combine Image Sets", "run_combine"),
      ("show_converter",          "Folder", "Image Converter",    "run_converter"),
      ("show_duplicates",         "Folder", "Find Duplicates",    "run_duplicates"),
      ("show_pdf_combiner",       "Folder", "PDF Combiner",       "run_pdf_combiner"),
      ("show_pdf_splitter",       "File",   "PDF Splitter",       "run_pdf_splitter"),
      ("show_pdf_to_images",      "File",   "PDF to Images",      "run_pdf_to_images"),
  ]


  def _make_button(self, parent, text, cmd):
      t = self._theme()
      f = tk.Frame(parent, bg=t["fg"], padx=1, pady=1)
      lbl = tk.Label(f, text=text, bg=t["bg"], fg=t["fg"],
                     font=('', 10), width=22, cursor="hand2")
      lbl.pack()
      lbl.bind("<Button-1>", lambda e: cmd())
      lbl.bind("<Enter>",    lambda e: lbl.configure(bg=self._theme()["hover"]))
      lbl.bind("<Leave>",    lambda e: lbl.configure(bg=self._theme()["bg"]))
      f.pack(pady=2)
      return f, lbl


  def _rebuild_buttons(self):
      for w in self._btn_frame.winfo_children():
          w.destroy()


      fixed_sections = [
          ("Input", [
              ("Add Input",    self.pick_files),
              ("Clear Input",  self.clear_input),
          ]),
          ("Utility", [
              ("Status",       self.run_status),
              ("Clear Log",    self.clear_log),
              ("Clear Output", self.clear_output),
              ("Cancel Job",   self.cancel_job),
          ]),
          ("Preferences", [
              ("Config",       self.open_config),
              ("Options",      self.open_settings),
          ]),
      ]


      from collections import OrderedDict
      toggleable_sections = OrderedDict()
      for key, section, label, method in self.TOGGLEABLE:
          if self.config.get(key, True):
              toggleable_sections.setdefault(section, []).append((label, getattr(self, method)))


      all_sections = list(toggleable_sections.items()) + fixed_sections


      for section_label, cmds in all_sections:
          tk.Label(self._btn_frame, text=section_label, font=('', 10, 'bold')).pack(anchor='w', pady=(8, 2))
          for label, cmd in cmds:
              self._make_button(self._btn_frame, label, cmd)


      self._apply_theme()


  def _run(self, fn):
      self.cancel_event.clear()
      self._job_running = True
      def wrapper():
          try:
              fn()
          finally:
              self._job_running = False
      threading.Thread(target=wrapper, daemon=True).start()


  def cancel_job(self):
      if not getattr(self, '_job_running', False):
          print("  No job is running.")
          return
      self.cancel_event.set()
      print("  Cancelling...")


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


  def open_config(self):
      win = tk.Toplevel(self.root)
      win.title("Config")
      win.resizable(False, False)


      labels = [("input", "Input directory"), ("output", "Output directory")]
      entries = {}
      for i, (key, label) in enumerate(labels):
          tk.Label(win, text=label, anchor='w').grid(
              row=i, column=0, padx=10, pady=4, sticky='w')
          e = tk.Entry(win, width=50)
          e.insert(0, self.config.get(key, ""))
          e.grid(row=i, column=1, padx=10, pady=4)
          entries[key] = e


      def save():
          for key, entry in entries.items():
              val = entry.get().strip()
              if val and Path(val).exists():
                  self.config[key] = val
              elif val:
                  messagebox.showwarning("Invalid Path", f"Does not exist: {val}")
                  return
          save_config(self.config)
          win.destroy()


      def set_all():
          path = entries["input"].get().strip()
          if path and Path(path).exists():
              for e in entries.values():
                  e.delete(0, tk.END)
                  e.insert(0, path)


      btn = tk.Frame(win)
      btn.grid(row=len(labels), column=0, columnspan=2, pady=10)
      for txt, cmd in [("Set All", set_all), ("Save", save), ("Cancel", win.destroy)]:
          tk.Button(btn, text=txt, command=cmd).pack(side='left', padx=5)


  def open_settings(self):
      win = tk.Toplevel(self.root)
      win.title("Options")
      win.resizable(False, False)


      fields = [
          ("auto_clear_input", "Auto Clear Input After Job",    "check", None),
          ("replace_output",   "Replace Output Each Run",       "check", None),
          ("sort_output",      "Sort Output by Operation Type", "check", None),
          ("default_sort",     "Default Sort Mode",             "combo", ["ask", "natural", "none"]),
          ("default_dpi",      "Default DPI (PDF to Images)",   "combo", ["ask", "72", "96", "150", "200", "300", "600"]),
          ("default_img_fmt",  "Default Image Format",          "combo", ["ask", "jpg", "png", "webp", "bmp", "tiff"]),
          ("hotkey_continue",  "Continue Hotkey",               "combo", ["Return", "space", "Right"]),
          ("hotkey_cancel",    "Cancel Hotkey",                 "combo", ["Escape", "space", "Left"]),
          ("throttle_cpu",     "Throttle: Max CPU % (0 = off)",      "combo", ["0", "50", "60", "70", "80", "90"]),
          ("throttle_mem",     "Throttle: Max Memory % (0 = off)",   "combo", ["0", "50", "60", "70", "80", "90"]),
      ]


      row = 0
      tk.Label(win, text="General", font=('', 10, 'bold'), anchor='w').grid(
          row=row, column=0, columnspan=2, padx=10, pady=(10, 2), sticky='w')
      row += 1


      vars_ = {}
      for key, label, typ, opts in fields:
          tk.Label(win, text=label, anchor='w').grid(
              row=row, column=0, padx=10, pady=5, sticky='w')
          if typ == "check":
              v = tk.BooleanVar(value=bool(self.config.get(key, False)))
              tk.Checkbutton(win, variable=v).grid(row=row, column=1, padx=10, sticky='w')
          else:
              v = tk.StringVar(value=str(self.config.get(key, opts[0])))
              ttk.Combobox(win, textvariable=v, values=opts, state='readonly', width=20).grid(
                  row=row, column=1, padx=10, sticky='w')
          vars_[key] = v
          row += 1


      tk.Label(win, text="Visible Buttons", font=('', 10, 'bold'), anchor='w').grid(
          row=row, column=0, columnspan=2, padx=10, pady=(14, 2), sticky='w')
      row += 1


      btn_vars = {}
      for key, section, label, _ in self.TOGGLEABLE:
          v = tk.BooleanVar(value=bool(self.config.get(key, True)))
          tk.Label(win, text=f"{label}  ({section})", anchor='w').grid(
              row=row, column=0, padx=10, pady=3, sticky='w')
          tk.Checkbutton(win, variable=v).grid(row=row, column=1, padx=10, sticky='w')
          btn_vars[key] = v
          row += 1


      def save():
          for key, v in vars_.items():
              val = v.get()
              if key in ("auto_clear_input", "replace_output", "sort_output"):
                  self.config[key] = bool(val)
              elif key in ("throttle_cpu", "throttle_mem"):
                  self.config[key] = int(str(val).split()[0])
              elif key == "default_dpi":
                  self.config[key] = val if val == "ask" else int(val)
              else:
                  self.config[key] = val
          for key, v in btn_vars.items():
              self.config[key] = bool(v.get())
          save_config(self.config)
          self._rebuild_buttons()
          win.destroy()


      btn = tk.Frame(win)
      btn.grid(row=row, column=0, columnspan=2, pady=10)
      tk.Button(btn, text="Save",   command=save).pack(side='left', padx=5)
      tk.Button(btn, text="Cancel", command=win.destroy).pack(side='left', padx=5)


  def pick_files(self):
      input_dir = get_input(self.config)
      input_dir.mkdir(parents=True, exist_ok=True)
      dialog_result = queue.Queue()


      def open_dialog(choice):
          if choice == "FILES":
              paths = filedialog.askopenfilenames(title="Select files to add to Input")
              dialog_result.put(list(paths))
          elif choice == "FOLDER":
              folder = filedialog.askdirectory(title="Select a folder to add to Input")
              dialog_result.put([folder] if folder else [])
          else:
              dialog_result.put([])


      def run():
          print("Add to Input")
          print("  Enter = Files   Space = Folder   Escape = Cancel")
          choice = thread_safe_input("Waiting for key...").strip()
          if choice not in ("FILES", "FOLDER"):
              print("  Cancelled.")
              return
          self.root.after(0, lambda: open_dialog(choice))
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


      self._run(run)


  def run_folders_to_pdf(self):  self._run(lambda: folders_to_pdf(self.config, self.cancel_event))
  def run_images_to_pdf(self):   self._run(lambda: images_to_pdf(self.config, self.cancel_event))
  def run_folder_renamer(self):  self._run(lambda: folder_renamer(self.config, self.cancel_event))
  def run_file_renamer(self):    self._run(lambda: file_renamer(self.config, self.cancel_event))
  def run_combine(self):         self._run(lambda: combine_image_sets(self.config, self.cancel_event))
  def run_converter(self):       self._run(lambda: image_converter(self.config, self.cancel_event))
  def run_duplicates(self):      self._run(lambda: find_duplicates(self.config, self.cancel_event))
  def run_pdf_splitter(self):    self._run(lambda: pdf_splitter(self.config, self.cancel_event))
  def run_pdf_combiner(self):    self._run(lambda: pdf_combiner(self.config, self.cancel_event))
  def run_pdf_to_images(self):   self._run(lambda: pdf_to_images(self.config, self.cancel_event))
  def run_status(self):          self._run(lambda: status(self.config))




if __name__ == "__main__":
  root = tk.Tk()
  root.geometry("900x600")
  app = App(root)
  root.mainloop()



