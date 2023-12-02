#!/usr/bin/env python3
#
# Copyright © 2023 Keith Packard <keithp@keithp.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 59 Temple Place, Suite 330, Boston, MA 02111-1307 USA.
#

from __future__ import annotations
import math
import json
import sys
import argparse
import csv
from io import StringIO

class Point:
    x: float
    y: float

    def __init__(self, x: float, y: float) -> None:
        self.x = x
        self.y = y

    def __str__(self) -> str:
        return "<%f,%f>" % (self.x, self.y)


    def lerp_half(self, o) -> Point:
        """Return the point midway between self and o"""
        return Point(self.x + (o.x - self.x) / 2, self.y + (o.y - self.y) / 2)

    def distance_to_point_squared(self, b) -> float:
        dx = b.x - self.x
        dy = b.y - self.y

        return dx * dx + dy * dy

    def distance_to_line_squared(self, p1, p2) -> float:
        #
        #  Convert to normal form (AX + BY + C = 0)
        #
        #  (X - x1) * (y2 - y1) = (Y - y1) * (x2 - x1)
        #
        #  X * (y2 - y1) - Y * (x2 - x1) - x1 * (y2 - y1) + y1 * (x2 - x1) = 0
        #
        #  A = (y2 - y1)
        #  B = (x1 - x2)
        #  C = (y1x2 - x1y2)
        #
        #  distance² = (AX + BC + C)² / (A² + B²)
        #
        A = p2.y - p1.y
        B = p1.x - p2.x
        C = p1.y * p2.x - p1.x * p2.y

        num = abs(A * self.x + B * self.y + C)
        den = A * A + B * B
        if den == 0:
            return self._distance_to_point_squared(p1)
        else:
            return (num * num) / den


class Rect:
    top_left: Point
    bottom_right: Point

    def __init__(
        self, top_left: Point = Point(0, 0), bottom_right: Point = Point(0, 0)
    ) -> None:
        self.top_left = top_left
        self.bottom_right = bottom_right

    def __str__(self) -> str:
        return "%s - %s" % (self.top_left, self.bottom_right)

    def is_empty(self) -> bool:
        return (
            self.top_left.x >= self.bottom_right.x
            or self.top_left.y >= self.bottom_right.y
        )


class Draw:
    last_x: float
    last_y: float

    def __init__(self) -> None:
        self.last_x = 0
        self.last_y = 0

    def move(self, x: float, y: float) -> None:
        self.last_x = x
        self.last_y = y

    def draw(self, x: float, y: float) -> None:
        self.last_x = x
        self.last_y = y

    def curve(self, x1: float, y1: float, x2: float, y2: float, x3: float, y3: float) -> None:
        self.last_x = x3
        self.last_y = y3

    def rect(self, r: Rect)-> None:
        self.move(r.top_left.x, r.top_left.y)
        self.draw(r.bottom_right.x, r.top_left.y)
        self.draw(r.bottom_right.x, r.bottom_right.y)
        self.draw(r.top_left.x, r.bottom_right.y)
        self.draw(r.top_left.x, r.top_left.y)


class OffsetDraw(Draw):
    offset_x: float
    offset_y: float
    chain: Draw

    def __init__(self, chain: Draw) -> None:
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.chain = chain

    def step(self, offset_x: float, offset_y: float) -> None:
        self.offset_x += offset_x

    def move(self, x: float, y: float) -> None:
        self.chain.move(x + self.offset_x, y + self.offset_y)
        super().move(x, y)

    def draw(self, x: float, y: float) -> None:
        self.chain.draw(x + self.offset_x, y + self.offset_y)
        super().draw(x, y)

    def curve(self, x1: float, y1: float, x2: float, y2: float, x3: float, y3: float) -> None:
        self.chain.curve(
            x1 + self.offset_x,
            y1 + self.offset_y,
            x2 + self.offset_x,
            y2 + self.offset_y,
            x3 + self.offset_x,
            y3 + self.offset_y,
        )
        super().curve(x1, y1, x2, y2, x3, y3)


class Matrix:
    xx: float
    xy: float
    x0: float

    yx: float
    yy: float
    y0: float

    def __init__(
        self,
        xx: float = 1,
        xy: float = 0,
        x0: float = 0,
        yx: float = 0,
        yy: float = 1,
        y0: float = 0,
    ) -> None:
        self.xx = xx
        self.xy = xy
        self.x0 = x0

        self.yx = yx
        self.yy = yy
        self.y0 = y0

    def __mul__(self, o) -> Matrix:
        return Matrix(
            xx=self.xx * o.xx + self.yx * o.xy,
            yx=self.xx * o.yx + self.yx * o.yy,
            xy=self.xy * o.xx + self.yy * o.xy,
            yy=self.xy * o.yx + self.yy * o.yy,
            x0=self.x0 * o.xx + self.y0 * o.xy + o.x0,
            y0=self.x0 * o.yx + self.y0 * o.yy + o.y0,
        )

    def translate(self, tx: float, ty: float) -> Matrix:
        return Matrix(x0=tx, y0=ty) * self

    def scale(self, sx: float, sy: float) -> Matrix:
        return Matrix(xx=sx, yy=sy) * self

    def rotate(self, a: float) -> Matrix:
        c = math.cos(a)
        s = math.sin(a)
        return Matrix(xx=c, yx=s, xy=-s, yy=c) * self

    def sheer(self, sx: float, sy: float) -> Matrix:
        return Matrix(yx=sx, xy=sy) * self

    def point(self, p: Point) -> Point:
        return Point(
            self.xx * p.x + self.yx * p.y + self.x0,
            self.xy * p.x + self.yy * p.y + self.y0,
        )

    def distance(self, p: Point) -> Point:
        return Point(self.xx * p.x + self.yx * p.y, self.xy * p.x + self.yy * p.y)


class Spline:
    a: Point
    b: Point
    c: Point
    d: Point

    def __init__(self, a: Point, b: Point, c: Point, d: Point) -> None:
        self.a = a
        self.b = b
        self.c = c
        self.d = d

    def de_casteljau(self) -> tuple[Spline,Spline]:
        ab = self.a.lerp_half(self.b)
        bc = self.b.lerp_half(self.c)
        cd = self.c.lerp_half(self.d)
        abbc = ab.lerp_half(bc)
        bccd = bc.lerp_half(cd)
        final = abbc.lerp_half(bccd)

        return (Spline(self.a, ab, abbc, final), Spline(final, bccd, cd, self.d))

    #
    # Return an upper bound on the error (squared) that could
    # result from approximating a spline as a line segment
    # connecting the two endpoints
    #

    def error_squared(self) -> float:
        berr = self.b.distance_to_line_squared(self.a, self.d)
        cerr = self.c.distance_to_line_squared(self.a, self.d)

        return max(berr, cerr)

    def decompose(self, tolerance_squared: float) -> tuple[Point]:
        if self.error_squared() <= tolerance_squared:
            return (self.a)
        else:
            d = self.de_casteljau()
            return d[0].decompose(tolerance_squared) + d[1].decompose(tolerance_squared)


