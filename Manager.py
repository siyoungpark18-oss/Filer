from PIL import Image
from pathlib import Path
import re
import shutil
import img2pdf
import json
import hashlib
import time
import psutil
from pypdf import PdfReader, PdfWriter




CONFIG_PATH = Path.home() / ".file_folder_manager" / "config.json"


SENTINEL = "\x00CANCELLED\x00"


DEFAULTS = {
   "input":            "./resources",
   "output":           "./resources",
   "default_sort":     "ask",
   "default_dpi":      "ask",
   "default_img_fmt":  "ask",
   "auto_clear_input": False,
   "replace_output":   True,
   "sort_output":      False,
   "hotkey_continue":  "Return",
   "hotkey_cancel":    "Escape",
   "throttle_cpu":     80,
   "throttle_mem":     80,
   "dark_mode":        False,
}




def load_config():
   CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
   if CONFIG_PATH.exists():
       with open(CONFIG_PATH, 'r') as f:
           data = json.load(f)
       for k, v in DEFAULTS.items():
           data.setdefault(k, v)
       return data
   return DEFAULTS.copy()




def save_config(config):
   CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
   with open(CONFIG_PATH, 'w') as f:
       json.dump(config, f, indent=2)




def get_input(config):
   return Path(config["input"]) / "Input"




def get_output(config, operation, run_name):
   if config.get("sort_output", False):
       folder = Path(config["output"]) / "output" / operation / run_name
   else:
       folder = Path(config["output"]) / "output" / run_name
   if config.get("replace_output", True) and folder.exists():
       shutil.rmtree(folder)
   folder.mkdir(parents=True, exist_ok=True)
   return folder




def do_auto_clear(config):
   if config.get("auto_clear_input"):
       src = get_input(config)
       if src.exists():
           count = sum(1 for _ in src.iterdir())
           for item in src.iterdir():
               try:
                   shutil.rmtree(item) if item.is_dir() else item.unlink()
               except Exception as e:
                   print(f"  Auto-clear failed: {item.name}: {e}")
           print(f"  Input cleared ({count} item(s) removed).")




def resolve_sort(config):
   mode = config.get("default_sort", "ask")
   if mode == "natural":
       return True
   if mode == "none":
       return False
   raw = input("Sort order? 1=Natural  2=None (default 1): ").strip()
   if raw == SENTINEL:
       return None
   return raw != "2"




def throttle_if_needed(config):
   cpu_limit = config.get("throttle_cpu", 80)
   mem_limit = config.get("throttle_mem", 80)
   if cpu_limit == 0 and mem_limit == 0:
       return
   while True:
       cpu = psutil.cpu_percent(interval=0.2)
       mem = psutil.virtual_memory().percent
       if cpu <= cpu_limit and mem <= mem_limit:
           break
       time.sleep(0.5)




def natural_sort_key(name):
   return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', name)]




def collect_image_paths(folder, image_extensions):
   paths = []
   items = sorted(folder.iterdir(), key=lambda x: natural_sort_key(x.name))
   for item in items:
       if item.is_file() and item.suffix.lower() in image_extensions:
           paths.append(item)
       elif item.is_dir():
           sub = collect_image_paths(item, image_extensions)
           paths.extend(sub)
           if sub:
               print(f"    {item.name}/  →  {len(sub)} image(s)")
   return paths




def save_pdf(image_paths, output_path):
   if not image_paths:
       print("  No images to save.")
       return
   print(f"  Converting {len(image_paths)} images → PDF...")
   with open(output_path, 'wb') as f:
       f.write(img2pdf.convert([str(p) for p in image_paths]))
   size_mb = output_path.stat().st_size / (1024 * 1024)
   print(f"  Saved: {output_path.name}  ({size_mb:.1f} MB)")




def _get_run_name(prompt="Run name (Enter to skip): "):
   val = input(prompt).strip()
   if val == SENTINEL:
       return None
   return val or "Output"




def _cancel():
   print("  Cancelled.")
   print("")




