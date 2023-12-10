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
import os
import numbers
from typing import Any
from io import StringIO

class Point:
    x: float
    y: float

    def __init__(self, x: float, y: float) -> None:
        self.x = x
        self.y = y

    def __str__(self) -> str:
        return "%f,%f" % (self.x, self.y)

    def lerp_half(self, o) -> Point:
        """Return the point midway between self and o"""
        return Point(self.x + (o.x - self.x) / 2, self.y + (o.y - self.y) / 2)


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

    def __str__(self) -> str:
        return "%s %s %s %s" % (self.a, self.b, self.c, self.d)

    def de_casteljau(self) -> tuple[Spline,Spline]:
        ab = self.a.lerp_half(self.b)
        bc = self.b.lerp_half(self.c)
        cd = self.c.lerp_half(self.d)
        abbc = ab.lerp_half(bc)
        bccd = bc.lerp_half(cd)
        final = abbc.lerp_half(bccd)

        return (Spline(self.a, ab, abbc, final), Spline(final, bccd, cd, self.d))

    #
    # Return an upper bound on the error (squared * 16) that could
    # result from approximating a spline as a line segment
    # connecting the two endpoints
    #
    # From https://hcklbrrfnn.files.wordpress.com/2012/08/bez.pdf
    #

    def error_squared(self) -> float:
        ux = 3 * self.b.x - 2 * self.a.x - self.d.x
        uy = 3 * self.b.y - 2 * self.a.y - self.d.y
        vx = 3 * self.c.x - 2 * self.d.x - self.a.x
        vy = 3 * self.c.y - 2 * self.d.y - self.a.y

        ux *= ux
        uy *= uy
        vx *= vx
        vy *= vy
        if ux < vx:
            ux = vx
        if uy < vy:
            uy = vy
        return ux + uy

    def decompose(self, tolerance: float) -> tuple[Point, ...]:
        if self.error_squared() <= 16 * tolerance * tolerance:
            return (self.d,)
        (s1, s2) = self.de_casteljau()
        return s1.decompose(tolerance) + s2.decompose(tolerance)


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
        ps = s.decompose(self.tolerance)
        for p in ps:
            self.draw(p.x, p.y)


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


UCS_PAGE_SHIFT = 8
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


    def gen_pages(self) -> tuple[int,...]:
        pages: list[int] = []
        offset = 0
        page = -1
        while offset < len(self.outlines):
            ucs4 = self.outlines[offset]
            offset += 1
            if self.ucs_page(ucs4) != page:
                page = self.ucs_page(ucs4)
                pages += [page]
            stroke = offset + 6 + self.outlines[offset + 4] + self.outlines[offset + 5]
            while self.outlines[stroke] != 'e':
                cmd = self.outlines[stroke]
                if cmd == 'm' or cmd == 'l':
                    stroke += 3
                elif cmd == '2':
                    stroke += 5
                elif cmd == 'c':
                    stroke += 7
                else:
                    raise ValueError
            offset = stroke + 1
        return tuple(pages)

    #
    # Re-generate the font glyph offset table
    #
    def gen_offsets(self, page: int) -> tuple[int, ...]:
        offsets: list[int] = 256*[1]
        offset = 0
        while offset < len(self.outlines):
            ucs4 = self.outlines[offset]
            offset += 1
            if self.ucs_page(ucs4) == page:
                offsets[self.ucs_char_in_page(ucs4)] = offset
            stroke = offset + 6 + self.outlines[offset + 4] + self.outlines[offset + 5]
            while self.outlines[stroke] != 'e':
                cmd = self.outlines[stroke]
                if cmd == 'm' or cmd == 'l':
                    stroke += 3
                elif cmd == '2':
                    stroke += 5
                elif cmd == 'c':
                    stroke += 7
                else:
                    raise ValueError
            offset = stroke + 1
        return tuple(offsets)

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
                print("unknown font op %s in glyph %d" % (op, ucs4))
                raise ValueError
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
        ret = TextMetrics()
        started = False
        for g in s:
            m = self.glyph_metrics(ord(g))
            m.left_side_bearing += x
            m.right_side_bearing += x
            m.width += x
            if started:
                ret.left_side_bearing = min(ret.left_side_bearing, m.left_side_bearing)
                ret.right_side_bearing = max(
                    ret.right_side_bearing, m.right_side_bearing
                )
                ret.ascent = max(ret.ascent, m.ascent)
                ret.descent = max(ret.descent, m.descent)
                ret.width = max(ret.width, m.width)
            else:
                ret = m
                started = True
            x = m.width
        return ret

