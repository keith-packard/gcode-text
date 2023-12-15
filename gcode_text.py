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
    'm', 1, -42,
    'l', 1, -14,
    'm', 0, 0,
    'l', 0, -2,
    'l', 2, -2,
    'l', 2, 0,
    'l', 0, 0,
    'e',
   0x22, # '"'
    0, 8, 47, -37, 2, 3,
    0, 16, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -47,
    'l', 0, -37,
    'm', 8, -37,
    'l', 8, -47,
    'e',
   0x23, # '#'
    0, 30, 50, 14, 2, 5,
    0, 30, #  snap_x
    -24, -21, -15, -12, 0, #  snap_y
    'm', 15, -42,
    'l', 6, 0,
    'm', 26, -42,
    'l', 17, 0,
    'm', 2, -27,
    'l', 30, -27,
    'm', 0, -15,
    'l', 28, -15,
    'e',
   0x24, # '$'
    0, 28, 50, 8, 4, 4,
    0, 10, 18, 28, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 14, -48,
    'l', 14, 6,
    'm', 27, -40,
    'c', 22, -42, 0, -45, 0, -32,
    'c', 0, -21, 28, -23, 28, -11,
    'c', 28, 3, 5, 0, 0, -2,
    'e',
   0x25, # '%'
    0, 36, 42, 0, 4, 7,
    0, 14, 22, 36, #  snap_x
    -42, -38, -28, -21, -15, -14, 0, #  snap_y
    'm', 12, -31,
    'c', 12, -45, 0, -45, 0, -31,
    'c', 0, -17, 12, -17, 12, -31,
    'm', 28, -42,
    'l', 8, 0,
    'm', 36, -11,
    'c', 36, -25, 24, -25, 24, -11,
    'c', 24, 3, 36, 3, 36, -11,
    'e',
   0x26, # '&'
    0, 33, 42, 0, 4, 4,
    0, 10, 22, 40, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 30, -22,
    'c', 30, -13, 24, 0, 12, 0,
    'c', 7, 0, 0, -1, 0, -10,
    'c', 0, -24, 22, -21, 22, -34,
    'c', 22, -45, 5, -45, 5, -34,
    'c', 5, -30, 7, -26, 10, -23,
    'l', 33, 0,
    'e',
   0x27, # '''
    0, 4, 47, -37, 2, 3,
    0, 4, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -47,
    'l', 0, -37,
    'e',
   0x28, # '('
    0, 12, 44, 6, 2, 3,
    0, 14, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 12, -44,
    'c', -3, -30, -3, -8, 12, 6,
    'e',
   0x29, # ')'
    0, 12, 44, 6, 2, 3,
    0, 14, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -44,
    'c', 15, -30, 15, -8, 0, 6,
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
    -2, 2, 2, 8, 2, 3,
    0, 4, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 1, 0,
    'l', 0, 0,
    'l', 0, -2,
    'l', 2, -2,
    'c', 2, 2, 1, 6, -2, 8,
    'e',
   0x2d, # '-'
    0, 36, 18, -18, 2, 4,
    0, 36, #  snap_x
    -21, -18, -15, 0, #  snap_y
    'm', 0, -18,
    'l', 36, -18,
    'e',
   0x2e, # '.'
    0, 2, 2, 0, 2, 3,
    0, 4, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, 0,
    'l', 0, -2,
    'l', 2, -2,
    'l', 2, 0,
    'l', 0, 0,
    'e',
   0x2f, # '/'
    0, 26, 44, 6, 2, 3,
    0, 36, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 26, -44,
    'l', 0, 6,
    'e',
   0x30, # '0'
    0, 24, 42, 0, 2, 4,
    0, 28, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 24, -21,
    'c', 24, -49, 0, -49, 0, -21,
    'c', 0, 7, 24, 7, 24, -21,
    'e',
   0x31, # '1'
    0, 24, 42, 0, 3, 3,
    0, 17, 28, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 6, -36,
    'l', 14, -42,
    'l', 14, 0,
    'e',
   0x32, # '2'
    0, 24, 42, 0, 4, 4,
    0, 2, 26, 28, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 1, -40,
    'c', 4, -42, 24, -46, 23, -31,
    'c', 23, -24, 20, -20, 0, 0,
    'l', 24, 0,
    'e',
   0x33, # '3'
    0, 24, 42, 0, 2, 5,
    0, 28, #  snap_x
    -42, -26, -21, -15, 0, #  snap_y
    'm', 1, -40,
    'c', 26, -49, 33, -22, 6, -22,
    'c', 34, -22, 27, 8, 0, -2,
    'e',
   0x34, # '4'
    0, 24, 42, 0, 3, 4,
    0, 20, 30, #  snap_x
    -21, -15, -14, 0, #  snap_y
    'm', 19, 0,
    'l', 19, -42,
    'l', 0, -11,
    'l', 24, -11,
    'e',
   0x35, # '5'
    0, 24, 42, 0, 2, 5,
    0, 28, #  snap_x
    -42, -28, -21, -15, 0, #  snap_y
    'm', 21, -42,
    'l', 1, -42,
    'l', 0, -23,
    'c', 9, -27, 24, -24, 24, -13,
    'c', 24, 2, 4, 1, 0, -2,
    'e',
   0x36, # '6'
    0, 24, 42, 0, 2, 5,
    0, 26, #  snap_x
    -42, -26, -21, -15, 0, #  snap_y
    'm', 23, -41,
    'c', 19, -42, 0, -47, 0, -19,
    'c', 0, 8, 24, 2, 24, -12,
    'c', 24, -25, 4, -31, 1, -12,
    'e',
   0x37, # '7'
    0, 24, 42, 0, 2, 4,
    0, 28, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 24, -42,
    'l', 7, 0,
    'e',
   0x38, # '8'
    0, 24, 42, 0, 4, 4,
    0, 2, 26, 28, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 22, -33,
    'c', 22, -45, 2, -45, 2, -33,
    'c', 2, -21, 24, -22, 24, -10,
    'c', 24, 3, 0, 3, 0, -10,
    'c', 0, -22, 22, -21, 22, -33,
    'e',
   0x39, # '9'
    0, 24, 42, 0, 2, 5,
    0, 26, #  snap_x
    -42, -21, -16, -15, 0, #  snap_y
    'm', 1, -1,
    'c', 5, 0, 24, 5, 24, -23,
    'c', 24, -50, 0, -44, 0, -30,
    'c', 0, -17, 20, -11, 23, -30,
    'e',
   0x3a, # ':'
    0, 2, 28, 0, 2, 3,
    0, 4, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, 0,
    'l', 0, -2,
    'l', 2, -2,
    'l', 2, 0,
    'l', 0, 0,
    'm', 0, -26,
    'l', 0, -28,
    'l', 2, -28,
    'l', 2, -26,
    'l', 0, -26,
    'e',
   0x3b, # ';'
    -2, 2, 28, 8, 2, 3,
    0, 4, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 1, 0,
    'l', 0, 0,
    'l', 0, -2,
    'l', 2, -2,
    'c', 2, 2, 1, 6, -2, 8,
    'm', 0, -26,
    'l', 0, -28,
    'l', 2, -28,
    'l', 2, -26,
    'l', 0, -26,
    'e',
   0x3c, # '<'
    0, 36, 31, -5, 2, 3,
    0, 32, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 36, -31,
    'l', 0, -18,
    'l', 36, -5,
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
    0, 36, 31, -5, 2, 3,
    0, 32, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -31,
    'l', 36, -18,
    'l', 0, -5,
    'e',
   0x3f, # '?'
    0, 24, 42, 0, 3, 4,
    0, 12, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -40,
    'c', 5, -43, 24, -44, 24, -32,
    'c', 24, -24, 11, -22, 11, -12,
    'm', 10, 0,
    'l', 10, -2,
    'l', 12, -2,
    'l', 12, 0,
    'l', 10, 0,
    'e',
   0x40, # '@'
    0, 42, 42, 0, 1, 6,
    30, #  snap_x
    -42, -32, -21, -15, -10, 0, #  snap_y
    'm', 29, -26,
    'c', 26, -35, 12, -36, 10, -22,
    'c', 8, -8, 29, 0, 30, -32,
    'c', 23, -4, 42, -5, 42, -22,
    'c', 42, -49, 0, -49, 0, -22,
    'c', 0, 6, 31, 2, 36, -6,
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
    'l', 12, -42,
    'c', 32, -42, 31, -22, 10, -22,
    'm', 0, -22,
    'l', 10, -22,
    'c', 32, -22, 36, 0, 10, 0,
    'l', 0, 0,
    'e',
   0x43, # 'C'
    0, 30, 42, 0, 2, 4,
    0, 30, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 30, -40,
    'c', 18, -45, 0, -40, 0, -21,
    'c', 0, -2, 18, 3, 30, -2,
    'e',
   0x44, # 'D'
    0, 28, 42, 0, 2, 4,
    0, 28, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, 0,
    'l', 0, -42,
    'l', 10, -42,
    'c', 34, -42, 34, 0, 10, 0,
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
    'l', 24, -22,
    'e',
   0x46, # 'F'
    0, 26, 42, 0, 2, 5,
    0, 26, #  snap_x
    -42, -22, -21, -15, 0, #  snap_y
    'm', 26, -42,
    'l', 0, -42,
    'l', 0, 0,
    'm', 0, -22,
    'l', 24, -22,
    'e',
   0x47, # 'G'
    0, 30, 42, 0, 2, 5,
    0, 30, #  snap_x
    -42, -21, -16, -15, 0, #  snap_y
    'm', 30, -40,
    'c', 18, -45, 0, -40, 0, -21,
    'c', 0, -2, 18, 3, 30, -2,
    'l', 30, -20,
    'l', 21, -20,
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
    0, 4, 42, 0, 1, 3,
    0, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 2, -42,
    'l', 2, 0,
    'e',
   0x4a, # 'J'
    0, 20, 42, 0, 2, 3,
    0, 20, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 20, -42,
    'l', 20, -12,
    'c', 20, 2, 3, 0, 0, -1,
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
    'l', 16, -20,
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
    'm', 0, -21,
    'c', 0, -49, 32, -49, 32, -21,
    'c', 32, 7, 0, 7, 0, -21,
    'e',
   0x50, # 'P'
    0, 28, 42, 0, 2, 5,
    0, 28, #  snap_x
    -42, -21, -20, -15, 0, #  snap_y
    'm', 0, 0,
    'l', 0, -42,
    'l', 10, -42,
    'c', 34, -42, 34, -20, 10, -20,
    'l', 0, -20,
    'e',
   0x51, # 'Q'
    0, 32, 42, 4, 2, 4,
    0, 32, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 32, -21,
    'c', 32, -49, 0, -49, 0, -21,
    'c', 0, 7, 32, 7, 32, -21,
    'm', 19, -11,
    'l', 32, 4,
    'e',
   0x52, # 'R'
    0, 28, 42, 0, 2, 5,
    0, 28, #  snap_x
    -42, -22, -21, -15, 0, #  snap_y
    'm', 0, 0,
    'l', 0, -42,
    'l', 10, -42,
    'c', 29, -42, 29, -22, 10, -22,
    'l', 0, -22,
    'm', 14, -22,
    'l', 28, 0,
    'e',
   0x53, # 'S'
    0, 28, 42, 0, 2, 4,
    0, 28, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 27, -40,
    'c', 22, -42, 0, -45, 0, -32,
    'c', 0, -21, 28, -23, 28, -11,
    'c', 28, 3, 5, 0, 0, -2,
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
    'l', 0, -18,
    'c', 0, 6, 28, 6, 28, -18,
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
    'l', 12, 0,
    'l', 20, -28,
    'l', 28, 0,
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
    'l', 16, -19,
    'l', 16, 0,
    'm', 32, -42,
    'l', 16, -19,
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
    0, 26, 44, 6, 2, 3,
    0, 36, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -44,
    'l', 26, 6,
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
    0, 32, 42, -26, 2, 3,
    0, 32, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -26,
    'l', 16, -42,
    'l', 32, -26,
    'e',
   0x5f, # '_'
    0, 36, 0, 0, 2, 3,
    0, 36, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, 0,
    'l', 36, 0,
    'e',
   0x60, # '`'
    0, 6, 46, -38, 2, 3,
    0, 4, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 6, -38,
    'l', 0, -46,
    'e',
   0x61, # 'a'
    0, 24, 28, 0, 2, 4,
    0, 24, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 2, -26,
    'c', 11, -30, 24, -29, 24, -17,
    'l', 24, 0,
    'm', 24, -15,
    'c', 14, -16, 0, -16, 0, -7,
    'c', 0, 4, 24, 2, 24, -13,
    'e',
   0x62, # 'b'
    0, 24, 42, 0, 2, 4,
    0, 24, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 0, 0,
    'm', 0, -14,
    'c', 0, -32, 24, -32, 24, -14,
    'c', 24, 4, 0, 4, 0, -14,
    'e',
   0x63, # 'c'
    0, 19, 28, 0, 2, 4,
    0, 24, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 19, -27,
    'c', 14, -29, 0, -29, 0, -14,
    'c', 0, 0, 14, 1, 19, -1,
    'e',
   0x64, # 'd'
    0, 24, 42, 0, 2, 4,
    0, 24, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 24, -42,
    'l', 24, 0,
    'm', 24, -14,
    'c', 24, -32, 0, -32, 0, -14,
    'c', 0, 4, 24, 4, 24, -14,
    'e',
   0x65, # 'e'
    0, 24, 28, 0, 2, 5,
    0, 24, #  snap_x
    -28, -21, -16, -15, 0, #  snap_y
    'm', 0, -15,
    'l', 24, -15,
    'c', 24, -32, 0, -32, 0, -15,
    'c', 0, 0, 14, 2, 24, -2,
    'e',
   0x66, # 'f'
    0, 14, 42, 0, 3, 5,
    0, 6, 16, #  snap_x
    -42, -28, -21, -15, 0, #  snap_y
    'm', 16, -41,
    'c', 10, -43, 6, -40, 6, -33,
    'l', 6, 0,
    'm', 0, -27,
    'l', 14, -27,
    'e',
   0x67, # 'g'
    0, 24, 28, 14, 2, 5,
    0, 24, #  snap_x
    -28, -21, -15, 0, 14, #  snap_y
    'm', 24, -28,
    'l', 24, 0,
    'c', 24, 17, 8, 15, 2, 12,
    'm', 24, -14,
    'c', 24, -32, 0, -32, 0, -14,
    'c', 0, 4, 24, 4, 24, -14,
    'e',
   0x68, # 'h'
    0, 24, 42, 0, 2, 4,
    0, 22, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 0, 0,
    'm', 0, -16,
    'c', 4, -30, 24, -33, 24, -16,
    'l', 24, 0,
    'e',
   0x69, # 'i'
    0, 4, 41, 0, 3, 3,
    0, 2, 4, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 2, -28,
    'l', 2, 0,
    'm', 1, -39,
    'l', 1, -41,
    'l', 3, -41,
    'l', 3, -39,
    'l', 1, -39,
    'e',
   0x6a, # 'j'
    -8, 4, 41, 14, 3, 4,
    0, 2, 4, #  snap_x
    -21, -15, 0, 14, #  snap_y
    'm', 2, -28,
    'l', 2, 5,
    'c', 2, 12, -2, 15, -8, 13,
    'm', 1, -39,
    'l', 1, -41,
    'l', 3, -41,
    'l', 3, -39,
    'l', 1, -39,
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
    0, 4, 42, 0, 1, 3,
    0, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 2, -42,
    'l', 2, 0,
    'e',
   0x6d, # 'm'
    0, 40, 28, 0, 3, 4,
    0, 22, 44, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 0, -28,
    'l', 0, 0,
    'm', 0, -16,
    'c', 2, -29, 20, -34, 20, -16,
    'l', 20, 0,
    'm', 20, -16,
    'c', 22, -29, 40, -34, 40, -16,
    'l', 40, 0,
    'e',
   0x6e, # 'n'
    0, 24, 28, 0, 2, 4,
    0, 22, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 0, -28,
    'l', 0, 0,
    'm', 0, -16,
    'c', 4, -30, 24, -33, 24, -16,
    'l', 24, 0,
    'e',
   0x6f, # 'o'
    0, 24, 28, 0, 2, 4,
    0, 26, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 24, -14,
    'c', 24, -33, 0, -33, 0, -14,
    'c', 0, 5, 24, 5, 24, -14,
    'e',
   0x70, # 'p'
    0, 24, 28, 14, 2, 4,
    0, 24, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 0, 14,
    'l', 0, -28,
    'm', 0, -14,
    'c', 0, 4, 24, 4, 24, -14,
    'c', 24, -32, 0, -32, 0, -14,
    'e',
   0x71, # 'q'
    0, 24, 28, 14, 2, 4,
    0, 24, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 24, 14,
    'l', 24, -28,
    'm', 24, -14,
    'c', 24, 4, 0, 4, 0, -14,
    'c', 0, -32, 24, -32, 24, -14,
    'e',
   0x72, # 'r'
    0, 16, 28, 0, 2, 4,
    0, 16, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 0, -28,
    'l', 0, 0,
    'm', 0, -12,
    'c', 3, -23, 7, -28, 16, -28,
    'e',
   0x73, # 's'
    0, 22, 28, 0, 2, 4,
    0, 22, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 20, -27,
    'c', 17, -28, 0, -30, 0, -21,
    'c', 0, -15, 22, -14, 22, -7,
    'c', 22, 2, 7, 0, 2, -1,
    'e',
   0x74, # 't'
    0, 16, 42, 0, 3, 4,
    0, 6, 16, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 7, -42,
    'l', 7, -10,
    'c', 7, -2, 10, 1, 16, -1,
    'm', 0, -31,
    'l', 14, -31,
    'e',
   0x75, # 'u'
    0, 24, 28, 0, 2, 3,
    0, 22, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 24, 0,
    'l', 24, -28,
    'm', 24, -12,
    'c', 20, 2, 0, 5, 0, -12,
    'l', 0, -28,
    'e',
   0x76, # 'v'
    0, 22, 28, 0, 2, 3,
    0, 24, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -28,
    'l', 11, 0,
    'l', 22, -28,
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
    'c', 6, 14, 4, 15, -2, 13,
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
    0, 8, 44, 0, 3, 5,
    0, 6, 16, #  snap_x
    -44, -24, -21, -15, 0, #  snap_y
    'm', 8, -44,
    'c', 5, -44, 4, -43, 4, -36,
    'c', 4, -21, 2, -22, 0, -22,
    'c', 2, -22, 4, -23, 4, -8,
    'c', 4, -1, 5, 0, 8, 0,
    'e',
   0x7c, # '|'
    0, 4, 44, 6, 1, 3,
    0, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 2, -44,
    'l', 2, 6,
    'e',
   0x7d, # '}'
    0, 8, 44, 0, 3, 5,
    0, 10, 16, #  snap_x
    -44, -24, -21, -15, 0, #  snap_y
    'm', 0, -44,
    'c', 3, -44, 4, -43, 4, -36,
    'c', 4, -21, 6, -22, 8, -22,
    'c', 6, -22, 4, -23, 4, -8,
    'c', 4, -1, 3, 0, 0, 0,
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
    'm', 1, 0,
    'l', 1, -28,
    'm', 0, -42,
    'l', 0, -40,
    'l', 2, -40,
    'l', 2, -42,
    'l', 0, -42,
    'e',
   0xa2, # '¢'
    0, 19, 32, 4, 3, 4,
    0, 13, 24, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 17, -32,
    'l', 4, 4,
    'm', 19, -27,
    'c', 14, -29, 0, -29, 0, -14,
    'c', 0, 0, 14, 1, 19, -1,
    'e',
   0xa3, # '£'
    0, 20, 39, 0, 3, 3,
    0, 6, 20, #  snap_x
    -42, -16, 0, #  snap_y
    'm', 20, -38,
    'c', 12, -40, 6, -37, 5, -25,
    'l', 5, 0,
    'm', 0, -21,
    'l', 15, -21,
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
    'm', 4, -20,
    'l', 28, -20,
    'm', 4, -10,
    'l', 28, -10,
    'm', 0, -42,
    'l', 16, -19,
    'l', 16, 0,
    'm', 32, -42,
    'l', 16, -19,
    'e',
   0xa6, # '¦'
    0, 4, 44, 6, 1, 3,
    0, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 2, -44,
    'l', 2, -24,
    'm', 2, -14,
    'l', 2, 6,
    'e',
   0xa7, # '§'
    0, 19, 43, 0, 4, 2,
    0, 3, 22, 25, #  snap_x
    -43, 0, #  snap_y
    'm', 5, -30,
    'c', 1, -27, 0, -26, 0, -22,
    'c', 0, -13, 19, -17, 19, -7,
    'c', 19, -3, 13, 2, 0, -1,
    'm', 14, -14,
    'c', 17, -16, 19, -17, 19, -21,
    'c', 19, -30, 0, -28, 0, -36,
    'c', 0, -40, 6, -45, 17, -42,
    'e',
   0xa8, # '¨'
    0, 12, 42, -40, 4, 2,
    0, 4, 8, 12, #  snap_x
    -38, -42, #  snap_y
    'm', 0, -40,
    'l', 0, -42,
    'l', 2, -42,
    'l', 2, -40,
    'l', 0, -40,
    'm', 10, -40,
    'l', 10, -42,
    'l', 12, -42,
    'l', 12, -40,
    'l', 10, -40,
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
    'm', 22, -20,
    'c', 21, -22, 18, -24, 15, -24,
    'c', 10, -24, 7, -20, 7, -15,
    'c', 7, -10, 10, -6, 15, -6,
    'c', 19, -6, 21, -8, 22, -10,
    'e',
   0xaa, # 'ª'
    0, 12, 42, -24, 2, 3,
    0, 16, #  snap_x
    -42, -23, -20, #  snap_y
    'm', 1, -24,
    'l', 12, -24,
    'm', 1, -41,
    'c', 6, -43, 12, -42, 12, -36,
    'l', 12, -28,
    'm', 12, -35,
    'c', 7, -36, 0, -36, 0, -31,
    'c', 0, -26, 12, -27, 12, -34,
    'e',
   0xab, # '«'
    0, 19, 28, -2, 2, 3,
    0, 28, #  snap_x
    -28, -15, -2, #  snap_y
    'm', 7, -28,
    'l', 0, -15,
    'l', 7, -2,
    'm', 19, -28,
    'l', 12, -15,
    'l', 19, -2,
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
    'm', 10, -6,
    'l', 10, -24,
    'l', 14, -24,
    'c', 22, -24, 22, -15, 14, -15,
    'l', 10, -15,
    'm', 16, -15,
    'l', 22, -6,
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
    0, 12, 42, -21, 4, 4,
    0, 2, 26, 28, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 1, -41,
    'c', 2, -42, 12, -44, 12, -36,
    'c', 12, -33, 10, -31, 0, -21,
    'l', 12, -21,
    'e',
   0xb3, # '³'
    0, 12, 42, -21, 2, 5,
    0, 28, #  snap_x
    -42, -26, -21, -15, 0, #  snap_y
    'm', 1, -41,
    'c', 13, -45, 17, -32, 3, -32,
    'c', 17, -32, 14, -17, 0, -22,
    'e',
   0xb4, # '´'
    0, 6, 42, -34, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -34,
    'l', 6, -42,
    'e',
   0xb5, # 'µ'
    0, 26, 28, 14, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 26, 0,
    'c', 25, -1, 24, -2, 24, -8,
    'l', 24, -28,
    'm', 24, -12,
    'c', 20, 2, 0, 5, 0, -12,
    'l', 0, -28,
    'l', 0, 14,
    'e',
   0xb6, # '¶'
    0, 27, 42, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 15, -42,
    'l', 15, 0,
    'm', 27, 0,
    'l', 27, -42,
    'l', 11, -42,
    'c', -4, -42, -4, -25, 11, -26,
    'l', 15, -26,
    'e',
   0xb7, # '·'
    0, 4, 22, -20, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -20,
    'l', 0, -22,
    'l', 2, -22,
    'l', 2, -20,
    'l', 0, -20,
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
    'c', 6, -38, 8, -40, 9, -42,
    'l', 9, -21,
    'e',
   0xba, # 'º'
    0, 12, 42, -24, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -24,
    'l', 12, -24,
    'm', 12, -35,
    'c', 12, -44, 0, -44, 0, -35,
    'c', 0, -25, 12, -25, 12, -35,
    'e',
   0xbb, # '»'
    0, 19, 28, -2, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 12, -28,
    'l', 19, -15,
    'l', 12, -2,
    'm', 0, -28,
    'l', 7, -15,
    'l', 0, -2,
    'e',
   0xbc, # '¼'
    0, 36, 42, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 6, 0,
    'l', 27, -42,
    'm', 2, -38,
    'c', 4, -38, 6, -40, 7, -42,
    'l', 7, -21,
    'm', 34, 0,
    'l', 34, -21,
    'l', 24, -5,
    'l', 36, -5,
    'e',
   0xbd, # '½'
    0, 36, 42, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 6, 0,
    'l', 27, -42,
    'm', 2, -38,
    'c', 4, -38, 6, -40, 7, -42,
    'l', 7, -21,
    'm', 25, -20,
    'c', 26, -21, 36, -23, 36, -15,
    'c', 36, -12, 34, -10, 24, 0,
    'l', 36, 0,
    'e',
   0xbe, # '¾'
    0, 36, 42, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 1, -41,
    'c', 13, -45, 17, -32, 3, -32,
    'c', 17, -32, 14, -17, 0, -22,
    'm', 6, 0,
    'l', 27, -42,
    'm', 34, 0,
    'l', 34, -21,
    'l', 24, -5,
    'l', 36, -5,
    'e',
   0xbf, # '¿'
    0, 24, 42, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 24, -2,
    'c', 19, 1, 0, 2, 0, -10,
    'c', 0, -18, 13, -20, 13, -30,
    'm', 14, -42,
    'l', 14, -40,
    'l', 12, -40,
    'l', 12, -42,
    'l', 14, -42,
    'e',
   0xc0, # 'À'
    0, 32, 55, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, 0,
    'l', 16, -42,
    'l', 32, 0,
    'm', 6, -14,
    'l', 26, -14,
    'm', 19, -47,
    'l', 13, -55,
    'e',
   0xc1, # 'Á'
    0, 32, 55, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, 0,
    'l', 16, -42,
    'l', 32, 0,
    'm', 6, -14,
    'l', 26, -14,
    'm', 13, -47,
    'l', 19, -55,
    'e',
   0xc2, # 'Â'
    0, 32, 55, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, 0,
    'l', 16, -42,
    'l', 32, 0,
    'm', 6, -14,
    'l', 26, -14,
    'm', 11, -47,
    'l', 16, -55,
    'l', 21, -47,
    'e',
   0xc3, # 'Ã'
    0, 32, 53, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, 0,
    'l', 16, -42,
    'l', 32, 0,
    'm', 6, -14,
    'l', 26, -14,
    'm', 8, -49,
    'c', 14, -62, 18, -38, 24, -51,
    'e',
   0xc4, # 'Ä'
    0, 32, 51, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, 0,
    'l', 16, -42,
    'l', 32, 0,
    'm', 6, -14,
    'l', 26, -14,
    'm', 10, -49,
    'l', 10, -51,
    'l', 12, -51,
    'l', 12, -49,
    'l', 10, -49,
    'm', 20, -49,
    'l', 20, -51,
    'l', 22, -51,
    'l', 22, -49,
    'l', 20, -49,
    'e',
   0xc5, # 'Å'
    0, 32, 54, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 16, -46,
    'c', 14, -46, 12, -48, 12, -50,
    'c', 12, -52, 14, -54, 16, -54,
    'c', 18, -54, 20, -52, 20, -50,
    'c', 20, -48, 18, -46, 16, -46,
    'm', 0, 0,
    'l', 16, -42,
    'l', 32, 0,
    'm', 6, -14,
    'l', 26, -14,
    'e',
   0xc6, # 'Æ'
    0, 34, 42, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, 0,
    'l', 16, -42,
    'l', 32, -42,
    'm', 20, -42,
    'l', 22, 0,
    'l', 34, 0,
    'm', 31, -22,
    'l', 21, -22,
    'm', 21, -14,
    'l', 6, -14,
    'e',
   0xc7, # 'Ç'
    0, 30, 42, 6, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 18, 0,
    'c', 20, 2, 18, 8, 11, 5,
    'm', 30, -40,
    'c', 18, -45, 0, -40, 0, -21,
    'c', 0, -2, 18, 3, 30, -2,
    'e',
   0xc8, # 'È'
    0, 26, 55, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 16, -47,
    'l', 10, -55,
    'm', 26, -42,
    'l', 0, -42,
    'l', 0, 0,
    'l', 26, 0,
    'm', 0, -22,
    'l', 24, -22,
    'e',
   0xc9, # 'É'
    0, 26, 55, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 26, -42,
    'l', 0, -42,
    'l', 0, 0,
    'l', 26, 0,
    'm', 0, -22,
    'l', 24, -22,
    'm', 10, -47,
    'l', 16, -55,
    'e',
   0xca, # 'Ê'
    0, 26, 55, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 26, -42,
    'l', 0, -42,
    'l', 0, 0,
    'l', 26, 0,
    'm', 0, -22,
    'l', 24, -22,
    'm', 8, -47,
    'l', 13, -55,
    'l', 18, -47,
    'e',
   0xcb, # 'Ë'
    0, 26, 51, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 26, -42,
    'l', 0, -42,
    'l', 0, 0,
    'l', 26, 0,
    'm', 0, -22,
    'l', 24, -22,
    'm', 6, -49,
    'l', 6, -51,
    'l', 8, -51,
    'l', 8, -49,
    'l', 6, -49,
    'm', 16, -49,
    'l', 16, -51,
    'l', 18, -51,
    'l', 18, -49,
    'l', 16, -49,
    'e',
   0xcc, # 'Ì'
    -4, 4, 55, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 2, -42,
    'l', 2, 0,
    'm', 2, -47,
    'l', -4, -55,
    'e',
   0xcd, # 'Í'
    0, 4, 55, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 2, -42,
    'l', 2, 0,
    'm', 2, -47,
    'l', 8, -55,
    'e',
   0xce, # 'Î'
    -3, 4, 55, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 2, -42,
    'l', 2, 0,
    'm', -3, -47,
    'l', 2, -55,
    'l', 7, -47,
    'e',
   0xcf, # 'Ï'
    -4, 4, 51, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 2, -42,
    'l', 2, 0,
    'm', -4, -49,
    'l', -4, -51,
    'l', -2, -51,
    'l', -2, -49,
    'l', -4, -49,
    'm', 6, -49,
    'l', 6, -51,
    'l', 8, -51,
    'l', 8, -49,
    'l', 6, -49,
    'e',
   0xd0, # 'Ð'
    -4, 28, 42, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, 0,
    'l', 0, -42,
    'l', 10, -42,
    'c', 34, -42, 34, 0, 10, 0,
    'l', 0, 0,
    'm', -4, -21,
    'l', 10, -21,
    'e',
   0xd1, # 'Ñ'
    0, 28, 53, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, 0,
    'l', 0, -42,
    'l', 28, 0,
    'l', 28, -42,
    'm', 6, -49,
    'c', 12, -62, 16, -38, 22, -51,
    'e',
   0xd2, # 'Ò'
    0, 32, 55, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -21,
    'c', 0, -49, 32, -49, 32, -21,
    'c', 32, 7, 0, 7, 0, -21,
    'm', 19, -47,
    'l', 13, -55,
    'e',
   0xd3, # 'Ó'
    0, 32, 55, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -21,
    'c', 0, -49, 32, -49, 32, -21,
    'c', 32, 7, 0, 7, 0, -21,
    'm', 13, -47,
    'l', 19, -55,
    'e',
   0xd4, # 'Ô'
    0, 32, 55, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -21,
    'c', 0, -49, 32, -49, 32, -21,
    'c', 32, 7, 0, 7, 0, -21,
    'm', 11, -47,
    'l', 16, -55,
    'l', 21, -47,
    'e',
   0xd5, # 'Õ'
    0, 32, 53, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -21,
    'c', 0, -49, 32, -49, 32, -21,
    'c', 32, 7, 0, 7, 0, -21,
    'm', 8, -49,
    'c', 14, -62, 18, -38, 24, -51,
    'e',
   0xd6, # 'Ö'
    0, 32, 51, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -21,
    'c', 0, -49, 32, -49, 32, -21,
    'c', 32, 7, 0, 7, 0, -21,
    'm', 10, -49,
    'l', 10, -51,
    'l', 12, -51,
    'l', 12, -49,
    'l', 10, -49,
    'm', 20, -49,
    'l', 20, -51,
    'l', 22, -51,
    'l', 22, -49,
    'l', 20, -49,
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
    'm', 0, -21,
    'c', 0, -49, 32, -49, 32, -21,
    'c', 32, 7, 0, 7, 0, -21,
    'm', 1, 2,
    'l', 31, -44,
    'e',
   0xd9, # 'Ù'
    0, 28, 55, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 0, -18,
    'c', 0, 6, 28, 6, 28, -18,
    'l', 28, -42,
    'm', 17, -47,
    'l', 11, -55,
    'e',
   0xda, # 'Ú'
    0, 28, 55, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 0, -18,
    'c', 0, 6, 28, 6, 28, -18,
    'l', 28, -42,
    'm', 13, -47,
    'l', 19, -55,
    'e',
   0xdb, # 'Û'
    0, 28, 55, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 0, -18,
    'c', 0, 6, 28, 6, 28, -18,
    'l', 28, -42,
    'm', 9, -47,
    'l', 14, -55,
    'l', 19, -47,
    'e',
   0xdc, # 'Ü'
    0, 28, 51, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 0, -18,
    'c', 0, 6, 28, 6, 28, -18,
    'l', 28, -42,
    'm', 8, -49,
    'l', 8, -51,
    'l', 10, -51,
    'l', 10, -49,
    'l', 8, -49,
    'm', 18, -49,
    'l', 18, -51,
    'l', 20, -51,
    'l', 20, -49,
    'l', 18, -49,
    'e',
   0xdd, # 'Ý'
    0, 32, 55, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -42,
    'l', 16, -19,
    'l', 16, 0,
    'm', 32, -42,
    'l', 16, -19,
    'm', 13, -47,
    'l', 19, -55,
    'e',
   0xde, # 'Þ'
    0, 24, 42, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, 0,
    'l', 0, -42,
    'm', 0, -21,
    'c', 0, -3, 24, -3, 24, -21,
    'c', 24, -39, 0, -39, 0, -21,
    'e',
   0xdf, # 'ß'
    0, 32, 42, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, 0,
    'l', 0, -27,
    'c', 0, -36, 4, -42, 16, -42,
    'c', 33, -42, 34, -23, 14, -22,
    'c', 38, -22, 38, 5, 10, -1,
    'e',
   0xe0, # 'à'
    0, 24, 45, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 2, -26,
    'c', 11, -30, 24, -29, 24, -17,
    'l', 24, 0,
    'm', 24, -15,
    'c', 14, -16, 0, -16, 0, -7,
    'c', 0, 4, 24, 2, 24, -13,
    'm', 15, -37,
    'l', 9, -45,
    'e',
   0xe1, # 'á'
    0, 24, 45, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 2, -26,
    'c', 11, -30, 24, -29, 24, -17,
    'l', 24, 0,
    'm', 24, -15,
    'c', 14, -16, 0, -16, 0, -7,
    'c', 0, 4, 24, 2, 24, -13,
    'm', 9, -37,
    'l', 15, -45,
    'e',
   0xe2, # 'â'
    0, 24, 45, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 2, -26,
    'c', 11, -30, 24, -29, 24, -17,
    'l', 24, 0,
    'm', 24, -15,
    'c', 14, -16, 0, -16, 0, -7,
    'c', 0, 4, 24, 2, 24, -13,
    'm', 7, -37,
    'l', 12, -45,
    'l', 17, -37,
    'e',
   0xe3, # 'ã'
    0, 24, 43, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 2, -26,
    'c', 11, -30, 24, -29, 24, -17,
    'l', 24, 0,
    'm', 24, -15,
    'c', 14, -16, 0, -16, 0, -7,
    'c', 0, 4, 24, 2, 24, -13,
    'm', 4, -39,
    'c', 10, -52, 14, -28, 20, -41,
    'e',
   0xe4, # 'ä'
    0, 24, 41, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 2, -26,
    'c', 11, -30, 24, -29, 24, -17,
    'l', 24, 0,
    'm', 24, -15,
    'c', 14, -16, 0, -16, 0, -7,
    'c', 0, 4, 24, 2, 24, -13,
    'm', 7, -39,
    'l', 7, -41,
    'l', 9, -41,
    'l', 9, -39,
    'l', 7, -39,
    'm', 17, -39,
    'l', 17, -41,
    'l', 19, -41,
    'l', 19, -39,
    'l', 17, -39,
    'e',
   0xe5, # 'å'
    0, 24, 45, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 2, -26,
    'c', 11, -30, 24, -29, 24, -17,
    'l', 24, 0,
    'm', 24, -15,
    'c', 14, -16, 0, -16, 0, -7,
    'c', 0, 4, 24, 2, 24, -13,
    'm', 12, -37,
    'c', 10, -37, 8, -39, 8, -41,
    'c', 8, -43, 10, -45, 12, -45,
    'c', 14, -45, 16, -43, 16, -41,
    'c', 16, -39, 14, -37, 12, -37,
    'e',
   0xe6, # 'æ'
    0, 45, 28, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 2, -26,
    'c', 11, -30, 22, -29, 22, -17,
    'l', 22, -13,
    'c', 22, 2, 0, 4, 0, -7,
    'c', 0, -16, 14, -16, 22, -15,
    'm', 22, -15,
    'l', 45, -15,
    'm', 45, -15,
    'c', 45, -32, 22, -32, 22, -15,
    'c', 22, 2, 36, 1, 45, -2,
    'e',
   0xe7, # 'ç'
    0, 19, 28, 6, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 19, -27,
    'c', 14, -29, 0, -29, 0, -14,
    'c', 0, 0, 14, 1, 19, -1,
    'm', 13, 0,
    'c', 15, 2, 13, 8, 6, 5,
    'e',
   0xe8, # 'è'
    0, 24, 45, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -15,
    'l', 24, -15,
    'c', 24, -32, 0, -32, 0, -15,
    'c', 0, 0, 14, 2, 24, -2,
    'm', 15, -37,
    'l', 9, -45,
    'e',
   0xe9, # 'é'
    0, 24, 45, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -15,
    'l', 24, -15,
    'c', 24, -32, 0, -32, 0, -15,
    'c', 0, 0, 14, 2, 24, -2,
    'm', 9, -37,
    'l', 15, -45,
    'e',
   0xea, # 'ê'
    0, 24, 45, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -15,
    'l', 24, -15,
    'c', 24, -32, 0, -32, 0, -15,
    'c', 0, 0, 14, 2, 24, -2,
    'm', 7, -37,
    'l', 12, -45,
    'l', 17, -37,
    'e',
   0xeb, # 'ë'
    0, 24, 41, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -15,
    'l', 24, -15,
    'c', 24, -32, 0, -32, 0, -15,
    'c', 0, 0, 14, 2, 24, -2,
    'm', 6, -39,
    'l', 6, -41,
    'l', 8, -41,
    'l', 8, -39,
    'l', 6, -39,
    'm', 16, -39,
    'l', 16, -41,
    'l', 18, -41,
    'l', 18, -39,
    'l', 16, -39,
    'e',
   0xec, # 'ì'
    0, 4, 45, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 2, -28,
    'l', 2, 0,
    'm', 2, -37,
    'l', -4, -45,
    'e',
   0xed, # 'í'
    0, 5, 45, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 2, -28,
    'l', 2, 0,
    'm', 2, -37,
    'l', 8, -45,
    'e',
   0xee, # 'î'
    -5, 2, 45, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -28,
    'l', 0, 0,
    'm', -5, -37,
    'l', 0, -45,
    'l', 5, -37,
    'e',
   0xef, # 'ï'
    -5, 4, 41, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 2, -28,
    'l', 2, 0,
    'm', -4, -39,
    'l', -4, -41,
    'l', -2, -41,
    'l', -2, -39,
    'l', -4, -39,
    'm', 6, -39,
    'l', 6, -41,
    'l', 8, -41,
    'l', 8, -39,
    'l', 6, -39,
    'e',
   0xf0, # 'ð'
    0, 26, 42, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 26, -14,
    'c', 26, -33, 0, -33, 0, -14,
    'c', 0, 5, 26, 5, 26, -14,
    'c', 26, -25, 18, -37, 5, -42,
    'm', 4, -33,
    'l', 21, -42,
    'e',
   0xf1, # 'ñ'
    0, 24, 43, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -28,
    'l', 0, 0,
    'm', 0, -16,
    'c', 4, -30, 24, -33, 24, -16,
    'l', 24, 0,
    'm', 4, -39,
    'c', 10, -52, 14, -28, 20, -41,
    'e',
   0xf2, # 'ò'
    0, 24, 45, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 24, -14,
    'c', 24, -33, 0, -33, 0, -14,
    'c', 0, 5, 24, 5, 24, -14,
    'm', 15, -37,
    'l', 9, -45,
    'e',
   0xf3, # 'ó'
    0, 24, 45, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 24, -14,
    'c', 24, -33, 0, -33, 0, -14,
    'c', 0, 5, 24, 5, 24, -14,
    'm', 9, -37,
    'l', 15, -45,
    'e',
   0xf4, # 'ô'
    0, 24, 45, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 24, -14,
    'c', 24, -33, 0, -33, 0, -14,
    'c', 0, 5, 24, 5, 24, -14,
    'm', 7, -37,
    'l', 12, -45,
    'l', 17, -37,
    'e',
   0xf5, # 'õ'
    0, 24, 43, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 24, -14,
    'c', 24, -33, 0, -33, 0, -14,
    'c', 0, 5, 24, 5, 24, -14,
    'm', 4, -39,
    'c', 10, -52, 14, -28, 20, -41,
    'e',
   0xf6, # 'ö'
    0, 24, 40, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 24, -14,
    'c', 24, -33, 0, -33, 0, -14,
    'c', 0, 5, 24, 5, 24, -14,
    'm', 6, -39,
    'l', 6, -41,
    'l', 8, -41,
    'l', 8, -39,
    'l', 6, -39,
    'm', 16, -39,
    'l', 16, -41,
    'l', 18, -41,
    'l', 18, -39,
    'l', 16, -39,
    'e',
   0xf7, # '÷'
    0, 36, 29, -7, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -18,
    'l', 36, -18,
    'm', 17, -7,
    'l', 17, -9,
    'l', 19, -9,
    'l', 19, -7,
    'l', 17, -7,
    'm', 17, -27,
    'l', 17, -29,
    'l', 19, -29,
    'l', 19, -27,
    'l', 17, -27,
    'e',
   0xf8, # 'ø'
    0, 24, 30, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 24, -14,
    'c', 24, -33, 0, -33, 0, -14,
    'c', 0, 5, 24, 5, 24, -14,
    'm', 0, 2,
    'l', 24, -30,
    'e',
   0xf9, # 'ù'
    0, 24, 45, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 24, 0,
    'l', 24, -28,
    'm', 24, -12,
    'c', 20, 2, 0, 5, 0, -12,
    'l', 0, -28,
    'm', 15, -37,
    'l', 9, -45,
    'e',
   0xfa, # 'ú'
    0, 24, 45, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 24, 0,
    'l', 24, -28,
    'm', 24, -12,
    'c', 20, 2, 0, 5, 0, -12,
    'l', 0, -28,
    'm', 9, -37,
    'l', 15, -45,
    'e',
   0xfb, # 'û'
    0, 24, 45, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 24, 0,
    'l', 24, -28,
    'm', 24, -12,
    'c', 20, 2, 0, 5, 0, -12,
    'l', 0, -28,
    'm', 7, -37,
    'l', 12, -45,
    'l', 17, -37,
    'e',
   0xfc, # 'ü'
    0, 24, 41, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 24, 0,
    'l', 24, -28,
    'm', 24, -12,
    'c', 20, 2, 0, 5, 0, -12,
    'l', 0, -28,
    'm', 6, -39,
    'l', 6, -41,
    'l', 8, -41,
    'l', 8, -39,
    'l', 6, -39,
    'm', 16, -39,
    'l', 16, -41,
    'l', 18, -41,
    'l', 18, -39,
    'l', 16, -39,
    'e',
   0xfd, # 'ý'
    -2, 24, 45, 14, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -28,
    'l', 12, 0,
    'm', 24, -28,
    'l', 12, 0,
    'c', 6, 14, 4, 15, -2, 13,
    'm', 9, -37,
    'l', 15, -45,
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
    -2, 24, 41, 14, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 0, -28,
    'l', 12, 0,
    'm', 24, -28,
    'l', 12, 0,
    'c', 6, 14, 4, 15, -2, 13,
    'm', 6, -39,
    'l', 6, -41,
    'l', 8, -41,
    'l', 8, -39,
    'l', 6, -39,
    'm', 16, -39,
    'l', 16, -41,
    'l', 18, -41,
    'l', 18, -39,
    'l', 16, -39,
    'e',
   0x300, # '̀'
    13, 19, 55, -47, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 19, -47,
    'l', 13, -55,
    'e',
   0x301, # '́'
    13, 19, 55, -47, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 13, -47,
    'l', 19, -55,
    'e',
   0x302, # '̂'
    11, 21, 55, -47, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 11, -47,
    'l', 16, -55,
    'l', 21, -47,
    'e',
   0x303, # '̃'
    8, 24, 53, -47, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -49,
    'c', 14, -62, 18, -38, 24, -51,
    'e',
   0x308, # '̈'
    10, 22, 51, -49, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 10, -49,
    'l', 10, -51,
    'l', 12, -51,
    'l', 12, -49,
    'l', 10, -49,
    'm', 20, -49,
    'l', 20, -51,
    'l', 22, -51,
    'l', 22, -49,
    'l', 20, -49,
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
    0, 4, 47, -37, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 1, -39,
    'l', 2, -39,
    'l', 2, -37,
    'l', 0, -37,
    'c', 0, -41, 1, -45, 4, -47,
    'e',
   0x2019, # '’'
    0, 4, 47, -37, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 3, -45,
    'l', 2, -45,
    'l', 2, -47,
    'l', 4, -47,
    'c', 4, -43, 3, -39, 0, -37,
    'e',
   0x201a, # '‚'
    0, 5, 2, 8, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 4, 0,
    'l', 3, 0,
    'l', 3, -2,
    'l', 5, -2,
    'c', 5, 2, 4, 6, 1, 8,
    'e',
   0x201b, # '‛'
    0, 4, 47, -37, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 1, -45,
    'l', 2, -45,
    'l', 2, -47,
    'l', 0, -47,
    'c', 0, -43, 1, -39, 4, -37,
    'e',
   0x201c, # '“'
    0, 13, 47, -37, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 1, -39,
    'l', 2, -39,
    'l', 2, -37,
    'l', 0, -37,
    'c', 0, -41, 1, -45, 4, -47,
    'm', 10, -39,
    'l', 11, -39,
    'l', 11, -37,
    'l', 9, -37,
    'c', 9, -41, 10, -45, 13, -47,
    'e',
   0x201d, # '”'
    0, 13, 47, -37, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 3, -45,
    'l', 2, -45,
    'l', 2, -47,
    'l', 4, -47,
    'c', 4, -43, 3, -39, 0, -37,
    'm', 12, -45,
    'l', 11, -45,
    'l', 11, -47,
    'l', 13, -47,
    'c', 13, -43, 12, -39, 9, -37,
    'e',
   0x201e, # '„'
    0, 13, 2, 8, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 3, 0,
    'l', 2, 0,
    'l', 2, -2,
    'l', 4, -2,
    'c', 4, 2, 3, 6, 0, 8,
    'm', 12, 0,
    'l', 11, 0,
    'l', 11, -2,
    'l', 13, -2,
    'c', 13, 2, 12, 6, 9, 8,
    'e',
   0x201f, # '‟'
    0, 13, 47, -37, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 1, -45,
    'l', 2, -45,
    'l', 2, -47,
    'l', 0, -47,
    'c', 0, -43, 1, -39, 4, -37,
    'm', 10, -45,
    'l', 11, -45,
    'l', 11, -47,
    'l', 9, -47,
    'c', 9, -43, 10, -39, 13, -37,
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
    0, 20, 2, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, 0,
    'l', 0, -2,
    'l', 2, -2,
    'l', 2, 0,
    'l', 0, 0,
    'm', 9, 0,
    'l', 9, -2,
    'l', 11, -2,
    'l', 11, 0,
    'l', 9, 0,
    'm', 18, 0,
    'l', 18, -2,
    'l', 20, -2,
    'l', 20, 0,
    'l', 18, 0,
    'e',
   0x2030, # '‰'
    0, 54, 42, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 12, -31,
    'c', 12, -45, 0, -45, 0, -31,
    'c', 0, -17, 12, -17, 12, -31,
    'm', 28, -42,
    'l', 8, 0,
    'm', 34, -11,
    'c', 34, -25, 22, -25, 22, -11,
    'c', 22, 3, 34, 3, 34, -11,
    'm', 54, -11,
    'c', 54, -25, 42, -25, 42, -11,
    'c', 42, 3, 54, 3, 54, -11,
    'e',
   0x2039, # '‹'
    0, 7, 28, -2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 7, -28,
    'l', 0, -15,
    'l', 7, -2,
    'e',
   0x203a, # '›'
    0, 7, 28, -2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -28,
    'l', 7, -15,
    'l', 0, -2,
    'e',
   0x2070, # '⁰'
    0, 12, 42, -20, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 12, -31,
    'c', 12, -45, 0, -45, 0, -31,
    'c', 0, -17, 12, -17, 12, -31,
    'e',
   0x2071, # 'ⁱ'
    0, 2, 42, -22, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 1, -36,
    'l', 1, -22,
    'm', 1, -41,
    'l', 1, -42,
    'l', 2, -42,
    'l', 2, -41,
    'l', 1, -41,
    'e',
   0x2074, # '⁴'
    0, 12, 42, -21, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 10, -21,
    'l', 10, -42,
    'l', 0, -26,
    'l', 12, -26,
    'e',
   0x2075, # '⁵'
    0, 12, 42, -21, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 11, -42,
    'l', 1, -42,
    'l', 0, -32,
    'c', 5, -34, 12, -33, 12, -27,
    'c', 12, -20, 2, -20, 0, -22,
    'e',
   0x2076, # '⁶'
    0, 12, 42, -21, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 11, -41,
    'c', 10, -42, 0, -44, 0, -30,
    'c', 0, -17, 12, -20, 12, -27,
    'c', 12, -33, 2, -36, 1, -27,
    'e',
   0x2077, # '⁷'
    0, 12, 42, -21, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -42,
    'l', 12, -42,
    'l', 4, -21,
    'e',
   0x2078, # '⁸'
    0, 12, 42, -21, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 11, -37,
    'c', 11, -43, 1, -43, 1, -37,
    'c', 1, -31, 12, -32, 12, -26,
    'c', 12, -19, 0, -19, 0, -26,
    'c', 0, -32, 11, -31, 11, -37,
    'e',
   0x2079, # '⁹'
    0, 12, 42, -21, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 1, -21,
    'c', 3, -21, 12, -18, 12, -32,
    'c', 12, -46, 0, -43, 0, -36,
    'c', 0, -29, 10, -27, 11, -35,
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
    0, 6, 43, -18, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 6, -43,
    'c', -1, -36, -1, -25, 6, -18,
    'e',
   0x207e, # '⁾'
    0, 6, 43, -18, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -43,
    'c', 8, -36, 8, -25, 0, -18,
    'e',
   0x207f, # 'ⁿ'
    0, 12, 35, -21, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -35,
    'l', 0, -21,
    'm', 0, -29,
    'c', 2, -36, 12, -37, 12, -29,
    'l', 12, -21,
    'e',
   0x2080, # '₀'
    0, 12, 19, 3, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 12, -8,
    'c', 12, -22, 0, -22, 0, -8,
    'c', 0, 6, 12, 6, 12, -8,
    'e',
   0x2081, # '₁'
    0, 12, 19, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 2, -15,
    'c', 4, -15, 6, -17, 7, -19,
    'l', 7, 2,
    'e',
   0x2082, # '₂'
    0, 12, 19, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 1, -18,
    'c', 2, -19, 12, -21, 12, -13,
    'c', 12, -10, 10, -8, 0, 2,
    'l', 12, 2,
    'e',
   0x2083, # '₃'
    0, 12, 19, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 1, -18,
    'c', 13, -22, 17, -9, 3, -9,
    'c', 17, -9, 14, 6, 0, 1,
    'e',
   0x2084, # '₄'
    0, 12, 19, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 10, 2,
    'l', 10, -19,
    'l', 0, -3,
    'l', 12, -3,
    'e',
   0x2085, # '₅'
    0, 12, 19, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 11, -19,
    'l', 1, -19,
    'l', 0, -9,
    'c', 5, -11, 12, -10, 12, -4,
    'c', 12, 3, 2, 3, 0, 1,
    'e',
   0x2086, # '₆'
    0, 12, 19, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 11, -18,
    'c', 10, -19, 0, -21, 0, -7,
    'c', 0, 6, 12, 3, 12, -4,
    'c', 12, -10, 2, -13, 1, -4,
    'e',
   0x2087, # '₇'
    0, 12, 19, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -19,
    'l', 12, -19,
    'l', 4, 2,
    'e',
   0x2088, # '₈'
    0, 12, 19, 3, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 11, -14,
    'c', 11, -20, 1, -20, 1, -14,
    'c', 1, -8, 12, -9, 12, -3,
    'c', 12, 4, 0, 4, 0, -3,
    'c', 0, -9, 11, -8, 11, -14,
    'e',
   0x2089, # '₉'
    0, 12, 19, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 1, 2,
    'c', 3, 2, 12, 5, 12, -9,
    'c', 12, -23, 0, -20, 0, -13,
    'c', 0, -6, 10, -4, 11, -12,
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
    0, 6, 20, 5, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 6, -20,
    'c', -1, -13, -1, -2, 6, 5,
    'e',
   0x208e, # '₎'
    0, 6, 20, 5, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -20,
    'c', 8, -13, 8, -2, 0, 5,
    'e',
   0x2090, # 'ₐ'
    0, 12, 12, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 1, -11,
    'c', 6, -13, 12, -12, 12, -6,
    'l', 12, 2,
    'm', 12, -5,
    'c', 7, -6, 0, -6, 0, -1,
    'c', 0, 4, 12, 3, 12, -4,
    'e',
   0x2091, # 'ₑ'
    0, 12, 12, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -5,
    'l', 12, -5,
    'c', 12, -14, 0, -14, 0, -5,
    'c', 0, 2, 7, 3, 12, 1,
    'e',
   0x2092, # 'ₒ'
    0, 12, 12, 3, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 12, -5,
    'c', 12, -14, 0, -14, 0, -5,
    'c', 0, 5, 12, 5, 12, -5,
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
    'm', 12, -5,
    'l', 0, -5,
    'c', 0, 4, 12, 4, 12, -5,
    'c', 12, -12, 5, -13, 0, -11,
    'e',
   0x2095, # 'ₕ'
    0, 12, 19, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -19,
    'l', 0, 2,
    'm', 0, -6,
    'c', 2, -13, 12, -14, 12, -6,
    'l', 12, 2,
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
    0, 2, 19, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 1, -19,
    'l', 1, 2,
    'e',
   0x2098, # 'ₘ'
    0, 20, 12, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -12,
    'l', 0, 2,
    'm', 0, -6,
    'c', 1, -12, 10, -15, 10, -6,
    'l', 10, 2,
    'm', 10, -6,
    'c', 11, -12, 20, -15, 20, -6,
    'l', 20, 2,
    'e',
   0x2099, # 'ₙ'
    0, 12, 12, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -12,
    'l', 0, 2,
    'm', 0, -6,
    'c', 2, -13, 12, -14, 12, -6,
    'l', 12, 2,
    'e',
   0x209a, # 'ₚ'
    0, 12, 12, 9, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, 9,
    'l', 0, -12,
    'm', 0, -5,
    'c', 0, 4, 12, 4, 12, -5,
    'c', 12, -14, 0, -14, 0, -5,
    'e',
   0x209b, # 'ₛ'
    0, 11, 12, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 10, -11,
    'c', 9, -12, 0, -13, 0, -8,
    'c', 0, -5, 11, -5, 11, -1,
    'c', 11, 3, 4, 2, 1, 1,
    'e',
   0x209c, # 'ₜ'
    0, 7, 19, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 3, -19,
    'l', 3, -3,
    'c', 3, 1, 4, 3, 7, 2,
    'm', 0, -13,
    'l', 6, -13,
    'e',
   0x20ac, # '€'
    0, 30, 42, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 30, -40,
    'c', 18, -45, 0, -40, 0, -21,
    'c', 0, -2, 18, 3, 30, -2,
    'm', 26, -17,
    'l', -2, -17,
    'm', -2, -25,
    'l', 28, -25,
    'e',
)

