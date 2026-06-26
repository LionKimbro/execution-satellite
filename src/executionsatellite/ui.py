import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageOps, ImageTk

from executionsatellite import core


g = {
    "root": None,
    "widgets": {},
    "entries": [],
    "events": queue.Queue(),
    "decisions": queue.Queue(),
    "running": False,
    "config": None,
    "path-vars": {},
    "preview-image": None,
    "preview-source-image": None,
    "context-entry": None,
}


def run(config):
    g["config"] = config
    root = tk.Tk()
    g["root"] = root
    root.title("Execution Satellite")
    root.geometry("1050x660")
    create_widgets(root)
    refresh_queue()
    root.protocol("WM_DELETE_WINDOW", handle_close)
    root.after(100, poll_worker_events)
    root.after(config["poll.ms"], periodic_refresh)
    root.mainloop()


def create_widgets(root):
    frame = ttk.Frame(root, padding=12)
    frame.grid(row=0, column=0, sticky="nsew")
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(2, weight=1)
    frame.rowconfigure(4, weight=1)

    title = ttk.Label(frame, text="Execution Satellite", font=("TkDefaultFont", 16, "bold"))
    title.grid(row=0, column=0, sticky="w", pady=(0, 10))

    path_frame = ttk.LabelFrame(frame, text="Execution locations", padding=8)
    path_frame.grid(row=1, column=0, sticky="ew", pady=(0, 10))
    path_frame.columnconfigure(1, weight=1)
    add_path_row(
        path_frame,
        0,
        "Launch folder",
        "execpath.staging-folder",
        "Must be completely blank when Go is pressed. The satellite owns its contents during the queue run.",
    )
    add_path_row(
        path_frame,
        1,
        "Leonardo save folder",
        "execpath.leonardo-save-folder",
        "Leonardo must save the generated Untitled.LDS file here.",
    )

    columns = ("state", "title", "job-id", "expires")
    tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
    tree.heading("state", text="State")
    tree.heading("title", text="Title")
    tree.heading("job-id", text="Job ID")
    tree.heading("expires", text="Expires")
    tree.column("state", width=90, stretch=False)
    tree.column("title", width=320)
    tree.column("job-id", width=240)
    tree.column("expires", width=230)
    tree.grid(row=2, column=0, sticky="nsew")
    tree.bind("<<TreeviewSelect>>", handle_selection)
    tree.bind("<Double-1>", handle_tree_double_click)
    tree.bind("<Button-3>", handle_tree_right_click)

    controls = ttk.Frame(frame)
    controls.grid(row=3, column=0, sticky="ew", pady=10)
    refresh_button = ttk.Button(controls, text="Refresh", command=refresh_queue)
    refresh_button.pack(side="left")
    start_button = ttk.Button(controls, text="Start Pending Queue", command=start_queue)
    start_button.pack(side="left", padx=(8, 0))
    checklist_button = ttk.Button(controls, text="Preflight Checklist", command=show_preflight_checklist)
    checklist_button.pack(side="left", padx=(8, 0))
    clear_button = ttk.Button(controls, text="Clear Queue", command=clear_queue)
    clear_button.pack(side="left", padx=(8, 0))
    pending_var = tk.StringVar(value="")
    ttk.Label(controls, textvariable=pending_var).pack(side="right")

    preview = ttk.PanedWindow(frame, orient="horizontal")
    preview.grid(row=4, column=0, sticky="nsew")
    preview_left = ttk.Frame(preview)
    preview_right = ttk.Frame(preview)
    preview.add(preview_left, weight=2)
    preview.add(preview_right, weight=1)

    preview_tree = ttk.Treeview(preview_left, columns=("value",), show="tree headings", height=10)
    preview_tree.heading("#0", text="Field")
    preview_tree.heading("value", text="Value")
    preview_tree.column("#0", width=220, stretch=False)
    preview_tree.column("value", width=520)
    preview_tree.pack(fill="both", expand=True)

    image_canvas = tk.Canvas(preview_right, background="#f2f2f2", highlightthickness=1, highlightbackground="#cccccc")
    image_canvas.pack(fill="both", expand=True)
    image_canvas.bind("<Configure>", lambda _event: redraw_preview_image())

    status_var = tk.StringVar(value="Ready.")
    ttk.Label(frame, textvariable=status_var, anchor="w").grid(row=5, column=0, sticky="ew", pady=(8, 0))

    g["widgets"] = {
        "tree": tree,
        "refresh": refresh_button,
        "start": start_button,
        "checklist": checklist_button,
        "clear": clear_button,
        "pending-var": pending_var,
        "preview-tree": preview_tree,
        "image-canvas": image_canvas,
        "status-var": status_var,
    }
    create_context_menu(root)