class LineDraw(Draw):
    tolerance: float
    chain: Draw

    def __init__(self, chain: Draw, tolerance: float) -> None:
        self.chain = chain
        self.tolerance = tolerance

    def move(self, x: float, y: float) -> None:
        self.chain.move(x, y)
        super().move(x, y)

    def draw(self, x: float, y: float) -> None:
        self.chain.draw(x, y)
        super().draw(x, y)

    def curve(self, x1: float, y1: float, x2: float, y2: float, x3: float, y3: float) -> None:
        s = Spline(
            Point(self.last_x, self.last_y), Point(x1, y1), Point(x2, y2), Point(x3, y3)
        )
        ps = s.decompose(self.tolerance * self.tolerance)
        for p in ps:
            self.draw(p.x, p.y)
        self.draw(x3, y3)


class MatrixDraw(Draw):
    matrix: Matrix
    chain: Draw

    def __init__(self, chain: Draw, matrix: Matrix) -> None:
        self.chain = chain
        self.matrix = matrix

    def move(self, x: float, y: float) -> None:
        point = self.matrix.point(Point(x, y))
        self.chain.move(point.x, point.y)
        super().move(x, y)

    def draw(self, x: float, y: float) -> None:
        point = self.matrix.point(Point(x, y))
        self.chain.draw(point.x, point.y)
        super().draw(x, y)

    def curve(self, x1: float, y1: float, x2: float, y2: float, x3: float, y3: float) -> None:
        b = self.matrix.point(Point(x1, y1))
        c = self.matrix.point(Point(x2, y2))
        d = self.matrix.point(Point(x3, y3))
        self.chain.curve(b.x, b.y, c.x, c.y, d.x, d.y)
        super().curve(x1, y1, x2, y2, x3, y3)


UCS_PAGE_SHIFT = 7
UCS_PER_PAGE = 1 << UCS_PAGE_SHIFT


# encodes a specific Unicode page
class Charmap:
    page: int
    offsets: tuple[int]

    def __init__(self, page, offsets) -> None:
        self.page = page
        self.offsets = offsets


class TextMetrics:
    left_side_bearing: float
    right_side_bearing: float
    ascent: float
    descent: float
    width: float
    font_ascent: float
    font_descent: float

    def __init__(
        self,
        left_side_bearing: float = 0,
        right_side_bearing: float = 0,
        ascent: float = 0,
        descent: float = 0,
        width: float = 0,
        font_ascent: float = 0,
        font_descent: float = 0,
    ):
        self.left_side_bearing = left_side_bearing
        self.right_side_bearing = right_side_bearing
        self.ascent = ascent
        self.descent = descent
        self.width = width
        self.font_ascent = font_ascent
        self.font_descent = font_descent

    def __str__(self):
        return "%f %f %f %f %f %f %f" % (
            self.left_side_bearing,
            self.right_side_bearing,
            self.ascent,
            self.descent,
            self.width,
            self.font_ascent,
            self.font_descent,
        )


class Font:
    name: str
    style: str
    charmap: tuple[Charmap]
    outlines: tuple
    space: int
    ascent: int
    descent: int
    height: int

    def __init__(self, name, style, charmap, outlines, space, ascent, descent, height) -> None:
        self.name = name
        self.style = style
        self.charmap = charmap
        self.outlines = outlines
        self.space = space
        self.ascent = ascent
        self.descent = descent
        self.height = height

    #  Extract the unicode page number from a ucs4 value
    def ucs_page(self, ucs4: int) -> int:
        return ucs4 >> UCS_PAGE_SHIFT

    #  Extract the ucs4 index within a page
    def ucs_char_in_page(self, ucs4: int) -> int:
        return ucs4 & (UCS_PER_PAGE - 1)

    #
    # Map a UCS4 value to the index of the start of the glyph within the
    # glyph array
    #
    def glyph_offset(self, ucs4: int) -> int:
        page = self.ucs_page(ucs4)
        idx = self.ucs_char_in_page(ucs4)
        for i in range(len(self.charmap)):
            if self.charmap[i].page == page:
                return self.charmap[i].offsets[idx]
        return self.charmap[0].offsets[0]

    #  Helper functions to extract data from the glyph array
    def glyph_left(self, offset: int) -> int:
        return self.outlines[offset + 0]

    def glyph_right(self, offset: int) -> int:
        return self.outlines[offset + 1]

    def glyph_ascent(self, offset: int) -> int:
        return self.outlines[offset + 2]

    def glyph_descent(self, offset: int) -> int:
        return self.outlines[offset + 3]

    def glyph_n_snap_x(self, offset: int) -> int:
        return self.outlines[offset + 4]

    def glyph_n_snap_y(self, offset: int) -> int:
        return self.outlines[offset + 5]

    def glyph_snap_x(self, offset: int, s: int) -> int:
        return self.outlines[offset + 6 + s]

    def glyph_snap_y(self, offset: int, s: int) -> int:
        return self.outlines[offset + 6 + self.glyph_n_snap_x(offset) + s]

    def glyph_draw(self, offset: int) -> int:
        return offset + 6 + self.glyph_n_snap_x(offset) + self.glyph_n_snap_y(offset)

    #
    # Our glyphs don't have a separate width value, instead the
    # width is "always" the right_side_bearing plus a fixed padding
    # value (font->space)
    #
    def glyph_width(self, offset: int) -> float:
        return self.glyph_right(offset) + self.space

    def gen_value(self, offset: int):
        """Return the next element of the outlines array"""
        while True:
            value = self.outlines[offset]
            offset = offset + 1
            yield value

    #
    # Draw a single glyph using the provide callbacks.
    #
    def glyph_path(self, ucs4: int, calls: Draw):
        glyph_start = self.glyph_offset(ucs4)
        offset = self.glyph_draw(glyph_start)

        x1 = 0
        y1 = 0

        value = self.gen_value(offset)

        while True:
            op = next(value)

            if op == "m":
                x1 = next(value)
                y1 = next(value)
                calls.move(x1, y1)
            elif op == "l":
                x1 = next(value)
                y1 = next(value)
                calls.draw(x1, y1)
            elif op == "c":
                x3 = next(value)
                y3 = next(value)
                x2 = next(value)
                y2 = next(value)
                x1 = next(value)
                y1 = next(value)
                calls.curve(x3, y3, x2, y2, x1, y1)
            elif op == "2":
                #  Compute the equivalent cubic spline
                _x1 = next(value)
                _y1 = next(value)
                x3 = x1 + 2 * (_x1 - x1) / 3
                y3 = y1 + 2 * (_y1 - y1) / 3
                x1 = next(value)
                y1 = next(value)
                x2 = x1 + 2 * (_x1 - x1) / 3
                y2 = y1 + 2 * (_y1 - y1) / 3
                calls.curve(x3, y3, x2, y2, x1, y1)
            elif op == "e":
                return self.glyph_width(glyph_start)
            else:
                print("unknown font op %s" % op)
                return self.glyph_width(glyph_start)

    #
    # Draw a sequence of glyphs using the provided callbacks,
    # stepping by the width of each glyph
    #

    def text_path(self, s: str, calls: Draw):
        l = len(s)
        glyph_calls = OffsetDraw(calls)

        for g in s:
            ucs4 = ord(g)
            width = self.glyph_path(ucs4, glyph_calls)
            glyph_calls.step(width, 0)

        return glyph_calls.offset_x

    def glyph_metrics(self, ucs4: int) -> TextMetrics:
        glyph_start = self.glyph_offset(ucs4)
        return TextMetrics(
            left_side_bearing=self.glyph_left(glyph_start),
            right_side_bearing=self.glyph_right(glyph_start),
            ascent=self.glyph_ascent(glyph_start),
            descent=self.glyph_descent(glyph_start),
            width=self.glyph_width(glyph_start),
            font_ascent=self.ascent,
            font_descent=self.descent,
        )

    def text_metrics(self, s: str) -> TextMetrics:
        x = 0.0
        ret = None
        for g in s:
            m = self.glyph_metrics(ord(g))
            m.left_side_bearing += x
            m.right_side_bearing += x
            m.width += x
            if ret:
                ret.left_side_bearing = min(ret.left_side_bearing, m.left_side_bearing)
                ret.right_side_bearing = max(
                    ret.right_side_bearing, m.right_side_bearing
                )
                ret.ascent = max(ret.ascent, m.ascent)
                ret.descent = max(ret.descent, m.descent)
                ret.width = max(ret.width, m.width)
            else:
                ret = m
            x = m.width
        return ret