def folders_to_pdf(config, cancel=None):
   src = get_input(config)
   src.mkdir(parents=True, exist_ok=True)


   print("Folders to PDF")
   print(f"  Input:  {src}")
   run_name = _get_run_name()
   if run_name is None:
       return _cancel()
   out = get_output(config, "folders to pdf", run_name)
   print(f"  Output: {out}")


   image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff'}
   folders = sorted([f for f in src.iterdir() if f.is_dir()],
                    key=lambda x: natural_sort_key(x.name))


   if not folders:
       print("  No folders found in Input!")
       print("")
       return


   print(f"  Found {len(folders)} folder(s). Scanning...")
   all_paths = []
   for folder in folders:
       if cancel and cancel.is_set():
           print("  Cancelled.")
           print("")
           return
       throttle_if_needed(config)
       paths = collect_image_paths(folder, image_extensions)
       all_paths.extend(paths)
       print(f"  [{folder.name}]  {len(paths)} image(s)")


   print(f"  Total: {len(all_paths)} images across {len(folders)} folders")


   if all_paths:
       save_pdf(all_paths, out / "output.pdf")
       do_auto_clear(config)
       print(f"  Done! → {out}")
       print("")
   else:
       print("  No images found in any folder.")
       print("")




def images_to_pdf(config, cancel=None):
   src = get_input(config)
   src.mkdir(parents=True, exist_ok=True)


   print("Images to PDF")
   print(f"  Input:  {src}")
   run_name = _get_run_name()
   if run_name is None:
       return _cancel()
   out = get_output(config, "images to pdf", run_name)
   print(f"  Output: {out}")


   image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff'}
   image_files = sorted(
       [f for f in src.rglob("*") if f.is_file() and f.suffix.lower() in image_extensions],
       key=lambda x: natural_sort_key(str(x.relative_to(src)))
   )


   if not image_files:
       print("  No images found in Input!")
       print("")
       return


   from collections import Counter
   ext_counts = Counter(f.suffix.lower() for f in image_files)
   summary = "  ".join(f"{v}× {k}" for k, v in sorted(ext_counts.items()))
   print(f"  Found {len(image_files)} images:  {summary}")
   if cancel and cancel.is_set():
       print("  Cancelled.")
       print("")
       return
   save_pdf(image_files, out / "output.pdf")
   do_auto_clear(config)
   print(f"  Done! → {out}")
   print("")




def folder_renamer(config, cancel=None):
   src = get_input(config)
   src.mkdir(parents=True, exist_ok=True)


   print("Folder Renamer")
   print(f"  Input:  {src}")
   run_name = _get_run_name()
   if run_name is None:
       return _cancel()
   out = get_output(config, "folder renamer", run_name)
   print(f"  Output: {out}")


   # Collect all folders at any depth, paired with their output destination
   # The parent structure is preserved; only the leaf folder name is changed to its number
   preview = []
   skipped = 0


   def collect(folder, dest_parent):
       nonlocal skipped
       subfolders = sorted([f for f in folder.iterdir() if f.is_dir()],
                           key=lambda x: natural_sort_key(x.name))
       for sub in subfolders:
           match = re.search(r'\d+(?:\.\d+)?', sub.name)
           if match:
               raw = match.group()
               if '.' in raw:
                   integer, decimal = raw.split('.', 1)
                   new_name = f"{int(integer)}.{decimal}"
               else:
                   new_name = str(int(raw))
               preview.append((sub, dest_parent / new_name))
           else:
               skipped += 1
               # Still recurse into skipped folders preserving their name
               collect(sub, dest_parent / sub.name)


   collect(src, out)


   if not preview and skipped == 0:
       print("  No folders found in Input!")
       print("")
       return


   print(f"  Found {len(preview)} folder(s) to rename{f', {skipped} skipped' if skipped else ''}.")
   print("  Preview (first 5):")
   for old, new in preview[:5]:
       print(f"    {old.name}  →  {new.name}")
   if len(preview) > 5:
       print(f"    ... and {len(preview) - 5} more")


   copied = failed = 0
   for old, new in preview:
       if cancel and cancel.is_set():
           print(f"  Cancelled. ({copied} renamed so far)")
           print("")
           return
       try:
           shutil.copytree(str(old), str(new), dirs_exist_ok=True)
           copied += 1
       except Exception as e:
           print(f"  Failed: {old.name}: {e}")
           failed += 1


   print(f"  Renamed: {copied}{f'   Failed: {failed}' if failed else ''}")
   do_auto_clear(config)
   print(f"  Done! → {out}")
   print("")




