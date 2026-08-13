"""
The 16x2 display. One handle, one show().

Hardware: I2C backpack on a PCF8574 at address 0x27, confirmed with
`i2cdetect -y 1`. Driver is RPLCD, installed with --break-system-packages.

show() rewrites both lines in place rather than calling clear() first. clear()
blanks the panel for a few milliseconds, and since the running count redraws on
every count event that reads as a visible flicker on every device through the
beam. Padding each line to 16 characters overwrites the old text with no gap.
"""
from RPLCD.i2c import CharLCD

COLS = 16
ROWS = 2
I2C_ADDRESS = 0x27
I2C_EXPANDER = "PCF8574"

_lcd = None


def _open():
    """Open the display once and keep the handle."""
    global _lcd
    if _lcd is None:
        # auto_linebreaks off: we place the cursor and pad explicitly, and the
        # driver's own wrapping would fight that on any string near 16 chars.
        lcd = CharLCD(I2C_EXPANDER, I2C_ADDRESS, cols=COLS, rows=ROWS,
                      auto_linebreaks=False)
        lcd.clear()
        _lcd = lcd
    return _lcd


def show(line1="", line2=""):
    """Write both lines. Text longer than 16 characters is truncated.

    Truncation is deliberate: a 16x2 panel cannot show more, and letting the
    driver wrap turns a slightly-too-long status into unreadable overflow on
    the second line, which is where the count lives.
    """
    lcd = _open()
    for row, text in enumerate((line1, line2)):
        lcd.cursor_pos = (row, 0)
        lcd.write_string(str(text)[:COLS].ljust(COLS))


def clear():
    """Blank the display."""
    _open().clear()


def close(blank=True):
    """Release the display, blanking it first unless blank=False.

    Leaving the last message up is useful when the person who needs to read it
    is not standing at the Pi when the program exits.
    """
    global _lcd
    if _lcd is not None:
        if blank:
            _lcd.clear()
        _lcd.close()
        _lcd = None


if __name__ == "__main__":
    import time

    # The screens main.py will actually draw, so this doubles as a preview of
    # what the crew sees during a session.
    screens = [
        ("BaettLedger", "LCD OK"),
        ("OUT session", "Count: 0"),
        ("OUT session", "Count: 3"),
        ("Captured #4", "cone"),
        ("OFFLINE", "queued: 12"),
        ("Draining...", "3 left"),
        ("Session closed", "Total: 4"),
        ("A-very-long-line-that-overflows", "0123456789ABCDEFGHIJ"),
    ]

    print(f"writing {len(screens)} screens to the LCD at 0x{I2C_ADDRESS:02x} ...\n")
    for line1, line2 in screens:
        show(line1, line2)
        print(f"  |{line1[:COLS]:<16}|")
        print(f"  |{line2[:COLS]:<16}|")
        print()
        time.sleep(1.5)

    show("BaettLedger OK", "16x2 @ 0x27")
    close(blank=False)  # leave it readable for whoever walks over next

    print("The panel ACKed at 0x27 and took every write without error.")
    print()
    print("That proves the bus and the address, NOT that the text is legible --")
    print("a wrong contrast pot or a dead backlight looks identical from here.")
    print("The display has been left showing:")
    print("  |BaettLedger OK  |")
    print("  |16x2 @ 0x27     |")
    print("If it is blank or shows solid blocks, turn the contrast pot on the")
    print("back of the I2C backpack until the characters appear.")