def add_path_row(parent, row, label, key, help_text):
    variable = tk.StringVar(value=str(g["config"][key]))
    g["path-vars"][key] = variable
    ttk.Label(parent, text=label).grid(row=row * 2, column=0, sticky="w", padx=(0, 8), pady=3)
    entry = ttk.Entry(parent, textvariable=variable)
    entry.grid(row=row * 2, column=1, sticky="ew", pady=3)
    ttk.Button(parent, text="Browse", command=lambda: browse_path(variable)).grid(
        row=row * 2, column=2, padx=(8, 0), pady=3
    )
    ttk.Button(parent, text="Open", command=lambda: open_path(variable)).grid(
        row=row * 2, column=3, padx=(6, 0), pady=3
    )
    ttk.Label(parent, text=help_text, foreground="#555555").grid(
        row=row * 2 + 1, column=1, columnspan=3, sticky="w", pady=(0, 4)
    )


def refresh_queue():
    entries = core.scan_inbox(
        g["config"]["projpath.inbox"],
        g["config"]["projpath.runs"],
    )
    g["entries"] = entries
    tree = g["widgets"]["tree"]
    selected = get_selected_entry()
    selected_source = str(selected["source-path"]) if selected else None
    tree.delete(*tree.get_children())

    for index, entry in enumerate(entries):
        iid = str(index)
        tree.insert(
            "",
            "end",
            iid=iid,
            values=(entry["state"], get_entry_title(entry), entry["job-id"], entry["expires-at"]),
        )
        if str(entry["source-path"]) == selected_source:
            tree.selection_set(iid)

    pending = sum(entry["state"] == "pending" for entry in entries)
    invalid = sum(entry["state"] == "invalid" for entry in entries)
    expired = sum(entry["state"] == "expired" for entry in entries)
    g["widgets"]["pending-var"].set(f"{pending} pending · {invalid} invalid · {expired} expired")
    set_status(f"Queue refreshed. {pending} job(s) ready.")


def handle_selection(_event=None):
    entry = get_selected_entry()
    if entry is None:
        show_preview(None)
        return
    show_preview(entry)


def get_entry_title(entry):
    request = entry.get("request")
    if request is None:
        return entry.get("message") or entry.get("job") or "(invalid request)"
    return request.get("title") or request.get("job") or entry.get("job")


def start_queue():
    if g["running"]:
        return
    pending = [entry for entry in g["entries"] if entry["state"] == "pending"]
    if not pending:
        messagebox.showinfo("Execution Satellite", "There are no pending jobs.")
        return
    sync_runtime_paths()
    problems = core.validate_queue_preflight(pending, g["config"])
    if problems:
        messagebox.showerror(
            "Execution Satellite — unsafe to launch",
            "\n\n".join(problems),
        )
        return
    if not messagebox.askokcancel(
        "Launch queue",
        f"Run {len(pending)} pending job(s)?\n\n"
        "The launch folder is blank. From this point until the queue ends, "
        "the satellite is authorized to clear and reuse its contents.\n\n"
        "Prepare Leonardo Design Studio and the execution desktop before continuing.",
    ):
        return

    g["running"] = True
    set_controls_enabled(False)
    set_status(f"Running {len(pending)} job(s). Do not touch mouse or keyboard during playback.")
    worker = threading.Thread(target=run_queue, args=(pending,), daemon=True)
    worker.start()


