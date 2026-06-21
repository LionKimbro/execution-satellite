import json
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

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

    columns = ("state", "job", "job-id", "expires")
    tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
    tree.heading("state", text="State")
    tree.heading("job", text="Job")
    tree.heading("job-id", text="Job ID")
    tree.heading("expires", text="Expires")
    tree.column("state", width=90, stretch=False)
    tree.column("job", width=220)
    tree.column("job-id", width=240)
    tree.column("expires", width=230)
    tree.grid(row=2, column=0, sticky="nsew")
    tree.bind("<<TreeviewSelect>>", handle_selection)

    controls = ttk.Frame(frame)
    controls.grid(row=3, column=0, sticky="ew", pady=10)
    refresh_button = ttk.Button(controls, text="Refresh", command=refresh_queue)
    refresh_button.pack(side="left")
    start_button = ttk.Button(controls, text="Start Pending Queue", command=start_queue)
    start_button.pack(side="left", padx=(8, 0))
    checklist_button = ttk.Button(controls, text="Preflight Checklist", command=show_preflight_checklist)
    checklist_button.pack(side="left", padx=(8, 0))
    pending_var = tk.StringVar(value="")
    ttk.Label(controls, textvariable=pending_var).pack(side="right")

    details = tk.Text(frame, height=14, wrap="word", state="disabled")
    details.grid(row=4, column=0, sticky="nsew")

    status_var = tk.StringVar(value="Ready.")
    ttk.Label(frame, textvariable=status_var, anchor="w").grid(row=5, column=0, sticky="ew", pady=(8, 0))

    g["widgets"] = {
        "tree": tree,
        "refresh": refresh_button,
        "start": start_button,
        "checklist": checklist_button,
        "pending-var": pending_var,
        "details": details,
        "status-var": status_var,
    }


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
    selected = tree.selection()
    selected_path = selected[0] if selected else None
    tree.delete(*tree.get_children())

    for index, entry in enumerate(entries):
        iid = str(index)
        tree.insert(
            "",
            "end",
            iid=iid,
            values=(entry["state"], entry["job"], entry["job-id"], entry["expires-at"]),
        )
        if iid == selected_path:
            tree.selection_set(iid)

    pending = sum(entry["state"] == "pending" for entry in entries)
    invalid = sum(entry["state"] == "invalid" for entry in entries)
    expired = sum(entry["state"] == "expired" for entry in entries)
    g["widgets"]["pending-var"].set(f"{pending} pending · {invalid} invalid · {expired} expired")
    set_status(f"Queue refreshed. {pending} job(s) ready.")


def handle_selection(_event=None):
    selection = g["widgets"]["tree"].selection()
    if not selection:
        show_details("")
        return
    entry = g["entries"][int(selection[0])]
    if entry["request"] is None:
        data = {
            "source-path": str(entry["source-path"]),
            "state": entry["state"],
            "message": entry["message"],
        }
    else:
        request = entry["request"]
        data = {
            "source-path": str(entry["source-path"]),
            "state": entry["state"],
            "job_id": request["job_id"],
            "job": request["job"],
            "input": {key: str(path) for key, path in request["input"].items()},
            "output": {key: str(path) for key, path in request["output"].items()},
            "response_path": str(request["response_path"]),
            "expires_at": request["expires_at"],
        }
    show_details(json.dumps(data, indent=2))


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


def set_status(message):
    g["widgets"]["status-var"].set(message)


def show_details(text):
    details = g["widgets"]["details"]
    details.configure(state="normal")
    details.delete("1.0", tk.END)
    details.insert("1.0", text)
    details.configure(state="disabled")


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