charmap = (
Charmap(page = 0x0000,
        offsets = (
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
   28,   37,   72,   97,  136,  182,  241,  298,
  317,  340,  363,  395,  422,  454,  474,  502,
  521,  552,  575,  611,  643,  670,  708,  747,
  770,  817,  856,  899,  946,  968,  995, 1017,
 1064, 1117, 1146, 1193, 1224, 1257, 1290, 1320,
 1358, 1390, 1408, 1434, 1465, 1487, 1515, 1540,
 1571, 1605, 1642, 1682, 1720, 1747, 1776, 1798,
 1826, 1851, 1880, 1906, 1932, 1951, 1977, 1999,
 2018, 2037, 2081, 2118, 2149, 2186, 2221, 2256,
 2301, 2334, 2369, 2412, 2443, 2461, 2508, 2541,
 2572, 2609, 2646, 2676, 2714, 2748, 2780, 2802,
 2830, 2855, 2888, 2914, 2961, 2979, 3026,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
 3051, 3060, 3095, 3133, 3172, 3239, 3282, 3306,
 3368, 3412, 3488, 3537, 3568, 3588, 3597, 3668,
 3685, 3728, 3759, 3795, 3827, 3847, 3890, 3929,
 3958, 3982, 4009, 4046, 4078, 4123, 4176, 4225,
 4271, 4306, 4341, 4379, 4418, 4477, 4537, 4581,
 4622, 4660, 4698, 4739, 4801, 4827, 4853, 4882,
 4932, 4971, 5007, 5044, 5081, 5121, 5162, 5223,
 5249, 5286, 5322, 5358, 5397, 5457, 5492, 5529,
 5570, 5620, 5670, 5723, 5777, 5851, 5926, 5990,
 6031, 6071, 6111, 6154, 6218, 6244, 6270, 6299,
 6349, 6393, 6434, 6469, 6504, 6542, 6581, 6640,
 6688, 6723, 6760, 6797, 6837, 6898, 6935, 6984,
        )),
Charmap(page = 0x0003,
        offsets = (
 7047, 7065, 7083, 7104,    1,    1,    1,    1,
 7126,    1,    1,    1,    1,    1,    1,    1,
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
Charmap(page = 0x0020,
        offsets = (
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
 7168, 7186, 7204, 7222, 7240, 7258, 7276, 7300,
 7324, 7355, 7386, 7417, 7448, 7498, 7548, 7598,
 7648, 7672, 7702,    1,    1,    1, 7793,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
 7850,    1,    1,    1,    1,    1,    1,    1,
    1, 7919, 7940,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
 7961, 7990,    1,    1, 8023, 8047, 8082, 8118,
 8139, 8182, 8218, 8242, 8260, 8284, 8306, 8328,
 8359, 8388, 8413, 8445, 8474, 8498, 8533, 8569,
 8590, 8633, 8669, 8693, 8711, 8735, 8757,    1,
 8779, 8821, 8853, 8882, 8906, 8938, 8969, 8999,
 9017, 9061, 9092, 9127, 9163,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1, 9194,    1,    1,    1,
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


class Values:

    def __init__(self):
        self.inch = True
        self.mm = False
        self.rect = False
        self.tesselate = False
        self.oblique = False
        self.sheer = 0.1
        self.flatness = 0.001
        self.speed = 100
        self.template = None
        self.device = None
        self.settings = None
        self.border = 0
        self.start_x = None
        self.start_y = None
        self.width = 4
        self.height = 1
        self.delta_x = 4
        self.delta_y = 1
        self.columns = 1
        self.value = None
        self.number = 1
        self.text = None
        self.align = 'center'
        self.font_height = False
        self.config_dir = '@SHARE_DIR@'
        self.rects = None
        self.file = None
        pass

    def handle_dict(self, d):
        values_vars = vars(self)
        for var in values_vars:
            if var in d and d[var] is not None:
                values_vars[var] = d[var]
            
    def handle_args(self, args):
        self.handle_dict(vars(args))


def config_open(name: str, values):
    try:
        return open(name)
    except FileNotFoundError:
        return open(os.path.join(values.config_dir, name))


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
    values: Values = None

    def __init__(self, values: Values):
        if values.device:
            self.set_json_file(values.device, values)

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
        if isinstance(settings, list):
            self.setting_values = settings
        else:
            f = StringIO(settings)
            reader = csv.reader(f, delimiter=',')
            setting_values = []
            for row in reader:
                setting_values = row
            for i in range(min(len(setting_values), len(self.setting_values))):
                self.setting_values[i] = setting_values[i]

    def set_json_file(self, json_file: str, values):
        with config_open(json_file, values) as file:
            self.set_values(json.load(file))


class GCode(Draw):
    f: Any
    device: Device

    def __init__(self, f: Any, device: Device, values: Values):
        self.f = f
        self.device = device
        self.values = values
        if values.settings != None:
            device.set_settings(values.settings)

    def start(self):
        print("%s" % self.device.start, file=self.f, end="")
        if self.device.settings != "":
            print(
                self.device.settings % tuple(self.device.setting_values), file=self.f, end=""
            )
        if self.values.mm:
            print("%s" % self.device.mm, file=self.f, end="")
        else:
            print("%s" % self.device.inch, file=self.f, end="")

    def move(self, x: float, y: float):
        print(self.device.move % (x, y), file=self.f, end="")
        super().move(x, y)

    def draw(self, x: float, y: float):
        if self.device.speed:
            s = self.device.draw % (x, y, self.values.speed)
        else:
            s = self.device.draw % (x, y)
        print(s, file=self.f, end="")
        super().draw(x, y)

    def curve(self, x1: float, y1: float, x2: float, y2: float, x3: float, y3: float):
        if self.device.speed:
            s = self.device.curve % (x1, y1, x2, y2, x3, y3, self.values.speed)
        else:
            s = self.device.curve % (x1, y1, x2, y2, x3, y3)
        print(s, file=self.f, end="")
        super().curve(x1, y1, x2, y2, x3, y3)

    def stop(self):
        print("%s" % self.device.stop, file=self.f, end="")

    def get_draw(self):
        if self.device.curve == "" or self.values.tesselate:
            return LineDraw(self, self.values.flatness)
        return self

    def text_path(self, m: Matrix, s: str):
        draw = MatrixDraw(self.get_draw(), m)
        font.text_path(s, draw)

    def text_into_rect(self, r: Rect, s: str):
        if self.values.rect:
            self.rect(r)

        rect_width = r.bottom_right.x - r.top_left.x - self.values.border * 2
        rect_height = r.bottom_right.y - r.top_left.y - self.values.border * 2

        if rect_width < 0:
            print("border %f too wide for rectangle %s" % (self.values.border, r))
            return
        if rect_height < 0:
            print("border %f too tall for rectangle %s" % (self.values.border, r))
            return

        metrics = font.text_metrics(s)

        text_width = metrics.right_side_bearing - metrics.left_side_bearing
        if self.values.font_height:
            ascent = metrics.font_ascent
            descent = metrics.font_descent
        else:
            ascent = metrics.ascent
            descent = metrics.descent

        text_height = ascent + descent

        if text_width == 0 or text_height == 0:
            print("Text is empty")
            return

        if self.values.oblique:
            text_width += text_height * self.values.sheer

        if text_width / text_height > rect_width / rect_height:
            scale = rect_width / text_width
        else:
            scale = rect_height / text_height

        text_off_y = (rect_height - text_height * scale) / 2

        if self.values.align == 'left':
            text_off_x = 0
        elif self.values.align == 'center':
            text_off_x = (rect_width - text_width * scale) / 2
        else:
            text_off_x = text_width

        text_x = text_off_x + r.top_left.x + self.values.border
        text_y = text_off_y + r.top_left.y + self.values.border
        text_x_span = text_width * scale
        text_y_span = text_height * scale

        print('%f,%f - %f,%f "%s"' % (text_x, text_y, text_x_span, text_y_span, s))

        matrix = Matrix()
        matrix = matrix.translate(
            text_off_x + r.top_left.x + self.values.border,
            text_off_y + r.top_left.y + self.values.border,
        )
        if self.values.oblique:
            matrix = matrix.sheer(-self.values.sheer, 0)

        matrix = matrix.scale(scale, scale)
        if self.device.y_invert:
            matrix = matrix.scale(1, -1)
        else:
            matrix = matrix.translate(0, ascent)

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
                        help='Use inch units',
                        default=None)
    parser.add_argument('-m', '--mm', action='store_true',
                        help='Use millimeter units',
                        default=None)
    parser.add_argument('-r', '--rect', action='store_true',
                        help='Draw bounding rectangles',
                        default=None)
    parser.add_argument('-O', '--oblique', action='store_true',
                        help='Draw the glyphs using a sheer transform',
                        default=None)
    parser.add_argument('--tesselate', action='store_true',
                        help='Force tesselation of splines',
                        default=None)
    parser.add_argument('--dump-offsets', action='store_true',
                        help='Dump glyph offsets to update font')
    parser.add_argument('--sheer', action='store', type=float,
                        help='Oblique sheer amount')
    parser.add_argument('-f', '--flatness', action='store', type=float,
                        help='Spline decomposition tolerance')
    parser.add_argument('-s', '--speed', action='store', type=float,
                        help='Feed rate')
    parser.add_argument('-t', '--template', action='store',
                        help='Template file name',
                        default=None)
    parser.add_argument('-d', '--device', action='store',
                        help='Device config file')
    parser.add_argument('-S', '--settings', action='store',
                        help='Device-specific settings values')
    parser.add_argument('-o', '--output', action='store',
                        help='Output file name',
                        default='-')
    parser.add_argument('-b', '--border', action='store', type=float,
                        help='Border width')
    parser.add_argument('-x', '--start-x', action='store', type=float,
                        help='Starting X for boxes')
    parser.add_argument('-y', '--start-y', action='store', type=float,
                        help='Starting Y for boxes')
    parser.add_argument('-w', '--width', action='store', type=float,
                        help='Box width')
    parser.add_argument('-h', '--height', action='store', type=float,
                        help='Box height')
    parser.add_argument('-X', '--delta-x', action='store', type=float,
                        help='X offset between boxes')
    parser.add_argument('-Y', '--delta-y', action='store', type=float,
                        help='Y offset between boxes')
    parser.add_argument('-c', '--columns', action='store', type=int,
                        help='Number of columns of boxes')
    parser.add_argument('-v', '--value', action='store', type=float,
                        help='Initial text numeric value')
    parser.add_argument('-n', '--number', action='store', type=float,
                        help='Number of numeric values')
    parser.add_argument('-T', '--text', action='store',
                        help='Text string')
    parser.add_argument('-a', '--align', action='store', type=str,
                        choices=['left', 'right', 'center'],
                        default=None)
    parser.add_argument('--font-height', action='store_true',
                        help='Use font height for strings instead of glyph heights',
                        default=None)
    parser.add_argument('-C', '--config-dir', action='store',
                        help='Directory containing device configuration files')
    parser.add_argument('file', nargs='*',
                        help='Text source files')
    args = parser.parse_args()

    if args.help:
        parser.print_help()
        sys.exit(0)

    if args.version:
        print("%s" % '@VERSION@')
        sys.exit(0)

    return args
    

def finite_rects(args):
    return args.template is not None


def load_template(template_file, values):

    with config_open(template_file, values) as file:
        template = json.load(file)
    if isinstance(template, list):
        value.rects = template
    elif isinstance(template, dict):
        values.handle_dict(template)

    if not isinstance(values.rects, list):
        print('template rects is not an array', file=sys.stderr)
        raise TypeError
    for e in tuple(values.rects):
        if not isinstance(e, list):
            print('rects element %s is not an array' % (e,), file=sys.stderr)
            raise TypeError
        if len(e) != 4:
            print('rects element %s does not contain four values' % (e,), file=sys.stderr)
            raise TypeError
        for v in tuple(e):
            if not isinstance(v, numbers.Number):
                print('rects value %r is not a number' % (v,), file=sys.stderr)
                raise TypeError

def get_rect(values):
    if values.rects is not None:
        for r in values.rects:
            yield Rect(Point(r[0], r[1]), Point(r[0] + r[2], r[1] + r[3]))
    else:
        y = values.start_y
        while True:
            x = values.start_x
            for c in range(values.columns):
                yield Rect(Point(x, y), Point(x+values.width, y+values.height))
                x += values.delta_x
            y += values.delta_y
    

def get_line(values):
    if values.value != None:
        v = values.value
        n = values.number
        while finite_rects(values) or n > 0:
            yield "%d" % v
            n -= 1
            v += 1
    if values.text != None:
        for l in values.text.splitlines():
            yield l
    for name in values.file:
        with open(name, "r", encoding='utf-8', errors='ignore') as f:
            for l in f.readlines():
                yield l.strip()

def main():
    values = Values()
    args = Args()

    if args.config_dir:
        values.config_dir = args.config_dir

    if args.template:
        load_template(args.template, values)

    values.handle_args(args)

    device = Device(values)

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

    rect_gen = get_rect(values)
    line_gen = get_line(values)

    gcode = GCode(output, device, values)
    gcode.start()

    while True:
        try:
            rect = next(rect_gen)
            line = next(line_gen)
            gcode.text_into_rect(rect, line)
        except StopIteration:
            break

    gcode.stop()

main()