#
# Each glyph contains metrics, a list of snap coordinates and then a list of
# drawing commands.
#
# The metrics contain four values:
#
#  0. left_side_bearing    distance from left edge of cell to left edge of glyph (+ left)
#  1. right_side_bearing   distance from left edge of cell to right edge of glyph (+ left)
#  2. ascent               distance from baseline to top of ink (+ up)
#  3. descent              distance from baseline to bottom of ink (+ down)
#
# Yes, the ascent value has an unexpected sign, but that's how fonts
# work elsewhere.
#
# The snap coordinates are in two lists, snap_x and snap_y. The
# lengths of each list occurs first, then the two arrays
#
#  4. snap_n_x             number of X snap coordinates
#  5. snap_n_y             number of Y snap coordinates
#  6. snap_x               array of snap_n_x coordinates
#  6 + snap_n_x. snap_y    array of snap_n_y coordinates
#
# The snap values aren't used in this particular implementation;
# they're useful when rasterizing the glyphs to a pixel grid; each
# snap coordinate should be moved to the nearest pixel value and values
# between the snap coordinates should be interpolated to fit.
#
# After the snap lists, there's a list of drawing operations ending with
# 'e':
#
#  'm': move (x, y)
#  'l': draw a line (x,y)
#  'c': draw a cubic spline (x1, y1, x2, y2, x3, y3)
#  '2': draw a quadratic spline (x1, y1, x2, y2)
#  'e': end of glyph
#
# The 'l', 'c' and '2' commands use the current position as an
# implicit additional coordinate.
#
# These glyphs are drawn in a 64x64 grid
#

