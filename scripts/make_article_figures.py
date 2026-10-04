#!/usr/bin/env python3
"""Render the figures used in the launch post.

The post in `docs/blog/devto-post.md` has three inline figures and one cover
image. They are generated from this script rather than exported from a design
tool so they can be reviewed, corrected and re-rendered like any other file in
the repository: change a label, run the script, look at the diff.

Output goes to `docs/assets/blog/`, which the docs workflow publishes, so the
same PNG can be referenced from the repository, the docs site and the post.

Needs Pillow:  pip install pillow
Run from the repository root:

    python scripts/make_article_figures.py

The palette is deliberately flat (no gradients, no shadows) and the light theme
matches where the figures are read: a dev.to article and the docs site.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover - the message is the point
    print("make_article_figures needs Pillow:  pip install pillow", file=sys.stderr)
    raise SystemExit(2) from None

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = REPO_ROOT / "docs" / "assets" / "blog"

PAPER = (255, 255, 255)
PANEL = (247, 247, 245)
STRIP = (240, 240, 237)
INK = (17, 24, 39)
BODY = (55, 65, 81)
MUTED = (122, 128, 138)
HAIR = (214, 214, 210)
ACCENT = (13, 110, 92)
ACCENT_SOFT = (232, 243, 240)
DENY = (161, 45, 45)
DENY_SOFT = (250, 238, 238)
CODE = (36, 41, 51)

SANS_CANDIDATES = (
    "C:/Windows/Fonts/segoeui.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
)
SANS_BOLD_CANDIDATES = (
    "C:/Windows/Fonts/segoeuib.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
)
MONO_CANDIDATES = (
    "C:/Windows/Fonts/consola.ttf",
    "/System/Library/Fonts/Menlo.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
)

MARGIN = 80
ARROW_HEAD = 13


def _font(candidates: tuple[str, ...], size: int) -> ImageFont.FreeTypeFont:
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size)
    raise SystemExit(f"no font found in {candidates}; add one to this script")


class Sheet:
    """A white page with the four drawing primitives these figures need.

    Every string goes through `text`, which refuses to draw a line wider than
    the box it was given. A clipped word is invisible in a code review and
    obvious on the page, so a figure that would clip is an error, not a
    cosmetic problem: the script stops and says which label overflowed.
    """

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.image = Image.new("RGB", (width, height), PAPER)
        self.draw = ImageDraw.Draw(self.image)
        self.fonts: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}
        # Every string drawn, with the rectangle it occupies. Two labels that
        # collide are invisible in a code review and obvious on the page, so the
        # figure checks itself before it is written out.
        self.labels: list[tuple[float, float, float, float, str]] = []

    def font(self, role: str, size: int) -> ImageFont.FreeTypeFont:
        key = (role, size)
        if key not in self.fonts:
            candidates = {
                "sans": SANS_CANDIDATES,
                "bold": SANS_BOLD_CANDIDATES,
                "mono": MONO_CANDIDATES,
            }[role]
            self.fonts[key] = _font(candidates, size)
        return self.fonts[key]

    def text(
        self,
        x: float,
        y: float,
        content: str,
        *,
        role: str = "sans",
        size: int = 24,
        fill: tuple[int, int, int] = BODY,
        anchor: str = "la",
        limit: int | None = None,
    ) -> None:
        font = self.font(role, size)
        width = font.getlength(content)
        if limit is not None and width > limit:
            raise SystemExit(
                f"label overflows its box by {int(width - limit)}px "
                f"(limit {limit}px): {content!r}\n"
                "Shorten the label or widen the box; do not ship a clipped figure."
            )
        ascent, descent = font.getmetrics()
        height = ascent + descent
        left = {"l": x, "m": x - width / 2, "r": x - width}[anchor[0]]
        top = {"a": y, "t": y, "m": y - height / 2, "s": y - ascent, "d": y - height}[anchor[1]]
        self.labels.append((left, top, left + width, top + height, content))
        self.draw.text((x, y), content, font=font, fill=fill, anchor=anchor)

    def check_layout(self) -> None:
        """Refuse to write a figure whose labels collide or leave the canvas."""
        for left, top, right, bottom, content in self.labels:
            if left < 0 or top < 0 or right > self.width or bottom > self.height:
                raise SystemExit(
                    f"label leaves the {self.width}x{self.height} canvas at "
                    f"({int(left)}, {int(top)}): {content!r}"
                )
        for index, first in enumerate(self.labels):
            for second in self.labels[index + 1 :]:
                if (
                    first[0] < second[2]
                    and second[0] < first[2]
                    and first[1] < second[3]
                    and second[1] < first[3]
                ):
                    raise SystemExit(
                        f"labels overlap: {first[4]!r} at ({int(first[0])}, {int(first[1])}) "
                        f"and {second[4]!r} at ({int(second[0])}, {int(second[1])})"
                    )

    def box(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        fill: tuple[int, int, int] = PAPER,
        outline: tuple[int, int, int] = HAIR,
        radius: int = 14,
        width: int = 2,
    ) -> None:
        self.draw.rounded_rectangle(
            (x, y, x + w, y + h), radius=radius, fill=fill, outline=outline, width=width
        )

    def arrow(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        *,
        colour: tuple[int, int, int] = MUTED,
        width: int = 3,
    ) -> None:
        x1, y1 = start
        x2, y2 = end
        self.draw.line((x1, y1, x2, y2), fill=colour, width=width)
        angle = math.atan2(y2 - y1, x2 - x1)
        for offset in (math.pi * 5 / 6, -math.pi * 5 / 6):
            self.draw.line(
                (
                    x2,
                    y2,
                    x2 + ARROW_HEAD * math.cos(angle + offset),
                    y2 + ARROW_HEAD * math.sin(angle + offset),
                ),
                fill=colour,
                width=width,
            )

    def heading(self, title: str, subtitle: str = "") -> int:
        """Draw the title block, return the first y a figure body may use."""
        self.text(MARGIN, MARGIN, title, role="bold", size=46, fill=INK, limit=self.width - 2 * MARGIN)
        if subtitle:
            self.text(
                MARGIN,
                MARGIN + 66,
                subtitle,
                size=25,
                fill=MUTED,
                limit=self.width - 2 * MARGIN,
            )
            return MARGIN + 132
        return MARGIN + 84

    def caption(self, content: str) -> None:
        self.text(
            MARGIN,
            self.height - MARGIN - 22,
            content,
            size=22,
            fill=MUTED,
            limit=self.width - 2 * MARGIN,
        )

    def save(self, path: Path) -> None:
        self.check_layout()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.image.save(path)
        print(f"{path.relative_to(REPO_ROOT)}: {self.width}x{self.height}, {len(self.labels)} labels")


def figure_cover(out: Path) -> None:
    """Cover: three agents, one cell. Reads at thumbnail size."""
    sheet = Sheet(1600, 672)
    sheet.text(MARGIN, 96, "Agent Memory Protocol", role="bold", size=64, fill=INK)
    sheet.text(
        MARGIN,
        186,
        "One shared memory for every agent you run",
        size=30,
        fill=MUTED,
    )
    sheet.draw.line((MARGIN, 262, 430, 262), fill=ACCENT, width=5)

    agents = ("LangChain agent", "LlamaIndex agent", "anything that can POST")
    top = 330
    for index, label in enumerate(agents):
        y = top + index * 74
        sheet.box(MARGIN, y, 380, 54, fill=PANEL, radius=12)
        sheet.text(MARGIN + 22, y + 27, label, size=23, fill=BODY, anchor="lm", limit=340)
        sheet.arrow((MARGIN + 380, y + 27), (MARGIN + 470, 382), colour=HAIR, width=2)

    cell_x, cell_y, cell_w, cell_h = 500, 300, 1020, 290
    sheet.box(cell_x, cell_y, cell_w, cell_h, fill=PAPER, outline=ACCENT, width=3)
    sheet.text(cell_x + 36, cell_y + 34, "one memory cell", role="bold", size=32, fill=INK)
    fields = (
        ("content", "what the agent stored"),
        ("identity", "owner, creator, session"),
        ("scoring", "importance and decay rate"),
        ("access_policy", "who may read and write it"),
    )
    for index, (field, gloss) in enumerate(fields):
        y = cell_y + 96 + index * 46
        sheet.text(cell_x + 36, y, field, role="mono", size=22, fill=ACCENT)
        sheet.text(cell_x + 300, y, gloss, size=22, fill=MUTED)

    sheet.text(
        MARGIN,
        cell_y + cell_h + 44,
        "over HTTP   ·   /amp/v1   ·   spec v0.1.0   ·   MIT",
        role="mono",
        size=22,
        fill=MUTED,
    )
    sheet.save(out / "amp-cover.png")


def figure_architecture(out: Path) -> None:
    """What the protocol is made of, top to bottom."""
    sheet = Sheet(1600, 1080)
    y = sheet.heading(
        "One wire format, any agent",
        "The contract is the HTTP shape. Clients are conveniences.",
    )

    callers = (
        ("python", "from amp_client import AMPClient"),
        ("node", "import { AMPClient } from '@amp/client'"),
        ("anything", "curl -X POST .../amp/v1/memories"),
    )
    col_w = (sheet.width - 2 * MARGIN - 2 * 28) // 3
    for index, (tag, line) in enumerate(callers):
        x = MARGIN + index * (col_w + 28)
        sheet.box(x, y, col_w, 96, fill=PANEL)
        sheet.text(x + 24, y + 24, tag, role="mono", size=22, fill=ACCENT, limit=col_w - 48)
        sheet.text(x + 24, y + 56, line, role="mono", size=17, fill=MUTED, limit=col_w - 48)
        sheet.arrow((x + col_w // 2, y + 96), (sheet.width // 2, y + 150), colour=HAIR)

    y += 150
    sheet.box(MARGIN, y, sheet.width - 2 * MARGIN, 92, fill=STRIP, outline=HAIR)
    sheet.text(MARGIN + 32, y + 30, "HTTP  /amp/v1", role="bold", size=30, fill=INK)
    sheet.text(
        sheet.width - MARGIN - 32,
        y + 33,
        "POST /memories   ·   GET /memories/search   ·   PATCH /memories/{id}",
        role="mono",
        size=21,
        fill=BODY,
        anchor="ra",
    )
    sheet.arrow((sheet.width // 2, y + 92), (sheet.width // 2, y + 146), colour=HAIR)

    y += 146
    server_h = 314
    sheet.box(MARGIN, y, sheet.width - 2 * MARGIN, server_h, fill=PAPER, outline=INK, width=3)
    sheet.text(MARGIN + 32, y + 26, "reference server", role="bold", size=30, fill=INK)
    parts = (
        ("Memory Cell schema", "one JSON shape for a memory, and the rules that make it immutable"),
        ("Access rules", "readable_by and writable_by, resolved in one place for every caller"),
        ("Lifecycle and decay", "importance falls, cells move active to stale to archived"),
    )
    for index, (title, gloss) in enumerate(parts):
        row_y = y + 88 + index * 74
        sheet.draw.line((MARGIN + 32, row_y - 12, sheet.width - MARGIN - 32, row_y - 12), fill=STRIP, width=2)
        sheet.text(MARGIN + 32, row_y + 8, title, role="bold", size=25, fill=BODY, limit=460)
        sheet.text(MARGIN + 520, row_y + 12, gloss, size=22, fill=MUTED, limit=880)

    y += server_h
    sheet.arrow((sheet.width // 2, y), (sheet.width // 2, y + 50), colour=HAIR)

    y += 50
    stores = (
        ("ChromaDB", "default, no infrastructure to run"),
        ("PostgreSQL + pgvector", "same contract, same tests"),
    )
    for index, (name, gloss) in enumerate(stores):
        x = MARGIN + index * ((sheet.width - 2 * MARGIN) // 2 + 14)
        box_w = (sheet.width - 2 * MARGIN) // 2 - 14
        sheet.box(x, y, box_w, 88, fill=ACCENT_SOFT, outline=ACCENT)
        sheet.text(x + 26, y + 20, name, role="bold", size=24, fill=ACCENT, limit=box_w - 52)
        sheet.text(x + 26, y + 54, gloss, size=20, fill=BODY, limit=box_w - 52)

    sheet.caption("Swapping storage changes no rule: one adapter contract test suite runs against both.")
    sheet.save(out / "amp-architecture.png")


def figure_access(out: Path) -> None:
    """The demo scene: one cell, one allowed reader, one refused."""
    sheet = Sheet(1600, 900)
    y = sheet.heading(
        "Permission lives on the cell",
        "The same question, asked by two agents, answered two ways.",
    )

    cell_x, cell_w = MARGIN, 700
    cell_y, cell_h = y + 30, 430
    sheet.box(cell_x, cell_y, cell_w, cell_h, fill=PANEL)
    sheet.text(cell_x + 32, cell_y + 28, "stored by agent_customer_service", size=22, fill=MUTED, limit=cell_w - 64)
    sheet.text(cell_x + 32, cell_y + 68, '"User prefers email correspondence."', size=27, fill=INK, limit=cell_w - 64)
    sheet.draw.line((cell_x + 32, cell_y + 122, cell_x + cell_w - 32, cell_y + 122), fill=HAIR, width=2)
    policy = (
        '"access_policy": {',
        '  "readable_by": ["agent_billing_*"],',
        '  "writable_by": ["agent_customer_service"],',
        '  "public": false',
        "}",
    )
    for index, line in enumerate(policy):
        sheet.text(cell_x + 32, cell_y + 150 + index * 34, line, role="mono", size=21, fill=CODE, limit=cell_w - 64)

    rows = (
        (True, "agent_billing_v1", "GET /memories/search", "200", "1 memory", "the policy allows it"),
        (False, "agent_marketing", "GET /memories/search", "403", "0 memories", "reads like a cell that does not exist"),
    )
    row_x, row_w = 880, 640
    for index, (allowed, agent, call, code, result, gloss) in enumerate(rows):
        row_y = cell_y + 40 + index * 250
        sheet.box(row_x, row_y, row_w, 210, fill=PAPER, outline=ACCENT if allowed else DENY, width=3)
        sheet.text(row_x + 28, row_y + 26, agent, role="mono", size=25, fill=INK)
        sheet.text(row_x + 28, row_y + 64, call, role="mono", size=19, fill=MUTED)
        tint = ACCENT_SOFT if allowed else DENY_SOFT
        ink = ACCENT if allowed else DENY
        sheet.box(row_x + 28, row_y + 104, 300, 48, fill=tint, outline=ink)
        sheet.text(row_x + 46, row_y + 128, f"{code}  ·  {result}", role="bold", size=23, fill=ink, anchor="lm")
        sheet.text(row_x + 28, row_y + 166, gloss, size=20, fill=MUTED, limit=row_w - 56)
        sheet.arrow(
            (cell_x + cell_w, row_y + 105),
            (row_x, row_y + 105),
            colour=ACCENT if allowed else DENY,
        )

    sheet.caption("An unreadable cell and a deleted cell answer the same way, so error codes cannot probe for data.")
    sheet.save(out / "amp-access.png")


def figure_decay(out: Path) -> None:
    """Importance against time, with the two thresholds marked."""
    sheet = Sheet(1600, 900)
    y = sheet.heading(
        "Memories that retire themselves",
        "Importance decays; the server walks cells along. No cron to write.",
    )

    left, right = MARGIN + 150, sheet.width - MARGIN
    top, bottom = y + 40, sheet.height - MARGIN - 110
    days = 60
    stale_at = 0.3
    decay_rate = 1 / 13.0
    days_to_stale = -math.log(stale_at) / decay_rate
    archive_day = min(days_to_stale + 30, days)
    score = lambda day: math.exp(-decay_rate * day)  # noqa: E731

    for index in range(7):
        gy = top + index * (bottom - top) / 6
        sheet.draw.line((left, gy, right, gy), fill=STRIP, width=1)
        sheet.text(left - 18, gy, f"{1 - index / 6:.2f}", size=18, fill=MUTED, anchor="rm")
    sheet.text(MARGIN - 50, (top + bottom) // 2, "importance", size=21, fill=MUTED, anchor="lm")
    sheet.draw.line((left, top, left, bottom), fill=HAIR, width=2)
    sheet.draw.line((left, bottom, right, bottom), fill=HAIR, width=2)
    for day in range(0, days + 1, 10):
        x = left + (right - left) * day / days
        sheet.draw.line((x, bottom, x, bottom + 8), fill=HAIR, width=2)
        sheet.text(x, bottom + 18, f"{day}d", size=19, fill=MUTED, anchor="ma")
    sheet.text((left + right) // 2, bottom + 56, "days since the cell was last touched", size=21, fill=MUTED, anchor="ma")

    # Archived band, drawn first so the curve sits on top of it.
    band_x = left + (right - left) * archive_day / days
    sheet.draw.rectangle((band_x, top, right, bottom), fill=DENY_SOFT)
    sheet.text((band_x + right) // 2, top + 22, "archived", role="bold", size=22, fill=DENY, anchor="ma")

    stale_y = top + (bottom - top) * (1 - stale_at)
    sheet.draw.line((left, stale_y, right, stale_y), fill=ACCENT, width=2)
    sheet.draw.line(
        (left, top, left, bottom), fill=HAIR, width=2
    )
    sheet.text(left + 14, stale_y - 30, "stale below 0.3", size=21, fill=ACCENT)

    points = [
        (left + (right - left) * day / days, top + (bottom - top) * (1 - score(day)))
        for day in range(days + 1)
    ]
    sheet.draw.line(points, fill=INK, width=4)
    for day, label in ((0, "active"), (days_to_stale, "goes stale"), (archive_day, "archived")):
        px = left + (right - left) * day / days
        py = top + (bottom - top) * (1 - score(day))
        sheet.draw.ellipse((px - 7, py - 7, px + 7, py + 7), fill=INK)
        sheet.text(px + 14, py - 44, label, role="bold", size=21, fill=BODY, anchor="la")

    sheet.text(
        left + 14,
        top + 24,
        "score = importance x decay, recomputed on a schedule",
        role="mono",
        size=19,
        fill=MUTED,
    )
    sheet.caption("Defaults are 0.3 and 30 days, and both are configurable. The curve is the default decay rate.")
    sheet.save(out / "amp-decay.png")


FIGURES = {
    "cover": figure_cover,
    "architecture": figure_architecture,
    "access": figure_access,
    "decay": figure_decay,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the article figures.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--only", choices=sorted(FIGURES), action="append")
    args = parser.parse_args()

    wanted = args.only or sorted(FIGURES)
    for name in wanted:
        FIGURES[name](args.out)
    print(f"{len(wanted)} figure(s) written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
