#!/usr/bin/env python3
"""Poll the One Nation donation page and log the raised amount."""

from __future__ import annotations

import argparse
import csv
import math
import re
import sys
import zlib
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


URL = "https://donate.onenation.org.au/fire-the-liar"
TARGET_CLASSES = {"fw-bold", "text-brand", "raisedAmount"}
DEFAULT_OUTPUT = Path("raised_amount_log.csv")
DEFAULT_GRAPH = Path("graph.png")

FONT = {
    " ": ["000", "000", "000", "000", "000", "000", "000"],
    "$": ["010", "111", "100", "110", "001", "111", "010"],
    ",": ["000", "000", "000", "000", "000", "010", "100"],
    ".": ["000", "000", "000", "000", "000", "000", "010"],
    "-": ["000", "000", "000", "111", "000", "000", "000"],
    "/": ["001", "001", "010", "010", "010", "100", "100"],
    ":": ["000", "010", "000", "000", "000", "010", "000"],
    "0": ["111", "101", "101", "101", "101", "101", "111"],
    "1": ["010", "110", "010", "010", "010", "010", "111"],
    "2": ["111", "001", "001", "111", "100", "100", "111"],
    "3": ["111", "001", "001", "111", "001", "001", "111"],
    "4": ["101", "101", "101", "111", "001", "001", "001"],
    "5": ["111", "100", "100", "111", "001", "001", "111"],
    "6": ["111", "100", "100", "111", "101", "101", "111"],
    "7": ["111", "001", "001", "010", "010", "100", "100"],
    "8": ["111", "101", "101", "111", "101", "101", "111"],
    "9": ["111", "101", "101", "111", "001", "001", "111"],
    "A": ["010", "101", "101", "111", "101", "101", "101"],
    "D": ["110", "101", "101", "101", "101", "101", "110"],
    "E": ["111", "100", "100", "111", "100", "100", "111"],
    "I": ["111", "010", "010", "010", "010", "010", "111"],
    "L": ["100", "100", "100", "100", "100", "100", "111"],
    "M": ["101", "111", "111", "101", "101", "101", "101"],
    "N": ["101", "111", "111", "111", "111", "111", "101"],
    "O": ["111", "101", "101", "101", "101", "101", "111"],
    "R": ["110", "101", "101", "110", "101", "101", "101"],
    "S": ["111", "100", "100", "111", "001", "001", "111"],
    "T": ["111", "010", "010", "010", "010", "010", "010"],
    "U": ["101", "101", "101", "101", "101", "101", "111"],
    "V": ["101", "101", "101", "101", "101", "101", "010"],
}


class RaisedAmountParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._capture_depth = 0
        self._parts: list[str] = []

    @property
    def value(self) -> str | None:
        text = " ".join(part.strip() for part in self._parts if part.strip())
        return text or None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        class_attr = attrs_dict.get("class", "")
        classes = set(class_attr.split())

        if TARGET_CLASSES.issubset(classes):
            self._capture_depth = 1
            return

        if self._capture_depth:
            self._capture_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._capture_depth:
            self._capture_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._capture_depth:
            self._parts.append(data)


def fetch_raised_amount(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0 Safari/537.36"
            )
        },
    )

    with urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        html = response.read().decode(charset, errors="replace")

    parser = RaisedAmountParser()
    parser.feed(html)

    if parser.value is None:
        raise ValueError(
            'Could not find an element containing class="fw-bold text-brand raisedAmount"'
        )

    return parser.value