def run_queue(entries):
    try:
        _run_queue(entries)
    except Exception as exc:
        g["events"].put(
            {
                "type": "queue-error",
                "message": f"{type(exc).__name__}: {exc}",
            }
        )


def _run_queue(entries):
    for queue_index, entry in enumerate(entries):
        attempt = 1
        while True:
            g["events"].put(
                {
                    "type": "job-started",
                    "entry": entry,
                    "queue-index": queue_index,
                    "queue-count": len(entries),
                    "attempt": attempt,
                }
            )
            run_dir = core.get_attempt_dir(
                g["config"]["projpath.runs"],
                entry["job-id"],
                attempt,
            )
            outcome = core.execute_job(entry["request"], g["config"], run_dir)
            if outcome["normal"]:
                response = core.make_response(entry["request"], outcome)
                core.complete_entry(entry, response, outcome)
                g["events"].put({"type": "job-finished", "entry": entry, "response": response})
                break

            g["events"].put(
                {
                    "type": "decision-required",
                    "entry": entry,
                    "outcome": outcome,
                    "attempt": attempt,
                }
            )
            decision = g["decisions"].get()
            if decision == "retry":
                attempt += 1
                continue

            response = core.make_response(entry["request"], outcome)
            if decision == "fail-job":
                core.complete_entry(entry, response, outcome)
                g["events"].put({"type": "job-finished", "entry": entry, "response": response})
                break

            core.complete_entry(entry, response, outcome)
            for remaining in entries[queue_index + 1 :]:
                failure = core.make_operator_failure(
                    remaining["request"],
                    "The operator failed the entire queue after an earlier job stopped.",
                    kind="queue_failed",
                )
                core.complete_entry(remaining, failure)
            g["events"].put({"type": "queue-failed"})
            return

    g["events"].put({"type": "queue-finished"})


def poll_worker_events():
    while True:
        try:
            event = g["events"].get_nowait()
        except queue.Empty:
            break
        handle_worker_event(event)
    g["root"].after(100, poll_worker_events)


def handle_worker_event(event):
    event_type = event["type"]
    if event_type == "job-started":
        set_status(
            f"Running {event['entry']['job-id']} "
            f"({event['queue-index'] + 1}/{event['queue-count']}), attempt {event['attempt']}."
        )
        return
    if event_type == "job-finished":
        set_status(f"{event['entry']['job-id']}: {event['response']['message']}")
        return
    if event_type == "decision-required":
        choose_after_abnormal_result(event)
        return
    if event_type == "queue-failed":
        finish_run("Queue failed by operator decision.")
        return
    if event_type == "queue-error":
        messagebox.showerror("Execution Satellite", event["message"])
        finish_run("Queue stopped because the satellite encountered an error.")
        return
    if event_type == "queue-finished":
        finish_run("Queue complete.")


def choose_after_abnormal_result(event):
    outcome = event["outcome"]
    answer = messagebox.askyesnocancel(
        "Execution stopped",
        f"{event['entry']['job-id']} stopped:\n\n{outcome['message']}\n\n"
        "Yes: retry this job\n"
        "No: fail this job and continue\n"
        "Cancel: fail the entire queue",
    )
    if answer is True:
        g["decisions"].put("retry")
    elif answer is False:
        g["decisions"].put("fail-job")
    else:
        g["decisions"].put("fail-queue")


def finish_run(message):
    g["running"] = False
    set_controls_enabled(True)
    refresh_queue()
    set_status(message)


def periodic_refresh():
    if not g["running"]:
        refresh_queue()
    g["root"].after(g["config"]["poll.ms"], periodic_refresh)


def handle_close():
    if g["running"]:
        messagebox.showwarning(
            "Execution Satellite",
            "The queue is running. Resolve or finish the active InputLog job before closing the satellite.",
        )
        return
    g["root"].destroy()


def set_controls_enabled(enabled):
    state = "normal" if enabled else "disabled"
    g["widgets"]["refresh"].configure(state=state)
    g["widgets"]["start"].configure(state=state)
    g["widgets"]["checklist"].configure(state=state)
    g["widgets"]["clear"].configure(state=state)


