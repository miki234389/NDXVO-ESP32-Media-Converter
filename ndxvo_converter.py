#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NDXVO ESP32 File Converter
==========================

Single-file GUI for converting videos / stills into MJPEG-AVI clips that an
ESP32 device with a 172x320 panel can play straight from an SD card.

Reference command this tool generalises:

    ffmpeg -y -i input5.mp4 -an -pix_fmt yuvj420p -c:v mjpeg -q:v 2 \
      -vf "fps=30,scale=-2:320:flags=lanczos,crop=172:320:(in_w-172)/2:0,hflip,vflip" \
      video5.avi

Run:      python ndxvo_converter.py
Requires: Python 3.9+, Pillow, and ffmpeg (bundled, on PATH, or beside the app).
"""

import base64
import io
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser

try:
    from PIL import Image, ImageTk, ImageDraw
except ImportError:  # pragma: no cover
    try:
        _r = tk.Tk()
        _r.withdraw()
        messagebox.showerror(
            "Missing dependency",
            "Pillow is required.\n\nInstall it with:\n\n    pip install pillow",
        )
    except Exception:
        print("Pillow is required:  pip install pillow", file=sys.stderr)
    sys.exit(1)


# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

APP_TITLE = "NDXVO ESP32 File Converter"

# The release workflow rewrites the line below in place, so it must stay exactly
# in the form  APP_VERSION = "<value>"  on a single line. The "-dev" default is
# what a run straight from source reports, which keeps it visibly distinct from
# a build produced by CI.
APP_VERSION = "1.0.0-dev"

OUT_W, OUT_H = 172, 320  # forced device resolution

# Geometry of the embedded device photo (800x800 source), measured against a
# reference shot of the panel showing a real UI.
MOCKUP_SCREEN = (297, 227, 207, 385)   # x, y, w, h of the active LCD area
MOCKUP_CROP = (255, 165, 545, 635)     # visible region of the photo we display
# The panel masks its corners; the radius is ~8.6% of the screen width.
# This affects the preview only — the encoded video is always a full rectangle.
CORNER_RADIUS_RATIO = 0.086

FPS_CHOICES = (30, 25)
ROTATION_CHOICES = (0, 90, 180, 270)
QUALITY_MIN, QUALITY_MAX = 1, 31       # ffmpeg -q:v range for mjpeg

PREVIEW_DEBOUNCE_MS = 150
STEP_SECONDS = 0.5

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".webm", ".mpg", ".mpeg",
              ".wmv", ".flv", ".3gp", ".ts", ".m2ts", ".mts", ".ogv"}

MOCKUP_B64 = (
    "/9j/4AAQSkZJRgABAQAAAQABAAD//gA7Q1JFQVRPUjogZ2QtanBlZyB2MS4wICh1c2luZyBJSkcgSlBFRyB2ODApLCBxdWFs"
    "aXR5ID0gOTAK/9sAQwADAgIDAgIDAwMDBAMDBAUIBQUEBAUKBwcGCAwKDAwLCgsLDQ4SEA0OEQ4LCxAWEBETFBUVFQwPFxgW"
    "FBgSFBUU/9sAQwEDBAQFBAUJBQUJFA0LDRQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQU"
    "FBQU/8AAEQgDIAMgAwEiAAIRAQMRAf/EAB8AAAEFAQEBAQEBAAAAAAAAAAABAgMEBQYHCAkKC//EALUQAAIBAwMCBAMFBQQE"
    "AAABfQECAwAEEQUSITFBBhNRYQcicRQygZGhCCNCscEVUtHwJDNicoIJChYXGBkaJSYnKCkqNDU2Nzg5OkNERUZHSElKU1RV"
    "VldYWVpjZGVmZ2hpanN0dXZ3eHl6g4SFhoeIiYqSk5SVlpeYmZqio6Slpqeoqaqys7S1tre4ubrCw8TFxsfIycrS09TV1tfY"
    "2drh4uPk5ebn6Onq8fLz9PX29/j5+v/EAB8BAAMBAQEBAQEBAQEAAAAAAAABAgMEBQYHCAkKC//EALURAAIBAgQEAwQHBQQE"
    "AAECdwABAgMRBAUhMQYSQVEHYXETIjKBCBRCkaGxwQkjM1LwFWJy0QoWJDThJfEXGBkaJicoKSo1Njc4OTpDREVGR0hJSlNU"
    "VVZXWFlaY2RlZmdoaWpzdHV2d3h5eoKDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW"
    "19jZ2uLj5OXm5+jp6vLz9PX29/j5+v/aAAwDAQACEQMRAD8A/VOiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKK"
    "KACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKK"
    "KACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKK"
    "KACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKK"
    "KACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKK"
    "KACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKK"
    "KACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKK"
    "KACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKK"
    "KACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKK"
    "KACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKK"
    "KACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKK"
    "KACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKK"
    "KACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKK"
    "KACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKK"
    "KACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKK"
    "KACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKK"
    "KACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKK"
    "KACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKK"
    "KACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKK"
    "KACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKK"
    "KACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKK"
    "KACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKK"
    "KACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKK"
    "KACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKK"
    "KACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKK"
    "KACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKK"
    "KACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKK"
    "KACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKK"
    "KACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKK"
    "KACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKRmCjJOB6mgBaKptrFgjFWvbdWHUGVf8AGmnXdNH/ADELX/v+"
    "v+NAF6iqI1zTj/y/2v8A3+X/ABpRrOnn/l+tv+/y/wCNK4F2iqg1exPS8tz/ANtV/wAaUanZnpdwH/toP8aYFqiq639s/wB2"
    "eJvo4qT7TF/z1T/voUASUVGJ4z/y0T/voUomjP8AGv5igB9FNDqf4h+dLnNAC0UUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUU"
    "UAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUU"
    "UAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRWTrHi3R"
    "PDpUarrGn6YW6fbLpIs/TcRXm/xT/ai8A/DLwzLqr+ItI1aZW2paWmpwl27knDE4GOwJJxgVMpKKbY0ruyPXqK/Kz9pn/gqD"
    "PfW1tpfhGzT5k813huHCAngCQjBbjnbx754x8mXf7cfxXlnkkg1CGzLHpFCcj8ya8z61iZzao0Lx7tqN/RWb++x1+xpqN5zs"
    "+yVz95PF3j7RfBFkbjVLtY2xlbdCGlf/AHV/r096+efir+0r4V8Sf2da2/8AaKRwSM86NGu1wRgDh+cHNfkZqH7YvxT1JH+0"
    "asHDcljbrlvxxzXPzftH+Pbhi73yf9+F5/SuSos3qTfKoRj2u2/m7L8j0MP/AGbBXrOTl5WSP180T4m/DGXw/Kt/Hql5eBHd"
    "bWZT5G7Bx0foc+30r5/tL7ULSazltbsK6Ozyhn3KELZAAbOevevgBf2kvHsacXq/9+F5/SpYf2mfHcbkmdGPqYgM1zzoZs9Y"
    "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"
    "EJkKn8D6VnQXE2n3cc8LmOeBw6OOqsDkEfiKpMD9P7zX5oP2MPGSxFIC2oQ2m2LGQubMEMQeSdpHPYiv1B8K8+GNI/684f8A"
    "0AV+WfjOFvEf7IHi7WLiYiSXWEu1ETbVlaSS1c7h7bjj6dM5r9S/CbB/C2jsBgNZwkD/AIAKjdth0NaiiimAUUUUAFFFFABR"
    "RRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABR"
    "RRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQBV1Rtum3ZPQQuf/HTX8+37TauPhf8"
    "HCRiNrLVNvGOmp3Gc/nX74fEG5ubTwhqclpJ5UwgfD7Q2BtJPB9hX4J/tPStN8Kfgq7Agmw1bGfT+058f1qU/eaHbS54HpyY"
    "iZu5NW6rWH/HuPqas1QgooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigArLvlxcN7jNal"
    "Zmof68/SmgP0fbUluf2HtUgMm6FdTtdzHkAE244+rKeK/VnwSjR+DtCRwVdbC3DA9QfLXNfk8u6T9gu9KYRE1a2Vhu9ZIf8A"
    "6x/E1+q/w4uLi68FaS90/mTfZ4/m2gcbRjge1Z83vcpVtLnS0UUVZIUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFA"
    "BRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFA"
    "BRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABXmOv/tMfC7wtrV3pGq+NdLstStJGhnt5JDujdTgqcDqDxXp1fh5+1rcTH9oz4hY"
    "baF1y7AAPPErVSVwP1L8V/tXfBvV9Av7FfHWmXE80DpFFGZCzOVO0DC9c4r8ZP2mblbr4U/BZlGNthqyn6jU56n8P3Kpqliz"
    "TSKwnjJJGQPmHaqn7SUQj+EvwSZcbZdM1OTj31O4/Lp/nNDjZgeG2H/HuPqas1WsP+PcfU1ZqQCiiigAooooAKKKKACiiigA"
    "ooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACszUP9efpWnWZqH+vP0poD7+1PWZrT9iuwsgMJqOsRq4I4+UxsAPf5"
    "R+dfo54R/as+DejeHtO09vHOmW08ECRyxSGQMrhQGByvXINfmN4nW5b9j/wyYpMRDWx+7J5YlVxj/D3rybxDchtWvz5shk+0"
    "SdsZ+Y9qSjeQ+h+3ugftMfC7xTrVppGleNdLvdSu5Fhgt45DukdjgKMjqTxXp1fh5+yVcTD9oz4e5bcG1y0BBPP+tWv3Dqmr"
    "CCiiipAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiii"
    "gAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACvw6/a1gM37RXxCIwB/b"
    "l4Djr/rmr9xa+AvjL/wTl8TfET4l+JfE+m+I9Ft4dV1Ca+SK684OnmOXwdqEcZ7VcWk9QPzs0KxdtUsyJAYzKoKN0+8PzqL9"
    "pZoz8JPgaEJO3Rr8HJ7/ANpXGa+1bv8A4JjeO9AtpNRl8QeHLi3s1NxIkc04d0X5mAzD1wDjkfWviH9omO4T4U/Bfz8f8gvU"
    "AmB/D/aVzihu70A8UsP+PcfU1ZqtYf8AHuPqas1ABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUU"
    "UUAFFFFABWbf/wDHx+ArSrNv/wDj4/AU0B92areQ2f7HPg7ztw/4qNAVUAHoORnvXjHiOyf+2r9jJhBO+EHT759K9h1+5W0/"
    "Y88C3LIJSPE8Z2tnDYQ9cf56V7fH/wAEzfH3ihf7WXxB4bgi1D/SkR5Z9yq/zAHEOM4IBwcURaUtQ6Hz3+yZBHD+0J8OsKTL"
    "/b1nly2RjzUx9P8A69fuDXwF8Gv+Ccvib4d/Evw14n1LxHotxDpWoQ3zxWvnF38tw+BuQDnHevv2qk03oAUUUVABRRRQAUUU"
    "UAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUU"
    "UAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAch8WJ7m28Aa29rOYJRaTcqqnI2Nkcg"
    "1+Fn7W20/Df4HMqhAfDs/C9P+P64z+ua/ePx9ZQ6h4J12GdBJG1jPlScf8s2r8I/2vWJ+GXwLXj5PDs3Q5xm9uCP0pRT5mxu"
    "1j5xsP8Aj3/E1ZqtYf8AHv8Aias0xBRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABWb"
    "f/8AHx+ArSrN1D/X/gKaA+6tTUt+yN4Ejf5oz4nTaSOclD/ga/X34YXFzc+CNJe6nM8pt4+SqjA2DA4Ar8h707/2QPh+qsAT"
    "4qQ4J5z5Zr9ivB2nxaX4W0m2hjESR2kS7Ac4wgFZNPn8irqxs0UUVoSFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRR"
    "QAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRR"
    "QAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAY3jQ48H64c4xYz8/9s2r8H/2v1/4th8CmyGz4bfLKOrfapyR+BOPwr92/"
    "H2R4G8RY4P8AZ1zg/wDbJq/Cv9sOEr8KfgNId3zeGSPu8f8AHzOev49KaA+aLD/j3/E1ZqtYf8e/4mrNIAooooAKKKKACiii"
    "gAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigArN1D/X/gK0qzdQ/wBf+ApoD7rv4gf2RvAE7EF28UxryO3l"
    "t/8AW/Kv2b0cbdKsh6QIP/HRX4x3kjH9kf4fxBFcDxQp3g8H92cD/PpX7O6T/wAguzP/AExTp/uio+0PoW6KKKoQUUUUAFFF"
    "FABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFF"
    "FABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQBg+PjjwN4iPpp1z/6Kavw2/bS"
    "j8n4W/AeNH3Rf8IvE4GO5klJ71+43xDJHgLxJjJP9mXPA/65NX4XftkXAk+GvwLjMm908KxDGOQBNOuPzUj8KaA+aLD/AI9/"
    "xNWarWH/AB7/AImrNIAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigArN1D/AF/4CtKs"
    "3UP9f+ApoD7sv4yf2Ovh8FUEt4pTDHj/AJZt/jX7OaUu3TLQE5IhQf8Ajor8ZJLcz/sl/DqRt2w+KkTajdMxt+vSv2esV22c"
    "C+kaj9Kj7TH0J6KKKoQUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRR"
    "RQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRR"
    "RQBznxHfy/h94nf+7pd0f/ITV+GH7ZUkknw5+BpkVufCsREjDqPPuBj9OnvX7k/FNivwy8XEdRo94f8AyC9fht+2aMfD34Eg"
    "Ky48HWv3hj/lrOf6011A+aNP/wBR+JqzVbT/APUfias0gCiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACii"
    "igAooooAKKKKACs3UP8AX/gK0qzdQ/1/4CmgPvm3kX/hlb4XxkFnHi2MnjgARmv2VgGIIx/sj+VfjRax4/ZR+GOxirnxfFhw"
    "en7tv15r9mIv9Un+6Kj7TH0H0UUVQgooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoo"
    "ooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoo"
    "ooAKKKKACiiigDlfitz8L/GA6H+x7zp/1wevw+/bckL+B/gSu0jb4KsiST6vP/hX7f8AxaAPws8ZZ6f2Ne5/78PX4d/tnED4"
    "efAtQuM+DbMnPJz511n37/yoQHzNp/8AqPxNWaraf/qPxNWaACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKK"
    "ACiiigAooooAKKKKACs3UP8AX/gK0qzdQ/1/4CmgPvvTw8/7LnwryzJAfF8aj1z5bf4V+yqDCL9K/GqwYL+yv8Ko1fDHxjC2"
    "wd/kP9K/ZYcVH2mPoLRRRVCCiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooo"
    "oAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooo"
    "oAKKKKAOQ+ML+X8JvGrnB26JfHnp/qHr8QP2zyD8OvgUwJIbwbZjkYwRNdCv27+NBx8HvHR/6gN//wCk71+JH7a0Lx/D34F5"
    "JKf8IbZYz7yXJ/z7U1uwPmDT/wDUfias1V0//UH/AHqtUgCiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACs3UP9f+ArSrN1D/X/AICmgP0D8OxKP2ZfhG7fffxpCmDzuXyz+lfsfX42aE7Sfs1/CCJI8oPGkBJ7/cIP"
    "9a/ZOp+0x9AooopiCiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKA"
    "CiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKA"
    "OL+NbbPg547bOMaDfnP/AG7vX4p/t0BB4G+BfltuT/hC7HBHT79x0r9qvjdkfBnx7g4P9gah/wCk0lfiV+2kd3w4+BLHfuPg"
    "+1B3pt4E10B+g/r3oW7A+YNP/wBQf96rVVdP/wBQf96rVABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABR"
    "RRQAUUUUAFFFFABWbqH+v/AVpVm3/wDx8fgKaA/Qjwvx+zf8GYjtZZPHMOeckfu6/Yqvx38GW4m/Z0+Dbvkt/wAJ3booBxj5"
    "P68flX7EVP2mPoFFFFMQUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABR"
    "RRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABR"
    "RRQBw3x1bb8EviCe48Pagf8AyWkr8Uf22UaL4dfAeN43R/8AhDbRsu+44Mtz+nf2BFftZ8eP+SH/ABC5x/xTuo8/9u0lfjL+"
    "3yuzwf8ABBDyV8G2IB7Y8y5x1prqB8laf/qD/vVaqrp/+oP+9VqkAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFAB"
    "RRRQAUUUUAFFFFABRRRQAVm3/wDx8fgK0qzb/wD4+PwFNAfoh4LiWT9nv4Iuq4C+PbdSSe+wH/P0r9gq/HzwI+z9nz4KxHjz"
    "PH1uRj/cx/Wv2DqftMfQKKKKYgooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAK"
    "KKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAK"
    "KKKACiiigDgfj8234FfEU+nhzUT/AOS0lfjP+3ysn/CJfBSRwBu8H2OBnJH7y6/HvX7N/HkRt8EPiCJnMcJ8P6gHdV3FV+zy"
    "ZIHfjtX43f8ABQbyl8JfBFYeUHg6xw3qu64wf5011A+QdP8A9Qf96rVVdP8A9Qf96rVIAooooAKKKKACiiigAooooAKKKKAC"
    "iiigAooooAKKKKACiiigAooooAKKKKACiiigArNv/wDj4/AVpVm3/wDx8fgKaA/RX4fr5vwD+CG4nK+PrZRk8Y2f/Wr9fa/I"
    "H4eKyfAv4FqMYfx9bE+v3RX6/VPVj6BRRRTEFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAU"
    "UUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAU"
    "UUUAFFFFABRRRQAUUUUAee/tDsU+AfxIYdR4b1E/+S0lfjl/wUIUL4c+CQ2lSvgrTh+G65r9i/2jG2/s/wDxKP8A1LWo/wDp"
    "NJX4/wD/AAUVi8jQfg1EQD5fhGxj3LznD3Q6/hTXUD450/8A1B/3qtVV0/8A1B/3qtUgCiiigAooooAKKKKACiiigAooooAK"
    "KKKACiiigAooooAKKKKACiiigAooooAKKKKACs2//wCPj8BWlWbf/wDHx+ApoD9Gfhpz8FPgYvUf8LAtQO3O3/8AVX681+RP"
    "w0RT8Iv2f0Xgnx5bEgnvgV+u1T9pj6BRRRTEFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAU"
    "UUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAU"
    "UUUAFFFFABRRRQAUUUUAec/tIHH7PnxLP/Utaj/6TSV+Qn/BRVz/AMIz8GFBVkbwnYuShypO656fmfzr9ev2kWC/s9/Esnp/"
    "wjeo/wDpM9fkN/wUUix4S+CUhkyf+ERsV2495zn9aa6gfGun/wCoP+9Vqqun/wCoP+9VqkAUUUUAFFFFABRRRQAUUUUAFFFF"
    "ABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAVmah/rz9K06zb/wD4+PwFNAfpD8LYEk+GP7P0qgKzePrZQo/u4H+NfrjX"
    "5KfCud5vhz+zfC67SPHUCj0YDbg/rX611P2mPoFFFFMQUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUU"
    "AFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUU"
    "AFFFFABRRRQAUUUUAFFFFABRRRQB5t+0rj/hnn4mbmKr/wAI3qOWHUD7M9fkH/wUWiMWg/BNc7kXwfZIG7Eh581+vX7TLiP9"
    "nb4mseg8N6gf/Jd6/JX/AIKWwxw6X8IVwWceGrdVcHC4EtyCMfl+VNAfFWnf6g/73+FWqq6d/qG/3v6CrVIAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigArM1D/X/hWnWZqH+v/CmgP0s+EcLN4D/Zw8x1zJ46hkXJ"
    "zxhOnpX6z1+SHwcJ/wCEa/Zvi37gPHEWR6H93X631P2mHQKKKKYBRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFF"
    "FFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFF"
    "FFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFAHmH7UJI/Zv+KGOT/wjWo/+k71+Sf/AAUmYtpHwZJBy3hW3O5uv+snOPTPNfrX"
    "+1Hgfs3/ABPJGQPDWoHA/wCvd6/Jf/gpDg+GPgngKP8Ailbb7vP8c3Q+lNdRHxbp3+ob/e/oKtVV07/UN/vf0FWqQwooooAK"
    "KKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigArNv/8Aj4/AVpVmah/r/wAKaA/ST4Jqv9gfs3xY"
    "Pmf8JvExz2AEVfrfX5JfA4+bpX7N2BhV8aIoPc8Rn8K/W2p+0w6BRRRTAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooA8t/ambZ+zX8Um9PDOo/+k71+UH/AAUxx/Y3wbVfup4ahQELgHEkw6du"
    "nT3r9Xv2qf8Ak2r4pY6/8I1qGP8AwHevyo/4KcIF0r4SHcp/4kKAYOcgTT85/Gmuoj4f07/UN/vf0FWqqad/qW/3v6CrdIYU"
    "UUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAVmah/r/wFadZmof68/SmgP0r+Bkqiy/Zs"
    "t1O9T4xEm7HA+WIc+/Wv1or8j/gHA32r9m9iBt/4SvAAOeiQn/P1r9cKnqwCiiimAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQ"
    "AUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQ"
    "AUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQB5Z+1OQP2bPihld3/FN342+v7h6/KT/gpXGP+EZ+DbIwKDw3"
    "BtI6HMk549q/Vj9q44/Zo+KHOP8AinL7n/tg1flZ/wAFMHR/Dvwh2Btv/CO2pXeOcb7jOeg9O1VHqJnw7p3+pb/eq3VTTv8A"
    "Ut/vVbqRhRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABWZqH+v/AArTrM1D/Xn6U0B+"
    "lXwBut99+zcgCqP+EodihGeTHCM/hgfnX601+S3wAtCuqfs4MVbcPFEowxz0ihJP61+tNT1YBRRRTAKKKKACiiigAooooAKK"
    "KKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKK"
    "KKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooA8n/axz/wAMzfFDAyf+EdvsD/ti1fmB/wAF"
    "S7NItN+GzQxCOGHSooQB/APNusD6fL+lfqB+1e+z9mj4nN0/4p695H/XJq/Mb/gqoEez+HsgZv8AjwVUGOGHnXXPt/8Arql1"
    "Ez4E07/Ut/vVbqpp3+pb/eq3UjCiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACszUP9"
    "efpWnWZqH+vP0poD9LfgLMP+Ek/Zui3AsfEEkmO/MUIz+P8ASv1mr8nP2f4AviL9nFi25j4inGe2BDCR/Wv1jqerAKKKKYBR"
    "RRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABR"
    "RRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFAHkf7XDbf2Y/iec4/4p"
    "+75z/wBMzX5j/wDBU+dJLL4eKrBiunRg7egPm3XH61+m37Xgz+zD8Tx0B0C7GT/1zNfmJ/wU8s3tdF8BLM6ySpZQqGRQAR5l"
    "115znNNdRM+DdO/1Lf71W6qad/qW/wB6rdIYUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABR"
    "RRQAVmah/rz9K06zNQ/15+lNAfpf+z/IZPFn7N6DBVdcmJbOefJh4x7AfrX6yV+Uv7PkUZ8Ufs5YwD/bty2Pb7PD/wDW/Ov1"
    "aqerAKKKKYBRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQA"
    "UUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFAHkX7XA"
    "z+zN8SwcEHQ7kc/7lfmj/wAFVVH2PwLubc62oUcdR593/gK/S39rs7f2ZfiUcZ/4klx/6DX5o/8ABVWMR2fgQEjd9kB456z3"
    "VXHZie58Aad/qm/3qt1U07/VN/vVbqBhRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFAB"
    "WZqH+vP0rTrM1D/Xn6U0B+m37OwdvGX7Oe7cFGsXKgdsi3iJ/E8V+rtflX+ztIv/AAl37OiHG86vdSDnn/j3iH6/0r9VKnqw"
    "CiiimAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFA"
    "BRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQB4/+1+pf9mL"
    "4lgcH+xLj8tvNfmp/wAFR8XXhn4d3m7ez2MQ3L0P7y5z+vav0r/a/Uv+zH8SgOv9iz/yr86P+CoGmif4a+BrwEh4La0DDGM7"
    "3u8n8wPzqlsxdT869O/1Tf71W6o6c+C6/jV6pGFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQ"
    "AUUUUAFZmoH9+fpWnWRdPvmkI55xTQH6ifs52zDxx+zochs6pdtj2FrHg/0r9U6/MX4D2Edj8Rf2Z4PmLyTajIzH+8lsoIHt"
    "X6dVPUAooopgFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFF"
    "ABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAcX8a"
    "fCMvj74ReM/DkA3XOqaPdWkI/wCmjxME/wDHsV+a37ZlgPHH7L/gy7hjP2iTw0lyAQc7raWOSUD/AGh55GOvJ9K/V2viD9on"
    "4dXPh3QPE+nWlsJovD98/irSoSm4TabPuF/bqO/lMzybR0VIR3FUhdT8R4JfJlVu3etYEEAjkGtj4t/D+f4b+N73S2XNk+Li"
    "xmU5SW3flCp78cZ9q5i0u/Lwj/d7H0pMZoUUgORS0gCiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigA"
    "oopksqwruY4FADLqYQxE5+Y8CpvBGgv4p8YaNpKKWN3dRxtjsu75j+C5P4VkTzmd8ngdh6V9Dfsr/DTU7m8HiiOAm5uZP7L0"
    "aNhzLPKRGXx/dXdgkdt/oaYH3b8FI38RftI/Aq0tgPJ0uy1e/IxysRMsSuf97yV/Ov0kr4+/Ym+GLf8ACW+KvHkzGfTbWGPw"
    "voMzjiSC3wLiVf8AZeZTg/79fYNSAUUUUwCiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKK"
    "KACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKK"
    "KACiiigAooooAKKKKACub8beEU8UWttJEyQanZOZbWd1ypyMPE47xuvysPoeqiukooA/I/8AbD/ZTXSSti+nzaf4dnmb+xtR"
    "lbd/Y1w2SbKU94WIxG2SGUAA7kxX53eL/Bur+Bdam0vWbN7S6jJwTyki5xuRujL7j6HB4r+m7xF4Z0rxbo13pOs2Fvqem3cR"
    "hntrmMOkiHqCD+H5CviX49f8E7v7d0yeHwq1v4i0TJePQdblK3VqccC2uzyR0AWQggD/AFmOKq4H4rRXMkP3Tkeh6VaTUVP3"
    "lIPtzX0f8WP2IfEHw/tZLx1vNDKOUey162aLb7pMAUkX3XI968Jm+GmvpO8UNtFeMilj9muI2OB1OM5x+FLQDLF7Cf48fUGl"
    "+2Q/3x+RqY+CNfBx/ZF3+EZo/wCEK17/AKBN3/37NA7EP2yH++PyNH2yH++PyNTf8ITr3/QJuv8Av2aP+EI1/wD6BN1/3xRo"
    "FiD7ZD/f/Q0fbIf7/wChqx/wg+v/APQJuf8Avij/AIQfX/8AoE3P/fFGgWK/2yH+/wDoaPtsP9/9DVn/AIQbX/8AoFXH/fNH"
    "/CC6/wD9Aq4/75FGgWK322H+/wDoaPtsP9/9DVr/AIQTxB/0Crj8h/jR/wAIH4g/6BU/5D/GjQRV+2w/3/0NH22H+/8Aoat/"
    "8IF4g/6BU/6f40f8IF4g/wCgVP8Ap/jRoBU+2w/3/wBDR9th/v8A6Grf/CA+If8AoFTfmv8AjS/8IB4h/wCgXN+a/wCNGgFL"
    "7bD/AHv0NH26H+8fyNXf+Ff+If8AoFzfmv8AjS/8K/8AEP8A0C5f++l/xo0Ao/bof7x/I0fbof7x/I1e/wCFfeIf+gXL/wB9"
    "L/jR/wAK+8Rf9AuX/vpf8aNB2KP26H+8fypDfxDoSfoKv/8ACvvEX/QLl/76X/GnD4deIyf+QXJ+MiD+tGgWMiTUSeEXHuaq"
    "u7SNliSfevSfDXwC8Qa+0Jnu9M0mKQ4zdXG51+qRhiPbOM19N/Br9hmS7vrKeDwzq3xAvH5Ba3NtpsbYzlnYhWGf7zYP92jQ"
    "R80fCX4Jaj47dNZ1KGSw8I2z7rm9dhGZlHVIt3UnGN3QZ9eK/VL9nD9mC48TaXFq4tx4d042YsbCDDB7O2cfvJAM/wCuZMKu"
    "fuA7jk4B9S+DX7F1tpZ03VfiA1lqN1ZbXtdBsFxY2zL90sSB5jDsAAoPY8Y+pIYI7eNY4kWONRgKgwB+FAGf4Z8Nab4O8P6f"
    "omj2iWOl2EK29vbxjhEUYA9z6k8k5JrUoopAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAU"
    "UUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAU"
    "UUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAMliSeNkkRXRhgqwyD+FYcvgDwxPJ5knhzSZHznc9jET+e2t+igDlpfhX4KnO"
    "ZfCGgyH1fTID/wCy1D/wp7wEf+ZI8Of+Cm3/APiK6+igDj/+FOeAf+hH8Of+Cm3/APiKP+FN+Af+hH8N/wDgpt//AIiuwooA"
    "47/hTfgH/oR/Df8A4Kbf/wCIo/4U34B/6Efw3/4Kbf8A+IrsaKAOO/4U14A/6Efw3/4KLf8A+Io/4U34AH/Mj+G//BTb/wDx"
    "FdjRQBx//Cm/AH/Qj+G//BRb/wDxFJ/wpvwB/wBCP4b/APBRb/8AxFdjRQBx3/Cm/AP/AEI/hv8A8FFv/wDEUf8ACmvAH/Qj"
    "+G//AAUW/wD8RXY0UAccPg14AHTwP4b/APBRb/8AxFH/AAprwB/0I/hv/wAFFv8A/EV2NFAHHf8ACmvAH/Qj+G//AAUW/wD8"
    "RS/8Kb8A/wDQj+G//BRb/wDxFdhRQBx3/CmvAH/Qj+G//BRb/wDxFH/Cm/AI/wCZH8N/+Ci3/wDiK7GigDjv+FN+AP8AoR/D"
    "f/got/8A4ij/AIU34B7eCPDfp/yCLf8A+IrsaKAOb0z4beEtEuVudO8L6LYXCcLLa6fDG4+hVQa6MDFLRQAUUUUAFFFFABRR"
    "RQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRR"
    "RQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRR"
    "RQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRR"
    "RQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRR"
    "RQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRR"
    "RQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRR"
    "RQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRR"
    "RQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRR"
    "RQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRR"
    "RQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRR"
    "RQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRR"
    "RQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRR"
    "RQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRR"
    "RQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRR"
    "RQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRR"
    "RQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRR"
    "RQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRR"
    "RQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRR"
    "RQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRR"
    "RQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRR"
    "RQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRR"
    "RQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRR"
    "RQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRR"
    "RQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRR"
    "RQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRR"
    "RQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRR"
    "RQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRR"
    "RQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRR"
    "RQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQB//9k="
)


# --------------------------------------------------------------------------
# Subprocess helpers
# --------------------------------------------------------------------------

def _no_window_kwargs():
    """Keep console windows from flashing up on Windows."""
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return {"startupinfo": si, "creationflags": 0x08000000}  # CREATE_NO_WINDOW
    return {}


def find_ffmpeg():
    """Locate ffmpeg: bundled in the frozen app, beside the script, then PATH."""
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"

    roots = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(meipass)
    roots.append(os.path.dirname(os.path.abspath(sys.argv[0])))
    if getattr(sys, "frozen", False):
        # Inside a macOS .app bundle: Contents/MacOS/<exe> -> Contents/Resources
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        roots.append(exe_dir)
        roots.append(os.path.join(os.path.dirname(exe_dir), "Resources"))

    for root in roots:
        cand = os.path.join(root, exe)
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand

    found = shutil.which("ffmpeg")
    if found:
        return found

    for cand in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"):
        if os.path.isfile(cand):
            return cand
    return None


FFMPEG = find_ffmpeg()


def run_capture(args, timeout=30):
    """Run ffmpeg and return (returncode, stdout_bytes, stderr_text)."""
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        **_no_window_kwargs(),
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
    return proc.returncode, out, err.decode("utf-8", "replace")


# --------------------------------------------------------------------------
# Media probing (parses `ffmpeg -i`, so no separate ffprobe binary is needed)
# --------------------------------------------------------------------------

class MediaInfo(object):
    def __init__(self, path):
        self.path = path
        self.ok = False
        self.error = ""
        self.is_image = os.path.splitext(path)[1].lower() in IMAGE_EXTS
        self.width = 0
        self.height = 0
        self.duration = 0.0
        self.fps = 0.0
        self.codec = ""

    @property
    def summary(self):
        if not self.ok:
            return self.error or "unreadable"
        base = "%s  |  %d x %d" % (os.path.basename(self.path), self.width, self.height)
        if self.is_image:
            return base + "  |  still image"
        return base + "  |  %.3g fps  |  %s" % (self.fps, format_time(self.duration))


_RE_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_RE_VIDEO = re.compile(r"Stream #\d+:\d+.*?:\s*Video:\s*([A-Za-z0-9_]+)")
_RE_SIZE = re.compile(r",\s*(\d{2,5})x(\d{2,5})\b")
_RE_FPS = re.compile(r"(\d+(?:\.\d+)?)\s+fps")
_RE_TBR = re.compile(r"(\d+(?:\.\d+)?)\s+tbr")


def probe(path):
    info = MediaInfo(path)
    if not FFMPEG:
        info.error = "ffmpeg not found"
        return info
    if not os.path.isfile(path):
        info.error = "file not found"
        return info

    _, _, err = run_capture([FFMPEG, "-hide_banner", "-i", path])

    video_lines = [ln for ln in err.splitlines() if _RE_VIDEO.search(ln)]
    if not video_lines:
        info.error = "no video stream found in this file"
        return info
    line = video_lines[0]

    m = _RE_VIDEO.search(line)
    info.codec = m.group(1) if m else ""

    m = _RE_SIZE.search(line)
    if not m:
        info.error = "could not determine resolution"
        return info
    info.width, info.height = int(m.group(1)), int(m.group(2))

    m = _RE_FPS.search(line) or _RE_TBR.search(line)
    if m:
        try:
            info.fps = float(m.group(1))
        except ValueError:
            info.fps = 0.0

    m = _RE_DURATION.search(err)
    if m:
        info.duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))

    # A "video" of one frame with no duration is really a still.
    if info.duration <= 0.04:
        info.is_image = True
        info.duration = 0.0

    info.ok = True
    return info


def format_time(seconds):
    seconds = max(0.0, float(seconds))
    m, s = divmod(seconds, 60)
    h, m = divmod(int(m), 60)
    if h:
        return "%d:%02d:%06.3f" % (h, m, s)
    return "%02d:%06.3f" % (m, s)


# --------------------------------------------------------------------------
# Filter chain
# --------------------------------------------------------------------------

class Params(object):
    """Everything the user can tweak."""

    def __init__(self):
        self.fps = 30
        self.quality = 2
        self.fit = "crop"          # crop | stretch | fit
        self.crop_x = 0.0          # -1 .. +1  (0 = centred)
        self.crop_y = 0.0
        self.rotation = 180        # matches the original hflip+vflip command
        self.mirror_h = False
        self.mirror_v = False
        self.pad_color = "#000000"
        self.duration = 5.0        # still-image clip length, seconds

    def copy(self):
        p = Params()
        p.__dict__.update(self.__dict__)
        return p


def _pad_color_ffmpeg(hex_color):
    return "0x" + hex_color.lstrip("#").upper()


def _even(value):
    """Round to the nearest multiple of 2, the way ffmpeg's `-2` sizing does."""
    return max(2, int(round(value / 2.0)) * 2)


