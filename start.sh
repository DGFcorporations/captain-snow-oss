#!/bin/sh
# Captain Snow container entrypoint.
# Cloud-only cascade — no local model to start (removed: unreliable tool
# calling, ~1.1GB of RAM saved). Provider health: `captainsnow doctor --ping`.
exec captainsnow serve
