import atexit
import os
import queue as _queue
import string
import sys
import threading
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager

if os.name != "nt":
    import select
    import termios
    import tty
else:
    import msvcrt


# =====================================================================
# Constants & Key Mappings
# =====================================================================


class _KeysMeta(type):
    """Metaclass to dynamically auto-generate constants for letters, numbers, and modifier combinations."""

    def __new__(mcs, name, bases, attrs):
        for char in string.ascii_lowercase:
            upper_char = char.upper()
            attrs[upper_char] = char
            attrs[f"SHIFT_{upper_char}"] = upper_char
            attrs[f"CTRL_{upper_char}"] = f"ctrl+{char}"
            attrs[f"ALT_{upper_char}"] = f"alt+{char}"

        for digit in string.digits:
            attrs[f"NUM_{digit}"] = digit
            attrs[f"CTRL_{digit}"] = f"ctrl+{digit}"
            attrs[f"ALT_{digit}"] = f"alt+{digit}"

        return super().__new__(mcs, name, bases, attrs)


class Keys(metaclass=_KeysMeta):
    """
    Standardized constant repository for Oakey key names, matching Textual syntax.
    """

    # Special & Navigation Keys
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    ENTER = "enter"
    ESCAPE = "escape"
    TAB = "tab"
    SHIFT_TAB = "shift+tab"
    BACKSPACE = "backspace"
    DELETE = "delete"
    INSERT = "insert"
    HOME = "home"
    END = "end"
    PAGE_UP = "page_up"
    PAGE_DOWN = "page_down"
    SPACE = "space"

    # Function Keys
    F1 = "f1"
    F2 = "f2"
    F3 = "f3"
    F4 = "f4"
    F5 = "f5"
    F6 = "f6"
    F7 = "f7"
    F8 = "f8"
    F9 = "f9"
    F10 = "f10"
    F11 = "f11"
    F12 = "f12"


# =====================================================================
# Exceptions
# =====================================================================


class OakeyError(Exception):
    """Base exception for all oakey errors."""


class TerminalRestoreError(OakeyError):
    """Raised when failing to restore terminal state."""


# =====================================================================
# Listener Class
# =====================================================================


