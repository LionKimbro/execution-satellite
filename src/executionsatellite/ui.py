import json
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from executionsatellite import core


g = {
    "root": None,
    "widgets": {},
    "entries": [],
    "events": queue.Queue(),
    "decisions": queue.Queue(),
    "running": False,
    "config": None,
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
    frame.rowconfigure(1, weight=1)
    frame.rowconfigure(3, weight=1)

    title = ttk.Label(frame, text="Execution Satellite", font=("TkDefaultFont", 16, "bold"))
    title.grid(row=0, column=0, sticky="w", pady=(0, 10))

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
    tree.grid(row=1, column=0, sticky="nsew")
    tree.bind("<<TreeviewSelect>>", handle_selection)

    controls = ttk.Frame(frame)
    controls.grid(row=2, column=0, sticky="ew", pady=10)
    refresh_button = ttk.Button(controls, text="Refresh", command=refresh_queue)
    refresh_button.pack(side="left")
    start_button = ttk.Button(controls, text="Start Pending Queue", command=start_queue)
    start_button.pack(side="left", padx=(8, 0))
    pending_var = tk.StringVar(value="")
    ttk.Label(controls, textvariable=pending_var).pack(side="right")

    details = tk.Text(frame, height=14, wrap="word", state="disabled")
    details.grid(row=3, column=0, sticky="nsew")

    status_var = tk.StringVar(value="Ready.")
    ttk.Label(frame, textvariable=status_var, anchor="w").grid(row=4, column=0, sticky="ew", pady=(8, 0))

    g["widgets"] = {
        "tree": tree,
        "refresh": refresh_button,
        "start": start_button,
        "pending-var": pending_var,
        "details": details,
        "status-var": status_var,
    }


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
    if not messagebox.askokcancel(
        "Launch queue",
        f"Run {len(pending)} pending job(s)?\n\n"
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
            outcome = core.execute_inputlog(entry["request"], g["config"], run_dir)
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


def set_status(message):
    g["widgets"]["status-var"].set(message)


def show_details(text):
    details = g["widgets"]["details"]
    details.configure(state="normal")
    details.delete("1.0", tk.END)
    details.insert("1.0", text)
    details.configure(state="disabled")