def file_renamer(config, cancel=None):
   src = get_input(config)
   src.mkdir(parents=True, exist_ok=True)


   print("File Renamer")
   print(f"  Input:  {src}")
   run_name = _get_run_name()
   if run_name is None:
       return _cancel()
   out = get_output(config, "renamed", run_name)
   print(f"  Output: {out}")


   items = sorted([f for f in src.rglob("*") if f.is_file()],
                  key=lambda x: natural_sort_key(x.name))


   if not items:
       print("  No files found in Input!")
       print("")
       return


   print(f"  Found {len(items)} file(s).")
   print("  Modes: 1=Prefix  2=Suffix  3=Replace  4=Sequence")
   mode = input("Choose mode (1-4): ").strip()
   if mode == SENTINEL:
       return _cancel()


   if mode == "1":
       param1 = input("Prefix to add: ")
       if param1 == SENTINEL:
           return _cancel()
       preview = [(f, out / f.relative_to(src).parent / (param1 + f.name)) for f in items]
   elif mode == "2":
       param1 = input("Suffix to add (before extension): ")
       if param1 == SENTINEL:
           return _cancel()
       preview = [(f, out / f.relative_to(src).parent / (f.stem + param1 + f.suffix)) for f in items]
   elif mode == "3":
       param1 = input("Find: ")
       if param1 == SENTINEL:
           return _cancel()
       param2 = input("Replace with (Enter for blank): ")
       if param2 == SENTINEL:
           return _cancel()
       preview = [(f, out / f.relative_to(src).parent / f.name.replace(param1, param2)) for f in items]
   elif mode == "4":
       param1 = input("Base name (e.g. 'photo'): ")
       if param1 == SENTINEL:
           return _cancel()
       start = input("Start number (default 1): ").strip()
       if start == SENTINEL:
           return _cancel()
       pad = input("Pad digits (default 3): ").strip()
       if pad == SENTINEL:
           return _cancel()
       start = int(start) if start else 1
       pad   = int(pad)   if pad   else 3
       preview = [(f, out / f.relative_to(src).parent / f"{param1}_{str(start + i).zfill(pad)}{f.suffix}")
                  for i, f in enumerate(items)]
   else:
       print("  Invalid mode.")
       print("")
       return


   print("  Preview (first 5):")
   for old, new in preview[:5]:
       print(f"    {old.name}  →  {new.name}")
   if len(preview) > 5:
       print(f"    ... and {len(preview) - 5} more")


   copied = failed = 0
   for old, new in preview:
       if cancel and cancel.is_set():
           print(f"  Cancelled. ({copied} renamed so far)")
           print("")
           return
       try:
           new.parent.mkdir(parents=True, exist_ok=True)
           shutil.copy2(str(old), str(new))
           copied += 1
       except Exception as e:
           print(f"  Failed: {old.name}: {e}")
           failed += 1


   print(f"  Renamed: {copied}{f'   Failed: {failed}' if failed else ''}")
   do_auto_clear(config)
   print(f"  Done! → {out}")
   print("")