class KeyListener:
    """
    An asynchronous-style, zero-dependency key listener that captures raw keyboard input,
    translates keys to Textual raw input format, and places them into a thread-safe queue.
    """

    # Common POSIX ANSI escape sequences -> Textual key names
    ESCAPE_SEQUENCES = {
        # Function Keys (Xterm & VT220 formats)
        "\x1bOP": "f1",
        "\x1b[11~": "f1",
        "\x1bOQ": "f2",
        "\x1b[12~": "f2",
        "\x1bOR": "f3",
        "\x1b[13~": "f3",
        "\x1bOS": "f4",
        "\x1b[14~": "f4",
        "\x1b[15~": "f5",
        "\x1b[17~": "f6",
        "\x1b[18~": "f7",
        "\x1b[19~": "f8",
        "\x1b[20~": "f9",
        "\x1b[21~": "f10",
        "\x1b[23~": "f11",
        "\x1b[24~": "f12",
        # Arrow & Navigation Keys
        "\x1b[A": "up",
        "\x1b[B": "down",
        "\x1b[C": "right",
        "\x1b[D": "left",
        "\x1b[H": "home",
        "\x1b[F": "end",
        "\x1b[2~": "insert",
        "\x1b[3~": "delete",
        "\x1b[5~": "page_up",
        "\x1b[6~": "page_down",
        "\x1b[Z": "shift+tab",
        # Modifier Navigation Combinations
        "\x1b[1;5A": "ctrl+up",
        "\x1b[1;5B": "ctrl+down",
        "\x1b[1;5C": "ctrl+right",
        "\x1b[1;5D": "ctrl+left",
        "\x1b[1;2A": "shift+up",
        "\x1b[1;2B": "shift+down",
        "\x1b[1;2C": "shift+right",
        "\x1b[1;2D": "shift+left",
    }

    # Pre-sort by length descending (longest sequences evaluated first)
    SORTED_ESCAPE_SEQUENCES = sorted(
        ESCAPE_SEQUENCES.items(), key=lambda x: len(x[0]), reverse=True
    )

    # Windows msvcrt virtual scan code mappings
    WIN_SPECIAL_KEYS = {
        # Navigation Keys
        "H": "up",
        "P": "down",
        "K": "left",
        "M": "right",
        "G": "home",
        "O": "end",
        "R": "insert",
        "S": "delete",
        "I": "page_up",
        "Q": "page_down",
        "\x0f": "shift+tab",
        "72": "ctrl+up",
        "80": "ctrl+down",
        "75": "ctrl+left",
        "77": "ctrl+right",
        # Function Keys
        ";": "f1",
        "<": "f2",
        "=": "f3",
        ">": "f4",
        "?": "f5",
        "@": "f6",
        "A": "f7",
        "B": "f8",
        "C": "f9",
        "D": "f10",
        "\x85": "f11",
        "\x86": "f12",
    }

    def __init__(
        self,
        target_queue: _queue.Queue | None = None,
        on_error: Callable[[Exception], None] | None = None,
        suppress_errors: bool = True,
    ):
        self._target_queue = (
            target_queue if target_queue is not None else _queue.Queue()
        )
        self.on_error = on_error
        self.suppress_errors = suppress_errors

        self._running = False
        self._paused = False
        self._thread: threading.Thread | None = None
        self._orig_attr = None
        self._posix_buffer = ""

        atexit.register(self.stop)

    # ------------------------------------------------------------------
    # Queue Accessors & Methods
    # ------------------------------------------------------------------

    @property
    def queue(self) -> _queue.Queue:
        """Returns the current queue being used by the listener."""
        return self._target_queue

    def get_queue(self) -> _queue.Queue:
        """Explicit method wrapper to return the active queue."""
        return self._target_queue

    def get(self, block: bool = True, timeout: float | None = None) -> str:
        return self._target_queue.get(block=block, timeout=timeout)

    def get_nowait(self) -> str:
        return self._target_queue.get_nowait()

    def put(self, item: str, block: bool = True, timeout: float | None = None) -> None:
        self._target_queue.put(item, block=block, timeout=timeout)

    def empty(self) -> bool:
        return self._target_queue.empty()

    def qsize(self) -> int:
        return self._target_queue.qsize()

    def clear(self) -> None:
        try:
            while not self._target_queue.empty():
                self._target_queue.get_nowait()
        except _queue.Empty:
            pass

    # ------------------------------------------------------------------
    # Pause, Resume & Handoff Controls
    # ------------------------------------------------------------------

    def pause(self) -> None:
        if self.is_running():
            self._paused = True
            self._stop_thread_and_restore()

    def resume(self) -> None:
        if self._paused:
            self._paused = False
            self.start()

    def is_paused(self) -> bool:
        return self._paused

    @contextmanager
    def handoff(self) -> Generator[None]:
        was_running = self.is_running()
        if was_running:
            self.pause()
        try:
            yield
        finally:
            if was_running:
                self.resume()

    # ------------------------------------------------------------------
    # Lifecycle & Context Manager
    # ------------------------------------------------------------------

    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    def start(self) -> "KeyListener":
        if self.is_running():
            return self

        self._running = True
        self._paused = False
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._paused = False
        self._stop_thread_and_restore()

    def _stop_thread_and_restore(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            if threading.current_thread() != self._thread:
                self._thread.join(timeout=1.0)
        self._thread = None
        self._posix_buffer = ""
        self._restore_terminal()

    def __enter__(self) -> "KeyListener":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()

    # ------------------------------------------------------------------
    # Internal Engine & Parser Logic
    # ------------------------------------------------------------------

    def _listen_loop(self) -> None:
        try:
            self._prepare_terminal()
        except Exception as e:
            self._handle_error(e)
            return

        try:
            while self._running:
                try:
                    key = self._read_next_key()
                    if key:
                        self._target_queue.put(key)
                except Exception as e:
                    self._handle_error(e)
                    if not self.suppress_errors:
                        break
        finally:
            self._restore_terminal()

    def _handle_error(self, err: Exception) -> None:
        if self.on_error:
            try:
                self.on_error(err)
            except Exception:
                pass

    def _prepare_terminal(self) -> None:
        if os.name != "nt":
            try:
                if self._orig_attr is None:
                    self._orig_attr = termios.tcgetattr(sys.stdin.fileno())
                tty.setraw(sys.stdin.fileno())
            except Exception as e:
                raise OakeyError(f"Failed to set terminal to raw mode: {e}") from e

    def _restore_terminal(self) -> None:
        if os.name != "nt" and self._orig_attr is not None:
            try:
                termios.tcsetattr(
                    sys.stdin.fileno(), termios.TCSADRAIN, self._orig_attr
                )
                self._orig_attr = None
            except Exception as e:
                if not self.suppress_errors:
                    raise TerminalRestoreError(
                        f"Failed restoring terminal attributes: {e}"
                    ) from e

    def _read_next_key(self) -> str | None:
        if os.name == "nt":
            return self._read_key_windows()
        return self._read_key_posix()

    def _read_key_windows(self) -> str | None:
        if not msvcrt.kbhit():
            time.sleep(0.01)
            return None

        ch = msvcrt.getwch()

        if ch in ("\x00", "\xe0"):
            if msvcrt.kbhit():
                code = msvcrt.getwch()
                return self.WIN_SPECIAL_KEYS.get(code, f"special_{ord(code)}")
            return None

        code = ord(ch)
        if code == 3:
            return "ctrl+c"
        if code in (13, 10):
            return "enter"
        if code == 9:
            return "tab"
        if code == 27:
            return "escape"
        if code == 8:
            return "backspace"
        if code == 32:
            return "space"
        if 1 <= code <= 26:
            return f"ctrl+{chr(code + 96)}"

        return ch

    def _read_key_posix(self) -> str | None:
        if not self._posix_buffer:
            rlist, _, _ = select.select([sys.stdin], [], [], 0.05)
            if rlist:
                try:
                    chunk = os.read(sys.stdin.fileno(), 1024).decode(
                        "utf-8", errors="replace"
                    )
                    self._posix_buffer += chunk
                except Exception:
                    pass

        if not self._posix_buffer:
            return None

        buf = self._posix_buffer

        for seq, name in self.SORTED_ESCAPE_SEQUENCES:
            if buf.startswith(seq):
                self._posix_buffer = buf[len(seq) :]
                return name

        if buf.startswith("\x1b"):
            if len(buf) >= 2 and buf[1] not in ("[", "O"):
                char = buf[1]
                self._posix_buffer = buf[2:]
                return f"alt+{char}"

            if len(buf) == 1:
                self._posix_buffer = ""
                return "escape"

            if any(seq.startswith(buf) for seq, _ in self.SORTED_ESCAPE_SEQUENCES):
                return None

            self._posix_buffer = ""
            return f"raw_{buf!r}"

        first_char = buf[0]
        self._posix_buffer = buf[1:]

        code = ord(first_char)
        if code == 3:
            return "ctrl+c"
        if first_char in ("\r", "\n"):
            return "enter"
        if first_char == "\t":
            return "tab"
        if first_char == " ":
            return "space"
        if code in (8, 127):
            return "backspace"
        if 1 <= code <= 26:
            return f"ctrl+{chr(code + 96)}"

        return first_char