def scaled_size(src_w, src_h, mode):
    """Intermediate size before cropping / padding, computed exactly.

    Deriving this in Python rather than leaving it to
    force_original_aspect_ratio keeps the numbers identical to a hand-written
    `scale=-2:320` and makes the emitted command readable.
    """
    if src_w <= 0 or src_h <= 0:
        return OUT_W, OUT_H
    if mode == "stretch":
        return OUT_W, OUT_H

    source_is_wider = src_w * OUT_H >= src_h * OUT_W
    cover = (mode != "fit")

    if source_is_wider == cover:
        # Height is the binding dimension.
        h = OUT_H
        w = _even(src_w * OUT_H / float(src_h))
    else:
        # Width is the binding dimension.
        w = OUT_W
        h = _even(src_h * OUT_W / float(src_w))

    if cover:  # rounding must never leave us short of full coverage
        w = max(w, OUT_W)
        h = max(h, OUT_H)
    return w, h


def build_vf(p, info, include_fps=True):
    """Assemble the -vf chain.

    Orientation filters go *last* whenever they preserve the frame's aspect
    (rotation 0 or 180) — that keeps the chain byte-for-byte equivalent to the
    hand-written `scale,crop,hflip,vflip` reference command, because lanczos
    resampling before a flip and after a flip differ in the last float bit.
    A 90/270 rotation must come first, since it swaps width and height.

    When the orientation filters run last, the crop offsets are pre-compensated
    so the sliders still mean "move the framing in the direction you see".
    """
    parts = []

    if include_fps and info is not None and not info.is_image:
        parts.append("fps=%d" % p.fps)

    ops = []
    if p.rotation == 90:
        ops.append("transpose=1")
    elif p.rotation == 180:
        ops.append("transpose=1")
        ops.append("transpose=1")
    elif p.rotation == 270:
        ops.append("transpose=2")
    if p.mirror_h:
        ops.append("hflip")
    if p.mirror_v:
        ops.append("vflip")

    orientation_last = p.rotation in (0, 180)

    src_w = info.width if info else 0
    src_h = info.height if info else 0

    crop_x, crop_y = p.crop_x, p.crop_y
    if orientation_last:
        if p.rotation == 180:
            crop_x, crop_y = -crop_x, -crop_y
        if p.mirror_h:
            crop_x = -crop_x
        if p.mirror_v:
            crop_y = -crop_y
    else:
        parts.extend(ops)
        src_w, src_h = src_h, src_w

    sw, sh = scaled_size(src_w, src_h, p.fit)
    parts.append("scale=%d:%d:flags=lanczos" % (sw, sh))

    if p.fit == "fit":
        if (sw, sh) != (OUT_W, OUT_H):
            parts.append("pad=%d:%d:%d:%d:%s"
                         % (OUT_W, OUT_H, (OUT_W - sw) // 2, (OUT_H - sh) // 2,
                            _pad_color_ffmpeg(p.pad_color)))
    elif p.fit == "crop":
        if (sw, sh) != (OUT_W, OUT_H):
            # Offset -1 = hard left/top, 0 = centred, +1 = hard right/bottom.
            x = int(round((sw - OUT_W) / 2.0 * (1.0 + crop_x)))
            y = int(round((sh - OUT_H) / 2.0 * (1.0 + crop_y)))
            x = max(0, min(sw - OUT_W, x))
            y = max(0, min(sh - OUT_H, y))
            parts.append("crop=%d:%d:%d:%d" % (OUT_W, OUT_H, x, y))

    if orientation_last:
        parts.extend(ops)

    return ",".join(parts)