def combine_image_sets(config, cancel=None):
   src = get_input(config)
   src.mkdir(parents=True, exist_ok=True)


   print("Combine Image Sets")
   print(f"  Input:  {src}")
   run_name = _get_run_name()
   if run_name is None:
       return _cancel()
   out = get_output(config, "combined image set", run_name)
   print(f"  Output: {out}")


   image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.webp'}
   sort_result = resolve_sort(config)
   if sort_result is None:
       return _cancel()
   use_sort = sort_result


   def collect_images(folder):
       all_items = sorted(folder.iterdir(), key=lambda x: natural_sort_key(x.name))
       images = []
       for item in all_items:
           if item.is_file() and item.suffix.lower() in image_extensions:
               images.append(item)
           elif item.is_dir():
               images.extend(collect_images(item))
       if use_sort:
           images = sorted(images, key=lambda x: natural_sort_key(x.name))
       return images


   folders = sorted([f for f in src.iterdir() if f.is_dir()],
                    key=lambda x: natural_sort_key(x.name))


   if not folders:
       print("  No folders found in Input!")
       print("")
       return


   print(f"  Found {len(folders)} top-level folder(s).")
   counter = 1
   for folder in folders:
       if cancel and cancel.is_set():
           print(f"  Cancelled. ({counter - 1} images combined so far)")
           print("")
           return
       throttle_if_needed(config)
       subfolders = sorted([f for f in folder.iterdir() if f.is_dir()],
                           key=lambda x: natural_sort_key(x.name))
       targets = [(f"{folder.name}/{sub.name}", sub) for sub in subfolders] if subfolders else [(folder.name, folder)]
       for label, target in targets:
           images = collect_images(target)
           start_idx = counter
           for img in images:
               dest = out / f"{str(counter).zfill(4)}{img.suffix}"
               shutil.copy2(img, dest)
               counter += 1
           print(f"  [{label}]  {len(images)} image(s)  →  {str(start_idx).zfill(4)}–{str(counter - 1).zfill(4)}")


   do_auto_clear(config)
   print(f"  Total: {counter - 1} images combined.")
   print(f"  Done! → {out}")
   print("")




def image_converter(config, cancel=None):
   src = get_input(config)
   src.mkdir(parents=True, exist_ok=True)


   print("Image Converter")
   print(f"  Input:  {src}")
   run_name = _get_run_name()
   if run_name is None:
       return _cancel()


   fmt = config.get("default_img_fmt", "ask")
   if fmt == "ask":
       fmt = input("Format (jpg/png/webp/bmp/tiff, default jpg): ").strip().lower()
       if fmt == SENTINEL:
           return _cancel()
       fmt = fmt or "jpg"
   else:
       print(f"  Format: {fmt}")


   # Normalise to Pillow's save format name and the output extension separately
   pillow_fmt = "JPEG" if fmt == "jpg" else fmt.upper()
   ext        = ".jpg" if fmt == "jpg" else f".{fmt}"


   out = get_output(config, "converted", run_name)
   print(f"  Output: {out}")


   image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.webp'}
   images = sorted(
       [f for f in src.rglob("*") if f.is_file() and f.suffix.lower() in image_extensions],
       key=lambda x: natural_sort_key(x.name)
   )


   if not images:
       print("  No images found in Input!")
       print("")
       return


   from collections import Counter
   ext_counts = Counter(f.suffix.lower() for f in images)
   summary = "  ".join(f"{v}× {k}" for k, v in sorted(ext_counts.items()))
   print(f"  Found {len(images)} images:  {summary}")
   print(f"  Converting all → {ext} ...")


   converted = copied = failed = 0
   for img_path in images:
       if cancel and cancel.is_set():
           print(f"  Cancelled. ({converted + copied} images processed so far)")
           print("")
           return
       throttle_if_needed(config)
       dest_dir = out / img_path.relative_to(src).parent
       dest_dir.mkdir(parents=True, exist_ok=True)
       dest = dest_dir / (img_path.stem + ext)
       # Treat .jpeg and .jpg as the same format
       src_ext = img_path.suffix.lower()
       already_correct = src_ext == ext or (ext == ".jpg" and src_ext == ".jpeg")
       if already_correct:
           shutil.copy2(img_path, dest)
           copied += 1
       else:
           try:
               img = Image.open(img_path)
               if pillow_fmt == "JPEG" and img.mode in ("RGBA", "P"):
                   img = img.convert("RGB")
               img.save(dest, pillow_fmt)
               converted += 1
           except Exception as e:
               print(f"  Failed: {img_path.name}: {e}")
               failed += 1


   print(f"  Converted: {converted}   Already correct: {copied}{f'   Failed: {failed}' if failed else ''}")
   do_auto_clear(config)
   print(f"  Done! → {out}")
   print("")