outlines = (
#  0x0 '\0'  offset 0
    0, 24, 42, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, 0,
    'l', 0, -42,
    'l', 24, -42,
    'l', 24, 0,
    'l', 0, 0,
    'e',
#  0x20 ' '  offset 28
    0, 4, 0, 0, 2, 3,
    -128, 0, #  snap_x
    -21, -15, 0, #  snap_y
    'e',
#  0x21 '!'  offset 40
    0, 4, 42, 0, 3, 3,
    0, 2, 4, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 2, -42,
    'l', 2, -14,
    'm', 2, -4,
    'c', 1, -4, 0, -3, 0, -2,
    'c', 0, -1, 1, 0, 2, 0,
    'c', 3, 0, 4, -1, 4, -2,
    'c', 4, -3, 3, -4, 2, -4,
    'e',
#  0x22 '"'  offset 90
    0, 16, 42, -28, 2, 3,
    0, 16, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 0, -28,
    'm', 16, -42,
    'l', 16, -28,
    'e',
#  0x23 '#'  offset 114
    0, 30, 50, 14, 2, 5,
    0, 30, #  snap_x
    -24, -21, -15, -12, 0, #  snap_y
    'm', 16, -50,
    'l', 2, 14,
    'm', 28, -50,
    'l', 14, 14,
    'm', 2, -24,
    'l', 30, -24,
    'm', 0, -12,
    'l', 28, -12,
    'e',
#  0x24 '$'  offset 152
    0, 28, 50, 8, 4, 4,
    0, 10, 18, 28, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 10, -50,
    'l', 10, 8,
    'm', 18, -50,
    'l', 18, 8,
    'm', 28, -36,
    'c', 24, -42, 18, -42, 14, -42,
    'c', 10, -42, 0, -42, 0, -34,
    'c', 0, -25, 8, -24, 14, -22,
    'c', 20, -20, 28, -19, 28, -9,
    'c', 28, 0, 18, 0, 14, 0,
    'c', 10, 0, 4, 0, 0, -6,
    'e',
#  0x25 '%'  offset 224
    0, 36, 42, 0, 4, 7,
    0, 14, 22, 36, #  snap_x
    -42, -38, -28, -21, -15, -14, 0, #  snap_y
    'm', 36, -42,
    'l', 0, 0,
    'm', 10, -42,
    'c', 12, -41, 14, -40, 14, -36,
    'c', 14, -30, 11, -28, 6, -28,
    'c', 2, -28, 0, -30, 0, -34,
    'c', 0, -39, 3, -42, 8, -42,
    'l', 10, -42,
    'c', 18, -37, 28, -37, 36, -42,
    'm', 28, -14,
    'c', 24, -14, 22, -11, 22, -6,
    'c', 22, -2, 24, 0, 28, 0,
    'c', 33, 0, 36, -2, 36, -8,
    'c', 36, -12, 34, -14, 30, -14,
    'l', 28, -14,
    'e',
#  0x26 '&'  offset 323
    0, 40, 42, 0, 4, 4,
    0, 10, 22, 40, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 40, -24,
    'c', 40, -27, 39, -28, 37, -28,
    'c', 29, -28, 32, 0, 12, 0,
    'c', 0, 0, 0, -8, 0, -10,
    'c', 0, -24, 22, -20, 22, -34,
    'c', 22, -45, 10, -45, 10, -34,
    'c', 10, -27, 25, 0, 36, 0,
    'c', 39, 0, 40, -1, 40, -4,
    'e',
#  0x27 '''  offset 390
    0, 4, 42, -30, 2, 3,
    0, 4, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 2, -38,
    'c', -1, -38, -1, -42, 2, -42,
    'c', 6, -42, 5, -33, 0, -30,
    'e',
#  0x28 '('  offset 419
    0, 14, 50, 14, 2, 3,
    0, 14, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 14, -50,
    'c', -5, -32, -5, -5, 14, 14,
    'e',
#  0x29 ')'  offset 441
    0, 14, 50, 14, 2, 3,
    0, 14, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -50,
    'c', 19, -34, 19, -2, 0, 14,
    'e',
# 0x2a '*'  offset 463
    0, 20, 30, -6, 3, 3,
    0, 10, 20, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 10, -30,
    'l', 10, -6,
    'm', 0, -24,
    'l', 20, -12,
    'm', 20, -24,
    'l', 0, -12,
    'e',
#  0x2b '+'  offset 494
    0, 36, 36, 0, 3, 4,
    0, 18, 36, #  snap_x
    -21, -18, -15, 0, #  snap_y
    'm', 18, -36,
    'l', 18, 0,
    'm', 0, -18,
    'l', 36, -18,
    'e',
#  0x2c ','  offset 520
    0, 4, 4, 8, 2, 3,
    0, 4, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 4, -2,
    'c', 4, 1, 0, 1, 0, -2,
    'c', 0, -5, 4, -5, 4, -2,
    'c', 4, 4, 2, 6, 0, 8,
    'e',
#  0x2d '-'  offset 556
    0, 36, 18, -18, 2, 4,
    0, 36, #  snap_x
    -21, -18, -15, 0, #  snap_y
    'm', 0, -18,
    'l', 36, -18,
    'e',
#  0x2e '.'  offset 575
    0, 4, 4, 0, 2, 3,
    0, 4, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 2, -4,
    'c', -1, -4, -1, 0, 2, 0,
    'c', 5, 0, 5, -4, 2, -4,
    'e',
#  0x2f '/'  offset 604
    0, 36, 50, 14, 2, 3,
    0, 36, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 36, -50,
    'l', 0, 14,
    'e',
#  0x30 '0'  offset 622
    0, 28, 42, 0, 2, 4,
    0, 28, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 14, -42,
    'c', 9, -42, 0, -42, 0, -21,
    'c', 0, 0, 9, 0, 14, 0,
    'c', 19, 0, 28, 0, 28, -21,
    'c', 28, -42, 19, -42, 14, -42,
    'e',
#  0x31 '1'  offset 666
    0, 28, 42, 0, 2, 3,
    0, 17, 28 #  snap_x
    -21, -15, 0, #  snap_y
    'm', 7, -34,
    'c', 11, -35, 15, -38, 17, -42,
    'l', 17, 0,
    'e',
#  0x32 '2'  offset 691
    0, 28, 42, 0, 4, 4,
    0, 2, 26, 28, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 2, -32,
    'c', 2, -34, 2, -42, 14, -42,
    'c', 26, -42, 26, -34, 26, -32,
    'c', 26, -30, 25, -25, 10, -10,
    'l', 0, 0,
    'l', 28, 0,
    'e',
#  0x33 '3'  offset 736
    0, 28, 42, 0, 2, 5,
    0, 28, #  snap_x
    -42, -26, -21, -15, 0, #  snap_y
    'm', 4, -42,
    'l', 26, -42,
    'l', 14, -26,
    'c', 21, -26, 28, -26, 28, -14,
    'c', 28, 0, 17, 0, 13, 0,
    'c', 8, 0, 3, -1, 0, -8,
    'e',
#  0x34 '4'  offset 780
    0, 28, 42, 0, 3, 4,
    0, 20, 30, #  snap_x
    -21, -15, -14, 0, #  snap_y
    'm', 20, -42,
    'l', 0, -14,
    'l', 30, -14,
    'm', 20, -42,
    'l', 20, 0,
    'e',
#  0x35 '5'  offset 809
    0, 28, 42, 0, 2, 5,
    0, 28, #  snap_x
    -42, -28, -21, -15, 0, #  snap_y
    'm', 24, -42,
    'l', 4, -42,
    'l', 2, -24,
    'c', 5, -27, 10, -28, 13, -28,
    'c', 16, -28, 28, -28, 28, -14,
    'c', 28, 0, 16, 0, 13, 0,
    'c', 10, 0, 3, 0, 0, -8,
    'e',
#  0x36 '6'  offset 860
    0, 28, 42, 0, 2, 5,
    0, 26, #  snap_x
    -42, -26, -21, -15, 0, #  snap_y
    'm', 24, -36,
    'c', 22, -41, 19, -42, 14, -42,
    'c', 9, -42, 0, -41, 0, -19,
    'c', 0, -1, 9, 0, 13, 0,
    'c', 18, 0, 26, -3, 26, -13,
    'c', 26, -18, 23, -26, 13, -26,
    'c', 10, -26, 1, -24, 0, -14,
    'e',
#  0x37 '7'  offset 919
    0, 28, 42, 0, 2, 4,
    0, 28, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 28, -42,
    'l', 8, 0,
    'm', 0, -42,
    'l', 28, -42,
    'e',
#  0x38 '8'  offset 944
    0, 28, 42, 0, 4, 4,
    0, 2, 26, 28, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 14, -42,
    'c', 5, -42, 2, -40, 2, -34,
    'c', 2, -18, 28, -32, 28, -11,
    'c', 28, 0, 18, 0, 14, 0,
    'c', 10, 0, 0, 0, 0, -11,
    'c', 0, -32, 26, -18, 26, -34,
    'c', 26, -40, 23, -42, 14, -42,
    'e',
#  0x39 '9'  offset 1004
    0, 28, 42, 0, 2, 5,
    0, 26, #  snap_x
    -42, -21, -16, -15, 0, #  snap_y
    'm', 26, -28,
    'c', 25, -16, 13, -16, 13, -16,
    'c', 8, -16, 0, -19, 0, -29,
    'c', 0, -34, 3, -42, 13, -42,
    'c', 24, -42, 26, -32, 26, -23,
    'c', 26, -14, 24, 0, 12, 0,
    'c', 7, 0, 4, -2, 2, -6,
    'e',
#  0x3a ':'  offset 1063
    0, 4, 28, 0, 2, 3,
    0, 4, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 2, -28,
    'c', -1, -28, -1, -24, 2, -24,
    'c', 5, -24, 5, -28, 2, -28,
    'm', 2, -4,
    'c', -1, -4, -1, 0, 2, 0,
    'c', 5, 0, 5, -4, 2, -4,
    'e',
#  0x3b ';'  offset 1109
    0, 4, 28, 8, 2, 3,
    0, 4, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 2, -28,
    'c', -1, -28, -1, -24, 2, -24,
    'c', 5, -24, 5, -28, 2, -28,
    'm', 4, -2,
    'c', 4, 1, 0, 1, 0, -2,
    'c', 0, -5, 4, -5, 4, -2,
    'c', 4, 3, 2, 6, 0, 8,
    'e',
#  0x3c '<'  offset 1162
    0, 32, 36, 0, 2, 3,
    0, 32, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 32, -36,
    'l', 0, -18,
    'l', 32, 0,
    'e',
#  0x3d '='  offset 1183
    0, 36, 24, -12, 2, 5,
    0, 36, #  snap_x
    -24, -21, -15, -12, 0, #  snap_y
    'm', 0, -24,
    'l', 36, -24,
    'm', 0, -12,
    'l', 36, -12,
    'e',
#  0x3e '>'  offset 1209
    0, 32, 36, 0, 2, 3,
    0, 32, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -36,
    'l', 32, -18,
    'l', 0, 0,
    'e',
#  0x3f '?'  offset 1230
    0, 24, 42, 0, 3, 4,
    0, 12, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -32,
    'c', 0, -34, 0, -42, 12, -42,
    'c', 24, -42, 24, -34, 24, -32,
    'c', 24, -29, 24, -24, 12, -20,
    'l', 12, -14,
    'm', 12, -4,
    'c', 9, -4, 9, 0, 12, 0,
    'c', 15, 0, 15, -4, 12, -4,
    'e',
#  0x40 '@'  offset 1288
    0, 42, 42, 0, 1, 6,
    30, #  snap_x
    -42, -32, -21, -15, -10, 0, #  snap_y
    'm', 30, -26,
    'c', 28, -31, 24, -32, 21, -32,
    'c', 10, -32, 10, -23, 10, -19,
    'c', 10, -13, 11, -10, 19, -10,
    'c', 30, -10, 28, -21, 30, -32,
    'c', 27, -10, 30, -10, 34, -10,
    'c', 41, -10, 42, -19, 42, -22,
    'c', 42, -34, 34, -42, 21, -42,
    'c', 9, -42, 0, -34, 0, -21,
    'c', 0, -9, 8, 0, 21, 0,
    'c', 30, 0, 34, -3, 36, -6,
    'e',
#  0x41 'A'  offset 1375
    0, 32, 42, 0, 2, 4,
    0, 32, #  snap_x
    -21, -15, -14, 0, #  snap_y
    'm', 16, -42,
    'l', 0, 0,
    'm', 16, -42,
    'l', 32, 0,
    'm', 6, -14,
    'l', 26, -14,
    'e',
#  0x42 'B'  offset 1406
    0, 28, 42, 0, 2, 5,
    0, 28, #  snap_x
    -42, -22, -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 0, 0,
    'm', 0, -42,
    'l', 18, -42,
    'c', 32, -42, 32, -22, 18, -22,
    'm', 0, -22,
    'l', 18, -22,
    'c', 32, -22, 32, 0, 18, 0,
    'l', 0, 0,
    'e',
#  0x43 'C'  offset 1455
    0, 30, 42, 0, 2, 4,
    0, 30, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 30, -32,
    'c', 26, -42, 21, -42, 16, -42,
    'c', 2, -42, 0, -29, 0, -21,
    'c', 0, -13, 2, 0, 16, 0,
    'c', 21, 0, 26, 0, 30, -10,
    'e',
#  0x44 'D'  offset 1499
    0, 28, 42, 0, 2, 4,
    0, 28, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 0, 0,
    'm', 0, -42,
    'l', 14, -42,
    'c', 33, -42, 33, 0, 14, 0,
    'l', 0, 0,
    'e',
#  0x45 'E'  offset 1534
    0, 26, 42, 0, 2, 5,
    0, 26, #  snap_x
    -42, -22, -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 0, 0,
    'm', 0, -42,
    'l', 26, -42,
    'm', 0, -22,
    'l', 16, -22,
    'm', 0, 0,
    'l', 26, 0,
    'e',
#  0x46 'F'  offset 1572
    0, 26, 42, 0, 2, 5,
    0, 26, #  snap_x
    -42, -22, -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 0, 0,
    'm', 0, -42,
    'l', 26, -42,
    'm', 0, -22,
    'l', 16, -22,
    'e',
#  0x47 'G'  offset 1604
    0, 30, 42, 0, 2, 5,
    0, 30, #  snap_x
    -42, -21, -16, -15, 0, #  snap_y
    'm', 30, -32,
    'c', 26, -42, 21, -42, 16, -42,
    'c', 2, -42, 0, -29, 0, -21,
    'c', 0, -13, 2, 0, 16, 0,
    'c', 28, 0, 30, -7, 30, -16,
    'm', 20, -16,
    'l', 30, -16,
    'e',
#  0x48 'H'  offset 1655
    0, 28, 42, 0, 2, 4,
    0, 28, #  snap_x
    -22, -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 0, 0,
    'm', 28, -42,
    'l', 28, 0,
    'm', 0, -22,
    'l', 28, -22,
    'e',
#  0x49 'I'  offset 1686
    0, 0, 42, 0, 1, 3,
    0, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 0, 0,
    'e',
#  0x4a 'J'  offset 1703
    0, 20, 42, 0, 2, 3,
    0, 20, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 20, -42,
    'l', 20, -10,
    'c', 20, 3, 0, 3, 0, -10,
    'l', 0, -14,
    'e',
#  0x4b 'K'  offset 1731
    0, 28, 42, 0, 2, 3,
    0, 28, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 0, 0,
    'm', 28, -42,
    'l', 0, -14,
    'm', 10, -24,
    'l', 28, 0,
    'e',
#  0x4c 'L'  offset 1761
    0, 24, 42, 0, 2, 3,
    0, 24, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 0, 0,
    'm', 0, 0,
    'l', 24, 0,
    'e',
#  0x4d 'M'  offset 1785
    0, 32, 42, 0, 2, 3,
    0, 32, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 0, 0,
    'm', 0, -42,
    'l', 16, 0,
    'm', 32, -42,
    'l', 16, 0,
    'm', 32, -42,
    'l', 32, 0,
    'e',
#  0x4e 'N'  offset 1821
    0, 28, 42, 0, 2, 3,
    0, 28, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 0, 0,
    'm', 0, -42,
    'l', 28, 0,
    'm', 28, -42,
    'l', 28, 0,
    'e',
#  0x4f 'O'  offset 1851
    0, 32, 42, 0, 2, 4,
    0, 32, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 16, -42,
    'c', 2, -42, 0, -29, 0, -21,
    'c', 0, -13, 2, 0, 16, 0,
    'c', 30, 0, 32, -13, 32, -21,
    'c', 32, -29, 30, -42, 16, -42,
    'e',
#  0x50 'P'  offset 1895
    0, 28, 42, 0, 2, 5,
    0, 28, #  snap_x
    -42, -21, -20, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 0, 0,
    'm', 0, -42,
    'l', 18, -42,
    'c', 32, -42, 32, -20, 18, -20,
    'l', 0, -20,
    'e',
#  0x51 'Q'  offset 1931
    0, 32, 42, 4, 2, 4,
    0, 32, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 16, -42,
    'c', 2, -42, 0, -29, 0, -21,
    'c', 0, -13, 2, 0, 16, 0,
    'c', 30, 0, 32, -13, 32, -21,
    'c', 32, -29, 30, -42, 16, -42,
    'm', 18, -8,
    'l', 30, 4,
    'e',
#  0x52 'R'  offset 1981
    0, 28, 42, 0, 2, 5,
    0, 28, #  snap_x
    -42, -22, -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 0, 0,
    'm', 0, -42,
    'l', 18, -42,
    'c', 32, -42, 31, -22, 18, -22,
    'l', 0, -22,
    'm', 14, -22,
    'l', 28, 0,
    'e',
#  0x53 'S'  offset 2023
    0, 28, 42, 0, 2, 4,
    0, 28, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 28, -36,
    'c', 25, -41, 21, -42, 14, -42,
    'c', 10, -42, 0, -42, 0, -34,
    'c', 0, -17, 28, -28, 28, -9,
    'c', 28, 0, 19, 0, 14, 0,
    'c', 7, 0, 3, -1, 0, -6,
    'e',
#  0x54 'T'  offset 2074
    0, 28, 42, 0, 3, 4,
    0, 14, 28, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 14, -42,
    'l', 14, 0,
    'm', 0, -42,
    'l', 28, -42,
    'e',
#  0x55 'U'  offset 2100
    0, 28, 42, 0, 2, 3,
    0, 28, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 0, -12,
    'c', 0, 4, 28, 4, 28, -12,
    'l', 28, -42,
    'e',
#  0x56 'V'  offset 2128
    0, 32, 42, 0, 2, 3,
    0, 32, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 16, 0,
    'm', 32, -42,
    'l', 16, 0,
    'e',
#  0x57 'W'  offset 2152
    0, 40, 42, 0, 2, 3,
    0, 40, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 10, 0,
    'm', 20, -42,
    'l', 10, 0,
    'm', 20, -42,
    'l', 30, 0,
    'm', 40, -42,
    'l', 30, 0,
    'e',
#  0x58 'X'  offset 2188
    0, 28, 42, 0, 2, 3,
    0, 28, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 28, 0,
    'm', 28, -42,
    'l', 0, 0,
    'e',
#  0x59 'Y'  offset 2212
    0, 32, 42, 0, 3, 3,
    0, 16, 32, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 16, -22,
    'l', 16, 0,
    'm', 32, -42,
    'l', 16, -22,
    'e',
#  0x5a 'Z'  offset 2240
    0, 28, 42, 0, 2, 4,
    0, 28, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 28, -42,
    'l', 0, 0,
    'm', 0, -42,
    'l', 28, -42,
    'm', 0, 0,
    'l', 28, 0,
    'e',
#  0x5b '['  offset 2271
    0, 14, 44, 0, 2, 4,
    0, 14, #  snap_x
    -44, -21, -15, 0, #  snap_y
    'm', 14, -44,
    'l', 0, -44,
    'l', 0, 0,
    'l', 14, 0,
    'e',
#  0x5c '\'  offset 2296
    0, 36, 50, 14, 2, 3,
    0, 36, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -50,
    'l', 36, 14,
    'e',
#  0x5d ']'  offset 2314
    0, 14, 44, 0, 2, 4,
    0, 14, #  snap_x
    -44, -21, -15, 0, #  snap_y
    'm', 0, -44,
    'l', 14, -44,
    'l', 14, 0,
    'l', 0, 0,
    'e',
#  0x5e '^'  offset 2339
    0, 32, 46, -18, 2, 3,
    0, 32, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 16, -46,
    'l', 0, -18,
    'm', 16, -46,
    'l', 32, -18,
    'e',
#  0x5f '_'  offset 2363
    0, 36, 0, 0, 2, 3,
    0, 36, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, 0,
    'l', 36, 0,
    'e',
#  0x60 '`'  offset 2381
    0, 4, 42, -30, 2, 3,
    0, 4, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 4, -42,
    'c', 2, -40, 0, -39, 0, -32,
    'c', 0, -31, 1, -30, 2, -30,
    'c', 5, -30, 5, -34, 2, -34,
    'e',
#  0x61 'a'  offset 2417
    0, 24, 28, 0, 2, 4,
    0, 24, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 24, -28,
    'l', 24, 0,
    'm', 24, -22,
    'c', 21, -27, 18, -28, 13, -28,
    'c', 2, -28, 0, -19, 0, -14,
    'c', 0, -9, 2, 0, 13, 0,
    'c', 18, 0, 21, -1, 24, -6,
    'e',
#  0x62 'b'  offset 2467
    0, 24, 42, 0, 2, 4,
    0, 24, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 0, 0,
    'm', 0, -22,
    'c', 3, -26, 6, -28, 11, -28,
    'c', 22, -28, 24, -19, 24, -14,
    'c', 24, -9, 22, 0, 11, 0,
    'c', 6, 0, 3, -2, 0, -6,
    'e',
#  0x63 'c'  offset 2517
    0, 24, 28, 0, 2, 4,
    0, 24, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 24, -22,
    'c', 21, -26, 18, -28, 13, -28,
    'c', 2, -28, 0, -19, 0, -14,
    'c', 0, -9, 2, 0, 13, 0,
    'c', 18, 0, 21, -2, 24, -6,
    'e',
#  0x64 'd'  offset 2561
    0, 24, 42, 0, 2, 4,
    0, 24, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 24, -42,
    'l', 24, 0,
    'm', 24, -22,
    'c', 21, -26, 18, -28, 13, -28,
    'c', 2, -28, 0, -19, 0, -14,
    'c', 0, -9, 2, 0, 13, 0,
    'c', 18, 0, 21, -2, 24, -6,
    'e',
#  0x65 'e'  offset 2611
    0, 24, 28, 0, 2, 5,
    0, 24, #  snap_x
    -28, -21, -16, -15, 0, #  snap_y
    'm', 0, -16,
    'l', 24, -16,
    'c', 24, -20, 24, -28, 13, -28,
    'c', 2, -28, 0, -19, 0, -14,
    'c', 0, -9, 2, 0, 13, 0,
    'c', 18, 0, 21, -2, 24, -6,
    'e',
#  0x66 'f'  offset 2659
    0, 16, 42, 0, 3, 5,
    0, 6, 16, #  snap_x
    -42, -28, -21, -15, 0, #  snap_y
    'm', 16, -42,
    'c', 8, -42, 6, -40, 6, -34,
    'l', 6, 0,
    'm', 0, -28,
    'l', 14, -28,
    'e',
#  0x67 'g'  offset 2693
    0, 24, 28, 14, 2, 5,
    0, 24, #  snap_x
    -28, -21, -15, 0, 14, #  snap_y
    'm', 24, -28,
    'l', 24, 4,
    'c', 23, 14, 16, 14, 13, 14,
    'c', 10, 14, 8, 14, 6, 12,
    'm', 24, -22,
    'c', 21, -26, 18, -28, 13, -28,
    'c', 2, -28, 0, -19, 0, -14,
    'c', 0, -9, 2, 0, 13, 0,
    'c', 18, 0, 21, -2, 24, -6,
    'e',
#  0x68 'h'  offset 2758
    0, 22, 42, 0, 2, 4,
    0, 22, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 0, 0,
    'm', 0, -20,
    'c', 8, -32, 22, -31, 22, -20,
    'l', 22, 0,
    'e',
#  0x69 'i'  offset 2790
    0, 4, 44, 0, 3, 3,
    0, 2, 4, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -42,
    'c', 0, -39, 4, -39, 4, -42,
    'c', 4, -45, 0, -45, 0, -42,
    'm', 2, -28,
    'l', 2, 0,
    'e',
#  0x6a 'j'  offset 2826
    -8, 4, 44, 14, 3, 4,
    0, 2, 4, #  snap_x
    -21, -15, 0, 14, #  snap_y
    'm', 0, -42,
    'c', 0, -39, 4, -39, 4, -42,
    'c', 4, -45, 0, -45, 0, -42,
    'm', 2, -28,
    'l', 2, 6,
    'c', 2, 13, -1, 14, -8, 14,
    'e',
#  0x6b 'k'  offset 2870
    0, 22, 42, 0, 2, 3,
    0, 22, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 0, 0,
    'm', 20, -28,
    'l', 0, -8,
    'm', 8, -16,
    'l', 22, 0,
    'e',
#  0x6c 'l'  offset 2900
    0, 0, 42, 0, 1, 3,
    0, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 0, 0,
    'e',
#  0x6d 'm'  offset 2917
    0, 44, 28, 0, 3, 4,
    0, 22, 44, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 0, -28,
    'l', 0, 0,
    'm', 0, -20,
    'c', 5, -29, 22, -33, 22, -20,
    'l', 22, 0,
    'm', 22, -20,
    'c', 27, -29, 44, -33, 44, -20,
    'l', 44, 0,
    'e',
#  0x6e 'n'  offset 2963
    0, 22, 28, 0, 2, 4,
    0, 22, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 0, -28,
    'l', 0, 0,
    'm', 0, -20,
    'c', 4, -28, 22, -34, 22, -20,
    'l', 22, 0,
    'e',
#  0x6f 'o'  offset 2995
    0, 26, 28, 0, 2, 4,
    0, 26, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 13, -28,
    'c', 2, -28, 0, -19, 0, -14,
    'c', 0, -9, 2, 0, 13, 0,
    'c', 24, 0, 26, -9, 26, -14,
    'c', 26, -19, 24, -28, 13, -28,
    'e',
#  0x70 'p'  offset 3039
    0, 24, 28, 14, 2, 4,
    0, 24, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 0, -28,
    'l', 0, 14,
    'm', 0, -22,
    'c', 3, -26, 6, -28, 11, -28,
    'c', 22, -28, 24, -19, 24, -14,
    'c', 24, -9, 22, 0, 11, 0,
    'c', 6, 0, 3, -2, 0, -6,
    'e',
#  0x71 'q'  offset 3089
    0, 24, 28, 14, 2, 4,
    0, 24, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 24, -28,
    'l', 24, 14,
    'm', 24, -22,
    'c', 21, -26, 18, -28, 13, -28,
    'c', 2, -28, 0, -19, 0, -14,
    'c', 0, -9, 2, 0, 13, 0,
    'c', 18, 0, 21, -2, 24, -6,
    'e',
#  0x72 'r'  offset 3139
    0, 16, 28, 0, 2, 4,
    0, 16, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 0, -28,
    'l', 0, 0,
    'm', 0, -16,
    'c', 2, -27, 7, -28, 16, -28,
    'e',
#  0x73 's'  offset 3168
    0, 22, 28, 0, 2, 4,
    0, 22, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 22, -22,
    'c', 22, -27, 16, -28, 11, -28,
    'c', 4, -28, 0, -26, 0, -22,
    'c', 0, -11, 22, -20, 22, -7,
    'c', 22, 0, 17, 0, 11, 0,
    'c', 6, 0, 0, -1, 0, -6,
    'e',
#  0x74 't'  offset 3219
    0, 16, 42, 0, 3, 4,
    0, 6, 16, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 6, -42,
    'l', 6, -8,
    'c', 6, -2, 8, 0, 16, 0,
    'm', 0, -28,
    'l', 14, -28,
    'e',
#  0x75 'u'  offset 3252
    0, 22, 28, 0, 2, 3,
    0, 22, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -28,
    'l', 0, -8,
    'c', 0, 6, 18, 0, 22, -8,
    'm', 22, -28,
    'l', 22, 0,
    'e',
#  0x76 'v'  offset 3283
    0, 24, 28, 0, 2, 3,
    0, 24, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -28,
    'l', 12, 0,
    'm', 24, -28,
    'l', 12, 0,
    'e',
#  0x77 'w'  offset 3307
    0, 32, 28, 0, 2, 3,
    0, 32, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -28,
    'l', 8, 0,
    'm', 16, -28,
    'l', 8, 0,
    'm', 16, -28,
    'l', 24, 0,
    'm', 32, -28,
    'l', 24, 0,
    'e',
#  0x78 'x'  offset 3343
    0, 22, 28, 0, 2, 3,
    0, 22, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -28,
    'l', 22, 0,
    'm', 22, -28,
    'l', 0, 0,
    'e',
#  0x79 'y'  offset 3367
    -2, 24, 28, 14, 2, 4,
    0, 24, #  snap_x
    -21, -15, 0, 14, #  snap_y
    'm', 0, -28,
    'l', 12, 0,
    'm', 24, -28,
    'l', 12, 0,
    'c', 6, 13, 0, 14, -2, 14,
    'e',
#  0x7a 'z'  offset 3399
    0, 22, 28, 0, 2, 4,
    0, 22, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 22, -28,
    'l', 0, 0,
    'm', 0, -28,
    'l', 22, -28,
    'm', 0, 0,
    'l', 22, 0,
    'e',
#  0x7b '{'  offset 3430
    0, 16, 44, 0, 3, 5,
    0, 6, 16, #  snap_x
    -44, -24, -21, -15, 0, #  snap_y
    'm', 16, -44,
    'c', 10, -44, 6, -42, 6, -36,
    'l', 6, -24,
    'l', 0, -24,
    'l', 6, -24,
    'l', 6, -8,
    'c', 6, -2, 10, 0, 16, 0,
    'e',
#  0x7c '|'  offset 3474
    0, 0, 50, 14, 1, 3,
    0, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -50,
    'l', 0, 14,
    'e',
#  0x7d '}'  offset 3491
    0, 16, 44, 0, 3, 5,
    0, 10, 16, #  snap_x
    -44, -24, -21, -15, 0, #  snap_y
    'm', 0, -44,
    'c', 6, -44, 10, -42, 10, -36,
    'l', 10, -24,
    'l', 16, -24,
    'l', 10, -24,
    'l', 10, -8,
    'c', 10, -2, 6, 0, 0, 0,
    'e',
#  0x7e '~'  offset 3535
    0, 36, 24, -12, 2, 5,
    0, 36, #  snap_x
    -24, -21, -15, -12, 0, #  snap_y
    'm', 0, -14,
    'c', 1, -21, 4, -24, 8, -24,
    'c', 18, -24, 18, -12, 28, -12,
    'c', 32, -12, 35, -15, 36, -22,
    'e',
)