#
# Each glyph contains metrics, a list of snap coordinates and then a list of
# drawing commands.
#
# The metrics contain four values:
#
#  -1. code point
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
   0x00, # ''
    0, 32, 42, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, 0,
    'l', 0, -42,
    'l', 32, -42,
    'l', 32, 0,
    'l', 0, 0,
    'e',
   0x20, # ' '
    0, 4, 0, 0, 1, 0,
    4, #  snap_x
    #  snap_y
    'e',
   0x21, # '!'
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
   0x22, # '"'
    0, 16, 42, -28, 2, 3,
    0, 16, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 0, -28,
    'm', 16, -42,
    'l', 16, -28,
    'e',
   0x23, # '#'
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
   0x24, # '$'
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
   0x25, # '%'
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
   0x26, # '&'
    0, 40, 42, 0, 4, 4,
    0, 10, 22, 40, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 40, -25,
    'c', 39, -27, 38, -28, 36, -28,
    'c', 29, -28, 32, 0, 12, 0,
    'c', 2, 0, 0, -7, 0, -10,
    'c', 0, -24, 22, -20, 22, -34,
    'c', 22, -40, 20, -42, 16, -42,
    'c', 13, -42, 10, -41, 10, -34,
    'c', 10, -27, 25, 0, 36, 0,
    'c', 38, 0, 39, -1, 40, -3,
    'e',
   0x27, # '''
    0, 4, 42, -30, 2, 3,
    0, 4, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 4, -40,
    'c', 4, -39, 3, -38, 2, -38,
    'c', 1, -38, 0, -39, 0, -40,
    'c', 0, -41, 1, -42, 2, -42,
    'c', 3, -42, 4, -41, 4, -40,
    'c', 4, -34, 2, -32, 0, -30,
    'e',
   0x28, # '('
    0, 14, 50, 14, 2, 3,
    0, 14, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 14, -50,
    'c', -5, -32, -5, -5, 14, 14,
    'e',
   0x29, # ')'
    0, 14, 50, 14, 2, 3,
    0, 14, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -50,
    'c', 19, -34, 19, -2, 0, 14,
    'e',
   0x2a, # '*'
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
   0x2b, # '+'
    0, 36, 36, 0, 3, 4,
    0, 18, 36, #  snap_x
    -21, -18, -15, 0, #  snap_y
    'm', 18, -36,
    'l', 18, 0,
    'm', 0, -18,
    'l', 36, -18,
    'e',
   0x2c, # ','
    0, 4, 4, 8, 2, 3,
    0, 4, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 4, -2,
    'c', 4, -1, 3, 0, 2, 0,
    'c', 1, 0, 0, -1, 0, -2,
    'c', 0, -3, 1, -4, 2, -4,
    'c', 3, -4, 4, -3, 4, -2,
    'c', 4, 4, 2, 6, 0, 8,
    'e',
   0x2d, # '-'
    0, 36, 18, -18, 2, 4,
    0, 36, #  snap_x
    -21, -18, -15, 0, #  snap_y
    'm', 0, -18,
    'l', 36, -18,
    'e',
   0x2e, # '.'
    0, 4, 4, 0, 2, 3,
    0, 4, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 2, -4,
    'c', 1, -4, 0, -3, 0, -2,
    'c', 0, -1, 1, 0, 2, 0,
    'c', 3, 0, 4, -1, 4, -2,
    'c', 4, -3, 3, -4, 2, -4,
    'e',
   0x2f, # '/'
    0, 36, 50, 14, 2, 3,
    0, 36, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 36, -50,
    'l', 0, 14,
    'e',
   0x30, # '0'
    0, 28, 42, 0, 2, 4,
    0, 28, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 14, -42,
    'c', 9, -42, 0, -42, 0, -21,
    'c', 0, 0, 9, 0, 14, 0,
    'c', 19, 0, 28, 0, 28, -21,
    'c', 28, -42, 19, -42, 14, -42,
    'e',
   0x31, # '1'
    0, 28, 42, 0, 3, 3,
    0, 17, 28, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 7, -34,
    'c', 11, -35, 15, -38, 17, -42,
    'l', 17, 0,
    'e',
   0x32, # '2'
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
   0x33, # '3'
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
   0x34, # '4'
    0, 28, 42, 0, 3, 4,
    0, 20, 30, #  snap_x
    -21, -15, -14, 0, #  snap_y
    'm', 20, 0,
    'l', 20, -42,
    'l', 0, -14,
    'l', 30, -14,
    'e',
   0x35, # '5'
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
   0x36, # '6'
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
   0x37, # '7'
    0, 28, 42, 0, 2, 4,
    0, 28, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 28, -42,
    'l', 8, 0,
    'e',
   0x38, # '8'
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
   0x39, # '9'
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
   0x3a, # ':'
    0, 4, 28, 0, 2, 3,
    0, 4, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 2, -28,
    'c', 1, -28, 0, -27, 0, -26,
    'c', 0, -25, 1, -24, 2, -24,
    'c', 3, -24, 4, -25, 4, -26,
    'c', 4, -27, 3, -28, 2, -28,
    'm', 2, -4,
    'c', 1, -4, 0, -3, 0, -2,
    'c', 0, -1, 1, 0, 2, 0,
    'c', 3, 0, 4, -1, 4, -2,
    'c', 4, -3, 3, -4, 2, -4,
    'e',
   0x3b, # ';'
    0, 4, 28, 8, 2, 3,
    0, 4, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 2, -28,
    'c', 1, -28, 0, -27, 0, -26,
    'c', 0, -25, 1, -24, 2, -24,
    'c', 3, -24, 4, -25, 4, -26,
    'c', 4, -27, 3, -28, 2, -28,
    'm', 4, -2,
    'c', 4, -1, 3, 0, 2, 0,
    'c', 1, 0, 0, -1, 0, -2,
    'c', 0, -3, 1, -4, 2, -4,
    'c', 3, -4, 4, -3, 4, -2,
    'c', 4, 3, 2, 6, 0, 8,
    'e',
   0x3c, # '<'
    0, 32, 36, 0, 2, 3,
    0, 32, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 32, -36,
    'l', 0, -18,
    'l', 32, 0,
    'e',
   0x3d, # '='
    0, 36, 24, -12, 2, 5,
    0, 36, #  snap_x
    -24, -21, -15, -12, 0, #  snap_y
    'm', 0, -24,
    'l', 36, -24,
    'm', 0, -12,
    'l', 36, -12,
    'e',
   0x3e, # '>'
    0, 32, 36, 0, 2, 3,
    0, 32, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -36,
    'l', 32, -18,
    'l', 0, 0,
    'e',
   0x3f, # '?'
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
   0x40, # '@'
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
   0x41, # 'A'
    0, 32, 42, 0, 2, 4,
    0, 32, #  snap_x
    -21, -15, -14, 0, #  snap_y
    'm', 0, 0,
    'l', 16, -42,
    'l', 32, 0,
    'm', 6, -14,
    'l', 26, -14,
    'e',
   0x42, # 'B'
    0, 28, 42, 0, 2, 5,
    0, 28, #  snap_x
    -42, -22, -21, -15, 0, #  snap_y
    'm', 0, 0,
    'l', 0, -42,
    'l', 18, -42,
    'c', 32, -42, 32, -22, 18, -22,
    'm', 0, -22,
    'l', 18, -22,
    'c', 32, -22, 32, 0, 18, 0,
    'l', 0, 0,
    'e',
   0x43, # 'C'
    0, 30, 42, 0, 2, 4,
    0, 30, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 30, -32,
    'c', 26, -42, 21, -42, 16, -42,
    'c', 2, -42, 0, -29, 0, -21,
    'c', 0, -13, 2, 0, 16, 0,
    'c', 21, 0, 26, 0, 30, -10,
    'e',
   0x44, # 'D'
    0, 28, 42, 0, 2, 4,
    0, 28, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, 0,
    'l', 0, -42,
    'l', 14, -42,
    'c', 33, -42, 33, 0, 14, 0,
    'l', 0, 0,
    'e',
   0x45, # 'E'
    0, 26, 42, 0, 2, 5,
    0, 26, #  snap_x
    -42, -22, -21, -15, 0, #  snap_y
    'm', 26, -42,
    'l', 0, -42,
    'l', 0, 0,
    'l', 26, 0,
    'm', 0, -22,
    'l', 16, -22,
    'e',
   0x46, # 'F'
    0, 26, 42, 0, 2, 5,
    0, 26, #  snap_x
    -42, -22, -21, -15, 0, #  snap_y
    'm', 26, -42,
    'l', 0, -42,
    'l', 0, 0,
    'm', 0, -22,
    'l', 16, -22,
    'e',
   0x47, # 'G'
    0, 30, 42, 0, 2, 5,
    0, 30, #  snap_x
    -42, -21, -16, -15, 0, #  snap_y
    'm', 30, -32,
    'c', 26, -42, 21, -42, 16, -42,
    'c', 2, -42, 0, -29, 0, -21,
    'c', 0, -13, 2, 0, 16, 0,
    'c', 28, 0, 30, -7, 30, -16,
    'l', 20, -16,
    'e',
   0x48, # 'H'
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
   0x49, # 'I'
    0, 0, 42, 0, 1, 3,
    0, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 0, 0,
    'e',
   0x4a, # 'J'
    0, 20, 42, 0, 2, 3,
    0, 20, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 20, -42,
    'l', 20, -10,
    'c', 20, 3, 0, 3, 0, -10,
    'l', 0, -14,
    'e',
   0x4b, # 'K'
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
   0x4c, # 'L'
    0, 24, 42, 0, 2, 3,
    0, 24, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 0, 0,
    'l', 24, 0,
    'e',
   0x4d, # 'M'
    0, 32, 42, 0, 2, 3,
    0, 32, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, 0,
    'l', 0, -42,
    'l', 16, 0,
    'l', 32, -42,
    'l', 32, 0,
    'e',
   0x4e, # 'N'
    0, 28, 42, 0, 2, 3,
    0, 28, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, 0,
    'l', 0, -42,
    'l', 28, 0,
    'l', 28, -42,
    'e',
   0x4f, # 'O'
    0, 32, 42, 0, 2, 4,
    0, 32, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 16, -42,
    'c', 2, -42, 0, -29, 0, -21,
    'c', 0, -13, 2, 0, 16, 0,
    'c', 30, 0, 32, -13, 32, -21,
    'c', 32, -29, 30, -42, 16, -42,
    'e',
   0x50, # 'P'
    0, 28, 42, 0, 2, 5,
    0, 28, #  snap_x
    -42, -21, -20, -15, 0, #  snap_y
    'm', 0, 0,
    'l', 0, -42,
    'l', 18, -42,
    'c', 32, -42, 32, -20, 18, -20,
    'l', 0, -20,
    'e',
   0x51, # 'Q'
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
   0x52, # 'R'
    0, 28, 42, 0, 2, 5,
    0, 28, #  snap_x
    -42, -22, -21, -15, 0, #  snap_y
    'm', 0, 0,
    'l', 0, -42,
    'l', 18, -42,
    'c', 32, -42, 31, -22, 18, -22,
    'l', 0, -22,
    'm', 14, -22,
    'l', 28, 0,
    'e',
   0x53, # 'S'
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
   0x54, # 'T'
    0, 28, 42, 0, 3, 4,
    0, 14, 28, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 14, -42,
    'l', 14, 0,
    'm', 0, -42,
    'l', 28, -42,
    'e',
   0x55, # 'U'
    0, 28, 42, 0, 2, 3,
    0, 28, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 0, -12,
    'c', 0, 4, 28, 4, 28, -12,
    'l', 28, -42,
    'e',
   0x56, # 'V'
    0, 32, 42, 0, 2, 3,
    0, 32, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 16, 0,
    'l', 32, -42,
    'e',
   0x57, # 'W'
    0, 40, 42, 0, 2, 3,
    0, 40, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 10, 0,
    'l', 20, -42,
    'l', 30, 0,
    'l', 40, -42,
    'e',
   0x58, # 'X'
    0, 28, 42, 0, 2, 3,
    0, 28, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 28, 0,
    'm', 28, -42,
    'l', 0, 0,
    'e',
   0x59, # 'Y'
    0, 32, 42, 0, 3, 3,
    0, 16, 32, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 16, -22,
    'l', 16, 0,
    'm', 32, -42,
    'l', 16, -22,
    'e',
   0x5a, # 'Z'
    0, 28, 42, 0, 2, 4,
    0, 28, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 28, -42,
    'l', 0, 0,
    'l', 28, 0,
    'e',
   0x5b, # '['
    0, 14, 44, 0, 2, 4,
    0, 14, #  snap_x
    -44, -21, -15, 0, #  snap_y
    'm', 14, -44,
    'l', 0, -44,
    'l', 0, 0,
    'l', 14, 0,
    'e',
   0x5c, # '\'
    0, 36, 50, 14, 2, 3,
    0, 36, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -50,
    'l', 36, 14,
    'e',
   0x5d, # ']'
    0, 14, 44, 0, 2, 4,
    0, 14, #  snap_x
    -44, -21, -15, 0, #  snap_y
    'm', 0, -44,
    'l', 14, -44,
    'l', 14, 0,
    'l', 0, 0,
    'e',
   0x5e, # '^'
    0, 32, 46, -18, 2, 3,
    0, 32, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -18,
    'l', 16, -46,
    'l', 32, -18,
    'e',
   0x5f, # '_'
    0, 36, 0, 0, 2, 3,
    0, 36, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, 0,
    'l', 36, 0,
    'e',
   0x60, # '`'
    0, 4, 42, -30, 2, 3,
    0, 4, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -32,
    'c', 0, -33, 1, -34, 2, -34,
    'c', 3, -34, 4, -33, 4, -32,
    'c', 4, -31, 3, -30, 2, -30,
    'c', 1, -30, 0, -31, 0, -32,
    'c', 0, -38, 2, -40, 4, -42,
    'e',
   0x61, # 'a'
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
   0x62, # 'b'
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
   0x63, # 'c'
    0, 24, 28, 0, 2, 4,
    0, 24, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 24, -22,
    'c', 21, -26, 18, -28, 13, -28,
    'c', 2, -28, 0, -19, 0, -14,
    'c', 0, -9, 2, 0, 13, 0,
    'c', 18, 0, 21, -2, 24, -6,
    'e',
   0x64, # 'd'
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
   0x65, # 'e'
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
   0x66, # 'f'
    0, 16, 42, 0, 3, 5,
    0, 6, 16, #  snap_x
    -42, -28, -21, -15, 0, #  snap_y
    'm', 16, -42,
    'c', 8, -42, 6, -40, 6, -34,
    'l', 6, 0,
    'm', 0, -28,
    'l', 14, -28,
    'e',
   0x67, # 'g'
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
   0x68, # 'h'
    0, 22, 42, 0, 2, 4,
    0, 22, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 0, 0,
    'm', 0, -20,
    'c', 8, -32, 22, -31, 22, -20,
    'l', 22, 0,
    'e',
   0x69, # 'i'
    0, 4, 44, 0, 3, 3,
    0, 2, 4, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -42,
    'c', 0, -39, 4, -39, 4, -42,
    'c', 4, -45, 0, -45, 0, -42,
    'm', 2, -28,
    'l', 2, 0,
    'e',
   0x6a, # 'j'
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
   0x6b, # 'k'
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
   0x6c, # 'l'
    0, 0, 42, 0, 1, 3,
    0, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 0, 0,
    'e',
   0x6d, # 'm'
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
   0x6e, # 'n'
    0, 22, 28, 0, 2, 4,
    0, 22, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 0, -28,
    'l', 0, 0,
    'm', 0, -20,
    'c', 4, -28, 22, -34, 22, -20,
    'l', 22, 0,
    'e',
   0x6f, # 'o'
    0, 26, 28, 0, 2, 4,
    0, 26, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 13, -28,
    'c', 2, -28, 0, -19, 0, -14,
    'c', 0, -9, 2, 0, 13, 0,
    'c', 24, 0, 26, -9, 26, -14,
    'c', 26, -19, 24, -28, 13, -28,
    'e',
   0x70, # 'p'
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
   0x71, # 'q'
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
   0x72, # 'r'
    0, 16, 28, 0, 2, 4,
    0, 16, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 0, -28,
    'l', 0, 0,
    'm', 0, -16,
    'c', 2, -27, 7, -28, 16, -28,
    'e',
   0x73, # 's'
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
   0x74, # 't'
    0, 16, 42, 0, 3, 4,
    0, 6, 16, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 6, -42,
    'l', 6, -8,
    'c', 6, -2, 8, 0, 16, 0,
    'm', 0, -28,
    'l', 14, -28,
    'e',
   0x75, # 'u'
    0, 22, 28, 0, 2, 3,
    0, 22, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -28,
    'l', 0, -8,
    'c', 0, 6, 18, 0, 22, -8,
    'm', 22, -28,
    'l', 22, 0,
    'e',
   0x76, # 'v'
    0, 24, 28, 0, 2, 3,
    0, 24, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -28,
    'l', 12, 0,
    'l', 24, -28,
    'e',
   0x77, # 'w'
    0, 32, 28, 0, 2, 3,
    0, 32, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -28,
    'l', 8, 0,
    'l', 16, -28,
    'l', 24, 0,
    'l', 32, -28,
    'e',
   0x78, # 'x'
    0, 22, 28, 0, 2, 3,
    0, 22, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -28,
    'l', 22, 0,
    'm', 22, -28,
    'l', 0, 0,
    'e',
   0x79, # 'y'
    -2, 24, 28, 14, 2, 4,
    0, 24, #  snap_x
    -21, -15, 0, 14, #  snap_y
    'm', 0, -28,
    'l', 12, 0,
    'm', 24, -28,
    'l', 12, 0,
    'c', 6, 13, 0, 14, -2, 14,
    'e',
   0x7a, # 'z'
    0, 22, 28, 0, 2, 4,
    0, 22, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 0, -28,
    'l', 22, -28,
    'l', 0, 0,
    'l', 22, 0,
    'e',
   0x7b, # '{'
    0, 16, 44, 0, 3, 5,
    0, 6, 16, #  snap_x
    -44, -24, -21, -15, 0, #  snap_y
    'm', 16, -44,
    'c', 10, -44, 6, -42, 6, -36,
    'l', 6, -22,
    'l', 0, -22,
    'l', 6, -22,
    'l', 6, -8,
    'c', 6, -2, 10, 0, 16, 0,
    'e',
   0x7c, # '|'
    0, 0, 50, 14, 1, 3,
    0, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -50,
    'l', 0, 14,
    'e',
   0x7d, # '}'
    0, 16, 44, 0, 3, 5,
    0, 10, 16, #  snap_x
    -44, -24, -21, -15, 0, #  snap_y
    'm', 0, -44,
    'c', 6, -44, 10, -42, 10, -36,
    'l', 10, -22,
    'l', 16, -22,
    'l', 10, -22,
    'l', 10, -8,
    'c', 10, -2, 6, 0, 0, 0,
    'e',
   0x7e, # '~'
    0, 36, 23, -12, 2, 5,
    0, 36, #  snap_x
    -24, -21, -15, -12, 0, #  snap_y
    'm', 0, -15,
    'c', 14, -40, 23, 5, 36, -20,
    'e',
   0xa0, # ' '
    0, 4, 0, 0, 1, 0,
    4, #  snap_x
    #  snap_y
    'e',
   0xa1, # '¡'
    0, 4, 42, 0, 3, 3,
    0, 2, 4, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 2, -28,
    'l', 2, 0,
    'm', 2, -38,
    'c', 1, -38, 0, -39, 0, -40,
    'c', 0, -41, 1, -42, 2, -42,
    'c', 3, -42, 4, -41, 4, -40,
    'c', 4, -39, 3, -38, 2, -38,
    'e',
   0xa2, # '¢'
    0, 24, 32, 4, 3, 4,
    0, 13, 24, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 24, -22,
    'c', 21, -26, 18, -28, 13, -28,
    'c', 2, -28, 0, -19, 0, -14,
    'c', 0, -9, 2, 0, 13, 0,
    'c', 18, 0, 21, -2, 24, -6,
    'm', 13, -32,
    'l', 13, 4,
    'e',
   0xa3, # '£'
    0, 20, 39, 0, 3, 3,
    0, 6, 20, #  snap_x
    -42, -16, 0, #  snap_y
    'm', 18, -34,
    'c', 12, -41, 6, -39, 6, -34,
    'l', 6, 0,
    'm', 0, -16,
    'l', 14, -16,
    'm', 0, 0,
    'l', 20, 0,
    'e',
   0xa4, # '¤'
    0, 16, 28, -12, 2, 2,
    2, 14, #  snap_x
    -26, -14, #  snap_y
    'm', 8, -26,
    'c', 4, -26, 2, -24, 2, -20,
    'c', 2, -16, 4, -14, 8, -14,
    'c', 12, -14, 14, -16, 14, -20,
    'c', 14, -24, 12, -26, 8, -26,
    'm', 0, -28,
    'l', 3, -25,
    'm', 16, -28,
    'l', 13, -25,
    'm', 0, -12,
    'l', 3, -15,
    'm', 16, -12,
    'l', 13, -15,
    'e',
   0xa5, # '¥'
    0, 32, 42, 0, 3, 5,
    0, 16, 32, #  snap_x
    -26, -21, -18, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 16, -22,
    'l', 16, 0,
    'm', 32, -42,
    'l', 16, -22,
    'm', 4, -26,
    'l', 28, -26,
    'm', 4, -18,
    'l', 28, -18,
    'e',
   0xa6, # '¦'
    0, 0, 50, 14, 1, 3,
    0, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -50,
    'l', 0, -22,
    'm', 0, -14,
    'l', 0, 14,
    'e',
   0xa7, # '§'
    0, 19, 43, 0, 4, 2,
    0, 3, 22, 25, #  snap_x
    -43, 0, #  snap_y
    'm', 11, -28,
    'c', 4, -28, 0, -26, 0, -22,
    'c', 0, -13, 17, -16, 17, -7,
    'c', 17, -3, 13, 1, 4, -2,
    'm', 8, -15,
    'c', 15, -15, 19, -17, 19, -21,
    'c', 19, -30, 2, -27, 2, -36,
    'c', 2, -40, 6, -44, 15, -41,
    'e',
   0xa8, # '¨'
    0, 12, 42, -38, 4, 2,
    0, 4, 8, 12, #  snap_x
    -38, -42, #  snap_y
    'm', 2, -38,
    'c', 1, -38, 0, -39, 0, -40,
    'c', 0, -41, 1, -42, 2, -42,
    'c', 3, -42, 4, -41, 4, -40,
    'c', 4, -39, 3, -38, 2, -38,
    'm', 10, -38,
    'c', 9, -38, 8, -39, 8, -40,
    'c', 8, -41, 9, -42, 10, -42,
    'c', 11, -42, 12, -41, 12, -40,
    'c', 12, -39, 11, -38, 10, -38,
    'e',
   0xa9, # '©'
    0, 30, 30, 0, 2, 4,
    0, 24, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 15, -30,
    'c', 6, -30, 0, -24, 0, -15,
    'c', 0, -6, 6, 0, 15, 0,
    'c', 24, 0, 30, -6, 30, -15,
    'c', 30, -24, 24, -30, 15, -30,
    'm', 22, -22,
    'c', 21, -23, 19, -25, 15, -25,
    'c', 7, -25, 5, -18, 5, -15,
    'c', 5, -11, 7, -5, 15, -5,
    'c', 19, -5, 21, -7, 22, -8,
    'e',
   0xaa, # 'ª'
    0, 12, 42, -24, 2, 3,
    0, 16, #  snap_x
    -42, -23, -20, #  snap_y
    'm', 12, -42,
    'l', 12, -28,
    'm', 12, -39,
    'c', 11, -41, 9, -42, 7, -42,
    'c', 1, -42, 0, -37, 0, -35,
    'c', 0, -32, 1, -28, 7, -28,
    'c', 9, -28, 11, -28, 12, -31,
    'm', 1, -24,
    'l', 12, -24,
    'e',
   0xab, # '«'
    0, 26, 28, -2, 2, 3,
    0, 28, #  snap_x
    -28, -15, -2, #  snap_y
    'm', 16, -28,
    'l', 0, -15,
    'l', 16, -2,
    'm', 26, -28,
    'l', 10, -15,
    'l', 26, -2,
    'e',
   0xac, # '¬'
    0, 36, 24, -12, 2, 1,
    0, 36, #  snap_x
    -24, #  snap_y
    'm', 0, -24,
    'l', 36, -24,
    'l', 36, -12,
    'e',
   0xad, # '­'
    0, 0, 0, 0, 1, 0,
    4, #  snap_x
    #  snap_y
    'e',
   0xae, # '®'
    0, 30, 30, 0, 3, 4,
    0, 9, 24, #  snap_x
    -28, -25, -15, 0, #  snap_y
    'm', 15, -30,
    'c', 6, -30, 0, -24, 0, -15,
    'c', 0, -6, 6, 0, 15, 0,
    'c', 24, 0, 30, -6, 30, -15,
    'c', 30, -24, 24, -30, 15, -30,
    'm', 9, -5,
    'l', 9, -25,
    'l', 18, -25,
    'c', 24, -25, 24, -15, 18, -15,
    'l', 9, -15,
    'm', 16, -15,
    'l', 22, -5,
    'e',
   0xaf, # '¯'
    0, 36, 43, -43, 2, 1,
    0, 36, #  snap_x
    -43, #  snap_y
    'm', 0, -43,
    'l', 36, -43,
    'e',
   0xb0, # '°'
    0, 12, 42, -30, 2, 2,
    0, 12, #  snap_x
    -30, -42, #  snap_y
    'm', 6, -30,
    'c', 2, -30, 0, -32, 0, -36,
    'c', 0, -40, 2, -42, 6, -42,
    'c', 10, -42, 12, -40, 12, -36,
    'c', 12, -32, 10, -30, 6, -30,
    'e',
   0xb1, # '±'
    0, 36, 36, -6, 3, 2,
    0, 18, 36, #  snap_x
    -21, 0, #  snap_y
    'm', 18, -36,
    'l', 18, -12,
    'm', 0, -24,
    'l', 36, -24,
    'm', 0, -6,
    'l', 36, -6,
    'e',
   0xb2, # '²'
    0, 14, 42, -21, 4, 4,
    0, 2, 26, 28, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 1, -37,
    'c', 1, -38, 1, -42, 7, -42,
    'c', 13, -42, 13, -38, 13, -37,
    'c', 13, -36, 13, -33, 5, -26,
    'l', 0, -21,
    'l', 14, -21,
    'e',
   0xb3, # '³'
    0, 14, 42, -21, 2, 5,
    0, 28, #  snap_x
    -42, -26, -21, -15, 0, #  snap_y
    'm', 2, -42,
    'l', 13, -42,
    'l', 7, -34,
    'c', 11, -34, 14, -34, 14, -28,
    'c', 14, -21, 9, -21, 7, -21,
    'c', 4, -21, 2, -21, 0, -25,
    'e',
   0xb4, # '´'
    0, 5, 42, -37, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -37,
    'l', 5, -42,
    'e',
   0xb5, # 'µ'
    0, 24, 28, 5, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, 5,
    'l', 0, -28,
    'l', 0, -9,
    'c', 0, 6, 18, 0, 22, -8,
    'm', 22, -28,
    'l', 22, -8,
    'c', 22, -2, 23, -1, 24, 0,
    'e',
   0xb6, # '¶'
    0, 27, 42, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 27, 0,
    'l', 27, -42,
    'l', 9, -42,
    'c', -4, -42, -4, -20, 9, -20,
    'l', 23, -20,
    'm', 23, -42,
    'l', 23, 0,
    'e',
   0xb7, # '·'
    0, 10, 23, -19, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 5, -23,
    'c', 4, -23, 3, -22, 3, -21,
    'c', 3, -20, 4, -19, 5, -19,
    'c', 6, -19, 7, -20, 7, -21,
    'c', 7, -22, 6, -23, 5, -23,
    'e',
   0xb8, # '¸'
    0, 24, 0, 4, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 15, 0,
    'c', 17, 2, 15, 8, 8, 5,
    'e',
   0xb9, # '¹'
    0, 14, 42, -21, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 4, -38,
    'm', 4, -38,
    'c', 6, -38, 8, -40, 9, -42,
    'l', 9, -21,
    'e',
   0xba, # 'º'
    0, 13, 42, -24, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -24,
    'l', 13, -24,
    'm', 7, -42,
    'c', 1, -42, 0, -37, 0, -35,
    'c', 0, -32, 1, -28, 7, -28,
    'c', 12, -28, 13, -32, 13, -35,
    'c', 13, -37, 12, -42, 7, -42,
    'e',
   0xbb, # '»'
    0, 26, 28, -2, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -2,
    'l', 16, -15,
    'l', 0, -28,
    'm', 10, -28,
    'l', 26, -15,
    'l', 10, -2,
    'e',
   0xbc, # '¼'
    0, 36, 42, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 5, -39,
    'c', 7, -39, 9, -40, 10, -42,
    'l', 10, -21,
    'm', 4, 0,
    'l', 32, -42,
    'm', 30, 0,
    'l', 30, -21,
    'l', 20, -7,
    'l', 36, -7,
    'e',
   0xbd, # '½'
    0, 36, 42, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 23, -16,
    'c', 23, -17, 23, -21, 29, -21,
    'c', 35, -21, 35, -17, 35, -16,
    'c', 35, -15, 35, -13, 27, -5,
    'l', 22, 0,
    'l', 36, 0,
    'm', 5, -39,
    'c', 7, -39, 9, -40, 10, -42,
    'l', 10, -21,
    'm', 4, 0,
    'l', 32, -42,
    'e',
   0xbe, # '¾'
    0, 36, 42, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 2, -42,
    'l', 13, -42,
    'l', 7, -34,
    'c', 11, -34, 14, -34, 14, -28,
    'c', 14, -21, 8, -21, 7, -21,
    'c', 4, -21, 2, -22, 0, -25,
    'm', 4, 0,
    'l', 32, -42,
    'm', 29, 0,
    'l', 29, -21,
    'l', 19, -7,
    'l', 34, -7,
    'e',
   0xbf, # '¿'
    0, 24, 42, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -10,
    'c', 0, -8, 0, 0, 12, 0,
    'c', 24, 0, 24, -8, 24, -10,
    'c', 24, -13, 24, -18, 12, -22,
    'l', 12, -28,
    'm', 12, -38,
    'c', 9, -38, 9, -42, 12, -42,
    'c', 15, -42, 15, -38, 12, -38,
    'e',
   0xc0, # 'À'
    0, 32, 50, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, 0,
    'l', 16, -42,
    'l', 32, 0,
    'm', 6, -14,
    'l', 26, -14,
    'm', 22, -45,
    'l', 10, -50,
    'e',
   0xc1, # 'Á'
    0, 32, 50, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, 0,
    'l', 16, -42,
    'l', 32, 0,
    'm', 6, -14,
    'l', 26, -14,
    'm', 10, -45,
    'l', 22, -50,
    'e',
   0xc2, # 'Â'
    0, 32, 50, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, 0,
    'l', 16, -42,
    'l', 32, 0,
    'm', 6, -14,
    'l', 26, -14,
    'm', 10, -45,
    'l', 16, -50,
    'l', 22, -45,
    'e',
   0xc3, # 'Ã'
    0, 32, 50, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, 0,
    'l', 16, -42,
    'l', 32, 0,
    'm', 6, -14,
    'l', 26, -14,
    'm', 8, -46,
    'c', 14, -57, 18, -37, 24, -48,
    'e',
   0xc4, # 'Ä'
    0, 32, 49, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, 0,
    'l', 16, -42,
    'l', 32, 0,
    'm', 6, -14,
    'l', 26, -14,
    'm', 12, -45,
    'c', 11, -45, 10, -46, 10, -47,
    'c', 10, -48, 11, -49, 12, -49,
    'c', 13, -49, 14, -48, 14, -47,
    'c', 14, -46, 13, -45, 12, -45,
    'm', 20, -45,
    'c', 19, -45, 18, -46, 18, -47,
    'c', 18, -48, 19, -49, 20, -49,
    'c', 21, -49, 22, -48, 22, -47,
    'c', 22, -46, 21, -45, 20, -45,
    'e',
   0xc5, # 'Å'
    0, 32, 48, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 16, -42,
    'c', 14, -42, 13, -43, 13, -45,
    'c', 13, -47, 14, -48, 16, -48,
    'c', 18, -48, 19, -47, 19, -45,
    'c', 19, -43, 18, -42, 16, -42,
    'm', 0, 0,
    'l', 16, -42,
    'l', 32, 0,
    'm', 6, -14,
    'l', 26, -14,
    'e',
   0xc6, # 'Æ'
    0, 44, 42, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 18, -42,
    'l', 18, 0,
    'l', 44, 0,
    'm', 18, -22,
    'l', 34, -22,
    'm', 0, 0,
    'l', 16, -42,
    'l', 44, -42,
    'm', 6, -14,
    'l', 18, -14,
    'e',
   0xc7, # 'Ç'
    0, 30, 42, 6, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 30, -32,
    'c', 26, -42, 21, -42, 16, -42,
    'c', 2, -42, 0, -29, 0, -21,
    'c', 0, -13, 2, 0, 16, 0,
    'c', 21, 0, 26, 0, 30, -10,
    'm', 18, 0,
    'c', 20, 2, 18, 8, 11, 5,
    'e',
   0xc8, # 'È'
    0, 26, 50, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 26, -42,
    'l', 0, -42,
    'l', 0, 0,
    'l', 26, 0,
    'm', 0, -22,
    'l', 16, -22,
    'm', 19, -45,
    'l', 7, -50,
    'e',
   0xc9, # 'É'
    0, 26, 50, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 26, -42,
    'l', 0, -42,
    'l', 0, 0,
    'l', 26, 0,
    'm', 0, -22,
    'l', 16, -22,
    'm', 7, -45,
    'l', 19, -50,
    'e',
   0xca, # 'Ê'
    0, 26, 50, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 26, -42,
    'l', 0, -42,
    'l', 0, 0,
    'l', 26, 0,
    'm', 0, -22,
    'l', 16, -22,
    'm', 7, -45,
    'l', 13, -50,
    'l', 19, -45,
    'e',
   0xcb, # 'Ë'
    0, 26, 49, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 26, -42,
    'l', 0, -42,
    'l', 0, 0,
    'l', 26, 0,
    'm', 0, -22,
    'l', 16, -22,
    'm', 9, -45,
    'c', 8, -45, 7, -46, 7, -47,
    'c', 7, -48, 8, -49, 9, -49,
    'c', 10, -49, 11, -48, 11, -47,
    'c', 11, -46, 10, -45, 9, -45,
    'm', 17, -45,
    'c', 16, -45, 15, -46, 15, -47,
    'c', 15, -48, 16, -49, 17, -49,
    'c', 18, -49, 19, -48, 19, -47,
    'c', 19, -46, 18, -45, 17, -45,
    'e',
   0xcc, # 'Ì'
    -12, 0, 50, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 0, 0,
    'm', 0, -45,
    'l', -12, -50,
    'e',
   0xcd, # 'Í'
    0, 0, 50, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 0, 0,
    'm', 0, -45,
    'l', 12, -50,
    'e',
   0xce, # 'Î'
    0, 0, 50, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 0, 0,
    'm', -6, -45,
    'l', 0, -50,
    'l', 6, -45,
    'e',
   0xcf, # 'Ï'
    0, 0, 49, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 0, 0,
    'm', -4, -45,
    'c', -5, -45, -6, -46, -6, -47,
    'c', -6, -48, -5, -49, -4, -49,
    'c', -3, -49, -2, -48, -2, -47,
    'c', -2, -46, -3, -45, -4, -45,
    'm', 4, -45,
    'c', 3, -45, 2, -46, 2, -47,
    'c', 2, -48, 3, -49, 4, -49,
    'c', 5, -49, 6, -48, 6, -47,
    'c', 6, -46, 5, -45, 4, -45,
    'e',
   0xd0, # 'Ð'
    0, 37, 42, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 9, 0,
    'l', 9, -42,
    'l', 23, -42,
    'c', 42, -42, 42, 0, 23, 0,
    'l', 9, 0,
    'm', 0, -21,
    'l', 18, -21,
    'e',
   0xd1, # 'Ñ'
    0, 28, 50, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, 0,
    'l', 0, -42,
    'l', 28, 0,
    'l', 28, -42,
    'm', 6, -46,
    'c', 12, -57, 16, -37, 22, -48,
    'e',
   0xd2, # 'Ò'
    0, 32, 50, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 16, -42,
    'c', 2, -42, 0, -29, 0, -21,
    'c', 0, -13, 2, 0, 16, 0,
    'c', 30, 0, 32, -13, 32, -21,
    'c', 32, -29, 30, -42, 16, -42,
    'm', 22, -45,
    'l', 10, -50,
    'e',
   0xd3, # 'Ó'
    0, 32, 50, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 16, -42,
    'c', 2, -42, 0, -29, 0, -21,
    'c', 0, -13, 2, 0, 16, 0,
    'c', 30, 0, 32, -13, 32, -21,
    'c', 32, -29, 30, -42, 16, -42,
    'm', 10, -45,
    'l', 22, -50,
    'e',
   0xd4, # 'Ô'
    0, 32, 50, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 16, -42,
    'c', 2, -42, 0, -29, 0, -21,
    'c', 0, -13, 2, 0, 16, 0,
    'c', 30, 0, 32, -13, 32, -21,
    'c', 32, -29, 30, -42, 16, -42,
    'm', 10, -45,
    'l', 16, -50,
    'l', 22, -45,
    'e',
   0xd5, # 'Õ'
    0, 32, 50, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 16, -42,
    'c', 2, -42, 0, -29, 0, -21,
    'c', 0, -13, 2, 0, 16, 0,
    'c', 30, 0, 32, -13, 32, -21,
    'c', 32, -29, 30, -42, 16, -42,
    'm', 8, -46,
    'c', 14, -57, 18, -37, 24, -48,
    'e',
   0xd6, # 'Ö'
    0, 32, 49, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 16, -42,
    'c', 2, -42, 0, -29, 0, -21,
    'c', 0, -13, 2, 0, 16, 0,
    'c', 30, 0, 32, -13, 32, -21,
    'c', 32, -29, 30, -42, 16, -42,
    'm', 12, -45,
    'c', 11, -45, 10, -46, 10, -47,
    'c', 10, -48, 11, -49, 12, -49,
    'c', 13, -49, 14, -48, 14, -47,
    'c', 14, -46, 13, -45, 12, -45,
    'm', 20, -45,
    'c', 19, -45, 18, -46, 18, -47,
    'c', 18, -48, 19, -49, 20, -49,
    'c', 21, -49, 22, -48, 22, -47,
    'c', 22, -46, 21, -45, 20, -45,
    'e',
   0xd7, # '×'
    0, 27, 34, -7, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -34,
    'l', 27, -7,
    'm', 0, -7,
    'l', 27, -34,
    'e',
   0xd8, # 'Ø'
    0, 32, 44, 2, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 16, -42,
    'c', 2, -42, 0, -29, 0, -21,
    'c', 0, -13, 2, 0, 16, 0,
    'c', 30, 0, 32, -13, 32, -21,
    'c', 32, -29, 30, -42, 16, -42,
    'm', 34, -44,
    'l', -2, 2,
    'e',
   0xd9, # 'Ù'
    0, 28, 50, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 0, -12,
    'c', 0, 4, 28, 4, 28, -12,
    'l', 28, -42,
    'm', 20, -45,
    'l', 8, -50,
    'e',
   0xda, # 'Ú'
    0, 28, 50, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 0, -12,
    'c', 0, 4, 28, 4, 28, -12,
    'l', 28, -42,
    'm', 8, -45,
    'l', 20, -50,
    'e',
   0xdb, # 'Û'
    0, 28, 50, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 0, -12,
    'c', 0, 4, 28, 4, 28, -12,
    'l', 28, -42,
    'm', 8, -45,
    'l', 14, -50,
    'l', 20, -45,
    'e',
   0xdc, # 'Ü'
    0, 28, 49, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 0, -12,
    'c', 0, 4, 28, 4, 28, -12,
    'l', 28, -42,
    'm', 10, -45,
    'c', 9, -45, 8, -46, 8, -47,
    'c', 8, -48, 9, -49, 10, -49,
    'c', 11, -49, 12, -48, 12, -47,
    'c', 12, -46, 11, -45, 10, -45,
    'm', 18, -45,
    'c', 17, -45, 16, -46, 16, -47,
    'c', 16, -48, 17, -49, 18, -49,
    'c', 19, -49, 20, -48, 20, -47,
    'c', 20, -46, 19, -45, 18, -45,
    'e',
   0xdd, # 'Ý'
    0, 32, 50, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 16, -22,
    'l', 16, 0,
    'm', 32, -42,
    'l', 16, -22,
    'm', 10, -45,
    'l', 22, -50,
    'e',
   0xde, # 'Þ'
    0, 28, 42, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, 0,
    'l', 0, -42,
    'm', 0, -31,
    'l', 18, -31,
    'c', 32, -32, 32, -9, 18, -9,
    'l', 0, -9,
    'e',
   0xdf, # 'ß'
    0, 32, 42, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, 0,
    'l', 0, -36,
    'c', 0, -40, 5, -42, 12, -42,
    'c', 19, -42, 24, -40, 24, -36,
    'c', 19, -36, 16, -34, 16, -27,
    'c', 16, -16, 32, -21, 32, -9,
    'c', 32, -2, 24, 0, 19, 0,
    'c', 13, 0, 11, -1, 10, -2,
    'e',
   0xe0, # 'à'
    0, 24, 36, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 24, -28,
    'l', 24, 0,
    'm', 24, -22,
    'c', 21, -27, 18, -28, 13, -28,
    'c', 2, -28, 0, -19, 0, -14,
    'c', 0, -9, 2, 0, 13, 0,
    'c', 18, 0, 21, -1, 24, -6,
    'm', 18, -31,
    'l', 6, -36,
    'e',
   0xe1, # 'á'
    0, 24, 36, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 24, -28,
    'l', 24, 0,
    'm', 24, -22,
    'c', 21, -27, 18, -28, 13, -28,
    'c', 2, -28, 0, -19, 0, -14,
    'c', 0, -9, 2, 0, 13, 0,
    'c', 18, 0, 21, -1, 24, -6,
    'm', 6, -31,
    'l', 18, -36,
    'e',
   0xe2, # 'â'
    0, 24, 36, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 24, -28,
    'l', 24, 0,
    'm', 24, -22,
    'c', 21, -27, 18, -28, 13, -28,
    'c', 2, -28, 0, -19, 0, -14,
    'c', 0, -9, 2, 0, 13, 0,
    'c', 18, 0, 21, -1, 24, -6,
    'm', 6, -31,
    'l', 12, -36,
    'l', 18, -31,
    'e',
   0xe3, # 'ã'
    0, 24, 36, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 24, -28,
    'l', 24, 0,
    'm', 24, -22,
    'c', 21, -27, 18, -28, 13, -28,
    'c', 2, -28, 0, -19, 0, -14,
    'c', 0, -9, 2, 0, 13, 0,
    'c', 18, 0, 21, -1, 24, -6,
    'm', 4, -32,
    'c', 10, -43, 14, -23, 20, -34,
    'e',
   0xe4, # 'ä'
    0, 24, 35, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 24, -28,
    'l', 24, 0,
    'm', 24, -22,
    'c', 21, -27, 18, -28, 13, -28,
    'c', 2, -28, 0, -19, 0, -14,
    'c', 0, -9, 2, 0, 13, 0,
    'c', 18, 0, 21, -1, 24, -6,
    'm', 8, -31,
    'c', 7, -31, 6, -32, 6, -33,
    'c', 6, -34, 7, -35, 8, -35,
    'c', 9, -35, 10, -34, 10, -33,
    'c', 10, -32, 9, -31, 8, -31,
    'm', 16, -31,
    'c', 15, -31, 14, -32, 14, -33,
    'c', 14, -34, 15, -35, 16, -35,
    'c', 17, -35, 18, -34, 18, -33,
    'c', 18, -32, 17, -31, 16, -31,
    'e',
   0xe5, # 'å'
    0, 24, 37, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 12, -31,
    'c', 10, -31, 9, -32, 9, -34,
    'c', 9, -36, 10, -37, 12, -37,
    'c', 14, -37, 15, -36, 15, -34,
    'c', 15, -32, 14, -31, 12, -31,
    'm', 24, -28,
    'l', 24, 0,
    'm', 24, -22,
    'c', 21, -27, 18, -28, 13, -28,
    'c', 2, -28, 0, -19, 0, -14,
    'c', 0, -9, 2, 0, 13, 0,
    'c', 18, 0, 21, -1, 24, -6,
    'e',
   0xe6, # 'æ'
    0, 46, 28, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 22, -16,
    'l', 46, -16,
    'c', 46, -20, 46, -28, 35, -28,
    'c', 24, -28, 22, -19, 22, -14,
    'c', 22, -9, 24, 0, 35, 0,
    'c', 40, 0, 43, -2, 46, -6,
    'm', 24, -28,
    'l', 24, -22,
    'c', 21, -27, 18, -28, 13, -28,
    'c', 2, -28, 0, -19, 0, -14,
    'c', 0, -9, 2, 0, 13, 0,
    'c', 18, 0, 21, -1, 24, -6,
    'l', 24, 0,
    'e',
   0xe7, # 'ç'
    0, 24, 28, 6, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 24, -22,
    'c', 21, -26, 18, -28, 13, -28,
    'c', 2, -28, 0, -19, 0, -14,
    'c', 0, -9, 2, 0, 13, 0,
    'c', 18, 0, 21, -2, 24, -6,
    'm', 15, 0,
    'c', 17, 2, 15, 8, 8, 5,
    'e',
   0xe8, # 'è'
    0, 24, 36, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -16,
    'l', 24, -16,
    'c', 24, -20, 24, -28, 13, -28,
    'c', 2, -28, 0, -19, 0, -14,
    'c', 0, -9, 2, 0, 13, 0,
    'c', 18, 0, 21, -2, 24, -6,
    'm', 18, -31,
    'l', 6, -36,
    'e',
   0xe9, # 'é'
    0, 24, 36, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -16,
    'l', 24, -16,
    'c', 24, -20, 24, -28, 13, -28,
    'c', 2, -28, 0, -19, 0, -14,
    'c', 0, -9, 2, 0, 13, 0,
    'c', 18, 0, 21, -2, 24, -6,
    'm', 6, -31,
    'l', 18, -36,
    'e',
   0xea, # 'ê'
    0, 24, 36, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -16,
    'l', 24, -16,
    'c', 24, -20, 24, -28, 13, -28,
    'c', 2, -28, 0, -19, 0, -14,
    'c', 0, -9, 2, 0, 13, 0,
    'c', 18, 0, 21, -2, 24, -6,
    'm', 6, -31,
    'l', 12, -36,
    'l', 18, -31,
    'e',
   0xeb, # 'ë'
    0, 24, 35, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -16,
    'l', 24, -16,
    'c', 24, -20, 24, -28, 13, -28,
    'c', 2, -28, 0, -19, 0, -14,
    'c', 0, -9, 2, 0, 13, 0,
    'c', 18, 0, 21, -2, 24, -6,
    'm', 8, -31,
    'c', 7, -31, 6, -32, 6, -33,
    'c', 6, -34, 7, -35, 8, -35,
    'c', 9, -35, 10, -34, 10, -33,
    'c', 10, -32, 9, -31, 8, -31,
    'm', 16, -31,
    'c', 15, -31, 14, -32, 14, -33,
    'c', 14, -34, 15, -35, 16, -35,
    'c', 17, -35, 18, -34, 18, -33,
    'c', 18, -32, 17, -31, 16, -31,
    'e',
   0xec, # 'ì'
    0, 0, 36, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -28,
    'l', 0, 0,
    'm', 0, -31,
    'l', -12, -36,
    'e',
   0xed, # 'í'
    0, 0, 36, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -28,
    'l', 0, 0,
    'm', 0, -31,
    'l', 12, -36,
    'e',
   0xee, # 'î'
    0, 0, 36, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -28,
    'l', 0, 0,
    'm', -6, -31,
    'l', 0, -36,
    'l', 6, -31,
    'e',
   0xef, # 'ï'
    0, 0, 35, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -28,
    'l', 0, 0,
    'm', -4, -31,
    'c', -5, -31, -6, -32, -6, -33,
    'c', -6, -34, -5, -35, -4, -35,
    'c', -3, -35, -2, -34, -2, -33,
    'c', -2, -32, -3, -31, -4, -31,
    'm', 4, -31,
    'c', 3, -31, 2, -32, 2, -33,
    'c', 2, -34, 3, -35, 4, -35,
    'c', 5, -35, 6, -34, 6, -33,
    'c', 6, -32, 5, -31, 4, -31,
    'e',
   0xf0, # 'ð'
    0, 26, 42, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 21, -26,
    'c', 20, -27, 20, -28, 13, -28,
    'c', 2, -28, 0, -19, 0, -14,
    'c', 0, -9, 2, 0, 13, 0,
    'c', 24, 0, 26, -9, 26, -14,
    'c', 26, -21, 21, -26, 19, -28,
    'l', 5, -42,
    'm', 4, -31,
    'l', 17, -40,
    'e',
   0xf1, # 'ñ'
    0, 22, 36, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -28,
    'l', 0, 0,
    'm', 0, -20,
    'c', 4, -28, 22, -34, 22, -20,
    'l', 22, 0,
    'm', 3, -32,
    'c', 9, -43, 13, -23, 19, -34,
    'e',
   0xf2, # 'ò'
    0, 26, 36, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 13, -28,
    'c', 2, -28, 0, -19, 0, -14,
    'c', 0, -9, 2, 0, 13, 0,
    'c', 24, 0, 26, -9, 26, -14,
    'c', 26, -19, 24, -28, 13, -28,
    'm', 19, -31,
    'l', 7, -36,
    'e',
   0xf3, # 'ó'
    0, 26, 36, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 13, -28,
    'c', 2, -28, 0, -19, 0, -14,
    'c', 0, -9, 2, 0, 13, 0,
    'c', 24, 0, 26, -9, 26, -14,
    'c', 26, -19, 24, -28, 13, -28,
    'm', 7, -31,
    'l', 19, -36,
    'e',
   0xf4, # 'ô'
    0, 26, 36, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 13, -28,
    'c', 2, -28, 0, -19, 0, -14,
    'c', 0, -9, 2, 0, 13, 0,
    'c', 24, 0, 26, -9, 26, -14,
    'c', 26, -19, 24, -28, 13, -28,
    'm', 7, -31,
    'l', 13, -36,
    'l', 19, -31,
    'e',
   0xf5, # 'õ'
    0, 26, 36, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 13, -28,
    'c', 2, -28, 0, -19, 0, -14,
    'c', 0, -9, 2, 0, 13, 0,
    'c', 24, 0, 26, -9, 26, -14,
    'c', 26, -19, 24, -28, 13, -28,
    'm', 5, -32,
    'c', 11, -43, 15, -23, 21, -34,
    'e',
   0xf6, # 'ö'
    0, 26, 35, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 13, -28,
    'c', 2, -28, 0, -19, 0, -14,
    'c', 0, -9, 2, 0, 13, 0,
    'c', 24, 0, 26, -9, 26, -14,
    'c', 26, -19, 24, -28, 13, -28,
    'm', 9, -31,
    'c', 8, -31, 7, -32, 7, -33,
    'c', 7, -34, 8, -35, 9, -35,
    'c', 10, -35, 11, -34, 11, -33,
    'c', 11, -32, 10, -31, 9, -31,
    'm', 17, -31,
    'c', 16, -31, 15, -32, 15, -33,
    'c', 15, -34, 16, -35, 17, -35,
    'c', 18, -35, 19, -34, 19, -33,
    'c', 19, -32, 18, -31, 17, -31,
    'e',
   0xf7, # '÷'
    0, 36, 29, -7, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -18,
    'l', 36, -18,
    'm', 18, -11,
    'c', 17, -11, 16, -10, 16, -9,
    'c', 16, -8, 17, -7, 18, -7,
    'c', 19, -7, 20, -8, 20, -9,
    'c', 20, -10, 19, -11, 18, -11,
    'm', 18, -29,
    'c', 17, -29, 16, -28, 16, -27,
    'c', 16, -26, 17, -25, 18, -25,
    'c', 19, -25, 20, -26, 20, -27,
    'c', 20, -28, 19, -29, 18, -29,
    'e',
   0xf8, # 'ø'
    0, 26, 30, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 13, -28,
    'c', 2, -28, 0, -19, 0, -14,
    'c', 0, -9, 2, 0, 13, 0,
    'c', 24, 0, 26, -9, 26, -14,
    'c', 26, -19, 24, -28, 13, -28,
    'm', -2, 2,
    'l', 28, -30,
    'e',
   0xf9, # 'ù'
    0, 22, 36, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -28,
    'l', 0, -8,
    'c', 0, 6, 18, 0, 22, -8,
    'm', 22, -28,
    'l', 22, 0,
    'm', 17, -31,
    'l', 5, -36,
    'e',
   0xfa, # 'ú'
    0, 22, 36, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -28,
    'l', 0, -8,
    'c', 0, 6, 18, 0, 22, -8,
    'm', 22, -28,
    'l', 22, 0,
    'm', 5, -31,
    'l', 17, -36,
    'e',
   0xfb, # 'û'
    0, 22, 36, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -28,
    'l', 0, -8,
    'c', 0, 6, 18, 0, 22, -8,
    'm', 22, -28,
    'l', 22, 0,
    'm', 5, -31,
    'l', 11, -36,
    'l', 17, -31,
    'e',
   0xfc, # 'ü'
    0, 22, 35, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -28,
    'l', 0, -8,
    'c', 0, 6, 18, 0, 22, -8,
    'm', 22, -28,
    'l', 22, 0,
    'm', 7, -31,
    'c', 6, -31, 5, -32, 5, -33,
    'c', 5, -34, 6, -35, 7, -35,
    'c', 8, -35, 9, -34, 9, -33,
    'c', 9, -32, 8, -31, 7, -31,
    'm', 15, -31,
    'c', 14, -31, 13, -32, 13, -33,
    'c', 13, -34, 14, -35, 15, -35,
    'c', 16, -35, 17, -34, 17, -33,
    'c', 17, -32, 16, -31, 15, -31,
    'e',
   0xfd, # 'ý'
    0, 24, 36, 14, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -28,
    'l', 12, 0,
    'm', 24, -28,
    'l', 12, 0,
    'c', 6, 13, 0, 14, -2, 14,
    'm', 6, -31,
    'l', 18, -36,
    'e',
   0xfe, # 'þ'
    0, 24, 42, 14, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -42,
    'l', 0, 14,
    'm', 0, -22,
    'c', 3, -26, 6, -28, 11, -28,
    'c', 22, -28, 24, -19, 24, -14,
    'c', 24, -9, 22, 0, 11, 0,
    'c', 6, 0, 3, -2, 0, -6,
    'e',
   0xff, # 'ÿ'
    0, 24, 35, 14, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -28,
    'l', 12, 0,
    'm', 24, -28,
    'l', 12, 0,
    'c', 6, 13, 0, 14, -2, 14,
    'm', 8, -31,
    'c', 7, -31, 6, -32, 6, -33,
    'c', 6, -34, 7, -35, 8, -35,
    'c', 9, -35, 10, -34, 10, -33,
    'c', 10, -32, 9, -31, 8, -31,
    'm', 16, -31,
    'c', 15, -31, 14, -32, 14, -33,
    'c', 14, -34, 15, -35, 16, -35,
    'c', 17, -35, 18, -34, 18, -33,
    'c', 18, -32, 17, -31, 16, -31,
    'e',
   0x2010, # '‐'
    0, 16, 18, -18, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -18,
    'l', 16, -18,
    'e',
   0x2011, # '‑'
    0, 16, 18, -18, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -18,
    'l', 16, -18,
    'e',
   0x2012, # '‒'
    0, 30, 18, -18, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -18,
    'l', 30, -18,
    'e',
   0x2013, # '–'
    0, 22, 18, -18, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -18,
    'l', 22, -18,
    'e',
   0x2014, # '—'
    0, 32, 18, -18, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, 0,
    'm', 0, -18,
    'l', 32, -18,
    'e',
   0x2015, # '―'
    0, 40, 18, -18, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -18,
    'l', 40, -18,
    'e',
   0x2016, # '‖'
    0, 8, 42, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -42,
    'l', 0, 0,
    'm', 8, 0,
    'l', 8, -42,
    'e',
   0x2017, # '‗'
    0, 24, 8, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, 0,
    'l', 24, 0,
    'm', 24, -8,
    'l', 0, -8,
    'e',
   0x2018, # '‘'
    0, 4, 42, -30, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -32,
    'c', 0, -33, 1, -34, 2, -34,
    'c', 3, -34, 4, -33, 4, -32,
    'c', 4, -31, 3, -30, 2, -30,
    'c', 1, -30, 0, -31, 0, -32,
    'c', 0, -38, 2, -40, 4, -42,
    'e',
   0x2019, # '’'
    0, 4, 42, -30, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 4, -40,
    'c', 4, -39, 3, -38, 2, -38,
    'c', 1, -38, 0, -39, 0, -40,
    'c', 0, -41, 1, -42, 2, -42,
    'c', 3, -42, 4, -41, 4, -40,
    'c', 4, -34, 2, -32, 0, -30,
    'e',
   0x201a, # '‚'
    0, 4, 4, 8, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 4, -2,
    'c', 4, -1, 3, 0, 2, 0,
    'c', 1, 0, 0, -1, 0, -2,
    'c', 0, -3, 1, -4, 2, -4,
    'c', 3, -4, 4, -3, 4, -2,
    'c', 4, 4, 2, 6, 0, 8,
    'e',
   0x201b, # '‛'
    0, 4, 42, -30, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -40,
    'c', 0, -39, 1, -38, 2, -38,
    'c', 3, -38, 4, -39, 4, -40,
    'c', 4, -41, 3, -42, 2, -42,
    'c', 1, -42, 0, -41, 0, -40,
    'c', 0, -34, 2, -32, 4, -30,
    'e',
   0x201c, # '“'
    0, 11, 42, -30, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -32,
    'c', 0, -33, 1, -34, 2, -34,
    'c', 3, -34, 4, -33, 4, -32,
    'c', 4, -31, 3, -30, 2, -30,
    'c', 1, -30, 0, -31, 0, -32,
    'c', 0, -38, 2, -40, 4, -42,
    'm', 7, -32,
    'c', 7, -33, 8, -34, 9, -34,
    'c', 10, -34, 11, -33, 11, -32,
    'c', 11, -31, 10, -30, 9, -30,
    'c', 8, -30, 7, -31, 7, -32,
    'c', 7, -38, 9, -40, 11, -42,
    'e',
   0x201d, # '”'
    0, 11, 42, -30, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 11, -40,
    'c', 11, -39, 10, -38, 9, -38,
    'c', 8, -38, 7, -39, 7, -40,
    'c', 7, -41, 8, -42, 9, -42,
    'c', 10, -42, 11, -41, 11, -40,
    'c', 11, -34, 9, -32, 7, -30,
    'm', 4, -40,
    'c', 4, -39, 3, -38, 2, -38,
    'c', 1, -38, 0, -39, 0, -40,
    'c', 0, -41, 1, -42, 2, -42,
    'c', 3, -42, 4, -41, 4, -40,
    'c', 4, -34, 2, -32, 0, -30,
    'e',
   0x201e, # '„'
    0, 11, 4, 8, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 11, -2,
    'c', 11, -1, 10, 0, 9, 0,
    'c', 8, 0, 7, -1, 7, -2,
    'c', 7, -3, 8, -4, 9, -4,
    'c', 10, -4, 11, -3, 11, -2,
    'c', 11, 4, 9, 6, 7, 8,
    'm', 4, -2,
    'c', 4, -1, 3, 0, 2, 0,
    'c', 1, 0, 0, -1, 0, -2,
    'c', 0, -3, 1, -4, 2, -4,
    'c', 3, -4, 4, -3, 4, -2,
    'c', 4, 4, 2, 6, 0, 8,
    'e',
   0x201f, # '‟'
    0, 32, 42, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -40,
    'c', 0, -39, 1, -38, 2, -38,
    'c', 3, -38, 4, -39, 4, -40,
    'c', 4, -41, 3, -42, 2, -42,
    'c', 1, -42, 0, -41, 0, -40,
    'c', 0, -34, 2, -32, 4, -30,
    'm', 7, -40,
    'c', 7, -39, 8, -38, 9, -38,
    'c', 10, -38, 11, -39, 11, -40,
    'c', 11, -41, 10, -42, 9, -42,
    'c', 8, -42, 7, -41, 7, -40,
    'c', 7, -34, 9, -32, 11, -30,
    'e',
   0x2020, # '†'
    0, 24, 42, 14, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 12, -42,
    'l', 12, 14,
    'm', 0, -24,
    'l', 24, -24,
    'e',
   0x2021, # '‡'
    0, 24, 42, 14, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 12, -42,
    'l', 12, 14,
    'm', 0, -24,
    'l', 24, -24,
    'm', 0, -6,
    'l', 24, -6,
    'e',
   0x2022, # '•'
    0, 18, 24, -6, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -15,
    'c', 0, -21, 4, -24, 9, -24,
    'c', 14, -24, 18, -20, 18, -15,
    'c', 18, -10, 14, -6, 9, -6,
    'c', 4, -6, 0, -10, 0, -15,
    'm', 2, -19,
    'l', 2, -11,
    'm', 4, -9,
    'l', 4, -21,
    'm', 6, -22,
    'l', 6, -8,
    'm', 8, -7,
    'l', 8, -23,
    'm', 10, -23,
    'l', 10, -7,
    'm', 12, -8,
    'l', 12, -22,
    'm', 14, -21,
    'l', 14, -9,
    'm', 16, -11,
    'l', 16, -19,
    'e',
   0x2026, # '…'
    0, 24, 4, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 2, -4,
    'c', 1, -4, 0, -3, 0, -2,
    'c', 0, -1, 1, 0, 2, 0,
    'c', 3, 0, 4, -1, 4, -2,
    'c', 4, -3, 3, -4, 2, -4,
    'm', 12, -4,
    'c', 11, -4, 10, -3, 10, -2,
    'c', 10, -1, 11, 0, 12, 0,
    'c', 13, 0, 14, -1, 14, -2,
    'c', 14, -3, 13, -4, 12, -4,
    'm', 22, -4,
    'c', 21, -4, 20, -3, 20, -2,
    'c', 20, -1, 21, 0, 22, 0,
    'c', 23, 0, 24, -1, 24, -2,
    'c', 24, -3, 23, -4, 22, -4,
    'e',
   0x2030, # '‰'
    0, 54, 42, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
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
    'm', 46, -14,
    'c', 42, -14, 40, -11, 40, -6,
    'c', 40, -2, 42, 0, 46, 0,
    'c', 51, 0, 54, -2, 54, -8,
    'c', 54, -12, 52, -14, 48, -14,
    'l', 46, -14,
    'e',
   0x2039, # '‹'
    0, 16, 28, -2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 16, -28,
    'l', 0, -15,
    'l', 16, -2,
    'e',
   0x203a, # '›'
    0, 16, 28, -2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -28,
    'l', 16, -15,
    'l', 0, -2,
    'e',
   0x2070, # '⁰'
    0, 14, 42, -21, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 7, -42,
    'c', 5, -42, 0, -42, 0, -31,
    'c', 0, -21, 5, -21, 7, -21,
    'c', 10, -21, 14, -21, 14, -31,
    'c', 14, -42, 10, -42, 7, -42,
    'e',
   0x2071, # 'ⁱ'
    0, 2, 42, -20, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -41,
    'c', 0, -40, 2, -40, 2, -41,
    'c', 2, -42, 0, -42, 0, -41,
    'm', 1, -34,
    'l', 1, -20,
    'e',
   0x2074, # '⁴'
    0, 14, 42, -21, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 10, -21,
    'l', 10, -42,
    'l', 0, -28,
    'l', 14, -28,
    'e',
   0x2075, # '⁵'
    0, 14, 42, -21, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 12, -42,
    'l', 2, -42,
    'l', 1, -33,
    'c', 3, -34, 5, -35, 7, -35,
    'c', 8, -35, 14, -35, 14, -28,
    'c', 14, -21, 8, -21, 7, -21,
    'c', 5, -21, 2, -21, 0, -25,
    'e',
   0x2076, # '⁶'
    0, 14, 42, -21, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 12, -39,
    'c', 11, -41, 10, -42, 7, -42,
    'c', 5, -42, 0, -41, 0, -30,
    'c', 0, -21, 5, -21, 7, -21,
    'c', 9, -21, 13, -22, 13, -27,
    'c', 13, -30, 12, -34, 7, -34,
    'c', 5, -34, 1, -33, 0, -28,
    'e',
   0x2077, # '⁷'
    0, 14, 42, -21, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -42,
    'l', 14, -42,
    'l', 4, -21,
    'e',
   0x2078, # '⁸'
    0, 14, 42, -21, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 7, -42,
    'c', 3, -42, 1, -41, 1, -38,
    'c', 1, -30, 14, -37, 14, -26,
    'c', 14, -21, 9, -21, 7, -21,
    'c', 5, -21, 0, -21, 0, -26,
    'c', 0, -37, 13, -30, 13, -38,
    'c', 13, -41, 12, -42, 7, -42,
    'e',
   0x2079, # '⁹'
    0, 14, 42, -21, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 13, -35,
    'c', 13, -29, 7, -29, 7, -29,
    'c', 4, -29, 0, -30, 0, -35,
    'c', 0, -38, 2, -42, 7, -42,
    'c', 12, -42, 13, -37, 13, -32,
    'c', 13, -28, 12, -21, 6, -21,
    'c', 4, -21, 2, -22, 1, -24,
    'e',
   0x207a, # '⁺'
    0, 18, 39, -21, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 9, -39,
    'l', 9, -21,
    'm', 0, -30,
    'l', 18, -30,
    'e',
   0x207b, # '⁻'
    0, 18, 30, -30, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -30,
    'l', 18, -30,
    'e',
   0x207c, # '⁼'
    0, 18, 33, -27, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -33,
    'l', 18, -33,
    'm', 0, -27,
    'l', 18, -27,
    'e',
   0x207d, # '⁽'
    0, 7, 46, -14, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 7, -46,
    'c', -2, -37, -2, -23, 7, -14,
    'e',
   0x207e, # '⁾'
    0, 8, 46, -14, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -46,
    'c', 10, -38, 10, -22, 0, -14,
    'e',
   0x207f, # 'ⁿ'
    0, 11, 35, -21, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -35,
    'l', 0, -21,
    'm', 0, -31,
    'c', 2, -35, 11, -38, 11, -31,
    'l', 11, -21,
    'e',
   0x2080, # '₀'
    0, 14, 19, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 7, -19,
    'c', 5, -19, 0, -19, 0, -8,
    'c', 0, 2, 5, 2, 7, 2,
    'c', 10, 2, 14, 2, 14, -8,
    'c', 14, -19, 10, -19, 7, -19,
    'e',
   0x2081, # '₁'
    0, 14, 19, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 4, -15,
    'm', 4, -15,
    'c', 6, -15, 8, -17, 9, -19,
    'l', 9, 2,
    'e',
   0x2082, # '₂'
    0, 14, 19, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 1, -14,
    'c', 1, -15, 1, -19, 7, -19,
    'c', 13, -19, 13, -15, 13, -14,
    'c', 13, -13, 13, -10, 5, -3,
    'l', 0, 2,
    'l', 14, 2,
    'e',
   0x2083, # '₃'
    0, 14, 19, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 2, -19,
    'l', 13, -19,
    'l', 7, -11,
    'c', 11, -11, 14, -11, 14, -5,
    'c', 14, 2, 9, 2, 7, 2,
    'c', 4, 2, 2, 2, 0, -2,
    'e',
   0x2084, # '₄'
    0, 14, 19, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 10, 2,
    'l', 10, -19,
    'l', 0, -5,
    'l', 14, -5,
    'e',
   0x2085, # '₅'
    0, 14, 19, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 12, -19,
    'l', 2, -19,
    'l', 1, -10,
    'c', 3, -11, 5, -12, 7, -12,
    'c', 8, -12, 14, -12, 14, -5,
    'c', 14, 2, 8, 2, 7, 2,
    'c', 5, 2, 2, 2, 0, -2,
    'e',
   0x2086, # '₆'
    0, 14, 19, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 12, -16,
    'c', 11, -18, 10, -19, 7, -19,
    'c', 5, -19, 0, -18, 0, -7,
    'c', 0, 2, 5, 2, 7, 2,
    'c', 9, 2, 13, 1, 13, -4,
    'c', 13, -7, 12, -11, 7, -11,
    'c', 5, -11, 1, -10, 0, -5,
    'e',
   0x2087, # '₇'
    0, 14, 19, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -19,
    'l', 14, -19,
    'l', 4, 2,
    'e',
   0x2088, # '₈'
    0, 14, 19, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 7, -19,
    'c', 3, -19, 1, -18, 1, -15,
    'c', 1, -7, 14, -14, 14, -3,
    'c', 14, 2, 9, 2, 7, 2,
    'c', 5, 2, 0, 2, 0, -3,
    'c', 0, -14, 13, -7, 13, -15,
    'c', 13, -18, 12, -19, 7, -19,
    'e',
   0x2089, # '₉'
    0, 14, 19, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 13, -12,
    'c', 13, -6, 7, -6, 7, -6,
    'c', 4, -6, 0, -7, 0, -12,
    'c', 0, -15, 2, -19, 7, -19,
    'c', 12, -19, 13, -14, 13, -9,
    'c', 13, -5, 12, 2, 6, 2,
    'c', 4, 2, 2, 1, 1, -1,
    'e',
   0x208a, # '₊'
    0, 18, 16, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 9, -16,
    'l', 9, 2,
    'm', 0, -7,
    'l', 18, -7,
    'e',
   0x208b, # '₋'
    0, 18, 12, -12, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -12,
    'l', 18, -12,
    'e',
   0x208c, # '₌'
    0, 18, 10, -4, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -10,
    'l', 18, -10,
    'm', 0, -4,
    'l', 18, -4,
    'e',
   0x208d, # '₍'
    0, 7, 24, 8, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 7, -24,
    'c', -2, -15, -2, -1, 7, 8,
    'e',
   0x208e, # '₎'
    0, 8, 24, 8, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -24,
    'c', 10, -16, 10, 0, 0, 8,
    'e',
   0x2090, # 'ₐ'
    0, 12, 12, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 12, -12,
    'l', 12, 2,
    'm', 12, -9,
    'c', 11, -11, 9, -12, 7, -12,
    'c', 1, -12, 0, -7, 0, -5,
    'c', 0, -2, 1, 2, 7, 2,
    'c', 9, 2, 11, 2, 12, -1,
    'e',
   0x2091, # 'ₑ'
    0, 12, 12, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -6,
    'l', 12, -6,
    'c', 12, -8, 12, -12, 7, -12,
    'c', 1, -12, 0, -7, 0, -5,
    'c', 0, -2, 1, 2, 7, 2,
    'c', 9, 2, 11, 1, 12, -1,
    'e',
   0x2092, # 'ₒ'
    0, 13, 12, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 7, -12,
    'c', 1, -12, 0, -7, 0, -5,
    'c', 0, -2, 1, 2, 7, 2,
    'c', 12, 2, 13, -2, 13, -5,
    'c', 13, -7, 12, -12, 7, -12,
    'e',
   0x2093, # 'ₓ'
    0, 11, 12, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -12,
    'l', 11, 2,
    'm', 11, -12,
    'l', 0, 2,
    'e',
   0x2094, # 'ₔ'
    0, 12, 12, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 12, -4,
    'l', 0, -4,
    'c', 0, -2, 0, 2, 5, 2,
    'c', 11, 2, 12, -3, 12, -5,
    'c', 12, -8, 11, -12, 5, -12,
    'c', 3, -12, 1, -11, 0, -9,
    'e',
   0x2095, # 'ₕ'
    0, 11, 19, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -19,
    'l', 0, 2,
    'm', 0, -8,
    'c', 4, -14, 11, -13, 11, -8,
    'l', 11, 2,
    'e',
   0x2096, # 'ₖ'
    0, 11, 19, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -19,
    'l', 0, 2,
    'm', 10, -12,
    'l', 0, -2,
    'm', 4, -6,
    'l', 11, 2,
    'e',
   0x2097, # 'ₗ'
    0, 0, 19, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -19,
    'l', 0, 2,
    'e',
   0x2098, # 'ₘ'
    0, 22, 12, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -12,
    'l', 0, 2,
    'm', 0, -8,
    'c', 3, -12, 11, -14, 11, -8,
    'l', 11, 2,
    'm', 11, -8,
    'c', 14, -12, 22, -14, 22, -8,
    'l', 22, 2,
    'e',
   0x2099, # 'ₙ'
    0, 11, 12, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -12,
    'l', 0, 2,
    'm', 0, -8,
    'c', 2, -12, 11, -15, 11, -8,
    'l', 11, 2,
    'e',
   0x209a, # 'ₚ'
    0, 12, 12, 9, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -12,
    'l', 0, 9,
    'm', 0, -9,
    'c', 2, -11, 3, -12, 6, -12,
    'c', 11, -12, 12, -7, 12, -5,
    'c', 12, -2, 11, 2, 6, 2,
    'c', 3, 2, 2, 1, 0, -1,
    'e',
   0x209b, # 'ₛ'
    0, 11, 12, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 11, -9,
    'c', 11, -11, 8, -12, 6, -12,
    'c', 2, -12, 0, -11, 0, -9,
    'c', 0, -3, 11, -8, 11, -1,
    'c', 11, 2, 9, 2, 6, 2,
    'c', 3, 2, 0, 2, 0, -1,
    'e',
   0x209c, # 'ₜ'
    0, 8, 19, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 3, -19,
    'l', 3, -2,
    'c', 3, 1, 4, 2, 8, 2,
    'm', 0, -12,
    'l', 7, -12,
    'e',
   0x20ac, # '€'
    0, 32, 42, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 30, -32,
    'c', 26, -42, 21, -42, 16, -42,
    'c', 2, -42, 0, -29, 0, -21,
    'c', 0, -13, 2, 0, 16, 0,
    'c', 21, 0, 26, 0, 30, -10,
    'm', -3, -26,
    'l', 21, -26,
    'm', -3, -16,
    'l', 15, -16,
    'e',
)