def build_generate_cmd(info, p, out_path):
    vf = build_vf(p, info, include_fps=not info.is_image)
    cmd = [FFMPEG or "ffmpeg", "-y"]
    if info.is_image:
        cmd += ["-loop", "1", "-framerate", str(p.fps), "-i", info.path,
                "-t", "%.3f" % p.duration]
    else:
        cmd += ["-i", info.path]
    cmd += ["-an", "-pix_fmt", "yuvj420p", "-c:v", "mjpeg", "-q:v", str(p.quality)]
    if vf:
        cmd += ["-vf", vf]
    cmd += [out_path]
    return cmd


def quote_cmd(cmd):
    out = []
    for a in cmd:
        if not a or re.search(r"[\s\"'(),;|&<>*?$]", a):
            out.append('"%s"' % a.replace('"', '\\"'))
        else:
            out.append(a)
    return " ".join(out)


# --------------------------------------------------------------------------
# Preview renderer (background thread, always renders the newest request only)
# --------------------------------------------------------------------------

class RenderJob(object):
    def __init__(self, seq, info, params, timestamp):
        self.seq = seq
        self.info = info
        self.params = params
        self.timestamp = timestamp


class RenderResult(object):
    def __init__(self, seq, original=None, processed=None, error=None):
        self.seq = seq
        self.original = original
        self.processed = processed
        self.error = error