charmap = (Charmap(page = 0x0000,
                  offsets = (
                    0,    0,    0,    0,    0,    0,    0,    0,
                    0,    0,    0,    0,    0,    0,    0,    0,
                    0,    0,    0,    0,    0,    0,    0,    0,
                    0,    0,    0,    0,    0,    0,    0,    0,
                    28,   40,   90,  114,  152,  224,  323,  390,
                    419,  441,  463,  494,  520,  556,  575,  604,
                    622,  666,  691,  736,  780,  809,  860,  919,
                    944, 1004, 1063, 1109, 1162, 1183, 1209, 1230,
                    1288, 1375, 1406, 1455, 1499, 1534, 1572, 1604,
                    1655, 1686, 1703, 1731, 1761, 1785, 1821, 1851,
                    1895, 1931, 1981, 2023, 2074, 2100, 2128, 2152,
                    2188, 2212, 2240, 2271, 2296, 2314, 2339, 2363,
                    2381, 2417, 2467, 2517, 2561, 2611, 2659, 2693,
                    2758, 2790, 2826, 2870, 2900, 2917, 2963, 2995,
                    3039, 3089, 3139, 3168, 3219, 3252, 3283, 3307,
                    3343, 3367, 3399, 3430, 3474, 3491, 3535,    0,
                      )),)