def find_duplicates(config, cancel=None):
   src = get_input(config)
   src.mkdir(parents=True, exist_ok=True)

   print("Find Duplicates")
   print(f"  Input:  {src}")
   run_name = _get_run_name()
   if run_name is None:
       return _cancel()
   out = get_output(config, "find duplicates", run_name)
   print(f"  Output: {out}")

   custom = input(f"Folder to scan (Enter for Input): ").strip()
   if custom == SENTINEL:
       return _cancel()
   target = Path(custom) if custom else src

   if not target.exists():
       print("  Folder doesn't exist.")
       print("")
       return

   print(f"  Scanning: {target}")
   image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.webp'}

   all_files = [f for f in target.rglob("*") if f.is_file() and f.suffix.lower() in image_extensions]
   print(f"  Hashing {len(all_files)} image(s)...")

   hashes = {}
   duplicates = []
   for f in all_files:
       if cancel and cancel.is_set():
           print("  Cancelled.")
           print("")
           return
       digest = hashlib.md5(f.read_bytes()).hexdigest()
       if digest in hashes:
           duplicates.append((f, hashes[digest]))
       else:
           hashes[digest] = f

   if not duplicates:
       print(f"  No duplicates found across {len(all_files)} images.")
       print("")
       return

   print(f"  Found {len(duplicates)} duplicate(s) out of {len(all_files)} images:")
   for dup, original in duplicates[:10]:
       print(f"    {dup.name}  ==  {original.name}")
   if len(duplicates) > 10:
       print(f"    ... and {len(duplicates) - 10} more")

   confirm = input(f"Delete all {len(duplicates)} duplicates? (y/Enter=yes): ").strip().lower()
   if confirm == SENTINEL:
       return _cancel()
   if confirm not in ("y", "yes", ""):
       print("  Cancelled.")
       print("")
       return

   deleted = failed = 0
   for dup, _ in duplicates:
       try:
           dup.unlink()
           deleted += 1
       except Exception as e:
           print(f"  Failed to delete {dup.name}: {e}")
           failed += 1

   print(f"  Deleted: {deleted}{f'   Failed: {failed}' if failed else ''}")
   do_auto_clear(config)
   print(f"  Done! → {out}")
   print("")




def pdf_combiner(config, cancel=None):
   src = get_input(config)
   src.mkdir(parents=True, exist_ok=True)


   print("PDF Combiner")
   print(f"  Input:  {src}")
   run_name = _get_run_name()
   if run_name is None:
       return _cancel()
   out = get_output(config, "pdf combined", run_name)
   print(f"  Output: {out}")


   sort_result = resolve_sort(config)
   if sort_result is None:
       return _cancel()
   pdfs = [f for f in src.rglob("*") if f.is_file() and f.suffix.lower() == ".pdf"]
   if sort_result:
       pdfs = sorted(pdfs, key=lambda x: natural_sort_key(x.name))


   if not pdfs:
       print("  No PDFs found in Input!")
       print("")
       return


   print(f"  Found {len(pdfs)} PDF(s). Combining...")
   writer = PdfWriter()
   total_pages = 0
   for pdf_path in pdfs:
       if cancel and cancel.is_set():
           print(f"  Cancelled. ({total_pages} pages combined so far)")
           print("")
           return
       throttle_if_needed(config)
       reader = PdfReader(str(pdf_path))
       for page in reader.pages:
           writer.add_page(page)
       total_pages += len(reader.pages)
       print(f"  [{pdf_path.name}]  {len(reader.pages)} page(s)  (running total: {total_pages})")


   out_path = out / "combined.pdf"
   with open(out_path, "wb") as f:
       writer.write(f)
   size_mb = out_path.stat().st_size / (1024 * 1024)
   print(f"  Saved: combined.pdf  ({total_pages} pages, {size_mb:.1f} MB)")
   do_auto_clear(config)
   print(f"  Done! → {out}")
   print("")




