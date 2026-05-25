"""Live workspace scan orchestration.

Sub-modules:

- ``paths`` — workspace hash + on-disk scan-dir resolution.
- ``envelope`` — atomic JSON writes + scan-envelope mutation helpers.
- ``pidfile`` — JSON pid file with start-time stamping; PID-recycle aware.
- ``history`` — meta.json, archive rotation, retention pruning, log rotation.
- ``eta`` — median per-child duration ETA from completed history.
- ``server`` — packaged dashboard resolver + read-only HTTP server.
- ``worker`` — sequential scan worker with signal handling + hard timeout.
- ``discovery`` — cross-workspace enumeration (list/stop_all).
"""