font = Font(
    name        = "Default",
    style       = "Roman",
    charmap     = charmap,
    outlines    = outlines,
    space       = 12,
    ascent      = 50,
    descent     = 14,
    height      = 72,
    )


class Device:
    start: str = "G90\nG17\n"
    settings: str = ""
    setting_values: list[str] = []
    inch: str = "G20\n"
    mm: str = "G21\n"
    move: str = "G00 X%f Y%f\n"
    speed: bool = True
    y_invert: bool = True
    draw: str = "G01 X%f Y%f F%f\n"
    curve: str = ""
    stop: str = "M30\n"

    def __init__(self, json: str = ""):
        if json != "":
            self.set_json(json)

    def bool(self, value):
        if value == "true":
            return True
        if value == "false":
            return False
        return value

    def set_values(self, values):
        for key, value in values.items():
            if key == "start":
                self.start = value
            elif key == "settings":
                self.settings = value
            elif key == "setting-values":
                self.setting_values = value
            elif key == "inch":
                self.inch = self.bool(value)
            elif key == "mm":
                self.mm = self.bool(value)
            elif key == "move":
                self.move = value
            elif key == "speed":
                self.speed = self.bool(value)
            elif key == "y-invert":
                self.y_invert = self.bool(value)
            elif key == "draw":
                self.draw = value
            elif key == "curve":
                self.curve = value
            elif key == "stop":
                self.stop = value

    def set_json(self, json: str):
        self.set_values(json.loads(str))

    def set_settings(self, settings: str):
        f = StringIO(settings)
        reader = csv.reader(f, delimiter=',')
        setting_values = []
        for row in reader:
            setting_values = row
        for i in range(min(len(setting_values), len(self.setting_values))):
            self.setting_values[i] = setting_values[i]

    def set_json_file(self, json_file: str):
        with open(json_file, "r") as file:
            self.set_values(json.load(file))