charmap = (
Charmap(page = 0x0000,
        offsets = (
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
   28,   37,   88,  113,  152,  225,  325,  400,
  451,  474,  497,  529,  556,  607,  627,  671,
  690,  735,  762,  808,  853,  880,  932,  992,
 1015, 1076, 1136, 1211, 1293, 1315, 1342, 1364,
 1423, 1511, 1540, 1587, 1632, 1665, 1698, 1728,
 1777, 1809, 1827, 1856, 1887, 1909, 1937, 1962,
 2007, 2041, 2092, 2132, 2184, 2211, 2240, 2262,
 2290, 2315, 2344, 2370, 2396, 2415, 2441, 2463,
 2482, 2533, 2584, 2635, 2680, 2731, 2780, 2815,
 2881, 2914, 2951, 2996, 3027, 3045, 3092, 3125,
 3170, 3221, 3272, 3302, 3354, 3388, 3420, 3442,
 3470, 3495, 3528, 3554, 3599, 3617, 3662,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
 3687, 3696, 3747, 3799, 3838, 3905, 3948, 3972,
 4034, 4110, 4186, 4242, 4273, 4293, 4302, 4373,
 4390, 4433, 4464, 4510, 4555, 4575, 4618, 4657,
 4702, 4726, 4756, 4807, 4839, 4884, 4947, 5009,
 5067, 5102, 5137, 5175, 5214, 5305, 5365, 5409,
 5464, 5502, 5540, 5581, 5675, 5701, 5727, 5756,
 5838, 5877, 5913, 5964, 6015, 6069, 6124, 6231,
 6257, 6308, 6344, 6380, 6419, 6511, 6546, 6582,
 6644, 6701, 6758, 6818, 6879, 6992, 7074, 7159,
 7214, 7268, 7322, 7379, 7489, 7515, 7541, 7570,
 7652, 7713, 7754, 7803, 7852, 7904, 7957, 8062,
 8142, 8191, 8228, 8265, 8305, 8398, 8435, 8484,
        )),
Charmap(page = 0x0020,
        offsets = (
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
 8579, 8597, 8615, 8633, 8651, 8672, 8690, 8714,
 8738, 8788, 8838, 8888, 8938, 9026, 9114, 9202,
 9290, 9314, 9344,    1,    1,    1, 9435,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
 9540,    1,    1,    1,    1,    1,    1,    1,
    1, 9667, 9688,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
 9709, 9752,    1,    1, 9787, 9811, 9860, 9917,
 9938, 9995, 10052, 10076, 10094, 10118, 10140, 10162,
 10193, 10236, 10264, 10306, 10348, 10372, 10421, 10478,
 10499, 10556, 10613, 10637, 10655, 10679, 10701,    1,
 10723, 10772, 10818, 10861, 10885, 10931, 10962, 10992,
 11010, 11054, 11085, 11134, 11184,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1, 11215,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
        )),
)

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


