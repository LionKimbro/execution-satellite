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
execution-satellite set execpath.staging-folder C:/Users/Robert/Launch
execution-satellite set execpath.leonardo-save-folder D:/tmp
```

The launch folder is a dedicated transient stage. It must be completely empty
when the operator starts a queue. If it is not empty, the satellite refuses to
run and deletes nothing. Once the blank-folder check passes and the operator
confirms Go, the satellite may clear and reuse that folder until the queue ends.