class GCode(Draw):
    f: any
    device: Device
    args: any

    def __init__(self, f: any, device: Device, args):
        self.f = f
        self.device = device
        self.args = args
        if args.settings != None:
            device.set_settings(args.settings)

    def start(self):
        print("%s" % self.device.start, file=self.f, end="")
        if self.device.settings != "":
            print(
                self.device.settings % tuple(self.device.setting_values), file=self.f, end=""
            )
        if self.args.mm:
            print("%s" % self.device.mm, file=self.f, end="")
        else:
            print("%s" % self.device.inch, file=self.f, end="")

    def move(self, x: float, y: float):
        print(self.device.move % (x, y), file=self.f, end="")
        super().move(x, y)

    def draw(self, x: float, y: float):
        if self.device.speed:
            s = self.device.draw % (x, y, self.args.speed)
        else:
            s = self.device.draw % (x, y)
        print(s, file=self.f, end="")
        super().draw(x, y)

    def curve(self, x1: float, y1: float, x2: float, y2: float, x3: float, y3: float):
        if self.device.speed:
            s = self.device.curve % (x1, y1, x2, y2, x3, y3, self.args.speed)
        else:
            s = self.device.curve % (x1, y1, x2, y2, x3, y3)
        print(s, file=self.f, end="")
        super().curve(x1, y1, x2, y2, x3, y3)

    def stop(self):
        print("%s" % self.device.stop, file=self.f, end="")

    def get_draw(self):
        if self.device.curve == "":
            return LineDraw(self, self.args.flatness)
        return self

    def text_path(self, m: Matrix, s: str):
        draw = MatrixDraw(self.get_draw(), m)
        font.text_path(s, draw)

    def text_into_rect(self, r: Rect, s: str):
        if self.args.rect:
            self.rect(r)

        rect_width = r.bottom_right.x - r.top_left.x - self.args.border * 2
        rect_height = r.bottom_right.y - r.top_left.y - self.args.border * 2

        metrics = font.text_metrics(s)

        text_width = metrics.right_side_bearing - metrics.left_side_bearing
        text_height = metrics.ascent + metrics.descent

        if self.args.oblique:
            text_width += text_height * self.args.oblique_sheer

        if text_width / text_height > rect_width / rect_height:
            scale = rect_width / text_width
        else:
            scale = rect_height / text_height

        text_off_x = (rect_width - text_width * scale) / 2
        text_off_y = (rect_height - text_height * scale) / 2

        matrix = Matrix()
        matrix = matrix.translate(
            text_off_x + r.top_left.x + self.args.border,
            text_off_y + r.top_left.y + self.args.border,
        )
        if self.args.oblique:
            matrix = matrix.sheer(-self.args.oblique_sheer, 0)

        matrix = matrix.scale(scale, scale)
        if self.device.y_invert:
            matrix = matrix.scale(1, -1)
        else:
            matrix = matrix.translate(0, metrics.ascent)

        self.text_path(matrix, s)


