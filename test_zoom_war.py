"""Cek cepat parser link:  python test_zoom_war.py"""
import zoom_war
from zoom_war import BLUE, build_zoommtg, fmt_id, paint, parse_link, visible_len

zoom_war.ANSI = True  # exercise the colored path too

assert parse_link("https://us06web.zoom.us/j/81234567890?pwd=abc") == \
    ("us06web.zoom.us", "81234567890", {"pwd": "abc"})
assert parse_link("812 3456 7890") == ("zoom.us", "81234567890", {})
assert parse_link("https://app.zoom.us/wc/join/81234567890?pwd=p")[0] == "zoom.us"
assert parse_link("https://zoom.us/w/81234567890?tk=T&pwd=x")[2] == {"pwd": "x", "tk": "T"}
for salah in ("https://zoom.us/j/812345678901234",          # 15 digit, bukan ID valid
              "https://zoom.us/my/budi?pwd=12345678901"):   # angka passcode bukan ID
    try:
        parse_link(salah)
        raise AssertionError(f"harusnya ditolak: {salah}")
    except ValueError:
        pass
assert build_zoommtg("zoom.us", "123456789", {"tk": "T"}, "Jane Doe") == \
    "zoommtg://zoom.us/join?action=join&confno=123456789&tk=T&uname=Jane%20Doe"
assert fmt_id("81234567890") == "812 3456 7890" and fmt_id("123456789") == "123 456 789"
assert visible_len(paint("abc", BLUE, bold=True)) == 3
print("OK")
