"""Cek cepat parser link:  python test_zoom_war.py"""
from zoom_war import build_zoommtg, parse_link

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
assert build_zoommtg("zoom.us", "123456789", {"tk": "T"}, "Abdani Z") == \
    "zoommtg://zoom.us/join?action=join&confno=123456789&tk=T&uname=Abdani%20Z"
print("OK")