def Args():
    parser = argparse.ArgumentParser(
        add_help=False,
        description='Render stroked text'
        )
    parser.add_argument('--help', action='store_true',
                        help='Print usage and exit')
    parser.add_argument('-V', '--version', action='store_true',
                        help='Print version and exit')
    parser.add_argument('-i', '--inch', action='store_true',
                        help='Use inch units')
    parser.add_argument('-m', '--mm', action='store_true',
                        help='Use millimeter units')
    parser.add_argument('-r', '--rect', action='store_true',
                        help='Draw bounding rectangles')
    parser.add_argument('-O', '--oblique', action='store_true',
                        help='Draw the glyphs using a sheer transform')
    parser.add_argument('--sheer', action='store', type=float,
                        help='Oblique sheer amount',
                        default=0.1)
    parser.add_argument('-f', '--flatness', action='store', type=float,
                        help='Spline decomposition tolerance',
                        default=0.001)
    parser.add_argument('-s', '--speed', action='store', type=float,
                        help='Feed rate',
                        default=100)
    parser.add_argument('-t', '--template', action='store',
                        help='Template file name',
                        default=None)
    parser.add_argument('-d', '--device', action='store',
                        help='Device config file',
                        default='')
    parser.add_argument('-S', '--settings', action='store',
                        help='Device-specific settings values',
                        default='')
    parser.add_argument('-o', '--output', action='store',
                        help='Output file name',
                        default='-')
    parser.add_argument('-b', '--border', action='store', type=float,
                        help='Border width',
                        default=0.1)
    parser.add_argument('-x', '--start-x', action='store', type=float,
                        help='Starting X for boxes',
                        default=0)
    parser.add_argument('-y', '--start-y', action='store', type=float,
                        help='Starting Y for boxes',
                        default=0)
    parser.add_argument('-w', '--width', action='store', type=float,
                        help='Box width',
                        default=4)
    parser.add_argument('-h', '--height', action='store', type=float,
                        help='Box height',
                        default=1)
    parser.add_argument('-X', '--delta-x', action='store', type=float,
                        help='X offset between boxes',
                        default=4)
    parser.add_argument('-Y', '--delta-y', action='store', type=float,
                        help='Y offset between boxes',
                        default=1)
    parser.add_argument('-c', '--columns', action='store', type=int,
                        help='Number of columns of boxes',
                        default=1)
    parser.add_argument('-v', '--value', action='store', type=float,
                        default=None,
                        help='Initial text numeric value')
    parser.add_argument('-n', '--number', action='store', type=float,
                        default=1,
                        help='Number of numeric values')
    parser.add_argument('-T', '--text', action='store',
                        help='Text string')
    parser.add_argument('-C', '--config-dir', action='store',
                        help='Directory containing device configuration files')
    parser.add_argument('file', nargs='*',
                        help='Text source files')
    args = parser.parse_args()

    for f in args.file:
        print("file: %s" % f)

    if args.help:
        parser.print_help()
        sys.exit(0)

    if args.version:
        print("%s" % '@VERSION@')
        sys.exit(0)

    return args;
    

def finite_rects(args):
    return args.template is not None


def get_rect(args):
    if args.template is not None:
        with open(args.template) as file:
            rects = json.load(file)
        for r in rects:
            yield Rect(Point(r[0], r[1]), Point(r[0] + r[2], r[1] + r[3]))
    else:
        y = args.start_y
        while True:
            x = args.start_x
            for c in range(args.columns):
                yield Rect(Point(x, y), Point(x+args.width, y+args.height))
                x += args.delta_x
            y += args.delta_y
    

def get_line(args):
    if args.value != None:
        v = args.value
        n = args.number
        while finite_rects(args) or n > 0:
            yield "%d" % v
            n -= 1
            v += 1
    if args.text != None:
        for l in args.text.splitlines():
            yield l
    for name in args.file:
        with open(name, "r") as f:
            for l in f.readlines():
                yield l

def main():
    args = Args()
    device = Device()
    if args.device:
        device.set_json_file(args.device)

    output = sys.stdout
    if args.output != '-':
        output = open(args.output, "w")

    rect_gen = get_rect(args)
    line_gen = get_line(args)

    gcode = GCode(output, device, args)
    gcode.start()

    while True:
        try:
            rect = next(rect_gen)
            line = next(line_gen)
            print("rect %s line %s" % (rect, line))
            gcode.text_into_rect(rect, line)
        except StopIteration:
            break

    gcode.stop()

main()