def pdf_to_images(config, cancel=None):
   try:
       from pdf2image import convert_from_path
   except ImportError:
       print("  pdf2image not installed — run: pip install pdf2image")
       print("  Also need poppler: brew install poppler")
       print("")
       return


   src = get_input(config)
   src.mkdir(parents=True, exist_ok=True)


   print("PDF to Images")
   print(f"  Input:  {src}")
   run_name = _get_run_name()
   if run_name is None:
       return _cancel()

   fmt = config.get("default_img_fmt", "ask")
   if fmt == "ask":
       raw = input("Format (jpg/png, default jpg): ").strip().lower()
       if raw == SENTINEL:
           return _cancel()
       fmt = raw or "jpg"
   else:
       print(f"  Format: {fmt}")
   if fmt not in ("jpg", "png"):
       print("  Invalid format.")
       print("")
       return

   dpi = config.get("default_dpi", "ask")
   if dpi == "ask":
       raw = input("DPI (default 150): ").strip()
       if raw == SENTINEL:
           return _cancel()
       dpi = int(raw) if raw else 150
   else:
       print(f"  DPI: {dpi}")

   out = get_output(config, "pdf to images", run_name)
   print(f"  Output: {out}")


   pdfs = sorted(
       [f for f in src.rglob("*") if f.is_file() and f.suffix.lower() == ".pdf"],
       key=lambda x: natural_sort_key(x.name)
   )
   if not pdfs:
       print("  No PDFs found in Input!")
       print("")
       return


   print(f"  Found {len(pdfs)} PDF(s).")
   total_pages = 0
   for pdf_path in pdfs:
       if cancel and cancel.is_set():
           print(f"  Cancelled. ({total_pages} pages exported so far)")
           print("")
           return
       pdf_out = out / pdf_path.stem
       pdf_out.mkdir(exist_ok=True)
       print(f"  Converting: {pdf_path.name}  (@ {dpi} DPI)...")
       print(f"  Note: cancelling will stop after the current page finishes.")
       page_count = len(PdfReader(str(pdf_path)).pages)
       for i in range(page_count):
           if cancel and cancel.is_set():
               print(f"  Cancelled. ({total_pages + i} pages exported so far)")
               print("")
               return
           throttle_if_needed(config)
           pages = convert_from_path(str(pdf_path), dpi=dpi, first_page=i + 1, last_page=i + 1)
           dest = pdf_out / f"{pdf_path.stem}_{str(i + 1).zfill(4)}.{fmt}"
           pages[0].save(str(dest), "JPEG" if fmt == "jpg" else "PNG")
       total_pages += page_count
       print(f"  [{pdf_path.name}]  {page_count} page(s)  →  {pdf_out.name}/")


   do_auto_clear(config)
   print(f"  Total: {len(pdfs)} PDF(s), {total_pages} page(s) exported.")
   print(f"  Done! → {out}")
   print("")




def pdf_splitter(config, cancel=None):
   src = get_input(config)
   src.mkdir(parents=True, exist_ok=True)


   print("PDF Splitter")
   print(f"  Input:  {src}")
   run_name = _get_run_name()
   if run_name is None:
       return _cancel()
   out = get_output(config, "pdf split", run_name)
   print(f"  Output: {out}")


   # Use rglob for consistency with other functions
   pdfs = sorted(
       [f for f in src.rglob("*") if f.is_file() and f.suffix.lower() == ".pdf"],
       key=lambda x: natural_sort_key(x.name)
   )
   if not pdfs:
       print("  No PDF found in Input!")
       print("")
       return
   if len(pdfs) > 1:
       print(f"  Multiple PDFs found, using first: {pdfs[0].name}")
   pdf_path = pdfs[0]


   reader = PdfReader(str(pdf_path))
   total = len(reader.pages)
   print(f"  Loaded: {pdf_path.name}  ({total} pages)")
   print(f"  Enter page numbers to split after. Empty input = done.")
   print(f"  Valid range: 1–{total - 1}")


   splits = [0]
   while True:
       cmd = input(f"Split after page (1-{total - 1}), or Enter to finish: ").strip().lower()
       if cmd == SENTINEL:
           return _cancel()
       if cmd in ("exit", ""):
           break
       try:
           page_num = int(cmd)
           if page_num < 1 or page_num >= total:
               print(f"  Must be between 1 and {total - 1}.")
               continue
           splits.append(page_num)
           print(f"  ✓ Split marked after page {page_num}. ({len(splits) - 1} split(s) so far)")
       except ValueError:
           print("  Invalid input.")


   splits = sorted(set(splits))
   splits.append(total)


   if len(splits) < 2:
       print("  No splits made.")
       print("")
       return


   stem = pdf_path.stem
   part_count = len(splits) - 1
   print(f"  Writing {part_count} part(s)...")
   for i in range(part_count):
       if cancel and cancel.is_set():
           print(f"  Cancelled. ({i} part(s) saved so far)")
           print("")
           return
       start, end = splits[i], splits[i + 1]
       writer = PdfWriter()
       for p in range(start, end):
           writer.add_page(reader.pages[p])
       out_path = out / f"{stem}_part{i + 1}.pdf"
       with open(out_path, "wb") as f:
           writer.write(f)
       print(f"  Part {i + 1}/{part_count}: pages {start + 1}–{end}  →  {out_path.name}")


   do_auto_clear(config)
   print(f"  Done! {part_count} part(s) saved.")
   print(f"  → {out}")
   print("")