def set_status(message):
    g["widgets"]["status-var"].set(message)


def show_preview(entry):
    preview = g["widgets"]["preview-tree"]
    preview.delete(*preview.get_children())
    g["preview-source-image"] = None
    g["preview-image"] = None
    clear_image_canvas("No image preview")

    if entry is None:
        return

    add_preview_row("state", entry["state"])
    add_preview_row("title", get_entry_title(entry))
    add_preview_row("job", entry["job"])
    add_preview_row("job_id", entry["job-id"])
    add_preview_row("source_path", entry["source-path"])
    add_preview_row("expires_at", entry["expires-at"])
    if entry.get("message"):
        add_preview_row("message", entry["message"])

    request = entry.get("request")
    if request is None:
        return

    add_preview_row("created_at", request["created_at"])
    add_preview_row("response_path", request["response_path"])
    input_parent = add_preview_section("input")
    for key, path in request["input"].items():
        add_preview_row(key, path, input_parent)
    output_parent = add_preview_section("output")
    for key, path in request["output"].items():
        add_preview_row(key, path, output_parent)

    image_path = get_preview_image_path(request)
    if image_path is not None:
        load_preview_image(image_path)


def add_preview_section(label):
    return g["widgets"]["preview-tree"].insert("", "end", text=label, values=("",), open=True)


def add_preview_row(field, value, parent=""):
    g["widgets"]["preview-tree"].insert(parent, "end", text=str(field), values=(str(value),))


def get_preview_image_path(request):
    if request["job"] != "layout_sticker_to_lds":
        return None
    path = request["input"].get("sticker_image_path")
    if path is None or not path.is_file():
        return None
    return path


def load_preview_image(path):
    try:
        with Image.open(path) as image:
            g["preview-source-image"] = image.copy()
    except Exception as exc:
        clear_image_canvas(f"Could not preview image:\n{exc}")
        return
    redraw_preview_image()


def redraw_preview_image():
    canvas = g["widgets"].get("image-canvas")
    if canvas is None:
        return
    image = g.get("preview-source-image")
    if image is None:
        return
    width = max(canvas.winfo_width(), 1)
    height = max(canvas.winfo_height(), 1)
    shown = ImageOps.contain(image, (width - 12, height - 12))
    g["preview-image"] = ImageTk.PhotoImage(shown)
    canvas.delete("all")
    x = width // 2
    y = height // 2
    canvas.create_image(x, y, image=g["preview-image"], anchor="center")


def clear_image_canvas(message=""):
    canvas = g["widgets"].get("image-canvas")
    if canvas is None:
        return
    canvas.delete("all")
    if message:
        canvas.create_text(12, 12, text=message, anchor="nw", fill="#666666", width=260)


def create_context_menu(root):
    menu = tk.Menu(root, tearoff=0)
    menu.add_command(label="View Job", command=lambda: view_job(g["context-entry"]))
    menu.add_command(label="Delete Job", command=lambda: delete_job(g["context-entry"]))
    menu.add_command(label="Reload Job", command=lambda: reload_job(g["context-entry"]))
    g["widgets"]["context-menu"] = menu


def handle_tree_double_click(_event):
    view_job(get_selected_entry())


def handle_tree_right_click(event):
    tree = g["widgets"]["tree"]
    iid = tree.identify_row(event.y)
    if not iid:
        return
    tree.selection_set(iid)
    entry = g["entries"][int(iid)]
    g["context-entry"] = entry
    g["widgets"]["context-menu"].tk_popup(event.x_root, event.y_root)


def get_selected_entry():
    selection = g["widgets"]["tree"].selection()
    if not selection:
        return None
    index = int(selection[0])
    if index < 0 or index >= len(g["entries"]):
        return None
    return g["entries"][index]


def view_job(entry):
    if entry is None:
        return
    path = entry["source-path"]
    if not path.exists():
        messagebox.showerror("Execution Satellite", f"Job file no longer exists:\n{path}")
        return
    os.startfile(path)


