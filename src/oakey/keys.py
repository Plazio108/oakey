
import string


class _KeysMeta(type):
    """Metaclass to dynamically auto-generate constants for letters, numbers, and modifier combinations."""
    def __new__(mcs, name, bases, attrs):
        # 1. Auto-generate letters (A-Z maps to lowercase, UPPER_A maps to uppercase, CTRL_A, ALT_A)
        for char in string.ascii_lowercase:
            upper_char = char.upper()
            attrs[upper_char] = char                    # Keys.A = "a"
            attrs[f"SHIFT_{upper_char}"] = upper_char   # Keys.SHIFT_A = "A"
            # Keys.CTRL_A = "ctrl+a"
            attrs[f"CTRL_{upper_char}"] = f"ctrl+{char}"
            attrs[f"ALT_{upper_char}"] = f"alt+{char}"   # Keys.ALT_A = "alt+a"

        # 2. Auto-generate numeric digits (NUM_0 to NUM_9, CTRL_0 to CTRL_9)
        for digit in string.digits:
            attrs[f"NUM_{digit}"] = digit
            attrs[f"CTRL_{digit}"] = f"ctrl+{digit}"
            attrs[f"ALT_{digit}"] = f"alt+{digit}"

        return super().__new__(mcs, name, bases, attrs)


class Keys(metaclass=_KeysMeta):
    """
    Standardized constant repository for Oakey key names, matching Textual syntax.
    Auto-generates letters (A-Z), numbers (0-9), and common combinations.
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