def config_open(name: str, args):
    try:
        return open(name)
    except FileNotFoundError:
        return open(os.path.join(args.config_dir, name))


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

    def set_json(self, str: str):
        self.set_values(json.loads(str))

    def set_settings(self, settings: str):
        f = StringIO(settings)
        reader = csv.reader(f, delimiter=',')
        setting_values = []
        for row in reader:
            setting_values = row
        for i in range(min(len(setting_values), len(self.setting_values))):
            self.setting_values[i] = setting_values[i]

    def set_json_file(self, json_file: str, args):
        with config_open(json_file, args) as file:
            self.set_values(json.load(file))


class GCode(Draw):
    f: Any
    device: Device
    args: Any

    def __init__(self, f: Any, device: Device, args):
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
        if self.device.curve == "" or self.args.tesselate:
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
            text_width += text_height * self.args.sheer

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
            matrix = matrix.sheer(-self.args.sheer, 0)

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
    parser.add_argument('--tesselate', action='store_true',
                        help='Force tesselation of splines')
    parser.add_argument('--dump-offsets', action='store_true',
                        help='Dump glyph offsets to update font')
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
                        default='@SHARE_DIR@',
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

    return args
    

def finite_rects(args):
    return args.template is not None


def validate_template(template):
    if not isinstance(template, list):
        print('template is not an array', file=sys.stderr)
        return False
    for e in tuple(template):
        if not isinstance(e, list):
            print('template element %s is not an array' % (e,), file=sys.stderr)
            return False
        if len(e) != 4:
            print('template element %s does not contain four values' % (e,), file=sys.stderr)
            return False
        for v in tuple(e):
            if not isinstance(v, numbers.Number):
                print('template value %r is not a number' % (v,), file=sys.stderr)
                return False
    return True

def get_rect(args):
    if args.template is not None:
        with config_open(args.template, args) as file:
            rects = json.load(file)
            if not validate_template(rects):
                raise TypeError
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
        with open(name, "r", encoding='utf-8', errors='ignore') as f:
            for l in f.readlines():
                yield l.strip()

def main():
    args = Args()
    device = Device()
    if args.device:
        device.set_json_file(args.device, args)

    output = sys.stdout
    if args.output != '-':
        output = open(args.output, "w")

    if args.dump_offsets:
        pages = font.gen_pages()
        for page in pages:
            print('Charmap(page = 0x%04x,' % page)
            print('        offsets = (')
            offsets = font.gen_offsets(page)
            for start in range(0, len(offsets), 8):
                for step in range(8):
                    print(" %4d," % offsets[start + step], file=output, end='')
                print("", file=output)
            print('        )),')
        sys.exit(0)

    rect_gen = get_rect(args)
    line_gen = get_line(args)

    gcode = GCode(output, device, args)
    gcode.start()

    while True:
        try:
            rect = next(rect_gen)
            line = next(line_gen)
            print('%s "%s"' % (rect, line))
            gcode.text_into_rect(rect, line)
        except StopIteration:
            break

    gcode.stop()

main()