class Renderer(threading.Thread):
    """Serialises preview renders and drops stale ones."""

    def __init__(self, out_queue):
        threading.Thread.__init__(self, daemon=True)
        self.out_queue = out_queue
        self._cv = threading.Condition()
        self._job = None
        self._stop = False
        self._orig_cache_key = None
        self._orig_cache_img = None

    def submit(self, job):
        with self._cv:
            self._job = job
            self._cv.notify()

    def shutdown(self):
        with self._cv:
            self._stop = True
            self._cv.notify()

    def run(self):
        while True:
            with self._cv:
                while self._job is None and not self._stop:
                    self._cv.wait()
                if self._stop:
                    return
                job, self._job = self._job, None

            try:
                result = self._render(job)
            except Exception as exc:  # keep the worker alive whatever happens
                result = RenderResult(job.seq, error=str(exc))

            with self._cv:
                superseded = self._job is not None
            if not superseded:
                self.out_queue.put(result)

    # -- internals ---------------------------------------------------------

    def _decode(self, data):
        return Image.open(io.BytesIO(data)).convert("RGB")

    def _extract_original(self, job):
        key = (job.info.path, round(job.timestamp, 3))
        if key == self._orig_cache_key and self._orig_cache_img is not None:
            return self._orig_cache_img

        cmd = [FFMPEG, "-hide_banner", "-loglevel", "error"]
        if not job.info.is_image:
            cmd += ["-ss", "%.3f" % job.timestamp]
        cmd += ["-i", job.info.path, "-frames:v", "1",
                "-f", "image2pipe", "-vcodec", "png", "-"]
        rc, out, err = run_capture(cmd)
        if not out:
            raise RuntimeError(err.strip() or "could not read a frame at this position")
        img = self._decode(out)
        self._orig_cache_key = key
        self._orig_cache_img = img
        return img

    def _extract_processed(self, job):
        p = job.params
        vf = build_vf(p, job.info, include_fps=False)
        cmd = [FFMPEG, "-hide_banner", "-loglevel", "error"]
        if not job.info.is_image:
            cmd += ["-ss", "%.3f" % job.timestamp]
        cmd += ["-i", job.info.path]
        if vf:
            cmd += ["-vf", vf]
        # Same codec and quality as the real export, so the preview shows the
        # actual MJPEG artefacts rather than a clean approximation.
        cmd += ["-frames:v", "1", "-pix_fmt", "yuvj420p",
                "-c:v", "mjpeg", "-q:v", str(p.quality),
                "-f", "image2pipe", "-"]
        rc, out, err = run_capture(cmd)
        if not out:
            raise RuntimeError(err.strip() or "ffmpeg produced no frame")
        return self._decode(out)

    def _render(self, job):
        if not FFMPEG:
            return RenderResult(job.seq, error="ffmpeg not found")
        original = self._extract_original(job)
        processed = self._extract_processed(job)
        return RenderResult(job.seq, original=original, processed=processed)


