import json
import subprocess

import lionscliapp as app

from executionsatellite import __version__
from executionsatellite import core
from executionsatellite import ui


def cmd_open():
    config = get_config()
    ensure_local_directories(config)
    ui.run(config)


def cmd_list():
    config = get_config()
    entries = core.scan_inbox(config["projpath.inbox"], config["projpath.runs"])
    for entry in entries:
        print(f"{entry['state']:9} {entry['job-id']} {entry['job']} {entry['message']}".rstrip())


def cmd_inspect():
    config = get_config()
    entries = core.scan_inbox(config["projpath.inbox"], config["projpath.runs"])
    output = []
    for entry in entries:
        output.append(
            {
                "state": entry["state"],
                "job_id": entry["job-id"],
                "job": entry["job"],
                "source_path": str(entry["source-path"]),
                "expires_at": entry["expires-at"],
                "message": entry["message"],
            }
        )
    print(json.dumps(output, indent=2))


def cmd_doctor():
    config = get_config()
    root = config["execpath.inputlog-root"]
    if not root.is_dir():
        raise SystemExit(f"InputLog root does not exist: {root}")

    try:
        result = subprocess.run(
            [config["inputlog.command"], "list"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as exc:
        raise SystemExit(f"Could not run InputLog: {exc}") from exc

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise SystemExit(f"InputLog list failed: {detail}")

    output = result.stdout.strip()
    print(f"InputLog root: {root}")
    print(output or "InputLog returned no recording list.")
    required = [config["recording.layout"], config["recording.print"]]
    available = {
        line.removesuffix(" *").strip()
        for line in output.splitlines()
        if line.strip() and not line.startswith("No recordings found")
    }
    missing = [name for name in required if name not in available]
    if missing:
        raise SystemExit("Missing required InputLog recording(s): " + ", ".join(missing))
    print("Execution Satellite preflight passed.")


def declare():
    app.declare_app("execution-satellite", __version__)
    app.describe_app("Human-gated InputLog executor for StickerDB production jobs.")
    app.declare_projectdir(".execution-satellite")
    app.set_flag("search_upwards_for_project_dir", True)

    app.declare_key("projpath.inbox", "inbox/")
    app.describe_key("projpath.inbox", "Satellite-owned inbox containing copied request JSON files.")
    app.declare_key("projpath.runs", "runs/")
    app.describe_key("projpath.runs", "Satellite-owned InputLog reports and terminal job records.")
    app.declare_key("execpath.inputlog-root", "C:/lion/installed/inputlog")
    app.describe_key("execpath.inputlog-root", "InputLog project root containing its .inputlog recordings.")
    app.declare_key("inputlog.command", "inputlog")
    app.describe_key("inputlog.command", "InputLog executable or command path.")
    app.declare_key("recording.layout", "layout")
    app.describe_key("recording.layout", "InputLog recording used for layout_sticker_to_lds.")
    app.declare_key("recording.print", "print-sticker")
    app.describe_key("recording.print", "InputLog recording used for print_lds_file.")
    app.declare_key("poll.ms", "2000")
    app.describe_key("poll.ms", "GUI inbox polling interval in milliseconds.")

    app.declare_cmd("", cmd_open)
    app.describe_cmd("", "Open the operator queue window.")
    app.declare_cmd("open", cmd_open)
    app.describe_cmd("open", "Open the operator queue window.")
    app.declare_cmd("list", cmd_list)
    app.describe_cmd("list", "List inbox requests and their local states.")
    app.declare_cmd("inspect", cmd_inspect)
    app.describe_cmd("inspect", "Print inbox state as JSON.")
    app.declare_cmd("doctor", cmd_doctor)
    app.describe_cmd("doctor", "Check InputLog availability and required recordings.")


def get_config():
    try:
        poll_ms = int(app.ctx["poll.ms"])
    except ValueError as exc:
        raise SystemExit("poll.ms must be an integer") from exc
    if poll_ms < 250:
        raise SystemExit("poll.ms must be at least 250")

    return {
        "projpath.inbox": app.ctx["projpath.inbox"],
        "projpath.runs": app.ctx["projpath.runs"],
        "execpath.inputlog-root": app.ctx["execpath.inputlog-root"],
        "inputlog.command": app.ctx["inputlog.command"],
        "recording.layout": app.ctx["recording.layout"],
        "recording.print": app.ctx["recording.print"],
        "poll.ms": poll_ms,
    }


def ensure_local_directories(config):
    config["projpath.inbox"].mkdir(parents=True, exist_ok=True)
    config["projpath.runs"].mkdir(parents=True, exist_ok=True)


def main():
    declare()
    app.main()


if __name__ == "__main__":
    main()
