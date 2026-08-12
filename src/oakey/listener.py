import os
import sys
import queue
from queue import Queue
import threading
import time
import atexit
import string
from typing import Optional, Callable, Any

# Platform-specific standard library imports
if os.name == "nt":
    import msvcrt
else:
    import termios
    import tty
    import select


# =====================================================================
# Exceptions
# =====================================================================

class OakeyError(Exception):
    """Base exception for all oakey errors."""
    pass


class TerminalRestoreError(OakeyError):
    """Raised when failing to restore terminal state."""
    pass


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
        "\x1b[1;5A": "ctrl+up",
        "\x1b[1;5B": "ctrl+down",
        "\x1b[1;5C": "ctrl+right",
        "\x1b[1;5D": "ctrl+left",
        "\x1b[1;2A": "shift+up",
        "\x1b[1;2B": "shift+down",
        "\x1b[1;2C": "shift+right",
        "\x1b[1;2D": "shift+left",
    }

    # Pre-sort by length descending (longest sequences evaluated first) to prevent partial sequence matching
    SORTED_ESCAPE_SEQUENCES = sorted(
        ESCAPE_SEQUENCES.items(), key=lambda x: len(x[0]), reverse=True)

    # Windows msvcrt virtual scan code mappings
    WIN_SPECIAL_KEYS = {
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
    }

    def __init__(
        self,
        target_queue: Optional[queue.Queue] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        suppress_errors: bool = True
    ):
        """
        :param target_queue: Optional queue to put keys into. Creates one if None.
        :param on_error: Optional callback function triggered when an exception occurs.
        :param suppress_errors: If True, errors in the thread won't crash the loop.
        """
        self._queue = target_queue if target_queue is not None else queue.Queue()
        self.on_error = on_error
        self.suppress_errors = suppress_errors

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._orig_attr = None
        self._posix_buffer = ""

        # Emergency exit hook to ensure terminal state is never left corrupted
        atexit.register(self.stop)

    # ------------------------------------------------------------------
    # Queue Accessors & Methods
    # ------------------------------------------------------------------

    @property
    def queue(self) -> Queue:
        """Returns the current queue being used by the listener."""
        return self._queue

    def get_queue(self) -> Queue:
        """Explicit method wrapper to return the active queue."""
        return self._queue

    def get(self, block: bool = True, timeout: Optional[float] = None) -> str:
        """Get a key event directly from the listener queue."""
        return self._queue.get(block=block, timeout=timeout)

    def get_nowait(self) -> str:
        """Fetch a key non-blockingly from the queue."""
        return self._queue.get_nowait()

    def put(self, item: str, block: bool = True, timeout: Optional[float] = None) -> None:
        """Inject an event/item manually into the queue."""
        self._queue.put(item, block=block, timeout=timeout)

    def empty(self) -> bool:
        """Checks if the queue is empty."""
        return self._queue.empty()

    def qsize(self) -> int:
        """Returns the current size of the queue."""
        return self._queue.qsize()

    def clear(self) -> None:
        """Flushes all unhandled key events from the queue."""
        with self._queue.mutex:
            self._queue.queue.clear()

    # ------------------------------------------------------------------
    # Lifecycle & Context Manager
    # ------------------------------------------------------------------

    def is_running(self) -> bool:
        """Returns True if the listener thread is active."""
        return self._running and self._thread is not None and self._thread.is_alive()

    def start(self) -> "KeyListener":
        """Starts the background listening thread."""
        if self.is_running():
            return self

        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        """Stops the listener thread and safely restores terminal settings."""
        self._running = False
        if self._thread and self._thread.is_alive():
            if threading.current_thread() != self._thread:
                self._thread.join(timeout=1.0)
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
        """Main loop executing in background thread."""
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
                        self._queue.put(key)
                except Exception as e:
                    self._handle_error(e)
                    if not self.suppress_errors:
                        break
        finally:
            self._restore_terminal()

    def _handle_error(self, err: Exception) -> None:
        """Triggers error callbacks or logs exceptions safely."""
        if self.on_error:
            try:
                self.on_error(err)
            except Exception:
                pass  # Avoid cascading failure inside error handler

    def _prepare_terminal(self) -> None:
        """Puts terminal into raw unbuffered mode on POSIX systems."""
        if os.name != "nt":
            try:
                self._orig_attr = termios.tcgetattr(sys.stdin.fileno())
                tty.setraw(sys.stdin.fileno())
            except Exception as e:
                raise OakeyError(
                    f"Failed to set terminal to raw mode: {e}") from e

    def _restore_terminal(self) -> None:
        """Restores original terminal state on POSIX systems."""
        if os.name != "nt" and self._orig_attr is not None:
            try:
                termios.tcsetattr(sys.stdin.fileno(),
                                  termios.TCSADRAIN, self._orig_attr)
                self._orig_attr = None
            except Exception as e:
                if not self.suppress_errors:
                    raise TerminalRestoreError(
                        f"Failed restoring terminal attributes: {e}") from e

    def _read_next_key(self) -> Optional[str]:
        """Routes reading logic by operating system."""
        if os.name == "nt":
            return self._read_key_windows()
        return self._read_key_posix()

    def _read_key_windows(self) -> Optional[str]:
        """Windows key capturing via msvcrt."""
        if not msvcrt.kbhit():
            time.sleep(0.01)
            return None

        ch = msvcrt.getwch()

        # Handle Extended Keys (arrows, function keys, etc.)
        if ch in ("\x00", "\xe0"):
            if msvcrt.kbhit():
                code = msvcrt.getwch()
                return self.WIN_SPECIAL_KEYS.get(code, f"special_{ord(code)}")
            return None

        # Control Codes & Characters
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

    def _read_key_posix(self) -> Optional[str]:
        """Unix/macOS chunked reading, exactly as Textual/prompt_toolkit handles it."""
        # 1. Pull everything from the OS into the buffer instantly
        if not self._posix_buffer:
            rlist, _, _ = select.select([sys.stdin], [], [], 0.05)
            if rlist:
                try:
                    # os.read bypasses sys.stdin's 1-byte bottleneck and grabs the whole sequence
                    chunk = os.read(sys.stdin.fileno(), 1024).decode(
                        'utf-8', errors='replace')
                    self._posix_buffer += chunk
                except Exception:
                    pass

        if not self._posix_buffer:
            return None

        buf = self._posix_buffer

        # 2. Check for known escape sequences (longest match first)
        for seq, name in self.SORTED_ESCAPE_SEQUENCES:
            if buf.startswith(seq):
                # Consume the sequence from the buffer and return
                self._posix_buffer = buf[len(seq):]
                return name

        # 3. Dynamic Escape (\x1b) parsing
        if buf.startswith("\x1b"):
            # Alt+Key combo (e.g., \x1ba -> alt+a)
            if len(buf) >= 2 and buf[1] not in ('[', 'O'):
                char = buf[1]
                self._posix_buffer = buf[2:]
                return f"alt+{char}"

            # Standalone Escape
            if len(buf) == 1:
                self._posix_buffer = ""
                return "escape"

            # If it's a known prefix (e.g. we read "\x1b[" but the rest hasn't arrived), wait.
            if any(seq.startswith(buf) for seq, _ in self.SORTED_ESCAPE_SEQUENCES):
                return None

            # Unknown sequence - consume it entirely so it doesn't block the loop
            self._posix_buffer = ""
            return f"raw_{repr(buf)}"

        # 4. Standard character parsing
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