# --------------------------------------------------------------------------
# Encoder (background thread with progress reporting)
# --------------------------------------------------------------------------

class Encoder(threading.Thread):
    def __init__(self, cmd, total_seconds, out_queue):
        threading.Thread.__init__(self, daemon=True)
        self.cmd = cmd
        self.total = max(0.001, float(total_seconds))
        self.out_queue = out_queue
        self.proc = None
        self._cancelled = False

    def cancel(self):
        self._cancelled = True
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.kill()
            except Exception:
                pass

    def run(self):
        cmd = list(self.cmd)
        cmd.insert(1, "-nostats")
        cmd.insert(1, "pipe:1")
        cmd.insert(1, "-progress")
        try:
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                **_no_window_kwargs()
            )
        except Exception as exc:
            self.out_queue.put(("encode_done", False, str(exc)))
            return

        for raw in iter(self.proc.stdout.readline, b""):
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith("out_time_ms="):
                try:
                    secs = int(line.split("=", 1)[1]) / 1_000_000.0
                    self.out_queue.put(("encode_progress",
                                        min(100.0, 100.0 * secs / self.total)))
                except ValueError:
                    pass

        err = self.proc.stderr.read().decode("utf-8", "replace")
        rc = self.proc.wait()

        if self._cancelled:
            self.out_queue.put(("encode_done", False, "cancelled"))
        elif rc == 0:
            self.out_queue.put(("encode_done", True, ""))
        else:
            tail = "\n".join([l for l in err.strip().splitlines() if l][-6:])
            self.out_queue.put(("encode_done", False, tail or ("ffmpeg exited with %d" % rc)))


