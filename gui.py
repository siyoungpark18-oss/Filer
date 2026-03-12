import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
from pathlib import Path
import threading
import queue
import sys
import io
import shutil
import webbrowser


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
        "log_bg":    "#f8f8f8",
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
        "log_bg":    "#2d2d2d",
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


# Tool button labels that should be dimmed when input is empty
TOOL_LABELS = {
    "Folders to PDF", "Images to PDF", "Folder Renamer", "File Renamer",
    "Combine Image Sets", "Image Converter", "Find Duplicates",
    "PDF Combiner", "PDF Splitter", "PDF to Images",
}


class App:
   def __init__(self, root):
       self.root = root
       self.root.title("File & Folder Manager")
       self.root.resizable(True, True)
       self.config = load_config()
       self.cancel_event = threading.Event()
       self._dark = self.config.get("dark_mode", False)
       # Track button label widgets: {text: lbl_widget}
       self._btn_labels = {}
       # Last known input item count for change detection
       self._last_input_count = -1
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
       # Re-apply dimming after theme change
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

       # ⚠ badge on Add Input and Config
       for label, lbl in self._btn_labels.items():
           try:
               if label in ("Add Input", "Config"):
                   if not configured:
                       current = lbl.cget("text")
                       if not current.startswith("⚠ "):
                           lbl.configure(text=f"⚠ {label}")
                   else:
                       lbl.configure(text=label)
           except tk.TclError:
               pass

       # Existing empty-input dimming (unchanged logic)
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

   def _poll_input(self):
       # Handle inline input requests from background threads
       try:
           prompt = input_queue.get_nowait()
           self._show_inline_input(prompt)
       except queue.Empty:
           pass

       # Update input count label and button states if count changed
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

       help_text = """Filer.

Filer is a file manager. 
To be more specific, it's specialized for image management en masse. It's meant to manage, convert, and compress folders with images or individual images in the thousands at a time and to do this with speed. 

And with this comes its true Niche or intended use. Ultimately, Filer is a companion to large scale Manga Piracy. To those who wish to own and obtain manga from third party sources you may find that a multitude of reasons can impede time-efficient management of what could be thousands of manga pages, each stored as an individual image. 

Following is the explanation of the use cases for each tool within this Niche. I hope it's useful in these areas at the very least.



The Intended use of each tool

Folders to PDF
This is a tool that quite unassumingly turns multiple folders into a PDF. However, this can be quite a feat to do manually when working with a manga. 

This tool is meant to be used to combine All or some of the individual chapters of a manga into a single pdf. Since chapters in a manga downloader such as Hakuneko or Mihon are downloaded individually, and a manga can have hundreds of chapters, this is a useful way to compress them into a single PDF if wanted. 

The PDF format is generally most useful for reading on monitors, provided were still talking about manga here.


Images to PDF
A companion tool to folders to pdf. This tool is comparatively simple and simply requires you to input a folder with multiple images in it. The tool will create an output based on the input.

This is also possible to do natively in many by simply pressing command A—or whatever shortcut allows you to select all files in a directory—and going through a selection process to create a PDF with the selected files. Which will vary depending on your operating system. In this case, the tool is not necessarily faster.


Folder Renamer
The folder renamer renames files based on the number in its file name. If there are multiple numbers, it is no good. 

However, its main use case is with Manga chapters. When manga is downloaded its usual format is in an image set form with the images of individual chapters or volumes in a folder.

Provided the naming conventions of the folders is simple and each folder is named by Chapter It can extract the number. This is useful in certain cases where the naming conventions are obscured by different scanlation groups.
For example, a MacOS computer system will sort files alphabetically by name so Chapter 27, Chapter 24 and Chapter 12 would be sorted before Episode 11, Episode 7 and Episode 3. By using the renamer, each folder will be renamed as just the Number, allowing the computer to sort by number effectively.

This program usually does nothing if there are no numbers available.


File Renamer
A similar but different tool that also renames files. They do not necessarily have to be an image or any format in this case. Instead of renaming individual files by number, it's more so designed for files. Manga translations usually do not name individual image files and instead simply sort them by chapter, hence this being the case.

This is a general renaming tool instead, which can replace certain parts of file names, add a prefix or suffix to the file name, or use the sequence function to sort by number similar to the file sorter. 

Sequence for example would name page1, photo2, file 3, with file1, file2, file3 for example, provided you use "file" as the base in this case


Combined Image Sets
This tool's ability is to combine multiple folders of images into a single folder with all the images. It should keep the same order.

In the context of a manga, it would combine for example folders Volume 1, Volume 2, and Volume 3 into a single folder. Normally, you'd have to move these files manually. If they are sorted by chapter—which can reach hundreds of chapters in a manga—this can be a real time saver. 

This combined image set can allow you to store entire completed works and all their chapters or volumes in 1 single folder. It would basically be a set of individual image files in a single folder. For larger works of Manga, this can mean thousands of individual image files that you would otherwise have to move manually. 

The combined image set is the Ideal format for a phone, but I never saw any good reason to keep them by chapter. I personally would rather organize each image set by the name of the work. If this is your stance as well, you're in luck, because this is the tool solely designed for this otherwise time consuming manual endeavor.


Image Converter
Can convert a ton of images to whatever format is on the list. In Manga scanlation, the file formats can vary between different forms internally within chapters. This tool can standardize the image format to make all the images a png or jpg, ect.


Find Duplicates
Finds exact image duplicates of files. Sometimes scanlation groups create scanlator pages where they can advertise. Usually these images are the same, so this is a pretty solid way to delete them. Rather dishonorable, but I never personally like to read these.


PDF combiner
Combines multiple pdfs. Nothing impressive honestly about this one you could do this locally much in the same way you can convert images to PDFs. It's here if one needs it though. Manga can be downloaded in the form of PDF's so if it's preferable to have them combined into a single pdf, this is the tool..


PDF Splitter
It splits pdfs at a certain page gap and creates both products. Each split process can split the pdf at multiple pages, and each sector of the PDF will be preserved in the output for use. Can be used to split combined volumes of manga or other media, though they usually aren't stored in PDF's and generally books favor epubs. 


PDF to Images
Converts A PDF to its prerequisite images. This is useful if you have the pdf but not the image set of a manga. Image sets are generally preferably for reading on a phone, so it can be useful if you only have the PDF and the image set is hard to obtain separately.
It's very resource intensive though. So resource intensive that sometimes it uses up all your computer's ram causing it to crash. 

DPI settings are for printing, so there's no reason to use a dpi higher than the minimum usually. Having it low should speed up the processing speed and have no noticeable effect on the files themselves



UTILITY

Add Input: 
Adds an input to the input folder. The desired output will be based on what's in the input folder


Clear Input:
Clears the current input folder and all of its files. The input folder still exists, but all the files are deleted from it. Since all the files moved into Input are copies of the original, no files are actually lost.


Status:
Displays what's currently in the input and output folders. A useful check. Otherwise you can also manually check what's in the input and output folders. Their directories are stated in Config.


Clear Log:
Clears the log in the user interface. It's best not to do this in the middle of a process so that you can see information on the current process.


Clear Output:
Clears the output folder and all of its files.


Cancel Job:
Cancels the current task. Since most of the tasks are so fast anyway, you likely even have time to cancel it unless the files in input are numerous. Usually, the program is so fast that you'll just end up clearing the output if you don't want it. 

However, processes like PDF to Images can be slow and take forever. You can use this button to cancel the current job. Because this program can take up a lot of RAM, this should prevent the app from using your resources for too long.


Config:
The config allows you to tell the program where you want the input and output files to be. This is useful if you manually want to check what's in them or manually move files into input and out of output. 

This is primarily useful since there's no streamlined way to find the output and move it to its desired location. But at the very least you can configure where the output is and place it in a place you can easily find.



Example of Workflow

First thing you need to do is add the files you want to work with
Click Add Input and add a manga volume or whatever files you want to process.

Next thing is you need to identify the process you want to apply to the files now in input and select it. Go through the instructions and process and the product will be in output.

Now take the product from output and move it wherever you'd like. The Output folder is not meant to store your desired files and newer outputs will replace older outputs as a functional way of deleting them. Move them to a place you can store or if you do not like the output or made a mistake, simply hit clear output. 

Once you've processed the input you can now clear the input if you don't need it. Usually the app does this for you by default, but you can turn that off in Config, allowing you to run multiple processes on an input before having you delete it manually. Once you don't need the input file, simply clear the input. You can check what's in the input or output with the Status button, that's what it's for.

This program is not meant to process multiple different inputs individually and only processes the files as a whole, so once an input file is not needed in the immediate future, you should delete it so it doesn't interfere with future processes.

If you want to process another set of files, then you simply add another input. Make sure to clear the input when you're done with it, but otherwise this is about it.



Other notes on Filers Functionality
This app is under active development by 1 dev and its fellow large language model. Its developer currently does not know how to code very well, but knows the basics.


"""
       text.insert('1.0', help_text)
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
       text.insert(tk.END, "Filer\n\n")
       text.insert(tk.END,
                   "Filer is a file manager. It's an open source project that specializes in managing image files in bulk. It's cool because you can manage files and the way they are formatted locally—no data or analytics are used and no data leaves your computer.\n\n")
       text.insert(tk.END, "To access the Github Page\n")
       insert_link("https://github.com/siyoungpark18-oss/Filer?tab=AGPL-3.0-1-ov-file")
       text.insert(tk.END, "\n\n\n")
       text.insert(tk.END, "To access the .dmg or disk image for MacOS users visit the link to download it here:\n")
       insert_link("https://drive.google.com/drive/u/2/folders/1gjRlr2hV7RjLBTGlGs2SqQgKNaW4T0Il")
       text.insert(tk.END,
                   "\nCurrently, to install its modern Windows or Linux counterpart, you must download the source files on github and run the builders.\n\n\n")
       text.insert(tk.END, "To view previous versions of Filer, visit the link ")
       insert_link("https://drive.google.com/drive/u/2/folders/1jT_qMHEpWVczcIwBHTYJt1QkrE6WL8pb")
       text.insert(tk.END, "\n\n")
       text.insert(tk.END,
                   "Filer—whats it for?\nWhile there are essentially an infinite number of file managers, Filer specializes in a few niches and carries a few advantages that I—the developer—think makes it worth considering in a few use cases.\n\n")
       text.insert(tk.END,
                   "This app works with copies—when using the app, feel free to delete the inputs and outputs as necessary because the original files are not lost. These utility functions exist to be used.\n\n")
       text.insert(tk.END,
                   "It's to be noted that only 1 file or folder can be attached at a time! It is very much possible to attach multiple files or folders, but it can be somewhat tedius. To process multiple files or folders at a time, it's suggested that you move all of the files you would like to manage into 1 folder beforehand and attach that folder all at once.\n\n")
       text.insert(tk.END,
                   "It is also suggested that there are only a few inputs at a time. With all processes the tool is capable of, you cannot pick the files within the input that are to be processed. It will process all of the files in the input automatically, and this is intentional. To avoid processing multiple files that are unrelated, you should clear the input periodically when you're done with the current files in input, and this is the intended workflow.\n\n")
       text.insert(tk.END,
                   "It has a few advantages, mainly that its\n- Open source—all the source files are on its github page available for download\n- Files are Locally Managed—there is no movement of any data or analytics\n- Minimalistic—the user interface is simple and quick to navigate once learned\n- Files are not uploaded, but rather copied into folders—This makes all file and folder processes much faster.\nBecause of this, you can also directly view the input and output folders and move files yourself separate from the interface.\n\n")
       text.insert(tk.END,
                   "This tool specializes in speed and volume—It may be a little more difficult to navigate for a beginner.\n\n\n")
       text.insert(tk.END,
                   "It has its disadvantages though with\n- Less Graphics—its probably not the easiest software out there to learn initially\n- Reliance on Keybinds—The software sometimes relies on keybinds for its request of input to avoid excessive pop-ups. This comes across as difficult to use.\n- Because of its speed, the Filer app can under certain circumstances use up all the available RAM resources and cause a computer to crash. This can be mitigated by the CPU and RAM throttles in the configuration to change it.\n- Only one folder or file can be attached at a time!!!\n")
       text.configure(state='disabled')

       tk.Button(win, text="Close", command=win.destroy).pack(pady=8)


   def _build_ui(self):
       left = tk.Frame(self.root, width=200)
       left.pack(side='left', fill='y', padx=10, pady=10)
       left.pack_propagate(False)

       title_row = tk.Frame(left)
       title_row.pack(fill='x', pady=(0, 2))
       tk.Label(title_row, text="File & Folder Manager", font=('', 11, 'bold')).pack(side='left')

       def _mini_btn(parent, text_or_var, cmd, side='right'):
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
           f.pack(side=side, padx=(2, 0))
           return lbl

       _mini_btn(title_row, "?", self._show_help)
       _mini_btn(title_row, "i", self._show_docs)
       self._dark_btn = _mini_btn(title_row, "🌙" if not self._dark else "☀", self._toggle_dark)

       # Live input status label
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

       log_frame = tk.Frame(self._right)
       log_frame.pack(fill='both', expand=True)

       self._scrollbar = tk.Scrollbar(log_frame)
       self._scrollbar.pack(side='right', fill='y')

       self.log = tk.Text(log_frame, state='disabled', wrap='word', font=('Courier', 11),
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
       "Config": "Set the Input and Output folder paths.",
       "Options": "Configure behaviour, defaults, throttles, and visible buttons.",
   }

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

       # Register for state management
       self._btn_labels[text] = lbl

       if tooltip and self.config.get("show_tooltips", True):
           info = tk.Label(row, text="i", bg=t["bg"], fg=t["hint_fg"],
                           font=('', 9), cursor="hand2", padx=2)
           info.pack(side='left', padx=(3, 0))
           info.bind("<Enter>", lambda e: info.configure(bg=self._theme()["hover"]))
           info.bind("<Leave>", lambda e: info.configure(bg=self._theme()["bg"]))
           self._show_tooltip(info, tooltip)

       return f, lbl

   def _rebuild_buttons(self):
       self._btn_labels.clear()
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
               self._make_button(self._btn_frame, label, cmd, tooltip=self.TOOLTIPS.get(label))

       self._apply_theme()
       self._update_button_states()

   def _run(self, fn):
       self.cancel_event.clear()
       self._job_running = True
       self.root.after(0, lambda: self._status_lbl.configure(text="● Running..."))

       def wrapper():
           try:
               fn()
           finally:
               self._job_running = False
               self.root.after(0, lambda: self._status_lbl.configure(text=""))
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

       paths = {
           "input": tk.StringVar(value=self.config.get("input", "")),
           "output": tk.StringVar(value=self.config.get("output", "")),
       }

       def pick(key):
           chosen = filedialog.askdirectory(title=f"Select {key} directory")
           if chosen:
               paths[key].set(chosen)
               _refresh_labels()

       def set_both():
           inp = paths["input"].get()
           if not inp:
               pick("input")
               inp = paths["input"].get()
           if inp:
               paths["output"].set(inp)
               _refresh_labels()

       def _refresh_labels():
           for key in ("input", "output"):
               val = paths[key].get()
               lbl_vals[key].configure(text=val if val else "  (not set)")

       row = 0
       lbl_vals = {}
       for key, title in (("input", "Input directory"), ("output", "Output directory")):
           tk.Label(win, text=title, anchor='w').grid(
               row=row, column=0, padx=10, pady=4, sticky='w')
           row += 1
           val = paths[key].get()
           lbl = tk.Entry(win, width=50, readonlybackground='white')
           lbl.insert(0, val if val else "")
           lbl.configure(state='readonly')
           lbl.grid(row=row, column=0, padx=10, pady=4)
           lbl_vals[key] = lbl
           tk.Button(win, text="Browse…", command=lambda k=key: pick(k)).grid(
               row=row, column=1, padx=(0, 10), pady=4)
           row += 1

       def _refresh_labels():
           for key in ("input", "output"):
               val = paths[key].get()
               lbl_vals[key].configure(state='normal')
               lbl_vals[key].delete(0, tk.END)
               lbl_vals[key].insert(0, val if val else "")
               lbl_vals[key].configure(state='readonly')

       btn = tk.Frame(win)
       btn.grid(row=row, column=0, columnspan=2, pady=10)
       for txt, cmd in [("Set Both", set_both), ("Save", lambda: _save()), ("Cancel", win.destroy)]:
           tk.Button(btn, text=txt, command=cmd).pack(side='left', padx=5)

       def _save():
           for key in ("input", "output"):
               val = paths[key].get().strip()
               if val and Path(val).exists():
                   self.config[key] = val
               elif val:
                   messagebox.showwarning("Invalid Path", f"Does not exist: {val}")
                   return
           save_config(self.config)
           self._update_button_states()
           win.destroy()

   def open_settings(self):
       win = tk.Toplevel(self.root)
       win.title("Options")
       win.resizable(False, False)

       fields = [
           ("auto_clear_input",   "Auto Clear Input After Job",        "check", None),
           ("replace_output",     "Replace Output Each Run",           "check", None),
           ("sort_output",        "Sort Output by Operation Type",     "check", None),
           ("guide_empty_input", "Dim out Tools when Input Empty",     "check", None),
           ("show_tooltips", "Show Tooltip Hints",                     "check", None),
           ("default_sort",       "Default Sort Mode",                 "combo", ["ask", "natural", "none"]),
           ("default_dpi",        "Default DPI (PDF to Images)",       "combo", ["ask", "72", "96", "150", "200", "300", "600"]),
           ("default_img_fmt",    "Default Image Format",              "combo", ["ask", "jpg", "png", "webp", "bmp", "tiff"]),
           ("hotkey_continue",    "Continue Hotkey",                   "combo", ["Return", "space", "Right"]),
           ("hotkey_cancel",      "Cancel Hotkey",                     "combo", ["Escape", "space", "Left"]),
           ("throttle_cpu",       "Throttle: Max CPU % (0 = off)",     "combo", ["0", "50", "60", "70", "80", "90"]),
           ("throttle_mem",       "Throttle: Max Memory % (0 = off)",  "combo", ["0", "50", "60", "70", "80", "90"]),
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
               v = tk.BooleanVar(value=bool(self.config.get(key, True if key in ("guide_empty_input", "show_tooltips") else False)))
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
               if key in ("auto_clear_input", "replace_output", "sort_output", "guide_empty_input", "show_tooltips"):
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
