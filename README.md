# execution-satellite

Human-gated execution of StickerDB production jobs through InputLog.

The satellite watches its lionscliapp-managed inbox, displays pending requests,
and runs them only after the operator explicitly launches the queue from a
prepared Leonardo Design Studio desktop.

## Run

```text
pip install -e .
execution-satellite
```

The default local state lives in `.execution-satellite/`:

```text
.execution-satellite/
  config.json
  inbox/
  runs/
```

StickerDB copies request JSON files into `inbox/`. The request retains absolute
paths to requester-owned inputs, outputs, and its response callback.

Useful commands:

```text
execution-satellite list
execution-satellite inspect
execution-satellite doctor
execution-satellite keys
execution-satellite get recording.layout
execution-satellite set execpath.inputlog-root C:/lion/installed/inputlog
```