# --------------------------------------------------------------------------
# GUI
# --------------------------------------------------------------------------

class App(tk.Tk):

    def __init__(self):
        tk.Tk.__init__(self)
        self.title("%s   v%s" % (APP_TITLE, APP_VERSION))
        self.geometry("1220x880")
        self.minsize(1140, 840)

        self.info = None
        self.params = Params()
        self.timestamp = 0.0
        self._seq = 0
        self._debounce_id = None
        self._suspend_traces = False
        self._photo_orig = None
        self._photo_proc = None
        self._orig_frame_pil = None
        self._device_pil = None
        self._last_canvas_size = {}
        self.encoder = None

        self.results = queue.Queue()
        self.renderer = Renderer(self.results)
        self.renderer.start()

        self.mockup = Image.open(io.BytesIO(base64.b64decode(MOCKUP_B64))).convert("RGB")
        _sw, _sh = MOCKUP_SCREEN[2], MOCKUP_SCREEN[3]
        self._screen_mask = self._rounded_mask(
            _sw, _sh, int(round(CORNER_RADIUS_RATIO * _sw)))
        self._blank_device = self._compose_device(None)

        self._build_vars()
        self._build_ui()
        self._update_enabled_state()
        self._show_blank()
        self._poll_results()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        if not FFMPEG:
            self.after(300, self._warn_no_ffmpeg)

    # -- variables ---------------------------------------------------------

    def _build_vars(self):
        p = self.params
        self.var_fps = tk.IntVar(value=p.fps)
        self.var_quality = tk.IntVar(value=p.quality)
        self.var_fit = tk.StringVar(value=p.fit)
        self.var_crop_x = tk.DoubleVar(value=p.crop_x)
        self.var_crop_y = tk.DoubleVar(value=p.crop_y)
        self.var_rotation = tk.IntVar(value=p.rotation)
        self.var_mirror_h = tk.BooleanVar(value=p.mirror_h)
        self.var_mirror_v = tk.BooleanVar(value=p.mirror_v)
        self.var_duration = tk.DoubleVar(value=p.duration)
        self.var_time = tk.DoubleVar(value=0.0)

        self.var_source = tk.StringVar(value="No file selected")
        self.var_output = tk.StringVar(value="")
        self.var_status = tk.StringVar(value="Ready")
        self.var_command = tk.StringVar(value="")
        self.var_timelabel = tk.StringVar(value="00:00.000")
        self.var_qualitylabel = tk.StringVar(value="2")

        for v in (self.var_fps, self.var_fit, self.var_rotation,
                  self.var_mirror_h, self.var_mirror_v, self.var_duration):
            v.trace_add("write", self._on_param_change)
        self.var_quality.trace_add("write", self._on_quality_change)
        self.var_crop_x.trace_add("write", self._on_param_change)
        self.var_crop_y.trace_add("write", self._on_param_change)

    # -- layout ------------------------------------------------------------

    def _build_ui(self):
        style = ttk.Style(self)
        for theme in ("aqua", "vista", "clam"):
            if theme in style.theme_names():
                style.theme_use(theme)
                break
        style.configure("Hint.TLabel", foreground="#666666")
        style.configure("Head.TLabel", font=("TkDefaultFont", 10, "bold"))

        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        # --- source row ---
        top = ttk.Frame(root)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        top.columnconfigure(1, weight=1)
        ttk.Button(top, text="Choose file…", command=self.on_choose_file)\
            .grid(row=0, column=0, padx=(0, 10))
        ttk.Label(top, textvariable=self.var_source).grid(row=0, column=1, sticky="w")

        # --- middle: previews + controls ---
        mid = ttk.Frame(root)
        mid.grid(row=1, column=0, sticky="nsew")
        mid.columnconfigure(0, weight=1)
        mid.columnconfigure(1, weight=0)
        mid.columnconfigure(2, weight=0)
        mid.rowconfigure(0, weight=1)

        self._build_preview_pane(mid)
        self._build_device_pane(mid)
        self._build_controls(mid)

        # --- bottom ---
        self._build_bottom(root)

    def _build_preview_pane(self, parent):
        box = ttk.LabelFrame(parent, text="Original frame", padding=8)
        box.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.canvas_orig = tk.Canvas(box, bg="#1e1e1e", highlightthickness=0,
                                     width=380, height=470)
        self.canvas_orig.pack(fill="both", expand=True)
        self.canvas_orig.bind("<Configure>",
                              lambda e: self._on_canvas_resize(e, "orig"))

    def _build_device_pane(self, parent):
        box = ttk.LabelFrame(parent, text="Device preview  (172 × 320)", padding=8)
        box.grid(row=0, column=1, sticky="ns", padx=(0, 10))
        cw = MOCKUP_CROP[2] - MOCKUP_CROP[0]
        ch = MOCKUP_CROP[3] - MOCKUP_CROP[1]
        self.canvas_dev = tk.Canvas(box, bg="#ffffff", highlightthickness=0,
                                    width=cw, height=ch)
        self.canvas_dev.pack(fill="both", expand=True)
        self.canvas_dev.bind("<Configure>",
                             lambda e: self._on_canvas_resize(e, "dev"))

    def _build_controls(self, parent):
        c = ttk.Frame(parent)
        c.grid(row=0, column=2, sticky="ns")
        r = 0

        ttk.Label(c, text="Fit mode", style="Head.TLabel")\
            .grid(row=r, column=0, columnspan=2, sticky="w"); r += 1
        for value, label in (("crop", "Crop  — fill, trim overflow"),
                             ("stretch", "Stretch  — distort to fit"),
                             ("fit", "Fit  — letterbox with padding")):
            ttk.Radiobutton(c, text=label, value=value, variable=self.var_fit)\
                .grid(row=r, column=0, columnspan=2, sticky="w", padx=(10, 0)); r += 1

        self.crop_widgets = []
        for label, var in (("Crop X", self.var_crop_x), ("Crop Y", self.var_crop_y)):
            lbl = ttk.Label(c, text=label)
            lbl.grid(row=r, column=0, sticky="w", padx=(10, 6), pady=(4, 0))
            sc = ttk.Scale(c, from_=-1.0, to=1.0, variable=var,
                           orient="horizontal", length=170)
            sc.grid(row=r, column=1, sticky="ew", pady=(4, 0))
            self.crop_widgets += [lbl, sc]
            r += 1
        btn = ttk.Button(c, text="Centre crop", width=12, command=self.on_centre_crop)
        btn.grid(row=r, column=1, sticky="w", pady=(2, 0))
        self.crop_widgets.append(btn)
        r += 1

        ttk.Separator(c).grid(row=r, column=0, columnspan=2, sticky="ew", pady=7); r += 1

        ttk.Label(c, text="Orientation", style="Head.TLabel")\
            .grid(row=r, column=0, columnspan=2, sticky="w"); r += 1
        rot = ttk.Frame(c)
        rot.grid(row=r, column=0, columnspan=2, sticky="w", padx=(10, 0), pady=(2, 0))
        ttk.Label(rot, text="Rotation").pack(side="left", padx=(0, 8))
        self.combo_rot = ttk.Combobox(rot, width=7, state="readonly",
                                      values=["%d°" % d for d in ROTATION_CHOICES])
        self.combo_rot.set("%d°" % self.params.rotation)
        self.combo_rot.bind("<<ComboboxSelected>>", self.on_rotation_pick)
        self.combo_rot.pack(side="left")
        ttk.Button(rot, text="↺", width=3, command=lambda: self.on_rotate_step(-90))\
            .pack(side="left", padx=(6, 0))
        ttk.Button(rot, text="↻", width=3, command=lambda: self.on_rotate_step(90))\
            .pack(side="left", padx=(3, 0))
        r += 1
        mir = ttk.Frame(c)
        mir.grid(row=r, column=0, columnspan=2, sticky="w", padx=(10, 0), pady=(4, 0))
        ttk.Checkbutton(mir, text="Mirror H", variable=self.var_mirror_h).pack(side="left")
        ttk.Checkbutton(mir, text="Mirror V", variable=self.var_mirror_v)\
            .pack(side="left", padx=(12, 0))
        r += 1

        ttk.Separator(c).grid(row=r, column=0, columnspan=2, sticky="ew", pady=7); r += 1

        ttk.Label(c, text="Output", style="Head.TLabel")\
            .grid(row=r, column=0, columnspan=2, sticky="w"); r += 1
        ttk.Label(c, text="Resolution 172 × 320 (fixed)   ·   MJPEG / AVI",
                  style="Hint.TLabel")\
            .grid(row=r, column=0, columnspan=2, sticky="w", padx=(10, 0)); r += 1

        fpsf = ttk.Frame(c)
        fpsf.grid(row=r, column=0, columnspan=2, sticky="w", padx=(10, 0), pady=(6, 0))
        ttk.Label(fpsf, text="FPS").pack(side="left", padx=(0, 8))
        for f in FPS_CHOICES:
            ttk.Radiobutton(fpsf, text=str(f), value=f, variable=self.var_fps)\
                .pack(side="left", padx=(0, 8))
        r += 1

        ttk.Label(c, text="Quality (q:v)").grid(row=r, column=0, sticky="w",
                                                padx=(10, 6), pady=(6, 0))
        qf = ttk.Frame(c)
        qf.grid(row=r, column=1, sticky="ew", pady=(6, 0))
        ttk.Scale(qf, from_=QUALITY_MIN, to=QUALITY_MAX, variable=self.var_quality,
                  orient="horizontal", length=140,
                  command=lambda v: self.var_quality.set(int(float(v))))\
            .pack(side="left")
        ttk.Label(qf, textvariable=self.var_qualitylabel, width=3).pack(side="left", padx=(6, 0))
        r += 1
        ttk.Label(c, text="lower = better quality, larger file", style="Hint.TLabel")\
            .grid(row=r, column=0, columnspan=2, sticky="w", padx=(10, 0)); r += 1

        self.pad_row = ttk.Frame(c)
        self.pad_row.grid(row=r, column=0, columnspan=2, sticky="w",
                          padx=(10, 0), pady=(6, 0))
        ttk.Label(self.pad_row, text="Pad colour").pack(side="left", padx=(0, 8))
        self.btn_pad = tk.Button(self.pad_row, width=4, relief="ridge",
                                 bg=self.params.pad_color, command=self.on_pick_pad_color)
        self.btn_pad.pack(side="left")
        r += 1

        self.dur_row = ttk.Frame(c)
        self.dur_row.grid(row=r, column=0, columnspan=2, sticky="w",
                          padx=(10, 0), pady=(6, 0))
        ttk.Label(self.dur_row, text="Still duration").pack(side="left", padx=(0, 8))
        ttk.Spinbox(self.dur_row, from_=0.1, to=3600, increment=0.5, width=7,
                    textvariable=self.var_duration).pack(side="left")
        ttk.Label(self.dur_row, text="s").pack(side="left", padx=(4, 0))
        r += 1

        ttk.Separator(c).grid(row=r, column=0, columnspan=2, sticky="ew", pady=7); r += 1
        ttk.Button(c, text="Reset to defaults", command=self.on_reset)\
            .grid(row=r, column=0, columnspan=2, sticky="w")

        c.columnconfigure(1, weight=1)

    def _build_bottom(self, root):
        bottom = ttk.Frame(root)
        bottom.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        bottom.columnconfigure(0, weight=1)

        # timeline
        self.timeline = ttk.Frame(bottom)
        self.timeline.grid(row=0, column=0, sticky="ew")
        self.timeline.columnconfigure(2, weight=1)
        ttk.Button(self.timeline, text="◀  −0.5 s", width=10,
                   command=lambda: self.on_step(-STEP_SECONDS))\
            .grid(row=0, column=0, padx=(0, 6))
        ttk.Button(self.timeline, text="+0.5 s  ▶", width=10,
                   command=lambda: self.on_step(STEP_SECONDS))\
            .grid(row=0, column=1, padx=(0, 12))
        self.scale_time = ttk.Scale(self.timeline, from_=0.0, to=1.0,
                                    variable=self.var_time, orient="horizontal",
                                    command=self.on_time_scrub)
        self.scale_time.grid(row=0, column=2, sticky="ew")
        ttk.Label(self.timeline, textvariable=self.var_timelabel, width=13,
                  anchor="e").grid(row=0, column=3, padx=(10, 0))

        # command line
        cmdf = ttk.LabelFrame(bottom, text="ffmpeg command", padding=6)
        cmdf.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        cmdf.columnconfigure(0, weight=1)
        self.txt_cmd = tk.Text(cmdf, height=3, wrap="word", relief="flat",
                               bg="#f5f5f5", font=("TkFixedFont",))
        self.txt_cmd.grid(row=0, column=0, sticky="ew")
        self.txt_cmd.configure(state="disabled")
        ttk.Button(cmdf, text="Copy", width=8, command=self.on_copy_cmd)\
            .grid(row=0, column=1, sticky="n", padx=(8, 0))

        # output + generate
        out = ttk.Frame(bottom)
        out.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        out.columnconfigure(1, weight=1)
        ttk.Label(out, text="Output").grid(row=0, column=0, padx=(0, 8))
        ttk.Entry(out, textvariable=self.var_output).grid(row=0, column=1, sticky="ew")
        ttk.Button(out, text="Save as…", command=self.on_save_as)\
            .grid(row=0, column=2, padx=(8, 0))
        self.btn_generate = ttk.Button(out, text="Generate", width=12,
                                       command=self.on_generate)
        self.btn_generate.grid(row=0, column=3, padx=(12, 0))

        prog = ttk.Frame(bottom)
        prog.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        prog.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(prog, mode="determinate", maximum=100.0)
        self.progress.grid(row=0, column=0, sticky="ew")
        ttk.Label(prog, textvariable=self.var_status, width=42, anchor="w")\
            .grid(row=0, column=1, padx=(10, 0))

    # -- image composition -------------------------------------------------

    @staticmethod
    def _rounded_mask(w, h, radius):
        """Anti-aliased rounded-rectangle mask, built by supersampling."""
        ss = 4
        big = Image.new("L", (w * ss, h * ss), 0)
        ImageDraw.Draw(big).rounded_rectangle(
            [0, 0, w * ss - 1, h * ss - 1], radius=max(0, radius) * ss, fill=255)
        return big.resize((w, h), Image.LANCZOS)

    def _compose_device(self, frame):
        """Paste a 172x320 frame into the device photo and crop to the visible area.

        The frame is masked with the panel's rounded corners so the preview
        matches the hardware.  The encoded file itself stays a full rectangle.
        """
        canvas = self.mockup.copy()
        x, y, w, h = MOCKUP_SCREEN
        if frame is None:
            screen = Image.new("RGB", (w, h), (8, 8, 8))
        else:
            screen = frame.resize((w, h), Image.LANCZOS)
        canvas.paste(screen, (x, y), self._screen_mask)
        return canvas.crop(MOCKUP_CROP)

    def _fit_into(self, img, box_w, box_h):
        iw, ih = img.size
        if iw <= 0 or ih <= 0:
            return img
        scale = min(box_w / float(iw), box_h / float(ih))
        scale = max(scale, 0.01)
        return img.resize((max(1, int(iw * scale)), max(1, int(ih * scale))),
                          Image.LANCZOS)

    @staticmethod
    def _canvas_size(canvas):
        """Usable size of a canvas, valid even before it has been mapped.

        winfo_width() reports 1 until the geometry manager has run, which would
        otherwise push the first drawing into the top-left corner.
        """
        w, h = canvas.winfo_width(), canvas.winfo_height()
        if w <= 1:
            w = canvas.winfo_reqwidth()
        if h <= 1:
            h = canvas.winfo_reqheight()
        return max(1, w), max(1, h)

    def _draw_canvas(self, canvas, pil_img, attr):
        canvas.delete("all")
        photo = ImageTk.PhotoImage(pil_img)
        setattr(self, attr, photo)  # keep a reference alive
        cw, ch = self._canvas_size(canvas)
        canvas.create_image(cw // 2, ch // 2, image=photo, anchor="center")

    def _redraw_original(self):
        canvas = self.canvas_orig
        cw, ch = self._canvas_size(canvas)
        if self._orig_frame_pil is None:
            canvas.delete("all")
            canvas.create_text(cw // 2, ch // 2,
                               text="Choose a video or image to begin",
                               fill="#888888", font=("TkDefaultFont", 11),
                               anchor="center")
            return
        self._draw_canvas(canvas,
                          self._fit_into(self._orig_frame_pil,
                                         max(32, cw - 4), max(32, ch - 4)),
                          "_photo_orig")

    def _redraw_device(self):
        self._draw_canvas(self.canvas_dev,
                          self._device_pil or self._blank_device, "_photo_proc")

    def _on_canvas_resize(self, event, which):
        size = (event.width, event.height)
        if self._last_canvas_size.get(which) == size:
            return
        self._last_canvas_size[which] = size
        if which == "orig":
            self._redraw_original()
        else:
            self._redraw_device()

    def _show_blank(self):
        self._orig_frame_pil = None
        self._device_pil = None
        self._redraw_device()
        self._redraw_original()

    # -- parameter plumbing ------------------------------------------------

    def _collect_params(self):
        p = self.params
        try:
            p.fps = int(self.var_fps.get())
            p.quality = max(QUALITY_MIN, min(QUALITY_MAX, int(self.var_quality.get())))
            p.fit = self.var_fit.get()
            p.crop_x = max(-1.0, min(1.0, float(self.var_crop_x.get())))
            p.crop_y = max(-1.0, min(1.0, float(self.var_crop_y.get())))
            p.rotation = int(self.var_rotation.get())
            p.mirror_h = bool(self.var_mirror_h.get())
            p.mirror_v = bool(self.var_mirror_v.get())
            p.duration = max(0.1, float(self.var_duration.get()))
        except (ValueError, tk.TclError):
            pass
        return p

    def _on_quality_change(self, *_):
        try:
            self.var_qualitylabel.set(str(int(self.var_quality.get())))
        except tk.TclError:
            pass
        self._on_param_change()

    def _on_param_change(self, *_):
        if self._suspend_traces:
            return
        self._update_enabled_state()
        self.schedule_preview()

    def _update_enabled_state(self):
        crop_on = self.var_fit.get() == "crop"
        for w in self.crop_widgets:
            try:
                w.configure(state=("normal" if crop_on else "disabled"))
            except tk.TclError:
                pass
        pad_on = self.var_fit.get() == "fit"
        self.btn_pad.configure(state=("normal" if pad_on else "disabled"))

        is_image = bool(self.info and self.info.is_image)
        if is_image:
            self.timeline.grid_remove()
            self.dur_row.grid()
        else:
            self.timeline.grid()
            self.dur_row.grid_remove()

    def schedule_preview(self):
        self._update_command_text()
        if self._debounce_id is not None:
            try:
                self.after_cancel(self._debounce_id)
            except Exception:
                pass
        self._debounce_id = self.after(PREVIEW_DEBOUNCE_MS, self._fire_preview)

    def _fire_preview(self):
        self._debounce_id = None
        if not self.info or not self.info.ok:
            return
        self._seq += 1
        self.var_status.set("Rendering preview…")
        self.renderer.submit(RenderJob(self._seq, self.info,
                                       self._collect_params().copy(), self.timestamp))

    def _update_command_text(self):
        if not self.info or not self.info.ok:
            text = ""
        else:
            text = quote_cmd(build_generate_cmd(self.info, self._collect_params(),
                                                self.var_output.get() or "output.avi"))
        self.txt_cmd.configure(state="normal")
        self.txt_cmd.delete("1.0", "end")
        self.txt_cmd.insert("1.0", text)
        self.txt_cmd.configure(state="disabled")
        self.var_command.set(text)

    # -- result pump -------------------------------------------------------

    def _poll_results(self):
        try:
            while True:
                item = self.results.get_nowait()
                if isinstance(item, RenderResult):
                    self._apply_render(item)
                elif isinstance(item, tuple):
                    self._apply_encoder_event(item)
        except queue.Empty:
            pass
        self.after(40, self._poll_results)

    def _apply_render(self, res):
        if res.seq != self._seq:
            return
        if res.error:
            self.var_status.set("Preview failed: " + res.error.splitlines()[0][:60])
            return
        self._orig_frame_pil = res.original
        self._device_pil = self._compose_device(res.processed)
        self._redraw_original()
        self._redraw_device()
        self.var_status.set("Ready")

    def _apply_encoder_event(self, item):
        kind = item[0]
        if kind == "encode_progress":
            self.progress["value"] = item[1]
            self.var_status.set("Encoding… %d%%" % int(item[1]))
        elif kind == "encode_done":
            ok, msg = item[1], item[2]
            self.encoder = None
            self.btn_generate.configure(text="Generate", state="normal")
            if ok:
                self.progress["value"] = 100
                out = self.var_output.get()
                self.var_status.set("Done → " + os.path.basename(out))
                messagebox.showinfo(APP_TITLE, "Finished.\n\n%s" % out)
            else:
                self.progress["value"] = 0
                if msg == "cancelled":
                    self.var_status.set("Cancelled")
                else:
                    self.var_status.set("Failed")
                    messagebox.showerror(APP_TITLE, "Encoding failed:\n\n%s" % msg)

    # -- actions -----------------------------------------------------------

    def _warn_no_ffmpeg(self):
        messagebox.showwarning(
            APP_TITLE,
            "ffmpeg was not found.\n\n"
            "Install it and make sure it is on your PATH, or place the ffmpeg "
            "binary next to this application.\n\n"
            "macOS:    brew install ffmpeg\n"
            "Windows:  winget install Gyan.FFmpeg")

    def on_choose_file(self):
        types = [
            ("Video and image files",
             " ".join("*" + e for e in sorted(VIDEO_EXTS | IMAGE_EXTS))),
            ("Video files", " ".join("*" + e for e in sorted(VIDEO_EXTS))),
            ("Image files", " ".join("*" + e for e in sorted(IMAGE_EXTS))),
            ("All files", "*.*"),
        ]
        path = filedialog.askopenfilename(title="Choose a video or image",
                                          filetypes=types)
        if not path:
            return
        self.load_file(path)

    def load_file(self, path):
        self.var_status.set("Reading file…")
        self.update_idletasks()
        info = probe(path)
        if not info.ok:
            self.info = None
            self._show_blank()
            self.var_source.set("No file selected")
            self.var_status.set("Ready")
            messagebox.showerror(APP_TITLE, "Could not read this file:\n\n%s" % info.error)
            return

        self.info = info
        self.var_source.set(info.summary)
        self.timestamp = 0.0

        self._suspend_traces = True
        self.var_time.set(0.0)
        self.scale_time.configure(to=max(0.001, info.duration))
        self._suspend_traces = False
        self.var_timelabel.set(format_time(0.0))

        stem = os.path.splitext(os.path.basename(path))[0]
        out = os.path.join(os.path.dirname(path), stem + ".avi")
        if os.path.abspath(out) == os.path.abspath(path):
            out = os.path.join(os.path.dirname(path), stem + "_esp32.avi")
        self.var_output.set(out)

        self._update_enabled_state()
        self.schedule_preview()

    def on_step(self, delta):
        if not self.info or self.info.is_image:
            return
        self.set_timestamp(self.timestamp + delta)

    def on_time_scrub(self, value):
        if self._suspend_traces or not self.info or self.info.is_image:
            return
        self.set_timestamp(float(value), from_scale=True)

    def set_timestamp(self, t, from_scale=False):
        if not self.info:
            return
        upper = max(0.0, self.info.duration - 0.001)
        t = max(0.0, min(upper, t))
        self.timestamp = t
        self.var_timelabel.set(format_time(t))
        if not from_scale:
            self._suspend_traces = True
            self.var_time.set(t)
            self._suspend_traces = False
        self.schedule_preview()

    def on_rotation_pick(self, _event=None):
        self.var_rotation.set(int(self.combo_rot.get().rstrip("°")))

    def on_rotate_step(self, delta):
        new = (int(self.var_rotation.get()) + delta) % 360
        self.combo_rot.set("%d°" % new)
        self.var_rotation.set(new)

    def on_centre_crop(self):
        self._suspend_traces = True
        self.var_crop_x.set(0.0)
        self._suspend_traces = False
        self.var_crop_y.set(0.0)

    def on_pick_pad_color(self):
        rgb, hexval = colorchooser.askcolor(color=self.params.pad_color,
                                            title="Pad colour")
        if hexval:
            self.params.pad_color = hexval
            self.btn_pad.configure(bg=hexval)
            self.schedule_preview()

    def on_reset(self):
        defaults = Params()
        self.params.pad_color = defaults.pad_color
        self.btn_pad.configure(bg=defaults.pad_color)
        self._suspend_traces = True
        self.var_fps.set(defaults.fps)
        self.var_quality.set(defaults.quality)
        self.var_fit.set(defaults.fit)
        self.var_crop_x.set(defaults.crop_x)
        self.var_crop_y.set(defaults.crop_y)
        self.var_rotation.set(defaults.rotation)
        self.combo_rot.set("%d°" % defaults.rotation)
        self.var_mirror_h.set(defaults.mirror_h)
        self.var_mirror_v.set(defaults.mirror_v)
        self.var_duration.set(defaults.duration)
        self._suspend_traces = False
        self.var_qualitylabel.set(str(defaults.quality))
        self._on_param_change()

    def on_copy_cmd(self):
        self.clipboard_clear()
        self.clipboard_append(self.var_command.get())
        self.var_status.set("Command copied to clipboard")

    def on_save_as(self):
        initial = self.var_output.get()
        path = filedialog.asksaveasfilename(
            title="Save output as", defaultextension=".avi",
            initialfile=os.path.basename(initial) or "output.avi",
            initialdir=os.path.dirname(initial) or os.getcwd(),
            filetypes=[("AVI video", "*.avi")])
        if path:
            self.var_output.set(path)
            self._update_command_text()

    def on_generate(self):
        if self.encoder is not None:
            self.encoder.cancel()
            return
        if not self.info or not self.info.ok:
            messagebox.showwarning(APP_TITLE, "Choose a source file first.")
            return
        out = self.var_output.get().strip()
        if not out:
            messagebox.showwarning(APP_TITLE, "Choose an output path first.")
            return
        if os.path.exists(out) and not messagebox.askyesno(
                APP_TITLE, "%s already exists.\n\nOverwrite it?" % os.path.basename(out)):
            return

        p = self._collect_params()
        cmd = build_generate_cmd(self.info, p, out)
        total = p.duration if self.info.is_image else self.info.duration

        self.progress["value"] = 0
        self.var_status.set("Encoding…")
        self.btn_generate.configure(text="Cancel")
        self.encoder = Encoder(cmd, total, self.results)
        self.encoder.start()

    def _on_close(self):
        if self.encoder is not None:
            self.encoder.cancel()
        self.renderer.shutdown()
        self.destroy()


def main():
    app = App()
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        app.after(200, lambda: app.load_file(sys.argv[1]))
    app.mainloop()


if __name__ == "__main__":
    main()