def status(config):
   src = get_input(config)
   out_base = Path(config["output"]) / "output"


   print("")
   if src.exists():
       items = list(src.iterdir())
       files = [i for i in items if i.is_file()]
       dirs  = [i for i in items if i.is_dir()]
       parts = []
       if dirs:  parts.append(f"{len(dirs)} folder(s)")
       if files: parts.append(f"{len(files)} file(s)")
       print(f"  Input: {', '.join(parts) if parts else 'empty'}")
       for d in sorted(dirs, key=lambda x: natural_sort_key(x.name)):
           sub_dirs = sorted([i for i in d.iterdir() if i.is_dir()], key=lambda x: natural_sort_key(x.name))
           file_count = sum(1 for _ in d.rglob("*") if _.is_file())
           print(f"    [folder] {d.name}/  ({file_count} file(s))")
           for sd in sub_dirs:
               sc = sum(1 for _ in sd.rglob("*") if _.is_file())
               print(f"             {sd.name}/  ({sc} file(s))")
       for f in sorted(files, key=lambda x: natural_sort_key(x.name)):
           print(f"    [file]   {f.name}")
   else:
       print("  Input: (doesn't exist)")


   if out_base.exists():
       items = [i for i in out_base.iterdir() if i.is_dir()]
       if items:
           print(f"  Output:")
           for op in sorted(items, key=lambda x: natural_sort_key(x.name)):
               file_count = sum(1 for f in op.rglob("*") if f.is_file())
               print(f"    {op.name}/  ({file_count} file(s))")
       else:
           print(f"  Output: empty")
   else:
       print(f"  Output: empty")
   print("")




def info():
   print("""
-- File & Folder Management --
'folders to pdf'     'images to pdf'     'folder renamer'
'file renamer'       'combine image sets' 'image converter'
'find duplicates'    'pdf splitter'       'pdf combiner'
'pdf to images'


-- Other --
'status'  'exit'


All output goes to output/
""")




def command_line():
   config = load_config()
   print("\nFile & Folder Manager — type 'info' for commands")
   while True:
       command = input(">>> ").strip().lower()
       try:
           if command == "info":                 info()
           elif command == "folders to pdf":     folders_to_pdf(config)
           elif command == "images to pdf":      images_to_pdf(config)
           elif command == "folder renamer":     folder_renamer(config)
           elif command == "file renamer":       file_renamer(config)
           elif command == "combine image sets": combine_image_sets(config)
           elif command == "image converter":    image_converter(config)
           elif command == "pdf splitter":       pdf_splitter(config)
           elif command == "pdf combiner":       pdf_combiner(config)
           elif command == "pdf to images":      pdf_to_images(config)
           elif command == "find duplicates":    find_duplicates(config)
           elif command == "status":             status(config)
           elif command == "exit":
               print("exiting...")
               break
           else:
               print("Invalid command. Type 'info' for list.")
       except KeyboardInterrupt:
           print("\nInterrupted.")




if __name__ == "__main__":
   command_line()