def delete_job(entry):
    if entry is None:
        return
    if g["running"]:
        messagebox.showwarning("Execution Satellite", "The queue is running. Do not delete queue items right now.")
        return
    if not messagebox.askyesno(
        "Delete job",
        f"Delete this local queue item?\n\n{entry['job-id']}\n{entry['source-path']}",
    ):
        return
    core.delete_queue_entry(entry)
    refresh_queue()
    set_status(f"Deleted local queue item: {entry['job-id']}")


def reload_job(entry):
    if entry is None:
        return
    if g["running"]:
        messagebox.showwarning("Execution Satellite", "The queue is running. Do not reload queue items right now.")
        return
    if not entry["source-path"].exists():
        refresh_queue()
        set_status(f"Job file is gone: {entry['source-path']}")
        return
    updated = core.load_queue_entry(entry["source-path"], g["config"]["projpath.runs"])
    index = g["entries"].index(entry)
    g["entries"][index] = updated
    tree = g["widgets"]["tree"]
    iid = str(index)
    tree.item(iid, values=(updated["state"], get_entry_title(updated), updated["job-id"], updated["expires-at"]))
    tree.selection_set(iid)
    show_preview(updated)
    set_status(f"Reloaded local queue item: {updated['job-id']}")


def clear_queue():
    if g["running"]:
        return
    results = plan_clear_queue(g["entries"])
    deleted = [item for item in results if item["fate"] == "deleted"]
    if not deleted:
        messagebox.showinfo("Clear Queue", "No non-pending local queue items were found.")
        return
    summary = summarize_clear_results(results)
    if not messagebox.askyesno("Clear Queue", summary + "\n\nProceed?"):
        return
    results = core.clear_non_pending_entries(g["entries"])
    deleted_count = sum(item["fate"] == "deleted" for item in results)
    kept_count = sum(item["fate"] == "kept" for item in results)
    refresh_queue()
    set_status(f"Clear Queue deleted {deleted_count} local item(s), kept {kept_count} pending item(s).")


def plan_clear_queue(entries):
    results = []
    for entry in entries:
        fate = "kept" if core.is_pending_entry(entry) else "deleted"
        results.append({"job-id": entry["job-id"], "state": entry["state"], "fate": fate})
    return results


def summarize_clear_results(results):
    counts = {}
    for item in results:
        key = (item["state"], item["fate"])
        counts[key] = counts.get(key, 0) + 1
    lines = ["Clear Queue keeps pending jobs and deletes all other local queue items.", ""]
    for (state, fate), count in sorted(counts.items()):
        lines.append(f"{state}: {fate} ({count})")
    return "\n".join(lines)


def sync_runtime_paths():
    for key, variable in g["path-vars"].items():
        raw = variable.get().strip()
        if not raw:
            continue
        g["config"][key] = Path(raw).expanduser().resolve()


def browse_path(variable):
    selected = filedialog.askdirectory(initialdir=variable.get().strip() or None)
    if selected:
        variable.set(selected)


def open_path(variable):
    path = Path(variable.get().strip()).expanduser()
    if not path.is_dir():
        messagebox.showerror("Execution Satellite", f"Folder does not exist:\n{path}")
        return
    os.startfile(path)


def show_preflight_checklist():
    sync_runtime_paths()
    pending = [entry for entry in g["entries"] if entry["state"] == "pending"]
    problems = core.validate_queue_preflight(pending, g["config"])
    automatic = "Automatic checks passed." if not problems else "\n".join(f"• {item}" for item in problems)
    generated = core.get_leonardo_output_path(g["config"])
    messagebox.showinfo(
        "Execution Satellite — preflight checklist",
        "AUTOMATIC CHECKS\n"
        f"{automatic}\n\n"
        "HUMAN CHECKS\n"
        "• The launch folder is open in the file-manager window expected by InputLog.\n"
        "• Leonardo Design Studio is open on the left-side screen.\n"
        "• Leonardo is configured to save generated layouts here:\n"
        f"  {generated}\n"
        "• The printer and required print settings are ready.\n"
        "• The desktop layout matches the InputLog recordings.\n"
        "• You will not touch the mouse or keyboard during playback.",
    )
