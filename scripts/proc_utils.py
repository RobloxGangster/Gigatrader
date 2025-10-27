import os
import signal

import psutil


def pid_is_alive(pid: int) -> bool:
    try:
        process = psutil.Process(pid)
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False


def kill_pid_tree(pid: int) -> None:
    try:
        process = psutil.Process(pid)
    except psutil.Error:
        return

    for child in process.children(recursive=True):
        try:
            if os.name == "nt":  # pragma: no cover - platform specific
                child.send_signal(signal.SIGTERM)
            child.terminate()
        except psutil.Error:
            pass

    try:
        if os.name == "nt":  # pragma: no cover - platform specific
            process.send_signal(signal.SIGTERM)
        process.terminate()
    except psutil.Error:
        pass