def append_row(output_path: Path, timestamp: str, raised_amount: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not output_path.exists()

    with output_path.open("a", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        if write_header:
            writer.writerow(["datetime", "raisedAmount"])
        writer.writerow([timestamp, raised_amount])


def parse_amount(value: str) -> float:
    cleaned = re.sub(r"[^\d.]", "", value)
    if not cleaned:
        raise ValueError(f"Could not parse raised amount: {value!r}")
    return float(cleaned)


def read_points(csv_path: Path) -> list[tuple[datetime, float]]:
    points: list[tuple[datetime, float]] = []
    if not csv_path.exists():
        return points

    with csv_path.open(newline="", encoding="utf-8") as csvfile:
        for row in csv.DictReader(csvfile):
            try:
                points.append(
                    (
                        datetime.fromisoformat(row["datetime"]),
                        parse_amount(row["raisedAmount"]),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue

    return points


def nice_amount(value: float) -> str:
    return f"${value:,.0f}"


def text_width(text: str, scale: int = 2) -> int:
    return sum((len(FONT.get(char.upper(), FONT[" "])[0]) + 1) * scale for char in text)


def draw_text(
    pixels: bytearray,
    width: int,
    height: int,
    x: int,
    y: int,
    text: str,
    color: tuple[int, int, int],
    scale: int = 2,
) -> None:
    cursor_x = x
    for char in text.upper():
        glyph = FONT.get(char, FONT[" "])
        for gy, row in enumerate(glyph):
            for gx, bit in enumerate(row):
                if bit == "1":
                    for sy in range(scale):
                        for sx in range(scale):
                            set_pixel(
                                pixels,
                                width,
                                height,
                                cursor_x + gx * scale + sx,
                                y + gy * scale + sy,
                                color,
                            )
        cursor_x += (len(glyph[0]) + 1) * scale


def set_pixel(
    pixels: bytearray,
    width: int,
    height: int,
    x: int,
    y: int,
    color: tuple[int, int, int],
) -> None:
    if 0 <= x < width and 0 <= y < height:
        offset = (y * width + x) * 3
        pixels[offset : offset + 3] = bytes(color)


def draw_line(
    pixels: bytearray,
    width: int,
    height: int,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    color: tuple[int, int, int],
    thickness: int = 1,
) -> None:
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy

    while True:
        radius = thickness // 2
        for yy in range(y0 - radius, y0 + radius + 1):
            for xx in range(x0 - radius, x0 + radius + 1):
                set_pixel(pixels, width, height, xx, yy, color)
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def write_png(path: Path, width: int, height: int, pixels: bytearray) -> None:
    def chunk(chunk_type: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        return len(data).to_bytes(4, "big") + chunk_type + data + crc.to_bytes(4, "big")

    raw = b"".join(
        b"\x00" + bytes(pixels[y * width * 3 : (y + 1) * width * 3])
        for y in range(height)
    )
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", width.to_bytes(4, "big") + height.to_bytes(4, "big") + b"\x08\x02\x00\x00\x00")
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def generate_graph(csv_path: Path, graph_path: Path) -> None:
    points = read_points(csv_path)
    width, height = 1000, 600
    background = (248, 249, 251)
    axis = (45, 55, 72)
    grid = (218, 224, 232)
    line = (21, 99, 181)
    text = (35, 42, 55)
    pixels = bytearray(background * width * height)

    left, right, top, bottom = 110, 40, 70, 95
    chart_w = width - left - right
    chart_h = height - top - bottom

    draw_text(pixels, width, height, 30, 24, "TOTAL AMOUNT RAISED", text, 3)

    if not points:
        draw_text(pixels, width, height, 330, 285, "NO DATA", text, 4)
        write_png(graph_path, width, height, pixels)
        return

    times = [point[0] for point in points]
    amounts = [point[1] for point in points]
    min_time, max_time = min(times), max(times)
    min_amount, max_amount = min(amounts), max(amounts)
    if math.isclose(min_amount, max_amount):
        min_amount -= 1
        max_amount += 1

    time_span = max((max_time - min_time).total_seconds(), 1)
    amount_span = max_amount - min_amount

    for i in range(6):
        y = top + round(chart_h * i / 5)
        draw_line(pixels, width, height, left, y, width - right, y, grid)
        amount = max_amount - amount_span * i / 5
        draw_text(pixels, width, height, 12, y - 7, nice_amount(amount), text, 2)

    draw_line(pixels, width, height, left, top, left, height - bottom, axis, 2)
    draw_line(pixels, width, height, left, height - bottom, width - right, height - bottom, axis, 2)

    plotted: list[tuple[int, int]] = []
    for timestamp, amount in points:
        x = left + round(((timestamp - min_time).total_seconds() / time_span) * chart_w)
        y = top + round(((max_amount - amount) / amount_span) * chart_h)
        plotted.append((x, y))

    for (x0, y0), (x1, y1) in zip(plotted, plotted[1:]):
        draw_line(pixels, width, height, x0, y0, x1, y1, line, 3)

    for x, y in plotted:
        draw_line(pixels, width, height, x - 4, y, x + 4, y, line, 2)
        draw_line(pixels, width, height, x, y - 4, x, y + 4, line, 2)

    label_scale = 2 if len(plotted) <= 8 else 1
    label_rows = 2 if label_scale == 2 else 3
    label_height = 7 * label_scale
    row_gap = 5 if label_scale == 2 else 3
    date_y = height - bottom + 16
    time_y = date_y + label_height + 3
    for index, ((x, _), (timestamp, _)) in enumerate(zip(plotted, points)):
        tick_bottom = height - bottom + 6
        draw_line(pixels, width, height, x, height - bottom, x, tick_bottom, axis)

        row_offset = (index % label_rows) * ((label_height * 2) + row_gap)
        date_label = timestamp.strftime("%d/%m")
        time_label = timestamp.strftime("%H:%M")
        label_x = max(
            left,
            min(
                x - text_width(date_label, label_scale) // 2,
                width - right - text_width(date_label, label_scale),
            ),
        )
        draw_text(pixels, width, height, label_x, date_y + row_offset, date_label, text, label_scale)

        time_x = max(
            left,
            min(
                x - text_width(time_label, label_scale) // 2,
                width - right - text_width(time_label, label_scale),
            ),
        )
        draw_text(pixels, width, height, time_x, time_y + row_offset, time_label, text, label_scale)

    latest = f"LATEST {nice_amount(amounts[-1])}"
    draw_text(pixels, width, height, width - 30 - text_width(latest, 2), 28, latest, text, 2)

    graph_path.parent.mkdir(parents=True, exist_ok=True)
    write_png(graph_path, width, height, pixels)


def run(url: str, output_path: Path, graph_path: Path) -> int:
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")

    try:
        raised_amount = fetch_raised_amount(url)
        append_row(output_path, timestamp, raised_amount)
        generate_graph(output_path, graph_path)
        print(f"{timestamp} {raised_amount}", flush=True)
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        print(f"{timestamp} ERROR: {exc}", file=sys.stderr, flush=True)
        return 1

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Poll a donation page and append the raised amount to a CSV file."
    )
    parser.add_argument("--url", default=URL, help=f"URL to poll. Default: {URL}")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"CSV file to append to. Default: {DEFAULT_OUTPUT}",
    )
    parser.add_argument(
        "--graph",
        type=Path,
        default=DEFAULT_GRAPH,
        help=f"PNG graph to write. Default: {DEFAULT_GRAPH}",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(run(args.url, args.output, args.graph))
