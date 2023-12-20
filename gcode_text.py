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
from lxml import etree # type: ignore
from svg.path import parse_path # type: ignore
from svg.path import Path, Move, Line, Arc, CubicBezier, QuadraticBezier, Close # type: ignore

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


class DebugDraw(Draw):
    def move(self, x: float, y: float) -> None:
        print('move %f %f' % (x, y))

    def draw(self, x: float, y: float) -> None:
        print('line %f %f' % (x, y))

    def curve(self, x1: float, y1: float, x2: float, y2: float, x3: float, y3: float) -> None:
        print('curve %f %f %f %f %f %f' % (x1, y1, x2, y2, x3, y3))

class MeasureDraw(Draw):

    def __init__(self, tolerance: float):
        self.min_x = 1e30
        self.max_x = -1e30
        self.min_y = 1e30
        self.max_y = -1e30
        self.last_x = 0
        self.last_y = 0
        self.tolerance = tolerance

    def __str__(self) -> str:
        return '%f,%f - %f,%f' % (self.min_x, self.min_y, self.max_x, self.max_y)
                

    def point(self, x: float, y: float) -> None:
        self.min_x = min(self.min_x, x)
        self.min_y = min(self.min_y, y)
        self.max_x = max(self.max_x, x)
        self.max_y = max(self.max_y, y)

    def smudge_point(self, x: float, y: float) -> None:
        self.min_x = min(self.min_x, x - self.tolerance)
        self.min_y = min(self.min_y, y - self.tolerance)
        self.max_x = max(self.max_x, x + self.tolerance)
        self.max_y = max(self.max_y, y + self.tolerance)

    def move(self, x: float, y: float) -> None:
        self.last_x = x
        self.last_y = y

    def draw(self, x: float, y: float) -> None:
        self.point(self.last_x, self.last_y)
        self.point(x, y)
        self.last_x = x
        self.last_y = y

    def curve(self, x1: float, y1: float, x2: float, y2: float, x3: float, y3: float) -> None:
        s = Spline(
            Point(self.last_x, self.last_y), Point(x1, y1), Point(x2, y2), Point(x3, y3)
        )
        ps = s.decompose(self.tolerance)
        for p in ps[:-1]:
            self.smudge_point(p.x, p.y)
        self.draw(ps[-1].x, ps[-1].y)

UCS_PAGE_SHIFT = 8
UCS_PER_PAGE = 1 << UCS_PAGE_SHIFT


# encodes a specific Unicode page
class Charmap:
    page: int
    offsets: tuple[int, ...]

    def __init__(self, page, offsets) -> None:
        self.page = page
        self.offsets = offsets

    def __str__(self) -> str:
        s = 'page = 0x%x, offsets = (\n' % (self.page)
        for base in range(0, len(self.offsets), 8):
            for off in range(8):
                s += '%5d,' % self.offsets[base + off]
            s += '\n'
        s += ')\n'
        return s

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
        return "l %f r %f w %f a %f d %f Fa %f Fd %f" % (
            self.left_side_bearing,
            self.right_side_bearing,
            self.width,
            self.ascent,
            self.descent,
            self.font_ascent,
            self.font_descent,
        )


svg_ns:str = '{http://www.w3.org/2000/svg}'

def svg_tag(tag: str) -> str:
    return svg_ns + tag

class Font:
    name: str
    style: str
    charmap: tuple[Charmap, ...]
    outlines: tuple[str|float|int, ...]
    space: int
    ascent: int
    descent: int
    height: int

    def __init__(self, name, style, charmap, outlines, space, ascent, descent, height, units_per_em = 64) -> None:
        self.name = name
        self.style = style
        self.charmap = charmap
        self.outlines = outlines
        self.space = space
        self.ascent = ascent
        self.descent = descent
        self.units_per_em = units_per_em

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
    def glyph_left(self, offset: int) -> float:
        val = self.outlines[offset + 0]
        assert isinstance(val, (int, float))
        return val

    def glyph_right(self, offset: int) -> float:
        val = self.outlines[offset + 1]
        assert isinstance(val, (int, float))
        return val

    def glyph_width(self, offset: int) -> float:
        val = self.outlines[offset + 2]
        assert isinstance(val, (int, float))
        return val
        
    def glyph_ascent(self, offset: int) -> float:
        val = self.outlines[offset + 3]
        assert isinstance(val, (int, float))
        return val

    def glyph_descent(self, offset: int) -> float:
        val = self.outlines[offset + 4]
        assert isinstance(val, (int, float))
        return val

    def glyph_n_snap_x(self, offset: int) -> int:
        val = self.outlines[offset + 5]
        assert isinstance(val, int)
        return val

    def glyph_n_snap_y(self, offset: int) -> int:
        val = self.outlines[offset + 6]
        assert isinstance(val, int)
        return val

    def glyph_snap_x(self, offset: int, s: int) -> float:
        val = self.outlines[offset + 7 + s]
        assert isinstance(val, (int, float))
        return val

    def glyph_snap_y(self, offset: int, s: int) -> float:
        val = self.outlines[offset + 7 + self.glyph_n_snap_x(offset) + s]
        assert isinstance(val, (int, float))
        return val

    def glyph_draw(self, offset: int) -> int:
        return offset + 7 + self.glyph_n_snap_x(offset) + self.glyph_n_snap_y(offset)

    def gen_value(self, offset: int):
        """Return the next element of the outlines array"""
        while True:
            value = self.outlines[offset]
            offset = offset + 1
            yield value

    def gen_outline_value(self, outline: tuple[Any,...], offset: int):
        """Return the next element of the outlines array"""
        while True:
            value = outline[offset]
            offset = offset + 1
            yield value

    def gen_pages(self) -> tuple[int,...]:
        pages: list[int] = []
        offset = 0
        page = -1
        while offset < len(self.outlines):
            ucs4 = int(self.outlines[offset])
            offset += 1
            if self.ucs_page(ucs4) != page:
                page = self.ucs_page(ucs4)
                pages += [page]
            stroke = offset + 7 + self.glyph_n_snap_x(offset) + self.glyph_n_snap_y(offset)
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
            ucs4 = int(self.outlines[offset])
            offset += 1
            if self.ucs_page(ucs4) == page:
                offsets[self.ucs_char_in_page(ucs4)] = offset
            stroke = offset + 7 + self.glyph_n_snap_x(offset) + self.glyph_n_snap_y(offset)
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

    def outline_path(self, ucs4: int, outlines: tuple[Any,...], offset: int, calls: Draw) -> None:
        x1 = 0
        y1 = 0

        value = self.gen_outline_value(outlines, offset)

        prev_op = None
        while True:
            op = next(value)

            if op == "m":
                if prev_op == op:
                    print('Extra move in 0x%x' % ucs4)
                _x1 = next(value)
                _y1 = next(value)
                if _x1 == x1 and _y1 == y1:
                    print('gratuitous move in 0x%x to %f %f' % (ucs4, _x1, _y1))
                x1 = _x1
                y1 = _y1
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
                return
            else:
                print("unknown font op %s in glyph %d at %d" % (op, ucs4, offset))
                raise ValueError
                return
            prev_op = op

    #
    # Draw a single glyph using the provide callbacks.
    #
    def glyph_path(self, ucs4: int, calls: Draw) -> float:
        glyph_start: int = self.glyph_offset(ucs4)
        offset: int = self.glyph_draw(glyph_start)

        self.outline_path(ucs4, self.outlines, offset, calls)
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

    def add_offset(self, ucs4: int, offset: int) -> None:
        page = self.ucs_page(ucs4)
        idx = self.ucs_char_in_page(ucs4)
        charmap = None
        for i in range(len(self.charmap)):
            if self.charmap[i].page == page:
                charmap = self.charmap[i]
                break
        else:
            charmap = Charmap(page, 256*[1])
            self.charmap += (charmap,)
        l = list(charmap.offsets)
        l[idx] = offset
        charmap.offsets = tuple(l)
        
    def measure_ink(self, ucs4: int, outlines: tuple[Any, ...], offset: int) -> list[float]:
        measure_calls = MeasureDraw(self.units_per_em / 1e6)
        self.outline_path(ucs4, outlines, offset, measure_calls)
        if measure_calls.min_x > measure_calls.max_x or measure_calls.min_y > measure_calls.max_y:
            measure_calls.min_x = 0
            measure_calls.max_x = 0
            measure_calls.min_y = 0
            measure_calls.max_y = 0
        return [measure_calls.min_x,
                measure_calls.max_x,
                0,
                -measure_calls.min_y,
                measure_calls.max_y]

    def set_svg_face(self, element):
        for name, value in sorted(element.items()):
            if name == 'ascent':
                self.ascent = float(value)
            elif name == 'descent':
                self.descent = abs(float(value))
            elif name == 'font-family':
                self.name = value
            elif name == 'units-per-em':
                self.units_per_em = float(value)

    def add_svg_glyph(self, element, missing) -> float:
        if missing:
            ucs4 = 0
        else:
            ucs4 = ord(element.get('unicode'))
        width = float(element.get('horiz-adv-x'))
        cur_x = 0
        cur_y = 0
        mov_x = 0
        mov_y = 0
        offset = len(self.outlines) + 1
        self.add_offset(ucs4, offset)
        outline: tuple[Any,...] = ()
        path_string = element.get('d')
        if path_string is not None:
            path = parse_path(path_string)
            for p in path:
                if p.start.real != cur_x or p.start.imag != cur_y:
                    outline += ('m', p.start.real, -p.start.imag)
                    mov_x = p.start.real
                    mov_y = p.start.imag
                if isinstance(p, Move):
                    pass
                elif isinstance(p, Line):
                    outline += ('l', p.end.real, -p.end.imag)
                elif isinstance(p, CubicBezier):
                    outline += ('c',
                                      p.control1.real, -p.control1.imag,
                                      p.control2.real, -p.control2.imag,
                                      p.end.real, -p.end.imag)
                elif isinstance(p, Close):
                    if cur_x != mov_x or cur_y != mov_y:
                        outline += ('l', mov_x, mov_y)
                cur_x = p.end.real
                cur_y = p.end.imag
        
        outline += ('e',)
        measure = self.measure_ink(ucs4, outline, 0)
        measure[2] = width
        new_outlines = (ucs4, ) + tuple(measure) + (0, 0) + outline
        self.outlines += new_outlines
        return width
        
    def dump_charmap(self):
        for i in range(len(self.charmap)):
            print('%s' % self.charmap[i])

    def dump_outlines(self):
        debug_draw = DebugDraw()
        for i in range(len(self.charmap)):
            charmap = self.charmap[i]
            for j in range(len(charmap.offsets)):
                if charmap.offsets[j] != 1:
                    ucs4 = charmap.page * 256 + j
                    print("ucs4 0x%x" % ucs4);
                    self.glyph_path(ucs4, debug_draw)

    @classmethod
    def parse_svg_font(cls, node_list):
        for node in node_list:
            if etree.iselement(node):
                if node.tag == svg_tag('defs'):
                    return Font.parse_svg_font(node)
                elif node.tag == svg_tag('font'):
                    font = Font('unknown', None, (), (), 0, 0, 0, 0)
                    for element in node:
                        if element.tag == svg_tag('font-face'):
                            font.set_svg_face(element)
                        elif element.tag == svg_tag('missing-glyph'):
                            font.space = font.add_svg_glyph(element, True)
                        elif element.tag == svg_tag('glyph'):
                            font.add_svg_glyph(element, False)
                    return font
                    

    @classmethod
    def svg_font(cls, filename: str) -> Font:
        parser = etree.XMLParser(remove_comments=True, recover=True, resolve_entities=False)
        try:
            doc = etree.parse(filename, parser=parser)
            svg_root = doc.getroot()
        except Exception as exc:
            print("Failed to load font (%s)" % exc)
            sys.exit(1)
        return Font.parse_svg_font(svg_root)


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
    9, 37, 45, 42, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 9, 0,
    'l', 9, -42,
    'l', 37, -42,
    'l', 37, 0,
    'l', 9, 0,
    'e',
   0x20, # ' '
    4, 4, 16, 0, 0, 1, 0,
    4, #  snap_x
    #  snap_y
    'e',
   0x21, # '!'
    11, 13, 24, 42, 0, 3, 3,
    0, 2, 4, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 12, -42,
    'l', 12, -14,
    'm', 11, 0,
    'l', 11, -2,
    'l', 13, -2,
    'l', 13, 0,
    'l', 11, 0,
    'e',
   0x22, # '"'
    13, 22, 35, 43, -30, 2, 3,
    0, 16, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 13, -43,
    'l', 13, -30,
    'm', 22, -30,
    'l', 22, -43,
    'e',
   0x23, # '#'
    2, 32, 35, 42, 0, 2, 5,
    0, 30, #  snap_x
    -24, -21, -15, -12, 0, #  snap_y
    'm', 14, -42,
    'l', 8, 0,
    'm', 26, -42,
    'l', 20, 0,
    'm', 4, -27,
    'l', 32, -27,
    'm', 2, -15,
    'l', 30, -15,
    'e',
   0x24, # '$'
    6, 29, 35, 49, 5, 4, 4,
    0, 10, 18, 28, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 27, -42,
    'c', 23, -43, 6, -46, 6, -33,
    'c', 6, -22, 29, -24, 29, -12,
    'c', 28, 2, 10, 0, 6, -3,
    'm', 17, 5,
    'l', 17, -49,
    'e',
   0x25, # '%'
    10, 52, 63, 42, 0, 4, 7,
    0, 14, 22, 36, #  snap_x
    -42, -38, -28, -21, -15, -14, 0, #  snap_y
    'm', 22, -31,
    'c', 22, -45, 10, -45, 10, -31,
    'c', 10, -17, 22, -17, 22, -31,
    'm', 44, -42,
    'l', 19, 0,
    'm', 52, -11,
    'c', 52, -25, 40, -25, 40, -11,
    'c', 40, 3, 52, 3, 52, -11,
    'e',
   0x26, # '&'
    8, 41, 45, 43, 0, 4, 4,
    0, 10, 22, 40, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 38, -22,
    'c', 38, -13, 32, 0, 20, 0,
    'c', 15, 0, 8, -1, 8, -10,
    'c', 8, -24, 30, -21, 30, -34,
    'c', 30, -45, 13, -45, 13, -34,
    'c', 13, -30, 15, -26, 18, -23,
    'l', 41, 0,
    'e',
   0x27, # '''
    9, 9, 18, 43, -30, 2, 3,
    0, 4, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 9, -43,
    'l', 9, -30,
    'e',
   0x28, # '('
    6, 16, 21, 46, 7, 2, 3,
    0, 14, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 16, -46,
    'c', 3, -30, 3, -9, 16, 7,
    'e',
   0x29, # ')'
    5, 15, 21, 46, 7, 2, 3,
    0, 14, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 5, -46,
    'c', 18, -30, 18, -9, 5, 7,
    'e',
   0x2a, # '*'
    8, 28, 35, 43, -19, 3, 3,
    0, 10, 20, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 18, -43,
    'l', 18, -19,
    'm', 8, -37,
    'l', 28, -25,
    'm', 28, -37,
    'l', 8, -25,
    'e',
   0x2b, # '+'
    4, 34, 38, 30, 0, 3, 4,
    0, 18, 36, #  snap_x
    -21, -18, -15, 0, #  snap_y
    'm', 19, -30,
    'l', 19, 0,
    'm', 4, -15,
    'l', 34, -15,
    'e',
   0x2c, # ','
    4, 8, 17, 2, 8, 2, 3,
    0, 4, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 7, 0,
    'l', 6, 0,
    'l', 6, -2,
    'l', 8, -2,
    'c', 8, 2, 7, 6, 4, 8,
    'e',
   0x2d, # '-'
    3, 17, 21, 17, -17, 2, 4,
    0, 36, #  snap_x
    -21, -18, -15, 0, #  snap_y
    'm', 3, -17,
    'l', 17, -17,
    'e',
   0x2e, # '.'
    7, 9, 17, 2, 0, 2, 3,
    0, 4, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 7, 0,
    'l', 7, -2,
    'l', 9, -2,
    'l', 9, 0,
    'l', 7, 0,
    'e',
   0x2f, # '/'
    1, 16, 17, 44, 0, 2, 3,
    0, 36, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 16, -44,
    'l', 1, 0,
    'e',
   0x30, # '0'
    5, 29, 35, 42, 0, 2, 4,
    0, 28, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 29, -21,
    'c', 29, -49, 5, -49, 5, -21,
    'c', 5, 7, 29, 7, 29, -21,
    'e',
   0x31, # '1'
    9, 20, 35, 42, 0, 3, 3,
    0, 17, 28, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 9, -33,
    'l', 20, -42,
    'l', 20, 0,
    'e',
   0x32, # '2'
    4, 28, 35, 43, 0, 4, 4,
    0, 2, 26, 28, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 5, -40,
    'c', 8, -42, 28, -46, 27, -31,
    'c', 27, -24, 24, -20, 4, 0,
    'l', 28, 0,
    'e',
   0x33, # '3'
    4, 28, 35, 42, 1, 2, 5,
    0, 28, #  snap_x
    -42, -26, -21, -15, 0, #  snap_y
    'm', 5, -40,
    'c', 30, -49, 37, -22, 10, -22,
    'c', 38, -22, 31, 8, 4, -2,
    'e',
   0x34, # '4'
    4, 28, 35, 42, 0, 3, 4,
    0, 20, 30, #  snap_x
    -21, -15, -14, 0, #  snap_y
    'm', 23, 0,
    'l', 23, -42,
    'l', 4, -11,
    'l', 28, -11,
    'e',
   0x35, # '5'
    4, 28, 35, 42, 0, 2, 5,
    0, 28, #  snap_x
    -42, -28, -21, -15, 0, #  snap_y
    'm', 25, -42,
    'l', 5, -42,
    'l', 4, -23,
    'c', 13, -27, 28, -24, 28, -13,
    'c', 28, 2, 8, 1, 4, -2,
    'e',
   0x36, # '6'
    4, 28, 35, 42, 0, 2, 5,
    0, 26, #  snap_x
    -42, -26, -21, -15, 0, #  snap_y
    'm', 27, -41,
    'c', 23, -42, 4, -47, 4, -19,
    'c', 4, 8, 28, 2, 28, -12,
    'c', 28, -25, 8, -31, 5, -12,
    'e',
   0x37, # '7'
    4, 28, 35, 42, 0, 2, 4,
    0, 28, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 4, -42,
    'l', 28, -42,
    'l', 11, 0,
    'e',
   0x38, # '8'
    4, 28, 35, 42, 0, 4, 4,
    0, 2, 26, 28, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 26, -33,
    'c', 26, -45, 6, -45, 6, -33,
    'c', 6, -21, 28, -22, 28, -10,
    'c', 28, 3, 4, 3, 4, -10,
    'c', 4, -22, 26, -21, 26, -33,
    'e',
   0x39, # '9'
    4, 28, 35, 42, 0, 2, 5,
    0, 26, #  snap_x
    -42, -21, -16, -15, 0, #  snap_y
    'm', 5, -1,
    'c', 9, 0, 28, 5, 28, -23,
    'c', 28, -50, 4, -44, 4, -30,
    'c', 4, -17, 24, -11, 27, -30,
    'e',
   0x3a, # ':'
    7, 9, 17, 28, 0, 2, 3,
    0, 4, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 7, 0,
    'l', 7, -2,
    'l', 9, -2,
    'l', 9, 0,
    'l', 7, 0,
    'm', 7, -26,
    'l', 7, -28,
    'l', 9, -28,
    'l', 9, -26,
    'l', 7, -26,
    'e',
   0x3b, # ';'
    5, 9, 17, 28, 8, 2, 3,
    0, 4, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 8, 0,
    'l', 7, 0,
    'l', 7, -2,
    'l', 9, -2,
    'c', 9, 2, 8, 6, 5, 8,
    'm', 7, -26,
    'l', 7, -28,
    'l', 9, -28,
    'l', 9, -26,
    'l', 7, -26,
    'e',
   0x3c, # '<'
    4, 34, 38, 29, -3, 2, 3,
    0, 32, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 34, -29,
    'l', 4, -16,
    'l', 34, -3,
    'e',
   0x3d, # '='
    4, 34, 38, 22, -9, 2, 5,
    0, 36, #  snap_x
    -24, -21, -15, -12, 0, #  snap_y
    'm', 4, -22,
    'l', 34, -22,
    'm', 4, -9,
    'l', 34, -9,
    'e',
   0x3e, # '>'
    4, 34, 38, 29, -3, 2, 3,
    0, 32, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 4, -29,
    'l', 34, -16,
    'l', 4, -3,
    'e',
   0x3f, # '?'
    5, 26, 31, 43, 0, 3, 4,
    0, 12, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 5, -40,
    'c', 10, -43, 26, -44, 26, -33,
    'c', 25, -24, 16, -23, 16, -12,
    'm', 15, 0,
    'l', 15, -2,
    'l', 17, -2,
    'l', 17, 0,
    'l', 15, 0,
    'e',
   0x40, # '@'
    4, 46, 50, 43, 0, 1, 6,
    30, #  snap_x
    -42, -32, -21, -15, -10, 0, #  snap_y
    'm', 33, -26,
    'c', 30, -35, 16, -36, 14, -22,
    'c', 12, -8, 33, 0, 34, -32,
    'c', 27, -4, 46, -5, 46, -22,
    'c', 46, -49, 4, -49, 4, -22,
    'c', 4, 6, 35, 2, 40, -6,
    'e',
   0x41, # 'A'
    6, 40, 45, 42, 0, 2, 4,
    0, 32, #  snap_x
    -21, -15, -14, 0, #  snap_y
    'm', 6, 0,
    'l', 23, -42,
    'l', 40, 0,
    'm', 12, -14,
    'l', 34, -14,
    'e',
   0x42, # 'B'
    8, 32, 38, 42, 0, 2, 5,
    0, 28, #  snap_x
    -42, -22, -21, -15, 0, #  snap_y
    'm', 8, 0,
    'l', 8, -42,
    'l', 20, -42,
    'c', 34, -42, 34, -22, 18, -22,
    'm', 8, -22,
    'l', 18, -22,
    'c', 36, -22, 36, 0, 18, 0,
    'l', 8, 0,
    'e',
   0x43, # 'C'
    7, 35, 38, 42, 0, 2, 4,
    0, 30, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 35, -40,
    'c', 23, -45, 7, -39, 7, -21,
    'c', 7, -3, 23, 3, 35, -2,
    'e',
   0x44, # 'D'
    8, 39, 45, 42, 0, 2, 4,
    0, 28, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 8, 0,
    'l', 8, -42,
    'l', 18, -42,
    'c', 45, -42, 45, 0, 18, 0,
    'l', 8, 0,
    'e',
   0x45, # 'E'
    9, 28, 35, 42, 0, 2, 5,
    0, 26, #  snap_x
    -42, -22, -21, -15, 0, #  snap_y
    'm', 28, -42,
    'l', 9, -42,
    'l', 9, 0,
    'l', 28, 0,
    'm', 9, -22,
    'l', 26, -22,
    'e',
   0x46, # 'F'
    8, 26, 31, 42, 0, 2, 5,
    0, 26, #  snap_x
    -42, -22, -21, -15, 0, #  snap_y
    'm', 26, -42,
    'l', 8, -42,
    'l', 8, 0,
    'm', 8, -22,
    'l', 25, -22,
    'e',
   0x47, # 'G'
    6, 37, 45, 42, 0, 2, 5,
    0, 30, #  snap_x
    -42, -21, -16, -15, 0, #  snap_y
    'm', 37, -39,
    'c', 25, -46, 6, -41, 6, -21,
    'c', 6, -2, 24, 3, 37, -2,
    'l', 37, -21,
    'l', 26, -21,
    'e',
   0x48, # 'H'
    9, 37, 45, 42, 0, 2, 4,
    0, 28, #  snap_x
    -22, -21, -15, 0, #  snap_y
    'm', 9, -42,
    'l', 9, 0,
    'm', 37, -42,
    'l', 37, 0,
    'm', 9, -22,
    'l', 37, -22,
    'e',
   0x49, # 'I'
    8, 8, 17, 42, 0, 1, 3,
    0, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 8, -42,
    'l', 8, 0,
    'e',
   0x4a, # 'J'
    2, 15, 24, 42, 0, 2, 3,
    0, 20, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 15, -42,
    'l', 15, -12,
    'c', 15, 2, 5, 0, 2, -1,
    'e',
   0x4b, # 'K'
    8, 36, 42, 42, 0, 2, 3,
    0, 28, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 8, -42,
    'l', 8, 0,
    'm', 35, -42,
    'l', 8, -14,
    'm', 16, -22,
    'l', 36, 0,
    'e',
   0x4c, # 'L'
    8, 29, 32, 42, 0, 2, 3,
    0, 24, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 8, -42,
    'l', 8, 0,
    'l', 29, 0,
    'e',
   0x4d, # 'M'
    8, 40, 47, 42, 0, 2, 3,
    0, 32, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 8, 0,
    'l', 8, -42,
    'l', 24, -20,
    'l', 40, -42,
    'l', 40, 0,
    'e',
   0x4e, # 'N'
    9, 37, 45, 42, 0, 2, 3,
    0, 28, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 9, 0,
    'l', 9, -42,
    'l', 37, 0,
    'l', 37, -42,
    'e',
   0x4f, # 'O'
    6, 42, 49, 42, 0, 2, 4,
    0, 32, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 6, -21,
    'c', 6, -49, 42, -49, 42, -21,
    'c', 42, 7, 6, 7, 6, -21,
    'e',
   0x50, # 'P'
    8, 31, 35, 42, 0, 2, 5,
    0, 28, #  snap_x
    -42, -21, -20, -15, 0, #  snap_y
    'm', 8, 0,
    'l', 8, -42,
    'l', 18, -42,
    'c', 35, -42, 35, -20, 18, -20,
    'l', 8, -20,
    'e',
   0x51, # 'Q'
    6, 42, 49, 42, 8, 2, 4,
    0, 32, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 6, -21,
    'c', 6, -49, 42, -49, 42, -21,
    'c', 42, 7, 6, 7, 6, -21,
    'm', 31, -1,
    'l', 40, 8,
    'e',
   0x52, # 'R'
    8, 33, 38, 42, 0, 2, 5,
    0, 28, #  snap_x
    -42, -22, -21, -15, 0, #  snap_y
    'm', 8, 0,
    'l', 8, -42,
    'l', 18, -42,
    'c', 34, -42, 34, -22, 18, -22,
    'l', 8, -22,
    'm', 22, -22,
    'l', 33, 0,
    'e',
   0x53, # 'S'
    4, 27, 31, 43, 1, 2, 4,
    0, 28, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 25, -41,
    'c', 21, -42, 4, -45, 4, -32,
    'c', 4, -21, 27, -23, 27, -11,
    'c', 26, 3, 8, 1, 4, -2,
    'e',
   0x54, # 'T'
    3, 31, 35, 42, 0, 3, 4,
    0, 14, 28, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 17, -42,
    'l', 17, 0,
    'm', 3, -42,
    'l', 31, -42,
    'e',
   0x55, # 'U'
    8, 36, 45, 42, 0, 2, 3,
    0, 28, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 8, -42,
    'l', 8, -18,
    'c', 8, 6, 36, 6, 36, -18,
    'l', 36, -42,
    'e',
   0x56, # 'V'
    5, 37, 42, 42, 0, 2, 3,
    0, 32, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 5, -42,
    'l', 21, 0,
    'l', 37, -42,
    'e',
   0x57, # 'W'
    4, 44, 45, 42, 0, 2, 3,
    0, 40, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 4, -42,
    'l', 16, 0,
    'l', 24, -28,
    'l', 32, 0,
    'l', 44, -42,
    'e',
   0x58, # 'X'
    7, 37, 42, 42, 0, 2, 3,
    0, 28, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 7, -42,
    'l', 37, 0,
    'm', 37, -42,
    'l', 7, 0,
    'e',
   0x59, # 'Y'
    5, 37, 42, 42, 0, 3, 3,
    0, 16, 32, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 5, -42,
    'l', 21, -19,
    'l', 21, 0,
    'm', 37, -42,
    'l', 21, -19,
    'e',
   0x5a, # 'Z'
    3, 31, 35, 42, 0, 2, 4,
    0, 28, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 3, -42,
    'l', 31, -42,
    'l', 3, 0,
    'l', 31, 0,
    'e',
   0x5b, # '['
    8, 17, 21, 45, 6, 2, 4,
    0, 14, #  snap_x
    -44, -21, -15, 0, #  snap_y
    'm', 17, -45,
    'l', 8, -45,
    'l', 8, 6,
    'l', 17, 6,
    'e',
   0x5c, # '\'
    0, 15, 17, 44, 0, 2, 3,
    0, 36, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, -44,
    'l', 15, 0,
    'e',
   0x5d, # ']'
    4, 13, 21, 45, 6, 2, 4,
    0, 14, #  snap_x
    -44, -21, -15, 0, #  snap_y
    'm', 4, -45,
    'l', 13, -45,
    'l', 13, 6,
    'l', 4, 6,
    'e',
   0x5e, # '^'
    8, 30, 38, 42, -19, 2, 3,
    0, 32, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 8, -19,
    'l', 19, -42,
    'l', 30, -19,
    'e',
   0x5f, # '_'
    0, 31, 31, -6, 6, 2, 3,
    0, 36, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 0, 6,
    'l', 31, 6,
    'e',
   0x60, # '`'
    4, 10, 17, 45, -37, 2, 3,
    0, 4, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 10, -37,
    'l', 4, -45,
    'e',
   0x61, # 'a'
    4, 28, 35, 29, 0, 2, 4,
    0, 24, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 6, -26,
    'c', 15, -30, 28, -29, 28, -17,
    'l', 28, 0,
    'm', 28, -15,
    'c', 18, -16, 4, -16, 4, -7,
    'c', 4, 4, 28, 2, 28, -13,
    'e',
   0x62, # 'b'
    8, 32, 38, 42, 0, 2, 4,
    0, 24, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 8, -42,
    'l', 8, 0,
    'm', 8, -14,
    'c', 8, -32, 32, -32, 32, -14,
    'c', 32, 4, 8, 4, 8, -14,
    'e',
   0x63, # 'c'
    5, 24, 28, 28, 0, 2, 4,
    0, 24, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 24, -27,
    'c', 19, -29, 5, -29, 5, -14,
    'c', 5, 0, 19, 1, 24, -1,
    'e',
   0x64, # 'd'
    6, 30, 38, 42, 0, 2, 4,
    0, 24, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 30, -42,
    'l', 30, 0,
    'm', 30, -14,
    'c', 30, -32, 6, -32, 6, -14,
    'c', 6, 4, 30, 4, 30, -14,
    'e',
   0x65, # 'e'
    5, 29, 35, 28, 0, 2, 5,
    0, 24, #  snap_x
    -28, -21, -16, -15, 0, #  snap_y
    'm', 5, -15,
    'l', 29, -15,
    'c', 29, -32, 5, -32, 5, -15,
    'c', 5, 0, 19, 2, 29, -2,
    'e',
   0x66, # 'f'
    3, 21, 24, 42, 0, 3, 5,
    0, 6, 16, #  snap_x
    -42, -28, -21, -15, 0, #  snap_y
    'm', 21, -41,
    'c', 15, -43, 11, -40, 11, -33,
    'l', 11, 0,
    'm', 3, -27,
    'l', 20, -27,
    'e',
   0x67, # 'g'
    5, 29, 38, 28, 15, 2, 5,
    0, 24, #  snap_x
    -28, -21, -15, 0, 14, #  snap_y
    'm', 29, -28,
    'l', 29, 0,
    'c', 29, 17, 13, 15, 7, 12,
    'm', 29, -14,
    'c', 29, -32, 5, -32, 5, -14,
    'c', 5, 4, 29, 4, 29, -14,
    'e',
   0x68, # 'h'
    7, 31, 38, 42, 0, 2, 4,
    0, 22, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 7, -42,
    'l', 7, 0,
    'm', 7, -16,
    'c', 11, -30, 31, -33, 31, -16,
    'l', 31, 0,
    'e',
   0x69, # 'i'
    7, 9, 17, 41, 0, 3, 3,
    0, 2, 4, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 8, -28,
    'l', 8, 0,
    'm', 7, -39,
    'l', 7, -41,
    'l', 9, -41,
    'l', 9, -39,
    'l', 7, -39,
    'e',
   0x6a, # 'j'
    0, 9, 17, 41, 14, 3, 4,
    0, 2, 4, #  snap_x
    -21, -15, 0, 14, #  snap_y
    'm', 8, -28,
    'l', 8, 3,
    'c', 8, 12, 6, 15, 0, 13,
    'm', 7, -39,
    'l', 7, -41,
    'l', 9, -41,
    'l', 9, -39,
    'l', 7, -39,
    'e',
   0x6b, # 'k'
    7, 29, 35, 42, 0, 2, 3,
    0, 22, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 7, -42,
    'l', 7, 0,
    'm', 26, -30,
    'l', 7, -11,
    'm', 14, -17,
    'l', 29, 0,
    'e',
   0x6c, # 'l'
    8, 8, 17, 42, 0, 1, 3,
    0, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 8, -42,
    'l', 8, 0,
    'e',
   0x6d, # 'm'
    7, 49, 56, 28, 0, 3, 4,
    0, 22, 44, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 7, -28,
    'l', 7, 0,
    'm', 7, -16,
    'c', 11, -30, 28, -33, 28, -16,
    'l', 28, 0,
    'm', 28, -16,
    'c', 32, -30, 49, -33, 49, -16,
    'l', 49, 0,
    'e',
   0x6e, # 'n'
    7, 31, 38, 28, 0, 2, 4,
    0, 22, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 7, -28,
    'l', 7, 0,
    'm', 7, -16,
    'c', 11, -30, 31, -33, 31, -16,
    'l', 31, 0,
    'e',
   0x6f, # 'o'
    6, 32, 38, 29, 1, 2, 4,
    0, 26, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 32, -14,
    'c', 32, -33, 6, -33, 6, -14,
    'c', 6, 5, 32, 5, 32, -14,
    'e',
   0x70, # 'p'
    8, 32, 38, 28, 14, 2, 4,
    0, 24, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 8, 14,
    'l', 8, -28,
    'm', 8, -14,
    'c', 8, 4, 32, 4, 32, -14,
    'c', 32, -32, 8, -32, 8, -14,
    'e',
   0x71, # 'q'
    6, 30, 38, 28, 14, 2, 4,
    0, 24, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 30, 14,
    'l', 30, -28,
    'm', 30, -14,
    'c', 30, 4, 6, 4, 6, -14,
    'c', 6, -32, 30, -32, 30, -14,
    'e',
   0x72, # 'r'
    8, 22, 24, 28, 0, 2, 4,
    0, 16, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 8, -28,
    'l', 8, 0,
    'm', 8, -12,
    'c', 10, -22, 15, -28, 22, -28,
    'e',
   0x73, # 's'
    4, 19, 24, 28, 1, 2, 4,
    0, 22, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 19, -27,
    'c', 17, -28, 4, -30, 4, -21,
    'c', 4, -15, 19, -14, 19, -7,
    'c', 19, 2, 9, 1, 4, -1,
    'e',
   0x74, # 't'
    3, 20, 25, 38, 0, 3, 4,
    0, 6, 16, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 11, -38,
    'l', 11, -10,
    'c', 11, -1, 15, 1, 20, -1,
    'm', 3, -28,
    'l', 19, -28,
    'e',
   0x75, # 'u'
    7, 31, 38, 28, 0, 2, 3,
    0, 22, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 31, 0,
    'l', 31, -28,
    'm', 31, -12,
    'c', 27, 2, 7, 5, 7, -12,
    'l', 7, -28,
    'e',
   0x76, # 'v'
    6, 26, 31, 28, 0, 2, 3,
    0, 24, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 6, -28,
    'l', 16, 0,
    'l', 26, -28,
    'e',
   0x77, # 'w'
    6, 46, 47, 28, 0, 2, 3,
    0, 32, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 6, -28,
    'l', 16, 0,
    'l', 26, -28,
    'l', 36, 0,
    'l', 46, -28,
    'e',
   0x78, # 'x'
    6, 25, 31, 28, 0, 2, 3,
    0, 22, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 6, -28,
    'l', 25, 0,
    'm', 25, -28,
    'l', 6, 0,
    'e',
   0x79, # 'y'
    3, 26, 31, 28, 13, 2, 4,
    0, 24, #  snap_x
    -21, -15, 0, 14, #  snap_y
    'm', 6, -28,
    'l', 16, 0,
    'm', 26, -28,
    'l', 16, 0,
    'c', 12, 13, 9, 14, 3, 12,
    'e',
   0x7a, # 'z'
    5, 27, 31, 28, 0, 2, 4,
    0, 22, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 5, -28,
    'l', 27, -28,
    'l', 5, 0,
    'l', 27, 0,
    'e',
   0x7b, # '{'
    4, 19, 21, 45, 5, 3, 5,
    0, 6, 16, #  snap_x
    -44, -24, -21, -15, 0, #  snap_y
    'm', 19, -45,
    'c', 11, -45, 11, -45, 11, -34,
    'c', 11, -19, 11, -20, 4, -20,
    'c', 11, -20, 11, -21, 11, -6,
    'c', 11, 5, 11, 5, 19, 5,
    'e',
   0x7c, # '|'
    7, 7, 14, 46, 6, 1, 3,
    0, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 7, -46,
    'l', 7, 6,
    'e',
   0x7d, # '}'
    2, 17, 21, 45, 5, 3, 5,
    0, 10, 16, #  snap_x
    -44, -24, -21, -15, 0, #  snap_y
    'm', 2, -45,
    'c', 10, -45, 10, -45, 10, -34,
    'c', 10, -19, 10, -20, 17, -20,
    'c', 10, -20, 10, -21, 10, -6,
    'c', 10, 5, 10, 5, 2, 5,
    'e',
   0x7e, # '~'
    6, 32, 38, 19, -13, 2, 5,
    0, 36, #  snap_x
    -24, -21, -15, -12, 0, #  snap_y
    'm', 6, -14,
    'c', 15, -27, 23, -5, 32, -18,
    'e',
   0xa0, # ' '
    4, 4, 16, 0, 0, 1, 0,
    4, #  snap_x
    #  snap_y
    'e',
   0xa1, # '¡'
    11, 13, 24, 29, 13, 3, 3,
    0, 2, 4, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 12, 13,
    'l', 12, -15,
    'm', 11, -29,
    'l', 11, -27,
    'l', 13, -27,
    'l', 13, -29,
    'l', 11, -29,
    'e',
   0xa2, # '¢'
    8, 27, 35, 34, 6, 3, 4,
    0, 13, 24, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 25, -34,
    'l', 13, 6,
    'm', 27, -27,
    'c', 22, -29, 8, -29, 8, -14,
    'c', 8, 0, 22, 1, 27, -1,
    'e',
   0xa3, # '£'
    7, 29, 35, 39, 0, 3, 3,
    0, 6, 20, #  snap_x
    -42, -16, 0, #  snap_y
    'm', 29, -37,
    'c', 20, -41, 12, -37, 12, -25,
    'l', 12, 0,
    'm', 7, -21,
    'l', 22, -21,
    'm', 7, 0,
    'l', 29, 0,
    'e',
   0xa4, # '¤'
    5, 29, 35, 32, -8, 2, 2,
    2, 14, #  snap_x
    -26, -14, #  snap_y
    'm', 17, -32,
    'c', 10, -32, 5, -27, 5, -20,
    'c', 5, -13, 10, -8, 17, -8,
    'c', 24, -8, 29, -13, 29, -20,
    'c', 29, -27, 24, -32, 17, -32,
    'm', 5, -32,
    'l', 8, -29,
    'm', 29, -32,
    'l', 26, -29,
    'm', 5, -8,
    'l', 8, -11,
    'm', 29, -8,
    'l', 26, -11,
    'e',
   0xa5, # '¥'
    1, 33, 35, 42, 0, 3, 5,
    0, 16, 32, #  snap_x
    -26, -21, -18, -15, 0, #  snap_y
    'm', 5, -20,
    'l', 29, -20,
    'm', 5, -10,
    'l', 29, -10,
    'm', 1, -42,
    'l', 17, -19,
    'l', 17, 0,
    'm', 33, -42,
    'l', 17, -19,
    'e',
   0xa6, # '¦'
    7, 7, 14, 41, 9, 1, 3,
    0, #  snap_x
    -21, -15, 0, #  snap_y
    'm', 7, -41,
    'l', 7, -21,
    'm', 7, -11,
    'l', 7, 9,
    'e',
   0xa7, # '§'
    8, 27, 35, 40, 3, 4, 2,
    0, 3, 22, 25, #  snap_x
    -43, 0, #  snap_y
    'm', 13, -27,
    'c', 9, -24, 8, -23, 8, -19,
    'c', 8, -10, 27, -14, 27, -4,
    'c', 27, 0, 21, 5, 8, 2,
    'm', 22, -11,
    'c', 25, -13, 27, -14, 27, -18,
    'c', 27, -27, 8, -25, 8, -33,
    'c', 8, -37, 14, -42, 25, -39,
    'e',
   0xa8, # '¨'
    3, 15, 17, 41, -39, 4, 2,
    0, 4, 8, 12, #  snap_x
    -38, -42, #  snap_y
    'm', 3, -39,
    'l', 3, -41,
    'l', 5, -41,
    'l', 5, -39,
    'l', 3, -39,
    'm', 13, -39,
    'l', 13, -41,
    'l', 15, -41,
    'l', 15, -39,
    'l', 13, -39,
    'e',
   0xa9, # '©'
    5, 45, 50, 40, 0, 2, 4,
    0, 24, #  snap_x
    -28, -21, -15, 0, #  snap_y
    'm', 25, -40,
    'c', 13, -40, 5, -32, 5, -20,
    'c', 5, -8, 13, 0, 25, 0,
    'c', 37, 0, 45, -8, 45, -20,
    'c', 45, -32, 37, -40, 25, -40,
    'm', 34, -27,
    'c', 33, -29, 29, -32, 25, -32,
    'c', 18, -32, 14, -27, 14, -20,
    'c', 14, -13, 18, -8, 25, -8,
    'c', 30, -8, 33, -11, 34, -13,
    'e',
   0xaa, # 'ª'
    2, 15, 18, 43, -27, 2, 3,
    0, 16, #  snap_x
    -42, -23, -20, #  snap_y
    'm', 3, -41,
    'c', 8, -43, 15, -43, 15, -36,
    'l', 15, -27,
    'm', 15, -35,
    'c', 10, -36, 2, -36, 2, -31,
    'c', 2, -25, 15, -26, 15, -34,
    'e',
   0xab, # '«'
    6, 27, 35, 28, -6, 2, 3,
    0, 28, #  snap_x
    -28, -15, -2, #  snap_y
    'm', 14, -28,
    'l', 6, -17,
    'l', 14, -6,
    'm', 27, -28,
    'l', 19, -17,
    'l', 27, -6,
    'e',
   0xac, # '¬'
    4, 32, 38, 22, -10, 2, 1,
    0, 36, #  snap_x
    -24, #  snap_y
    'm', 4, -22,
    'l', 32, -22,
    'l', 32, -10,
    'e',
   0xad, # '­'
    4, 4, 12, 0, 0, 1, 0,
    4, #  snap_x
    #  snap_y
    'e',
   0xae, # '®'
    5, 45, 50, 40, 0, 3, 4,
    0, 9, 24, #  snap_x
    -28, -25, -15, 0, #  snap_y
    'm', 25, -40,
    'c', 13, -40, 5, -32, 5, -20,
    'c', 5, -8, 13, 0, 25, 0,
    'c', 37, 0, 45, -8, 45, -20,
    'c', 45, -32, 37, -40, 25, -40,
    'm', 18, -8,
    'l', 18, -32,
    'l', 24, -32,
    'c', 34, -32, 34, -20, 24, -20,
    'l', 18, -20,
    'm', 26, -20,
    'l', 34, -8,
    'e',
   0xaf, # '¯'
    0, 17, 18, 39, -39, 2, 1,
    0, 36, #  snap_x
    -43, #  snap_y
    'm', 0, -39,
    'l', 17, -39,
    'e',
   0xb0, # '°'
    5, 19, 25, 42, -28, 2, 2,
    0, 12, #  snap_x
    -30, -42, #  snap_y
    'm', 12, -28,
    'c', 8, -28, 5, -31, 5, -35,
    'c', 5, -39, 8, -42, 12, -42,
    'c', 16, -42, 19, -39, 19, -35,
    'c', 19, -31, 16, -28, 12, -28,
    'e',
   0xb1, # '±'
    4, 34, 38, 31, -3, 3, 2,
    0, 18, 36, #  snap_x
    -21, 0, #  snap_y
    'm', 19, -31,
    'l', 19, -9,
    'm', 4, -20,
    'l', 34, -20,
    'm', 4, -3,
    'l', 34, -3,
    'e',
   0xb2, # '²'
    2, 15, 20, 42, -19, 4, 4,
    0, 2, 26, 28, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 3, -41,
    'c', 5, -42, 15, -44, 15, -36,
    'c', 15, -32, 13, -30, 2, -19,
    'l', 15, -19,
    'e',
   0xb3, # '³'
    2, 16, 20, 43, -19, 2, 5,
    0, 28, #  snap_x
    -42, -26, -21, -15, 0, #  snap_y
    'm', 3, -41,
    'c', 17, -46, 20, -31, 6, -31,
    'c', 21, -31, 17, -15, 2, -20,
    'e',
   0xb4, # '´'
    6, 12, 18, 42, -34, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 6, -34,
    'l', 12, -42,
    'e',
   0xb5, # 'µ'
    8, 34, 38, 28, 14, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 34, 0,
    'c', 33, -1, 32, -2, 32, -8,
    'l', 32, -28,
    'm', 32, -12,
    'c', 28, 2, 8, 5, 8, -12,
    'l', 8, -28,
    'l', 8, 14,
    'e',
   0xb6, # '¶'
    2, 30, 38, 42, 5, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 18, -42,
    'l', 18, 5,
    'm', 30, 5,
    'l', 30, -42,
    'l', 14, -42,
    'c', -1, -42, -1, -25, 14, -26,
    'l', 18, -26,
    'e',
   0xb7, # '·'
    7, 9, 17, 20, -18, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 7, -18,
    'l', 7, -20,
    'l', 9, -20,
    'l', 9, -18,
    'l', 7, -18,
    'e',
   0xb8, # '¸'
    8, 18, 18, 0, 14, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 15, 0,
    'l', 11, 5,
    'c', 21, 3, 18, 17, 8, 12,
    'e',
   0xb9, # '¹'
    5, 11, 20, 42, -19, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 5, -37,
    'l', 11, -42,
    'l', 11, -19,
    'e',
   0xba, # 'º'
    3, 18, 22, 43, -25, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 18, -34,
    'c', 18, -45, 3, -45, 3, -34,
    'c', 3, -23, 18, -23, 18, -35,
    'e',
   0xbb, # '»'
    8, 29, 35, 28, -6, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 8, -28,
    'l', 16, -17,
    'l', 8, -6,
    'm', 21, -28,
    'l', 29, -17,
    'l', 21, -6,
    'e',
   0xbc, # '¼'
    6, 44, 52, 42, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 6, -37,
    'l', 12, -42,
    'l', 12, -19,
    'm', 36, -42,
    'l', 12, 0,
    'm', 42, 0,
    'l', 42, -23,
    'l', 31, -6,
    'l', 44, -6,
    'e',
   0xbd, # '½'
    6, 47, 52, 42, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 6, -37,
    'l', 12, -42,
    'l', 12, -19,
    'm', 36, -42,
    'l', 12, 0,
    'm', 35, -22,
    'c', 36, -23, 47, -25, 47, -17,
    'c', 47, -13, 45, -11, 34, 0,
    'l', 47, 0,
    'e',
   0xbe, # '¾'
    4, 44, 52, 43, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 5, -41,
    'c', 19, -46, 22, -31, 8, -31,
    'c', 23, -31, 19, -15, 4, -20,
    'm', 39, -42,
    'l', 15, 0,
    'm', 42, 0,
    'l', 42, -23,
    'l', 31, -6,
    'l', 44, -6,
    'e',
   0xbf, # '¿'
    3, 27, 31, 29, 13, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 27, 11,
    'c', 22, 14, 3, 15, 3, 3,
    'c', 3, -5, 16, -7, 16, -17,
    'm', 17, -29,
    'l', 17, -27,
    'l', 15, -27,
    'l', 15, -29,
    'l', 17, -29,
    'e',
   0xc0, # 'À'
    6, 40, 45, 55, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 25, -47,
    'l', 19, -55,
    'm', 6, 0,
    'l', 23, -42,
    'l', 40, 0,
    'm', 12, -14,
    'l', 34, -14,
    'e',
   0xc1, # 'Á'
    6, 40, 45, 55, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 21, -47,
    'l', 27, -55,
    'm', 6, 0,
    'l', 23, -42,
    'l', 40, 0,
    'm', 12, -14,
    'l', 34, -14,
    'e',
   0xc2, # 'Â'
    6, 40, 45, 55, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 6, 0,
    'l', 23, -42,
    'l', 40, 0,
    'm', 12, -14,
    'l', 34, -14,
    'm', 18, -47,
    'l', 23, -55,
    'l', 28, -47,
    'e',
   0xc3, # 'Ã'
    6, 40, 45, 53, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 6, 0,
    'l', 23, -42,
    'l', 40, 0,
    'm', 12, -14,
    'l', 34, -14,
    'm', 15, -49,
    'c', 21, -62, 25, -38, 31, -51,
    'e',
   0xc4, # 'Ä'
    6, 40, 45, 51, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 6, 0,
    'l', 23, -42,
    'l', 40, 0,
    'm', 12, -14,
    'l', 34, -14,
    'm', 17, -49,
    'l', 17, -51,
    'l', 19, -51,
    'l', 19, -49,
    'l', 17, -49,
    'm', 27, -49,
    'l', 27, -51,
    'l', 29, -51,
    'l', 29, -49,
    'l', 27, -49,
    'e',
   0xc5, # 'Å'
    6, 40, 45, 54, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 23, -46,
    'c', 21, -46, 19, -48, 19, -50,
    'c', 19, -52, 21, -54, 23, -54,
    'c', 25, -54, 27, -52, 27, -50,
    'c', 27, -48, 25, -46, 23, -46,
    'm', 6, 0,
    'l', 23, -42,
    'l', 40, 0,
    'm', 12, -14,
    'l', 34, -14,
    'e',
   0xc6, # 'Æ'
    5, 53, 59, 42, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 5, 0,
    'l', 30, -42,
    'l', 52, -42,
    'm', 33, -42,
    'l', 36, 0,
    'l', 53, 0,
    'm', 50, -22,
    'l', 35, -22,
    'm', 34, -14,
    'l', 14, -14,
    'e',
   0xc7, # 'Ç'
    7, 35, 38, 42, 14, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 35, -40,
    'c', 23, -45, 7, -39, 7, -21,
    'c', 7, -3, 23, 3, 35, -2,
    'm', 25, 0,
    'l', 21, 5,
    'c', 31, 3, 28, 17, 18, 12,
    'e',
   0xc8, # 'È'
    9, 28, 35, 55, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 28, -42,
    'l', 9, -42,
    'l', 9, 0,
    'l', 28, 0,
    'm', 9, -22,
    'l', 26, -22,
    'm', 20, -47,
    'l', 14, -55,
    'e',
   0xc9, # 'É'
    9, 28, 35, 55, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 28, -42,
    'l', 9, -42,
    'l', 9, 0,
    'l', 28, 0,
    'm', 9, -22,
    'l', 26, -22,
    'm', 15, -47,
    'l', 21, -55,
    'e',
   0xca, # 'Ê'
    9, 28, 35, 55, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 28, -42,
    'l', 9, -42,
    'l', 9, 0,
    'l', 28, 0,
    'm', 9, -22,
    'l', 26, -22,
    'm', 13, -47,
    'l', 18, -55,
    'l', 23, -47,
    'e',
   0xcb, # 'Ë'
    9, 28, 35, 51, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 28, -42,
    'l', 9, -42,
    'l', 9, 0,
    'l', 28, 0,
    'm', 9, -22,
    'l', 26, -22,
    'm', 12, -49,
    'l', 12, -51,
    'l', 14, -51,
    'l', 14, -49,
    'l', 12, -49,
    'm', 22, -49,
    'l', 22, -51,
    'l', 24, -51,
    'l', 24, -49,
    'l', 22, -49,
    'e',
   0xcc, # 'Ì'
    3, 9, 17, 55, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 8, -42,
    'l', 8, 0,
    'm', 9, -47,
    'l', 3, -55,
    'e',
   0xcd, # 'Í'
    7, 13, 17, 55, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 8, -42,
    'l', 8, 0,
    'm', 7, -47,
    'l', 13, -55,
    'e',
   0xce, # 'Î'
    3, 13, 17, 55, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 8, -42,
    'l', 8, 0,
    'm', 3, -47,
    'l', 8, -55,
    'l', 13, -47,
    'e',
   0xcf, # 'Ï'
    2, 14, 17, 51, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 8, -42,
    'l', 8, 0,
    'm', 2, -49,
    'l', 2, -51,
    'l', 4, -51,
    'l', 4, -49,
    'l', 2, -49,
    'm', 12, -49,
    'l', 12, -51,
    'l', 14, -51,
    'l', 14, -49,
    'l', 12, -49,
    'e',
   0xd0, # 'Ð'
    2, 39, 45, 42, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 8, 0,
    'l', 8, -42,
    'l', 18, -42,
    'c', 45, -42, 45, 0, 18, 0,
    'l', 8, 0,
    'm', 2, -23,
    'l', 22, -23,
    'e',
   0xd1, # 'Ñ'
    9, 37, 45, 53, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 9, 0,
    'l', 9, -42,
    'l', 37, 0,
    'l', 37, -42,
    'm', 15, -49,
    'c', 21, -62, 25, -38, 31, -51,
    'e',
   0xd2, # 'Ò'
    6, 42, 49, 55, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 6, -21,
    'c', 6, -49, 42, -49, 42, -21,
    'c', 42, 7, 6, 7, 6, -21,
    'm', 26, -47,
    'l', 20, -55,
    'e',
   0xd3, # 'Ó'
    6, 42, 49, 55, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 6, -21,
    'c', 6, -49, 42, -49, 42, -21,
    'c', 42, 7, 6, 7, 6, -21,
    'm', 22, -47,
    'l', 28, -55,
    'e',
   0xd4, # 'Ô'
    6, 42, 49, 55, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 6, -21,
    'c', 6, -49, 42, -49, 42, -21,
    'c', 42, 7, 6, 7, 6, -21,
    'm', 19, -47,
    'l', 24, -55,
    'l', 29, -47,
    'e',
   0xd5, # 'Õ'
    6, 42, 49, 53, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 6, -21,
    'c', 6, -49, 42, -49, 42, -21,
    'c', 42, 7, 6, 7, 6, -21,
    'm', 16, -49,
    'c', 22, -62, 26, -38, 32, -51,
    'e',
   0xd6, # 'Ö'
    6, 42, 49, 51, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 6, -21,
    'c', 6, -49, 42, -49, 42, -21,
    'c', 42, 7, 6, 7, 6, -21,
    'm', 18, -49,
    'l', 18, -51,
    'l', 20, -51,
    'l', 20, -49,
    'l', 18, -49,
    'm', 28, -49,
    'l', 28, -51,
    'l', 30, -51,
    'l', 30, -49,
    'l', 28, -49,
    'e',
   0xd7, # '×'
    7, 30, 38, 27, -4, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 7, -27,
    'l', 30, -4,
    'm', 7, -4,
    'l', 30, -27,
    'e',
   0xd8, # 'Ø'
    6, 42, 49, 43, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 6, -21,
    'c', 6, -49, 42, -49, 42, -21,
    'c', 42, 7, 6, 7, 6, -21,
    'm', 41, -43,
    'l', 8, 0,
    'e',
   0xd9, # 'Ù'
    9, 37, 45, 55, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 9, -42,
    'l', 9, -18,
    'c', 9, 6, 37, 6, 37, -18,
    'l', 37, -42,
    'm', 25, -47,
    'l', 19, -55,
    'e',
   0xda, # 'Ú'
    9, 37, 45, 55, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 9, -42,
    'l', 9, -18,
    'c', 9, 6, 37, 6, 37, -18,
    'l', 37, -42,
    'm', 21, -47,
    'l', 27, -55,
    'e',
   0xdb, # 'Û'
    9, 37, 45, 55, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 9, -42,
    'l', 9, -18,
    'c', 9, 6, 37, 6, 37, -18,
    'l', 37, -42,
    'm', 18, -47,
    'l', 23, -55,
    'l', 28, -47,
    'e',
   0xdc, # 'Ü'
    9, 37, 45, 51, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 9, -42,
    'l', 9, -18,
    'c', 9, 6, 37, 6, 37, -18,
    'l', 37, -42,
    'm', 17, -49,
    'l', 17, -51,
    'l', 19, -51,
    'l', 19, -49,
    'l', 17, -49,
    'm', 27, -49,
    'l', 27, -51,
    'l', 29, -51,
    'l', 29, -49,
    'l', 27, -49,
    'e',
   0xdd, # 'Ý'
    5, 37, 42, 55, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 5, -42,
    'l', 21, -19,
    'l', 21, 0,
    'm', 37, -42,
    'l', 21, -19,
    'm', 19, -47,
    'l', 25, -55,
    'e',
   0xde, # 'Þ'
    8, 31, 35, 42, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 8, 0,
    'l', 8, -42,
    'm', 8, -35,
    'l', 18, -35,
    'c', 35, -35, 35, -13, 18, -13,
    'l', 8, -13,
    'e',
   0xdf, # 'ß'
    8, 34, 38, 42, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 8, 0,
    'l', 8, -27,
    'c', 8, -37, 11, -42, 19, -42,
    'c', 35, -42, 36, -23, 19, -22,
    'c', 39, -22, 39, 6, 16, -2,
    'e',
   0xe0, # 'à'
    4, 28, 35, 45, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 6, -26,
    'c', 15, -30, 28, -29, 28, -17,
    'l', 28, 0,
    'm', 28, -15,
    'c', 18, -16, 4, -16, 4, -7,
    'c', 4, 4, 28, 2, 28, -13,
    'm', 19, -37,
    'l', 13, -45,
    'e',
   0xe1, # 'á'
    4, 28, 35, 45, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 6, -26,
    'c', 15, -30, 28, -29, 28, -17,
    'l', 28, 0,
    'm', 28, -15,
    'c', 18, -16, 4, -16, 4, -7,
    'c', 4, 4, 28, 2, 28, -13,
    'm', 15, -37,
    'l', 21, -45,
    'e',
   0xe2, # 'â'
    4, 28, 35, 45, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 6, -26,
    'c', 15, -30, 28, -29, 28, -17,
    'l', 28, 0,
    'm', 28, -15,
    'c', 18, -16, 4, -16, 4, -7,
    'c', 4, 4, 28, 2, 28, -13,
    'm', 11, -37,
    'l', 16, -45,
    'l', 21, -37,
    'e',
   0xe3, # 'ã'
    4, 28, 35, 43, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 6, -26,
    'c', 15, -30, 28, -29, 28, -17,
    'l', 28, 0,
    'm', 28, -15,
    'c', 18, -16, 4, -16, 4, -7,
    'c', 4, 4, 28, 2, 28, -13,
    'm', 8, -39,
    'c', 14, -52, 18, -28, 24, -41,
    'e',
   0xe4, # 'ä'
    4, 28, 35, 41, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 6, -26,
    'c', 15, -30, 28, -29, 28, -17,
    'l', 28, 0,
    'm', 28, -15,
    'c', 18, -16, 4, -16, 4, -7,
    'c', 4, 4, 28, 2, 28, -13,
    'm', 11, -39,
    'l', 11, -41,
    'l', 13, -41,
    'l', 13, -39,
    'l', 11, -39,
    'm', 21, -39,
    'l', 21, -41,
    'l', 23, -41,
    'l', 23, -39,
    'l', 21, -39,
    'e',
   0xe5, # 'å'
    4, 28, 35, 45, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 6, -26,
    'c', 15, -30, 28, -29, 28, -17,
    'l', 28, 0,
    'm', 28, -15,
    'c', 18, -16, 4, -16, 4, -7,
    'c', 4, 4, 28, 2, 28, -13,
    'm', 16, -37,
    'c', 14, -37, 12, -39, 12, -41,
    'c', 12, -43, 14, -45, 16, -45,
    'c', 18, -45, 20, -43, 20, -41,
    'c', 20, -39, 18, -37, 16, -37,
    'e',
   0xe6, # 'æ'
    4, 49, 56, 29, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 6, -26,
    'c', 15, -30, 26, -29, 26, -17,
    'l', 26, -13,
    'c', 26, 2, 4, 4, 4, -7,
    'c', 4, -16, 18, -16, 26, -15,
    'l', 49, -15,
    'c', 49, -32, 26, -32, 26, -15,
    'c', 26, 2, 40, 1, 49, -2,
    'e',
   0xe7, # 'ç'
    5, 24, 28, 28, 14, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 24, -27,
    'c', 19, -29, 5, -29, 5, -14,
    'c', 5, 0, 19, 1, 24, -1,
    'm', 18, 0,
    'l', 14, 5,
    'c', 24, 3, 21, 17, 11, 12,
    'e',
   0xe8, # 'è'
    4, 28, 35, 45, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 4, -15,
    'l', 28, -15,
    'c', 28, -32, 4, -32, 4, -15,
    'c', 4, 0, 18, 2, 28, -2,
    'm', 19, -37,
    'l', 13, -45,
    'e',
   0xe9, # 'é'
    4, 28, 35, 45, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 4, -15,
    'l', 28, -15,
    'c', 28, -32, 4, -32, 4, -15,
    'c', 4, 0, 18, 2, 28, -2,
    'm', 14, -37,
    'l', 20, -45,
    'e',
   0xea, # 'ê'
    4, 28, 35, 45, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 4, -15,
    'l', 28, -15,
    'c', 28, -32, 4, -32, 4, -15,
    'c', 4, 0, 18, 2, 28, -2,
    'm', 11, -37,
    'l', 16, -45,
    'l', 21, -37,
    'e',
   0xeb, # 'ë'
    4, 28, 35, 41, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 4, -15,
    'l', 28, -15,
    'c', 28, -32, 4, -32, 4, -15,
    'c', 4, 0, 18, 2, 28, -2,
    'm', 10, -39,
    'l', 10, -41,
    'l', 12, -41,
    'l', 12, -39,
    'l', 10, -39,
    'm', 20, -39,
    'l', 20, -41,
    'l', 22, -41,
    'l', 22, -39,
    'l', 20, -39,
    'e',
   0xec, # 'ì'
    3, 9, 17, 45, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 8, -28,
    'l', 8, 0,
    'm', 9, -37,
    'l', 3, -45,
    'e',
   0xed, # 'í'
    7, 13, 17, 45, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 8, -28,
    'l', 8, 0,
    'm', 7, -37,
    'l', 13, -45,
    'e',
   0xee, # 'î'
    3, 13, 17, 45, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 8, -28,
    'l', 8, 0,
    'm', 3, -37,
    'l', 8, -45,
    'l', 13, -37,
    'e',
   0xef, # 'ï'
    2, 14, 17, 41, 0, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 8, -28,
    'l', 8, 0,
    'm', 2, -39,
    'l', 2, -41,
    'l', 4, -41,
    'l', 4, -39,
    'l', 2, -39,
    'm', 12, -39,
    'l', 12, -41,
    'l', 14, -41,
    'l', 14, -39,
    'l', 12, -39,
    'e',
   0xf0, # 'ð'
    5, 31, 38, 42, 1, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 31, -14,
    'c', 31, -33, 5, -33, 5, -14,
    'c', 5, 5, 31, 5, 31, -14,
    'c', 31, -25, 23, -37, 10, -42,
    'm', 9, -33,
    'l', 26, -42,
    'e',
   0xf1, # 'ñ'
    7, 31, 38, 43, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 7, -28,
    'l', 7, 0,
    'm', 7, -16,
    'c', 11, -30, 31, -33, 31, -16,
    'l', 31, 0,
    'm', 11, -39,
    'c', 17, -52, 21, -28, 27, -41,
    'e',
   0xf2, # 'ò'
    6, 32, 38, 45, 1, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 32, -14,
    'c', 32, -33, 6, -33, 6, -14,
    'c', 6, 5, 32, 5, 32, -14,
    'm', 21, -37,
    'l', 15, -45,
    'e',
   0xf3, # 'ó'
    6, 32, 38, 45, 1, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 32, -14,
    'c', 32, -33, 6, -33, 6, -14,
    'c', 6, 5, 32, 5, 32, -14,
    'm', 17, -37,
    'l', 23, -45,
    'e',
   0xf4, # 'ô'
    6, 32, 38, 45, 1, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 32, -14,
    'c', 32, -33, 6, -33, 6, -14,
    'c', 6, 5, 32, 5, 32, -14,
    'm', 14, -37,
    'l', 19, -45,
    'l', 24, -37,
    'e',
   0xf5, # 'õ'
    6, 32, 38, 43, 1, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 32, -14,
    'c', 32, -33, 6, -33, 6, -14,
    'c', 6, 5, 32, 5, 32, -14,
    'm', 11, -39,
    'c', 17, -52, 21, -28, 27, -41,
    'e',
   0xf6, # 'ö'
    6, 32, 38, 41, 1, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 32, -14,
    'c', 32, -33, 6, -33, 6, -14,
    'c', 6, 5, 32, 5, 32, -14,
    'm', 13, -39,
    'l', 13, -41,
    'l', 15, -41,
    'l', 15, -39,
    'l', 13, -39,
    'm', 23, -39,
    'l', 23, -41,
    'l', 25, -41,
    'l', 25, -39,
    'l', 23, -39,
    'e',
   0xf7, # '÷'
    4, 34, 38, 30, -3, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 4, -17,
    'l', 34, -17,
    'm', 18, -3,
    'l', 18, -5,
    'l', 20, -5,
    'l', 20, -3,
    'l', 18, -3,
    'm', 18, -28,
    'l', 18, -30,
    'l', 20, -30,
    'l', 20, -28,
    'l', 18, -28,
    'e',
   0xf8, # 'ø'
    6, 32, 38, 30, 1, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 32, -14,
    'c', 32, -33, 6, -33, 6, -14,
    'c', 6, 5, 32, 5, 32, -14,
    'm', 30, -30,
    'l', 6, 0,
    'e',
   0xf9, # 'ù'
    7, 31, 38, 45, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 31, 0,
    'l', 31, -28,
    'm', 31, -12,
    'c', 27, 2, 7, 5, 7, -12,
    'l', 7, -28,
    'm', 22, -37,
    'l', 16, -45,
    'e',
   0xfa, # 'ú'
    7, 31, 38, 45, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 31, 0,
    'l', 31, -28,
    'm', 31, -12,
    'c', 27, 2, 7, 5, 7, -12,
    'l', 7, -28,
    'm', 16, -37,
    'l', 22, -45,
    'e',
   0xfb, # 'û'
    7, 31, 38, 45, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 31, 0,
    'l', 31, -28,
    'm', 31, -12,
    'c', 27, 2, 7, 5, 7, -12,
    'l', 7, -28,
    'm', 14, -37,
    'l', 19, -45,
    'l', 24, -37,
    'e',
   0xfc, # 'ü'
    7, 31, 38, 41, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 31, 0,
    'l', 31, -28,
    'm', 31, -12,
    'c', 27, 2, 7, 5, 7, -12,
    'l', 7, -28,
    'm', 13, -39,
    'l', 13, -41,
    'l', 15, -41,
    'l', 15, -39,
    'l', 13, -39,
    'm', 23, -39,
    'l', 23, -41,
    'l', 25, -41,
    'l', 25, -39,
    'l', 23, -39,
    'e',
   0xfd, # 'ý'
    3, 26, 31, 45, 13, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 6, -28,
    'l', 16, 0,
    'm', 26, -28,
    'l', 16, 0,
    'c', 12, 13, 9, 14, 3, 12,
    'm', 14, -37,
    'l', 20, -45,
    'e',
   0xfe, # 'þ'
    8, 32, 38, 42, 14, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -42,
    'l', 8, 14,
    'm', 8, -22,
    'c', 11, -26, 14, -28, 19, -28,
    'c', 30, -28, 32, -19, 32, -14,
    'c', 32, -9, 30, 0, 19, 0,
    'c', 14, 0, 11, -2, 8, -6,
    'e',
   0xff, # 'ÿ'
    3, 26, 31, 41, 13, 2, 4,
    0, 24, #  snap_x
    -42, -21, -15, 0, #  snap_y
    'm', 6, -28,
    'l', 16, 0,
    'm', 26, -28,
    'l', 16, 0,
    'c', 12, 13, 9, 14, 3, 12,
    'm', 10, -39,
    'l', 10, -41,
    'l', 12, -41,
    'l', 12, -39,
    'l', 10, -39,
    'm', 20, -39,
    'l', 20, -41,
    'l', 22, -41,
    'l', 22, -39,
    'l', 20, -39,
    'e',
   0x100, # 'Ā'
    6, 40, 45, 48, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 6, 0,
    'l', 23, -42,
    'l', 40, 0,
    'm', 12, -14,
    'l', 34, -14,
    'm', 17, -48,
    'l', 29, -48,
    'e',
   0x101, # 'ā'
    4, 28, 35, 39, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 6, -26,
    'c', 15, -30, 28, -29, 28, -17,
    'l', 28, 0,
    'm', 28, -15,
    'c', 18, -16, 4, -16, 4, -7,
    'c', 4, 4, 28, 2, 28, -13,
    'm', 10, -39,
    'l', 22, -39,
    'e',
   0x102, # 'Ă'
    6, 40, 45, 50, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 6, 0,
    'l', 23, -42,
    'l', 40, 0,
    'm', 12, -14,
    'l', 34, -14,
    'm', 17, -50,
    'c', 20, -46, 26, -46, 29, -50,
    'e',
   0x103, # 'ă'
    4, 28, 35, 40, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 6, -26,
    'c', 15, -30, 28, -29, 28, -17,
    'l', 28, 0,
    'm', 28, -15,
    'c', 18, -16, 4, -16, 4, -7,
    'c', 4, 4, 28, 2, 28, -13,
    'm', 10, -40,
    'c', 13, -36, 19, -36, 22, -40,
    'e',
   0x104, # 'Ą'
    6, 47, 45, 42, 6, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 6, 0,
    'l', 23, -42,
    'l', 40, 0,
    'm', 12, -14,
    'l', 34, -14,
    'm', 40, 0,
    'c', 38, 2, 40, 8, 47, 5,
    'e',
   0x105, # 'ą'
    4, 35, 35, 29, 6, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 6, -26,
    'c', 15, -30, 28, -29, 28, -17,
    'l', 28, 0,
    'm', 28, -15,
    'c', 18, -16, 4, -16, 4, -7,
    'c', 4, 4, 28, 2, 28, -13,
    'm', 28, 0,
    'c', 26, 2, 28, 8, 35, 5,
    'e',
   0x106, # 'Ć'
    7, 35, 38, 55, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 35, -40,
    'c', 23, -45, 7, -39, 7, -21,
    'c', 7, -3, 23, 3, 35, -2,
    'm', 25, -47,
    'l', 31, -55,
    'e',
   0x107, # 'ć'
    5, 24, 31, 42, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 24, -27,
    'c', 19, -29, 5, -29, 5, -14,
    'c', 5, 0, 19, 1, 24, -1,
    'm', 16, -34,
    'l', 22, -42,
    'e',
   0x108, # 'Ĉ'
    7, 35, 38, 55, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 35, -40,
    'c', 23, -45, 7, -39, 7, -21,
    'c', 7, -3, 23, 3, 35, -2,
    'm', 21, -47,
    'l', 26, -55,
    'l', 31, -47,
    'e',
   0x109, # 'ĉ'
    5, 24, 31, 45, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 24, -27,
    'c', 19, -29, 5, -29, 5, -14,
    'c', 5, 0, 19, 1, 24, -1,
    'm', 14, -37,
    'l', 19, -45,
    'l', 24, -37,
    'e',
   0x10a, # 'Ċ'
    7, 35, 38, 51, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 35, -40,
    'c', 23, -45, 7, -39, 7, -21,
    'c', 7, -3, 23, 3, 35, -2,
    'm', 25, -49,
    'l', 25, -51,
    'l', 27, -51,
    'l', 27, -49,
    'l', 25, -49,
    'e',
   0x10b, # 'ċ'
    5, 24, 31, 40, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 24, -27,
    'c', 19, -29, 5, -29, 5, -14,
    'c', 5, 0, 19, 1, 24, -1,
    'm', 16, -38,
    'l', 16, -40,
    'l', 18, -40,
    'l', 18, -38,
    'l', 16, -38,
    'e',
   0x10c, # 'Č'
    7, 35, 38, 55, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 35, -40,
    'c', 23, -45, 7, -39, 7, -21,
    'c', 7, -3, 23, 3, 35, -2,
    'm', 21, -55,
    'l', 26, -47,
    'l', 31, -55,
    'e',
   0x10d, # 'č'
    5, 24, 31, 47, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 24, -27,
    'c', 19, -29, 5, -29, 5, -14,
    'c', 5, 0, 19, 1, 24, -1,
    'm', 14, -47,
    'l', 19, -39,
    'l', 24, -47,
    'e',
   0x10e, # 'Ď'
    8, 39, 45, 55, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, 0,
    'l', 8, -42,
    'l', 18, -42,
    'c', 45, -42, 45, 0, 18, 0,
    'l', 8, 0,
    'm', 17, -55,
    'l', 22, -47,
    'l', 27, -55,
    'e',
   0x10f, # 'ď'
    6, 38, 38, 42, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 30, -42,
    'l', 30, 0,
    'm', 30, -14,
    'c', 30, -32, 6, -32, 6, -14,
    'c', 6, 4, 30, 4, 30, -14,
    'm', 38, -42,
    'l', 36, -34,
    'e',
   0x110, # 'Đ'
    2, 39, 45, 42, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, 0,
    'l', 8, -42,
    'l', 18, -42,
    'c', 45, -42, 45, 0, 18, 0,
    'l', 8, 0,
    'm', 2, -23,
    'l', 22, -23,
    'e',
   0x111, # 'đ'
    6, 38, 38, 42, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 30, -42,
    'l', 30, 0,
    'm', 30, -14,
    'c', 30, -32, 6, -32, 6, -14,
    'c', 6, 4, 30, 4, 30, -14,
    'm', 22, -35,
    'l', 38, -35,
    'e',
   0x112, # 'Ē'
    9, 28, 35, 48, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 28, -42,
    'l', 9, -42,
    'l', 9, 0,
    'l', 28, 0,
    'm', 9, -22,
    'l', 26, -22,
    'm', 12, -48,
    'l', 24, -48,
    'e',
   0x113, # 'ē'
    5, 29, 35, 37, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 5, -15,
    'l', 29, -15,
    'c', 29, -32, 5, -32, 5, -15,
    'c', 5, 0, 19, 2, 29, -2,
    'm', 11, -37,
    'l', 23, -37,
    'e',
   0x114, # 'Ĕ'
    9, 28, 35, 50, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 28, -42,
    'l', 9, -42,
    'l', 9, 0,
    'l', 28, 0,
    'm', 9, -22,
    'l', 26, -22,
    'm', 12, -50,
    'c', 15, -46, 21, -46, 24, -50,
    'e',
   0x115, # 'ĕ'
    5, 29, 35, 40, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 5, -15,
    'l', 29, -15,
    'c', 29, -32, 5, -32, 5, -15,
    'c', 5, 0, 19, 2, 29, -2,
    'm', 11, -40,
    'c', 14, -36, 20, -36, 23, -40,
    'e',
   0x116, # 'Ė'
    9, 28, 35, 51, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 28, -42,
    'l', 9, -42,
    'l', 9, 0,
    'l', 28, 0,
    'm', 9, -22,
    'l', 26, -22,
    'm', 18, -49,
    'l', 18, -51,
    'l', 20, -51,
    'l', 20, -49,
    'l', 18, -49,
    'e',
   0x117, # 'ė'
    5, 29, 35, 41, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 5, -15,
    'l', 29, -15,
    'c', 29, -32, 5, -32, 5, -15,
    'c', 5, 0, 19, 2, 29, -2,
    'm', 16, -39,
    'l', 16, -41,
    'l', 18, -41,
    'l', 18, -39,
    'l', 16, -39,
    'e',
   0x118, # 'Ę'
    9, 33, 35, 42, 6, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 28, -42,
    'l', 9, -42,
    'l', 9, 0,
    'l', 28, 0,
    'm', 9, -22,
    'l', 26, -22,
    'm', 26, 0,
    'c', 24, 2, 26, 8, 33, 5,
    'e',
   0x119, # 'ę'
    5, 29, 35, 28, 6, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 5, -15,
    'l', 29, -15,
    'c', 29, -32, 5, -32, 5, -15,
    'c', 5, 0, 19, 2, 29, -2,
    'm', 22, 0,
    'c', 20, 2, 22, 8, 29, 5,
    'e',
   0x11a, # 'Ě'
    9, 28, 35, 55, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 28, -42,
    'l', 9, -42,
    'l', 9, 0,
    'l', 28, 0,
    'm', 9, -22,
    'l', 26, -22,
    'm', 13, -55,
    'l', 18, -47,
    'l', 23, -55,
    'e',
   0x11b, # 'ě'
    5, 29, 35, 45, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 5, -15,
    'l', 29, -15,
    'c', 29, -32, 5, -32, 5, -15,
    'c', 5, 0, 19, 2, 29, -2,
    'm', 12, -45,
    'l', 17, -37,
    'l', 22, -45,
    'e',
   0x11c, # 'Ĝ'
    6, 37, 45, 55, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 37, -39,
    'c', 25, -46, 6, -41, 6, -21,
    'c', 6, -2, 24, 3, 37, -2,
    'l', 37, -21,
    'l', 26, -21,
    'm', 21, -47,
    'l', 26, -55,
    'l', 31, -47,
    'e',
   0x11d, # 'ĝ'
    5, 29, 38, 45, 15, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 29, -28,
    'l', 29, 0,
    'c', 29, 17, 13, 15, 7, 12,
    'm', 29, -14,
    'c', 29, -32, 5, -32, 5, -14,
    'c', 5, 4, 29, 4, 29, -14,
    'm', 12, -37,
    'l', 17, -45,
    'l', 22, -37,
    'e',
   0x11e, # 'Ğ'
    6, 37, 45, 50, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 37, -39,
    'c', 25, -46, 6, -41, 6, -21,
    'c', 6, -2, 24, 3, 37, -2,
    'l', 37, -21,
    'l', 26, -21,
    'm', 20, -50,
    'c', 23, -46, 29, -46, 32, -50,
    'e',
   0x11f, # 'ğ'
    5, 29, 38, 40, 15, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 29, -28,
    'l', 29, 0,
    'c', 29, 17, 13, 15, 7, 12,
    'm', 29, -14,
    'c', 29, -32, 5, -32, 5, -14,
    'c', 5, 4, 29, 4, 29, -14,
    'm', 11, -40,
    'c', 14, -36, 20, -36, 23, -40,
    'e',
   0x120, # 'Ġ'
    6, 37, 45, 51, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 37, -39,
    'c', 25, -46, 6, -41, 6, -21,
    'c', 6, -2, 24, 3, 37, -2,
    'l', 37, -21,
    'l', 26, -21,
    'm', 25, -49,
    'l', 25, -51,
    'l', 27, -51,
    'l', 27, -49,
    'l', 25, -49,
    'e',
   0x121, # 'ġ'
    5, 29, 38, 41, 15, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 29, -28,
    'l', 29, 0,
    'c', 29, 17, 13, 15, 7, 12,
    'm', 29, -14,
    'c', 29, -32, 5, -32, 5, -14,
    'c', 5, 4, 29, 4, 29, -14,
    'm', 16, -39,
    'l', 16, -41,
    'l', 18, -41,
    'l', 18, -39,
    'l', 16, -39,
    'e',
   0x122, # 'Ģ'
    6, 37, 45, 42, 9, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 37, -39,
    'c', 25, -46, 6, -41, 6, -21,
    'c', 6, -2, 24, 3, 37, -2,
    'l', 37, -21,
    'l', 26, -21,
    'm', 28, 5,
    'l', 26, 9,
    'e',
   0x123, # 'ģ'
    5, 29, 38, 45, 15, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 29, -28,
    'l', 29, 0,
    'c', 29, 17, 13, 15, 7, 12,
    'm', 29, -14,
    'c', 29, -32, 5, -32, 5, -14,
    'c', 5, 4, 29, 4, 29, -14,
    'm', 18, -45,
    'l', 16, -37,
    'e',
   0x124, # 'Ĥ'
    9, 37, 45, 55, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 9, -42,
    'l', 9, 0,
    'm', 37, -42,
    'l', 37, 0,
    'm', 9, -22,
    'l', 37, -22,
    'm', 18, -47,
    'l', 23, -55,
    'l', 28, -47,
    'e',
   0x125, # 'ĥ'
    2, 31, 38, 50, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 7, -42,
    'l', 7, 0,
    'm', 7, -16,
    'c', 11, -30, 31, -33, 31, -16,
    'l', 31, 0,
    'm', 2, -42,
    'l', 7, -50,
    'l', 12, -42,
    'e',
   0x126, # 'Ħ'
    6, 40, 45, 42, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 9, -42,
    'l', 9, 0,
    'm', 37, -42,
    'l', 37, 0,
    'm', 9, -22,
    'l', 37, -22,
    'm', 6, -32,
    'l', 40, -32,
    'e',
   0x127, # 'ħ'
    0, 31, 38, 42, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 7, -42,
    'l', 7, 0,
    'm', 7, -16,
    'c', 11, -30, 31, -33, 31, -16,
    'l', 31, 0,
    'm', 0, -35,
    'l', 14, -35,
    'e',
   0x128, # 'Ĩ'
    0, 16, 17, 53, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -42,
    'l', 8, 0,
    'm', 0, -49,
    'c', 6, -62, 10, -38, 16, -51,
    'e',
   0x129, # 'ĩ'
    0, 16, 17, 43, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -28,
    'l', 8, 0,
    'm', 0, -39,
    'c', 6, -52, 10, -28, 16, -41,
    'e',
   0x12a, # 'Ī'
    2, 14, 17, 48, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -42,
    'l', 8, 0,
    'm', 2, -48,
    'l', 14, -48,
    'e',
   0x12b, # 'ī'
    2, 14, 17, 38, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -28,
    'l', 8, 0,
    'm', 2, -38,
    'l', 14, -38,
    'e',
   0x12c, # 'Ĭ'
    2, 14, 17, 50, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -42,
    'l', 8, 0,
    'm', 2, -50,
    'c', 5, -46, 11, -46, 14, -50,
    'e',
   0x12d, # 'ĭ'
    2, 14, 17, 40, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -28,
    'l', 8, 0,
    'm', 2, -40,
    'c', 5, -36, 11, -36, 14, -40,
    'e',
   0x12e, # 'Į'
    7, 15, 17, 42, 6, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -42,
    'l', 8, 0,
    'c', 6, 2, 8, 8, 15, 5,
    'e',
   0x12f, # 'į'
    7, 15, 17, 41, 6, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -28,
    'l', 8, 0,
    'm', 7, -39,
    'l', 7, -41,
    'l', 9, -41,
    'l', 9, -39,
    'l', 7, -39,
    'm', 8, 0,
    'c', 6, 2, 8, 8, 15, 5,
    'e',
   0x130, # 'İ'
    7, 9, 17, 51, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -42,
    'l', 8, 0,
    'm', 7, -49,
    'l', 7, -51,
    'l', 9, -51,
    'l', 9, -49,
    'l', 7, -49,
    'e',
   0x131, # 'ı'
    8, 8, 17, 28, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -28,
    'l', 8, 0,
    'e',
   0x132, # 'Ĳ'
    8, 21, 30, 42, 6, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -42,
    'l', 8, 0,
    'm', 21, -42,
    'l', 21, -6,
    'c', 21, 8, 11, 6, 8, 5,
    'e',
   0x133, # 'ĳ'
    6, 17, 25, 41, 14, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -28,
    'l', 8, 0,
    'm', 7, -39,
    'l', 7, -41,
    'l', 9, -41,
    'l', 9, -39,
    'l', 7, -39,
    'm', 16, -28,
    'l', 16, 5,
    'c', 16, 12, 12, 15, 6, 13,
    'm', 15, -39,
    'l', 15, -41,
    'l', 17, -41,
    'l', 17, -39,
    'l', 15, -39,
    'e',
   0x134, # 'Ĵ'
    2, 20, 24, 55, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 15, -42,
    'l', 15, -12,
    'c', 15, 2, 5, 0, 2, -1,
    'm', 10, -47,
    'l', 15, -55,
    'l', 20, -47,
    'e',
   0x135, # 'ĵ'
    0, 13, 17, 45, 14, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -28,
    'l', 8, 3,
    'c', 8, 12, 6, 15, 0, 13,
    'm', 3, -37,
    'l', 8, -45,
    'l', 13, -37,
    'e',
   0x136, # 'Ķ'
    8, 36, 42, 42, 9, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -42,
    'l', 8, 0,
    'm', 35, -42,
    'l', 8, -14,
    'm', 16, -22,
    'l', 36, 0,
    'm', 23, 5,
    'l', 21, 9,
    'e',
   0x137, # 'ķ'
    7, 29, 35, 42, 9, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 7, -42,
    'l', 7, 0,
    'm', 26, -30,
    'l', 7, -11,
    'm', 14, -17,
    'l', 29, 0,
    'm', 20, 5,
    'l', 18, 9,
    'e',
   0x138, # 'ĸ'
    8, 27, 32, 28, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -28,
    'l', 8, 0,
    'm', 26, -28,
    'l', 8, -9,
    'm', 14, -15,
    'l', 27, 0,
    'e',
   0x139, # 'Ĺ'
    8, 29, 32, 55, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -42,
    'l', 8, 0,
    'l', 29, 0,
    'm', 16, -47,
    'l', 22, -55,
    'e',
   0x13a, # 'ĺ'
    7, 13, 17, 55, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -42,
    'l', 8, 0,
    'm', 7, -47,
    'l', 13, -55,
    'e',
   0x13b, # 'Ļ'
    8, 29, 32, 42, 9, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -42,
    'l', 8, 0,
    'l', 29, 0,
    'm', 19, 5,
    'l', 17, 9,
    'e',
   0x13c, # 'ļ'
    7, 9, 17, 42, 9, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -42,
    'l', 8, 0,
    'm', 9, 5,
    'l', 7, 9,
    'e',
   0x13d, # 'Ľ'
    8, 29, 32, 42, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -42,
    'l', 8, 0,
    'l', 29, 0,
    'm', 17, -42,
    'l', 15, -38,
    'e',
   0x13e, # 'ľ'
    8, 15, 17, 42, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -42,
    'l', 8, 0,
    'm', 15, -42,
    'l', 13, -38,
    'e',
   0x13f, # 'Ŀ'
    8, 29, 32, 42, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -42,
    'l', 8, 0,
    'l', 29, 0,
    'm', 19, -20,
    'l', 19, -22,
    'l', 21, -22,
    'l', 21, -20,
    'l', 19, -20,
    'e',
   0x140, # 'ŀ'
    8, 16, 17, 42, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -42,
    'l', 8, 0,
    'm', 14, -20,
    'l', 14, -22,
    'l', 16, -22,
    'l', 16, -20,
    'l', 14, -20,
    'e',
   0x141, # 'Ł'
    3, 29, 32, 42, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -42,
    'l', 8, 0,
    'l', 29, 0,
    'm', 3, -15,
    'l', 23, -27,
    'e',
   0x142, # 'ł'
    3, 13, 17, 42, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -42,
    'l', 8, 0,
    'm', 3, -17,
    'l', 13, -25,
    'e',
   0x143, # 'Ń'
    9, 37, 45, 55, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 9, 0,
    'l', 9, -42,
    'l', 37, 0,
    'l', 37, -42,
    'm', 20, -47,
    'l', 26, -55,
    'e',
   0x144, # 'ń'
    7, 31, 38, 45, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 7, -28,
    'l', 7, 0,
    'm', 7, -16,
    'c', 11, -30, 31, -33, 31, -16,
    'l', 31, 0,
    'm', 16, -37,
    'l', 22, -45,
    'e',
   0x145, # 'Ņ'
    9, 37, 45, 42, 9, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 9, 0,
    'l', 9, -42,
    'l', 37, 0,
    'l', 37, -42,
    'm', 24, 5,
    'l', 22, 9,
    'e',
   0x146, # 'ņ'
    7, 31, 38, 28, 9, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 7, -28,
    'l', 7, 0,
    'm', 7, -16,
    'c', 11, -30, 31, -33, 31, -16,
    'l', 31, 0,
    'm', 20, 5,
    'l', 18, 9,
    'e',
   0x147, # 'Ň'
    9, 37, 45, 55, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 9, 0,
    'l', 9, -42,
    'l', 37, 0,
    'l', 37, -42,
    'm', 18, -55,
    'l', 23, -47,
    'l', 28, -55,
    'e',
   0x148, # 'ň'
    7, 31, 38, 45, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 7, -28,
    'l', 7, 0,
    'm', 7, -16,
    'c', 11, -30, 31, -33, 31, -16,
    'l', 31, 0,
    'm', 14, -45,
    'l', 19, -37,
    'l', 24, -45,
    'e',
   0x149, # 'ŉ'
    3, 31, 38, 35, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 7, -28,
    'l', 7, 0,
    'm', 7, -16,
    'c', 11, -30, 31, -33, 31, -16,
    'l', 31, 0,
    'm', 5, -35,
    'l', 3, -31,
    'e',
   0x14a, # 'Ŋ'
    9, 41, 50, 42, 13, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 9, -42,
    'l', 9, 0,
    'm', 9, -24,
    'c', 13, -44, 41, -50, 41, -24,
    'l', 41, 0,
    'c', 41, 11, 40, 13, 25, 13,
    'e',
   0x14b, # 'ŋ'
    7, 31, 38, 28, 11, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 7, -28,
    'l', 7, 0,
    'm', 7, -16,
    'c', 11, -30, 31, -33, 31, -16,
    'l', 31, 0,
    'c', 31, 10, 30, 11, 20, 11,
    'e',
   0x14c, # 'Ō'
    6, 42, 49, 48, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 6, -21,
    'c', 6, -49, 42, -49, 42, -21,
    'c', 42, 7, 6, 7, 6, -21,
    'm', 18, -48,
    'l', 30, -48,
    'e',
   0x14d, # 'ō'
    6, 32, 38, 38, 1, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 32, -14,
    'c', 32, -33, 6, -33, 6, -14,
    'c', 6, 5, 32, 5, 32, -14,
    'm', 13, -38,
    'l', 25, -38,
    'e',
   0x14e, # 'Ŏ'
    6, 42, 49, 50, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 6, -21,
    'c', 6, -49, 42, -49, 42, -21,
    'c', 42, 7, 6, 7, 6, -21,
    'm', 18, -50,
    'c', 21, -46, 27, -46, 30, -50,
    'e',
   0x14f, # 'ŏ'
    6, 32, 38, 40, 1, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 32, -14,
    'c', 32, -33, 6, -33, 6, -14,
    'c', 6, 5, 32, 5, 32, -14,
    'm', 13, -40,
    'c', 16, -36, 22, -36, 25, -40,
    'e',
   0x150, # 'Ő'
    6, 42, 49, 55, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 6, -21,
    'c', 6, -49, 42, -49, 42, -21,
    'c', 42, 7, 6, 7, 6, -21,
    'm', 20, -47,
    'l', 26, -55,
    'm', 28, -47,
    'l', 34, -55,
    'e',
   0x151, # 'ő'
    6, 32, 38, 45, 1, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 32, -14,
    'c', 32, -33, 6, -33, 6, -14,
    'c', 6, 5, 32, 5, 32, -14,
    'm', 15, -37,
    'l', 21, -45,
    'm', 23, -37,
    'l', 29, -45,
    'e',
   0x152, # 'Œ'
    6, 53, 59, 42, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 34, -3,
    'c', 20, 5, 6, -4, 6, -21,
    'c', 6, -38, 20, -47, 34, -39,
    'm', 53, -42,
    'l', 34, -42,
    'l', 34, 0,
    'l', 53, 0,
    'm', 34, -22,
    'l', 51, -22,
    'e',
   0x153, # 'œ'
    5, 55, 59, 29, 1, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 31, -14,
    'c', 31, -33, 5, -33, 5, -14,
    'c', 5, 5, 31, 5, 31, -14,
    'm', 31, -15,
    'l', 55, -15,
    'c', 55, -32, 31, -32, 31, -15,
    'c', 31, 0, 45, 2, 55, -2,
    'e',
   0x154, # 'Ŕ'
    8, 33, 38, 55, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, 0,
    'l', 8, -42,
    'l', 18, -42,
    'c', 34, -42, 34, -22, 18, -22,
    'l', 8, -22,
    'm', 22, -22,
    'l', 33, 0,
    'm', 17, -47,
    'l', 23, -55,
    'e',
   0x155, # 'ŕ'
    8, 22, 24, 45, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -28,
    'l', 8, 0,
    'm', 8, -12,
    'c', 10, -22, 15, -28, 22, -28,
    'm', 13, -37,
    'l', 19, -45,
    'e',
   0x156, # 'Ŗ'
    8, 33, 38, 42, 9, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, 0,
    'l', 8, -42,
    'l', 18, -42,
    'c', 34, -42, 34, -22, 18, -22,
    'l', 8, -22,
    'm', 22, -22,
    'l', 33, 0,
    'm', 21, 5,
    'l', 19, 9,
    'e',
   0x157, # 'ŗ'
    8, 22, 24, 28, 9, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -28,
    'l', 8, 0,
    'm', 8, -12,
    'c', 10, -22, 15, -28, 22, -28,
    'm', 17, 5,
    'l', 15, 9,
    'e',
   0x158, # 'Ř'
    8, 33, 38, 55, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, 0,
    'l', 8, -42,
    'l', 18, -42,
    'c', 34, -42, 34, -22, 18, -22,
    'l', 8, -22,
    'm', 22, -22,
    'l', 33, 0,
    'm', 14, -55,
    'l', 19, -47,
    'l', 24, -55,
    'e',
   0x159, # 'ř'
    8, 22, 24, 45, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -28,
    'l', 8, 0,
    'm', 8, -12,
    'c', 10, -22, 15, -28, 22, -28,
    'm', 10, -45,
    'l', 15, -37,
    'l', 20, -45,
    'e',
   0x15a, # 'Ś'
    4, 27, 31, 55, 1, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 25, -41,
    'c', 21, -42, 4, -45, 4, -32,
    'c', 4, -21, 27, -23, 27, -11,
    'c', 26, 3, 8, 1, 4, -2,
    'm', 14, -47,
    'l', 20, -55,
    'e',
   0x15b, # 'ś'
    4, 19, 29, 45, 1, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 19, -27,
    'c', 17, -28, 4, -30, 4, -21,
    'c', 4, -15, 19, -14, 19, -7,
    'c', 19, 2, 9, 1, 4, -1,
    'm', 11, -37,
    'l', 17, -45,
    'e',
   0x15c, # 'Ŝ'
    4, 27, 31, 55, 1, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 25, -41,
    'c', 21, -42, 4, -45, 4, -32,
    'c', 4, -21, 27, -23, 27, -11,
    'c', 26, 3, 8, 1, 4, -2,
    'm', 11, -47,
    'l', 16, -55,
    'l', 21, -47,
    'e',
   0x15d, # 'ŝ'
    4, 19, 29, 45, 1, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 19, -27,
    'c', 17, -28, 4, -30, 4, -21,
    'c', 4, -15, 19, -14, 19, -7,
    'c', 19, 2, 9, 1, 4, -1,
    'm', 7, -37,
    'l', 12, -45,
    'l', 17, -37,
    'e',
   0x15e, # 'Ş'
    4, 27, 36, 43, 14, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 25, -41,
    'c', 21, -42, 4, -45, 4, -32,
    'c', 4, -21, 27, -23, 27, -11,
    'c', 26, 3, 8, 1, 4, -2,
    'm', 17, 0,
    'l', 13, 5,
    'c', 23, 3, 20, 17, 10, 12,
    'e',
   0x15f, # 'ş'
    4, 19, 24, 28, 14, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 19, -27,
    'c', 17, -28, 4, -30, 4, -21,
    'c', 4, -15, 19, -14, 19, -7,
    'c', 19, 2, 9, 1, 4, -1,
    'm', 14, 0,
    'l', 10, 5,
    'c', 20, 3, 17, 17, 7, 12,
    'e',
   0x160, # 'Š'
    4, 27, 31, 55, 1, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 25, -41,
    'c', 21, -42, 4, -45, 4, -32,
    'c', 4, -21, 27, -23, 27, -11,
    'c', 26, 3, 8, 1, 4, -2,
    'm', 11, -55,
    'l', 16, -47,
    'l', 21, -55,
    'e',
   0x161, # 'š'
    4, 19, 24, 45, 1, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 19, -27,
    'c', 17, -28, 4, -30, 4, -21,
    'c', 4, -15, 19, -14, 19, -7,
    'c', 19, 2, 9, 1, 4, -1,
    'm', 7, -45,
    'l', 12, -37,
    'l', 17, -45,
    'e',
   0x162, # 'Ţ'
    3, 31, 35, 42, 14, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 17, -42,
    'l', 17, 0,
    'm', 3, -42,
    'l', 31, -42,
    'm', 17, 0,
    'l', 13, 5,
    'c', 23, 3, 20, 17, 10, 12,
    'e',
   0x163, # 'ţ'
    3, 20, 25, 38, 14, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 11, -38,
    'l', 11, -10,
    'c', 11, -1, 15, 1, 20, -1,
    'm', 3, -28,
    'l', 19, -28,
    'm', 17, 0,
    'l', 13, 5,
    'c', 23, 3, 20, 17, 10, 12,
    'e',
   0x164, # 'Ť'
    3, 31, 35, 55, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 17, -42,
    'l', 17, 0,
    'm', 3, -42,
    'l', 31, -42,
    'm', 12, -55,
    'l', 17, -47,
    'l', 22, -55,
    'e',
   0x165, # 'ť'
    3, 20, 25, 42, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 11, -38,
    'l', 11, -10,
    'c', 11, -1, 15, 1, 20, -1,
    'm', 3, -28,
    'l', 19, -28,
    'm', 18, -42,
    'l', 16, -38,
    'e',
   0x166, # 'Ŧ'
    3, 31, 35, 42, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 17, -42,
    'l', 17, 0,
    'm', 3, -42,
    'l', 31, -42,
    'm', 10, -21,
    'l', 24, -21,
    'e',
   0x167, # 'ŧ'
    3, 20, 25, 38, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 11, -38,
    'l', 11, -10,
    'c', 11, -1, 15, 1, 20, -1,
    'm', 3, -28,
    'l', 19, -28,
    'm', 3, -18,
    'l', 19, -18,
    'e',
   0x168, # 'Ũ'
    8, 36, 45, 53, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -42,
    'l', 8, -18,
    'c', 8, 6, 36, 6, 36, -18,
    'l', 36, -42,
    'm', 14, -49,
    'c', 20, -62, 24, -38, 30, -51,
    'e',
   0x169, # 'ũ'
    7, 31, 38, 43, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 31, 0,
    'l', 31, -28,
    'm', 31, -12,
    'c', 27, 2, 7, 5, 7, -12,
    'l', 7, -28,
    'm', 11, -39,
    'c', 17, -52, 21, -28, 27, -41,
    'e',
   0x16a, # 'Ū'
    8, 36, 45, 48, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -42,
    'l', 8, -18,
    'c', 8, 6, 36, 6, 36, -18,
    'l', 36, -42,
    'm', 16, -48,
    'l', 28, -48,
    'e',
   0x16b, # 'ū'
    7, 31, 38, 38, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 31, 0,
    'l', 31, -28,
    'm', 31, -12,
    'c', 27, 2, 7, 5, 7, -12,
    'l', 7, -28,
    'm', 13, -38,
    'l', 25, -38,
    'e',
   0x16c, # 'Ŭ'
    8, 36, 45, 50, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -42,
    'l', 8, -18,
    'c', 8, 6, 36, 6, 36, -18,
    'l', 36, -42,
    'm', 16, -50,
    'c', 19, -46, 25, -46, 28, -50,
    'e',
   0x16d, # 'ŭ'
    7, 31, 38, 40, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 31, 0,
    'l', 31, -28,
    'm', 31, -12,
    'c', 27, 2, 7, 5, 7, -12,
    'l', 7, -28,
    'm', 13, -40,
    'c', 16, -36, 22, -36, 25, -40,
    'e',
   0x16e, # 'Ů'
    8, 36, 45, 54, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -42,
    'l', 8, -18,
    'c', 8, 6, 36, 6, 36, -18,
    'l', 36, -42,
    'm', 22, -46,
    'c', 20, -46, 18, -48, 18, -50,
    'c', 18, -52, 20, -54, 22, -54,
    'c', 24, -54, 26, -52, 26, -50,
    'c', 26, -48, 24, -46, 22, -46,
    'e',
   0x16f, # 'ů'
    7, 31, 38, 45, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 31, 0,
    'l', 31, -28,
    'm', 31, -12,
    'c', 27, 2, 7, 5, 7, -12,
    'l', 7, -28,
    'm', 19, -37,
    'c', 17, -37, 15, -39, 15, -41,
    'c', 15, -43, 17, -45, 19, -45,
    'c', 21, -45, 23, -43, 23, -41,
    'c', 23, -39, 21, -37, 19, -37,
    'e',
   0x170, # 'Ű'
    8, 36, 45, 55, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -42,
    'l', 8, -18,
    'c', 8, 6, 36, 6, 36, -18,
    'l', 36, -42,
    'm', 18, -47,
    'l', 24, -55,
    'm', 26, -47,
    'l', 32, -55,
    'e',
   0x171, # 'ű'
    7, 31, 38, 45, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 31, 0,
    'l', 31, -28,
    'm', 31, -12,
    'c', 27, 2, 7, 5, 7, -12,
    'l', 7, -28,
    'm', 15, -37,
    'l', 21, -45,
    'm', 23, -37,
    'l', 29, -45,
    'e',
   0x172, # 'Ų'
    8, 36, 45, 42, 6, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -42,
    'l', 8, -18,
    'c', 8, 6, 36, 6, 36, -18,
    'l', 36, -42,
    'm', 22, 0,
    'c', 20, 2, 22, 8, 29, 5,
    'e',
   0x173, # 'ų'
    7, 31, 38, 28, 6, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 31, 0,
    'l', 31, -28,
    'm', 31, -12,
    'c', 27, 2, 7, 5, 7, -12,
    'l', 7, -28,
    'm', 17, 0,
    'c', 15, 2, 17, 8, 24, 5,
    'e',
   0x174, # 'Ŵ'
    4, 44, 45, 55, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 4, -42,
    'l', 16, 0,
    'l', 24, -28,
    'l', 32, 0,
    'l', 44, -42,
    'm', 19, -47,
    'l', 24, -55,
    'l', 29, -47,
    'e',
   0x175, # 'ŵ'
    6, 46, 47, 45, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 6, -28,
    'l', 16, 0,
    'l', 26, -28,
    'l', 36, 0,
    'l', 46, -28,
    'm', 21, -37,
    'l', 26, -45,
    'l', 31, -37,
    'e',
   0x176, # 'Ŷ'
    5, 37, 42, 55, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 5, -42,
    'l', 21, -19,
    'l', 21, 0,
    'm', 37, -42,
    'l', 21, -19,
    'm', 16, -47,
    'l', 21, -55,
    'l', 26, -47,
    'e',
   0x177, # 'ŷ'
    3, 26, 31, 45, 13, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 6, -28,
    'l', 16, 0,
    'm', 26, -28,
    'l', 16, 0,
    'c', 12, 13, 9, 14, 3, 12,
    'm', 11, -37,
    'l', 16, -45,
    'l', 21, -37,
    'e',
   0x178, # 'Ÿ'
    5, 37, 42, 51, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 5, -42,
    'l', 21, -19,
    'l', 21, 0,
    'm', 37, -42,
    'l', 21, -19,
    'm', 15, -49,
    'l', 15, -51,
    'l', 17, -51,
    'l', 17, -49,
    'l', 15, -49,
    'm', 25, -49,
    'l', 25, -51,
    'l', 27, -51,
    'l', 27, -49,
    'l', 25, -49,
    'e',
   0x179, # 'Ź'
    3, 31, 35, 55, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 3, -42,
    'l', 31, -42,
    'l', 3, 0,
    'l', 31, 0,
    'm', 16, -47,
    'l', 22, -55,
    'e',
   0x17a, # 'ź'
    5, 27, 31, 45, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 5, -28,
    'l', 27, -28,
    'l', 5, 0,
    'l', 27, 0,
    'm', 15, -37,
    'l', 21, -45,
    'e',
   0x17b, # 'Ż'
    3, 31, 35, 51, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 3, -42,
    'l', 31, -42,
    'l', 3, 0,
    'l', 31, 0,
    'm', 16, -49,
    'l', 16, -51,
    'l', 18, -51,
    'l', 18, -49,
    'l', 16, -49,
    'e',
   0x17c, # 'ż'
    5, 27, 31, 40, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 5, -28,
    'l', 27, -28,
    'l', 5, 0,
    'l', 27, 0,
    'm', 16, -38,
    'l', 16, -40,
    'l', 18, -40,
    'l', 18, -38,
    'l', 16, -38,
    'e',
   0x17d, # 'Ž'
    3, 31, 35, 55, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 3, -42,
    'l', 31, -42,
    'l', 3, 0,
    'l', 31, 0,
    'm', 12, -55,
    'l', 17, -47,
    'l', 22, -55,
    'e',
   0x17e, # 'ž'
    5, 27, 31, 45, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 5, -28,
    'l', 27, -28,
    'l', 5, 0,
    'l', 27, 0,
    'm', 11, -45,
    'l', 16, -37,
    'l', 21, -45,
    'e',
   0x17f, # 'ſ'
    3, 21, 24, 42, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 21, -41,
    'c', 15, -43, 11, -40, 11, -33,
    'l', 11, 0,
    'm', 3, -27,
    'l', 11, -27,
    'e',
   0x1c0, # 'ǀ'
    8, 8, 17, 44, 6, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -44,
    'l', 8, 6,
    'e',
   0x1c1, # 'ǁ'
    8, 16, 25, 44, 6, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -44,
    'l', 8, 6,
    'm', 16, -44,
    'l', 16, 6,
    'e',
   0x1c2, # 'ǂ'
    3, 17, 21, 44, 6, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 10, -44,
    'l', 10, 6,
    'm', 3, -26,
    'l', 17, -26,
    'm', 17, -14,
    'l', 3, -14,
    'e',
   0x1c3, # 'ǃ'
    11, 13, 24, 42, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 12, -42,
    'l', 12, -14,
    'm', 11, 0,
    'l', 11, -2,
    'l', 13, -2,
    'l', 13, 0,
    'l', 11, 0,
    'e',
   0x1c4, # 'Ǆ'
    8, 68, 72, 55, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, 0,
    'l', 8, -42,
    'l', 18, -42,
    'c', 45, -42, 45, 0, 18, 0,
    'l', 8, 0,
    'm', 40, -42,
    'l', 68, -42,
    'l', 40, 0,
    'l', 68, 0,
    'm', 49, -55,
    'l', 54, -47,
    'l', 59, -55,
    'e',
   0x1c5, # 'ǅ'
    8, 65, 69, 45, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, 0,
    'l', 8, -42,
    'l', 18, -42,
    'c', 45, -42, 45, 0, 18, 0,
    'l', 8, 0,
    'm', 43, -28,
    'l', 65, -28,
    'l', 43, 0,
    'l', 65, 0,
    'm', 49, -45,
    'l', 54, -37,
    'l', 59, -45,
    'e',
   0x1c6, # 'ǆ'
    6, 59, 63, 45, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 30, -42,
    'l', 30, 0,
    'm', 30, -14,
    'c', 30, -32, 6, -32, 6, -14,
    'c', 6, 4, 30, 4, 30, -14,
    'm', 37, -28,
    'l', 59, -28,
    'l', 37, 0,
    'l', 59, 0,
    'm', 43, -45,
    'l', 48, -37,
    'l', 53, -45,
    'e',
   0x1c7, # 'Ǉ'
    8, 39, 48, 42, 6, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -42,
    'l', 8, 0,
    'l', 29, 0,
    'm', 39, -42,
    'l', 39, -6,
    'c', 39, 8, 29, 6, 26, 5,
    'e',
   0x1c8, # 'ǈ'
    8, 38, 45, 42, 14, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -42,
    'l', 8, 0,
    'l', 29, 0,
    'm', 37, -28,
    'l', 37, 3,
    'c', 37, 12, 35, 15, 29, 13,
    'm', 36, -39,
    'l', 36, -41,
    'l', 38, -41,
    'l', 38, -39,
    'l', 36, -39,
    'e',
   0x1c9, # 'ǉ'
    8, 17, 25, 42, 14, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -42,
    'l', 8, 0,
    'm', 16, -28,
    'l', 16, 3,
    'c', 16, 12, 14, 15, 8, 13,
    'm', 15, -39,
    'l', 15, -41,
    'l', 17, -41,
    'l', 17, -39,
    'l', 15, -39,
    'e',
   0x1ca, # 'Ǌ'
    9, 47, 56, 42, 6, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 9, 0,
    'l', 9, -42,
    'l', 37, 0,
    'l', 37, -42,
    'm', 47, -42,
    'l', 47, -6,
    'c', 47, 8, 37, 6, 34, 5,
    'e',
   0x1cb, # 'ǋ'
    9, 46, 53, 42, 14, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 9, 0,
    'l', 9, -42,
    'l', 37, 0,
    'l', 37, -42,
    'm', 45, -28,
    'l', 45, 3,
    'c', 45, 12, 43, 15, 37, 13,
    'm', 44, -39,
    'l', 44, -41,
    'l', 46, -41,
    'l', 46, -39,
    'l', 44, -39,
    'e',
   0x1cc, # 'ǌ'
    7, 40, 47, 41, 14, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 7, -28,
    'l', 7, 0,
    'm', 7, -16,
    'c', 11, -30, 31, -33, 31, -16,
    'l', 31, 0,
    'm', 39, -28,
    'l', 39, 3,
    'c', 39, 12, 37, 15, 31, 13,
    'm', 38, -39,
    'l', 38, -41,
    'l', 40, -41,
    'l', 40, -39,
    'l', 38, -39,
    'e',
   0x1cd, # 'Ǎ'
    6, 40, 45, 55, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 6, 0,
    'l', 23, -42,
    'l', 40, 0,
    'm', 12, -14,
    'l', 34, -14,
    'm', 18, -55,
    'l', 23, -47,
    'l', 28, -55,
    'e',
   0x1ce, # 'ǎ'
    4, 28, 35, 45, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 6, -26,
    'c', 15, -30, 28, -29, 28, -17,
    'l', 28, 0,
    'm', 28, -15,
    'c', 18, -16, 4, -16, 4, -7,
    'c', 4, 4, 28, 2, 28, -13,
    'm', 11, -45,
    'l', 16, -37,
    'l', 21, -45,
    'e',
   0x1cf, # 'Ǐ'
    3, 13, 17, 55, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -42,
    'l', 8, 0,
    'm', 3, -55,
    'l', 8, -47,
    'l', 13, -55,
    'e',
   0x1d0, # 'ǐ'
    3, 13, 17, 45, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -28,
    'l', 8, 0,
    'm', 3, -45,
    'l', 8, -37,
    'l', 13, -45,
    'e',
   0x1d1, # 'Ǒ'
    6, 42, 49, 55, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 6, -21,
    'c', 6, -49, 42, -49, 42, -21,
    'c', 42, 7, 6, 7, 6, -21,
    'm', 19, -55,
    'l', 24, -47,
    'l', 29, -55,
    'e',
   0x1d2, # 'ǒ'
    6, 32, 38, 45, 1, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 32, -14,
    'c', 32, -33, 6, -33, 6, -14,
    'c', 6, 5, 32, 5, 32, -14,
    'm', 14, -45,
    'l', 19, -37,
    'l', 24, -45,
    'e',
   0x1d3, # 'Ǔ'
    8, 36, 45, 55, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -42,
    'l', 8, -18,
    'c', 8, 6, 36, 6, 36, -18,
    'l', 36, -42,
    'm', 17, -55,
    'l', 22, -47,
    'l', 27, -55,
    'e',
   0x1d4, # 'ǔ'
    7, 31, 38, 45, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 31, 0,
    'l', 31, -28,
    'm', 31, -12,
    'c', 27, 2, 7, 5, 7, -12,
    'l', 7, -28,
    'm', 14, -45,
    'l', 19, -37,
    'l', 24, -45,
    'e',
   0x2d8, # '˘'
    2, 14, 16, 40, -37, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 2, -40,
    'c', 5, -36, 11, -36, 14, -40,
    'e',
   0x2d9, # '˙'
    7, 9, 16, 41, -39, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 7, -39,
    'l', 7, -41,
    'l', 9, -41,
    'l', 9, -39,
    'l', 7, -39,
    'e',
   0x2da, # '˚'
    4, 12, 16, 45, -37, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -37,
    'c', 6, -37, 4, -39, 4, -41,
    'c', 4, -43, 6, -45, 8, -45,
    'c', 10, -45, 12, -43, 12, -41,
    'c', 12, -39, 10, -37, 8, -37,
    'e',
   0x2db, # '˛'
    6, 14, 16, 0, 6, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 7, 0,
    'c', 5, 2, 7, 8, 14, 5,
    'e',
   0x2dc, # '˜'
    0, 16, 16, 43, -37, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -39,
    'c', 6, -52, 10, -28, 16, -41,
    'e',
   0x2dd, # '˝'
    1, 15, 16, 45, -37, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 1, -37,
    'l', 7, -45,
    'm', 9, -37,
    'l', 15, -45,
    'e',
   0x300, # '̀'
    13, 19, 31, 55, -47, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 19, -47,
    'l', 13, -55,
    'e',
   0x301, # '́'
    13, 19, 31, 55, -47, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 13, -47,
    'l', 19, -55,
    'e',
   0x302, # '̂'
    11, 21, 33, 55, -47, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 11, -47,
    'l', 16, -55,
    'l', 21, -47,
    'e',
   0x303, # '̃'
    8, 24, 36, 53, -47, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -49,
    'c', 14, -62, 18, -38, 24, -51,
    'e',
   0x304, # '̄'
    10, 22, 36, 48, -48, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 10, -48,
    'l', 22, -48,
    'e',
   0x306, # '̆'
    10, 22, 34, 50, -47, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 10, -50,
    'c', 13, -46, 19, -46, 22, -50,
    'e',
   0x307, # '̇'
    15, 17, 29, 51, -49, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 15, -49,
    'l', 15, -51,
    'l', 17, -51,
    'l', 17, -49,
    'l', 15, -49,
    'e',
   0x308, # '̈'
    10, 22, 34, 51, -49, 2, 2,
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
   0x30a, # '̊'
    12, 20, 32, 54, -46, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 16, -46,
    'c', 14, -46, 12, -48, 12, -50,
    'c', 12, -52, 14, -54, 16, -54,
    'c', 18, -54, 20, -52, 20, -50,
    'c', 20, -48, 18, -46, 16, -46,
    'e',
   0x30b, # '̋'
    9, 23, 35, 55, -47, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 9, -47,
    'l', 15, -55,
    'm', 17, -47,
    'l', 23, -55,
    'e',
   0x30c, # '̌'
    11, 21, 33, 55, -47, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 11, -55,
    'l', 16, -47,
    'l', 21, -55,
    'e',
   0x327, # '̧'
    14, 16, 28, -5, 9, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 16, 5,
    'l', 14, 9,
    'e',
   0x328, # '̨'
    12, 20, 32, 0, 6, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 13, 0,
    'c', 11, 2, 13, 8, 20, 5,
    'e',
   0x370, # 'Ͱ'
    30, 32, 44, 42, -34, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 32, -42,
    'l', 30, -34,
    'e',
   0x2010, # '‐'
    4, 20, 24, 17, -17, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 4, -17,
    'l', 20, -17,
    'e',
   0x2011, # '‑'
    4, 20, 24, 17, -17, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 4, -17,
    'l', 20, -17,
    'e',
   0x2012, # '‒'
    5, 29, 35, 17, -17, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 5, -17,
    'l', 29, -17,
    'e',
   0x2013, # '–'
    0, 28, 28, 17, -17, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -17,
    'l', 28, -17,
    'e',
   0x2014, # '—'
    0, 56, 56, 17, -17, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -17,
    'l', 56, -17,
    'e',
   0x2015, # '―'
    0, 40, 52, 17, -17, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 0, -17,
    'l', 40, -17,
    'e',
   0x2016, # '‖'
    8, 16, 25, 42, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, -42,
    'l', 8, 0,
    'm', 16, 0,
    'l', 16, -42,
    'e',
   0x2017, # '‗'
    5, 29, 34, 8, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 5, 0,
    'l', 29, 0,
    'm', 29, -8,
    'l', 5, -8,
    'e',
   0x2018, # '‘'
    6, 10, 17, 42, -32, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 7, -34,
    'l', 8, -34,
    'l', 8, -32,
    'l', 6, -32,
    'c', 6, -36, 7, -40, 10, -42,
    'e',
   0x2019, # '’'
    6, 10, 17, 42, -32, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 9, -40,
    'l', 8, -40,
    'l', 8, -42,
    'l', 10, -42,
    'c', 10, -38, 9, -34, 6, -32,
    'e',
   0x201a, # '‚'
    5, 9, 17, 2, 8, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 8, 0,
    'l', 7, 0,
    'l', 7, -2,
    'l', 9, -2,
    'c', 9, 2, 8, 6, 5, 8,
    'e',
   0x201b, # '‛'
    6, 10, 17, 42, -32, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 7, -40,
    'l', 8, -40,
    'l', 8, -42,
    'l', 6, -42,
    'c', 6, -38, 7, -34, 10, -32,
    'e',
   0x201c, # '“'
    10, 26, 35, 42, -32, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 11, -34,
    'l', 12, -34,
    'l', 12, -32,
    'l', 10, -32,
    'c', 10, -36, 11, -40, 14, -42,
    'm', 23, -34,
    'l', 24, -34,
    'l', 24, -32,
    'l', 22, -32,
    'c', 22, -36, 23, -40, 26, -42,
    'e',
   0x201d, # '”'
    9, 25, 35, 42, -32, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 12, -40,
    'l', 11, -40,
    'l', 11, -42,
    'l', 13, -42,
    'c', 13, -38, 12, -34, 9, -32,
    'm', 24, -40,
    'l', 23, -40,
    'l', 23, -42,
    'l', 25, -42,
    'c', 25, -38, 24, -34, 21, -32,
    'e',
   0x201e, # '„'
    9, 25, 35, 4, 6, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 12, -2,
    'l', 11, -2,
    'l', 11, -4,
    'l', 13, -4,
    'c', 13, 0, 12, 4, 9, 6,
    'm', 24, -2,
    'l', 23, -2,
    'l', 23, -4,
    'l', 25, -4,
    'c', 25, 0, 24, 4, 21, 6,
    'e',
   0x201f, # '‟'
    10, 26, 35, 42, -32, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 11, -40,
    'l', 12, -40,
    'l', 12, -42,
    'l', 10, -42,
    'c', 10, -38, 11, -34, 14, -32,
    'm', 23, -40,
    'l', 24, -40,
    'l', 24, -42,
    'l', 22, -42,
    'c', 22, -38, 23, -34, 26, -32,
    'e',
   0x2020, # '†'
    5, 29, 35, 42, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 17, -42,
    'l', 17, 0,
    'm', 5, -30,
    'l', 29, -30,
    'e',
   0x2021, # '‡'
    5, 29, 35, 42, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 17, -42,
    'l', 17, 0,
    'm', 5, -30,
    'l', 29, -30,
    'm', 5, -12,
    'l', 29, -12,
    'e',
   0x2022, # '•'
    7, 25, 31, 30, -12, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 7, -21,
    'c', 7, -27, 11, -30, 16, -30,
    'c', 21, -30, 25, -26, 25, -21,
    'c', 25, -16, 21, -12, 16, -12,
    'c', 11, -12, 7, -16, 7, -21,
    'm', 9, -25,
    'l', 9, -17,
    'm', 11, -15,
    'l', 11, -27,
    'm', 13, -28,
    'l', 13, -14,
    'm', 15, -13,
    'l', 15, -29,
    'm', 17, -29,
    'l', 17, -13,
    'm', 19, -14,
    'l', 19, -28,
    'm', 21, -27,
    'l', 21, -15,
    'm', 23, -17,
    'l', 23, -25,
    'e',
   0x2026, # '…'
    9, 53, 63, 3, -1, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 9, -1,
    'l', 9, -3,
    'l', 11, -3,
    'l', 11, -1,
    'l', 9, -1,
    'm', 30, -1,
    'l', 30, -3,
    'l', 32, -3,
    'l', 32, -1,
    'l', 30, -1,
    'm', 51, -1,
    'l', 51, -3,
    'l', 53, -3,
    'l', 53, -1,
    'l', 51, -1,
    'e',
   0x2030, # '‰'
    3, 58, 62, 42, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 15, -31,
    'c', 15, -45, 3, -45, 3, -31,
    'c', 3, -17, 15, -17, 15, -31,
    'm', 33, -42,
    'l', 8, 0,
    'm', 38, -11,
    'c', 38, -25, 26, -25, 26, -11,
    'c', 26, 3, 38, 3, 38, -11,
    'm', 58, -11,
    'c', 58, -25, 46, -25, 46, -11,
    'c', 46, 3, 58, 3, 58, -11,
    'e',
   0x2039, # '‹'
    4, 12, 17, 28, -6, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 12, -28,
    'l', 4, -17,
    'l', 12, -6,
    'e',
   0x203a, # '›'
    5, 13, 17, 28, -6, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 5, -28,
    'l', 13, -17,
    'l', 5, -6,
    'e',
   0x2070, # '⁰'
    3, 16, 20, 43, -19, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 16, -31,
    'c', 16, -46, 3, -46, 3, -31,
    'c', 3, -15, 16, -15, 16, -31,
    'e',
   0x2071, # 'ⁱ'
    4, 5, 9, 42, -19, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 4, -34,
    'l', 4, -19,
    'm', 4, -40,
    'l', 4, -42,
    'l', 5, -42,
    'l', 5, -40,
    'l', 4, -40,
    'e',
   0x2074, # '⁴'
    2, 15, 20, 42, -19, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 13, -19,
    'l', 13, -42,
    'l', 2, -25,
    'l', 15, -25,
    'e',
   0x2075, # '⁵'
    2, 15, 20, 42, -18, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 14, -42,
    'l', 3, -42,
    'l', 2, -32,
    'c', 7, -34, 15, -32, 15, -26,
    'c', 15, -18, 4, -18, 2, -20,
    'e',
   0x2076, # '⁶'
    2, 15, 20, 42, -19, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 14, -41,
    'c', 13, -42, 2, -45, 2, -29,
    'c', 2, -15, 15, -18, 15, -26,
    'c', 15, -33, 4, -36, 3, -26,
    'e',
   0x2077, # '⁷'
    2, 15, 20, 42, -19, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 2, -42,
    'l', 15, -42,
    'l', 6, -19,
    'e',
   0x2078, # '⁸'
    2, 15, 20, 43, -18, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 14, -37,
    'c', 14, -44, 3, -44, 3, -37,
    'c', 3, -31, 15, -31, 15, -24,
    'c', 15, -17, 2, -17, 2, -24,
    'c', 2, -31, 14, -31, 14, -37,
    'e',
   0x2079, # '⁹'
    2, 15, 20, 42, -19, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 3, -20,
    'c', 5, -19, 15, -16, 15, -32,
    'c', 15, -46, 2, -43, 2, -35,
    'c', 2, -28, 13, -25, 15, -35,
    'e',
   0x207a, # '⁺'
    2, 18, 20, 37, -21, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 10, -37,
    'l', 10, -21,
    'm', 2, -29,
    'l', 18, -29,
    'e',
   0x207b, # '⁻'
    2, 18, 20, 32, -32, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 2, -32,
    'l', 18, -32,
    'e',
   0x207c, # '⁼'
    2, 18, 20, 37, -29, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 2, -37,
    'l', 18, -37,
    'm', 2, -29,
    'l', 18, -29,
    'e',
   0x207d, # '⁽'
    3, 9, 12, 47, -18, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 9, -47,
    'c', 2, -38, 2, -27, 9, -18,
    'e',
   0x207e, # '⁾'
    3, 9, 12, 47, -18, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 3, -47,
    'c', 10, -38, 10, -27, 3, -18,
    'e',
   0x207f, # 'ⁿ'
    4, 17, 21, 35, -19, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 4, -34,
    'l', 4, -19,
    'm', 4, -28,
    'c', 6, -35, 17, -37, 17, -28,
    'l', 17, -19,
    'e',
   0x2080, # '₀'
    3, 16, 20, 21, 3, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 16, -9,
    'c', 16, -24, 3, -24, 3, -9,
    'c', 3, 7, 16, 7, 16, -9,
    'e',
   0x2081, # '₁'
    5, 11, 20, 20, 3, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 5, -15,
    'l', 11, -20,
    'l', 11, 3,
    'e',
   0x2082, # '₂'
    2, 15, 20, 20, 3, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 3, -19,
    'c', 5, -20, 15, -22, 15, -14,
    'c', 15, -10, 13, -8, 2, 3,
    'l', 15, 3,
    'e',
   0x2083, # '₃'
    2, 16, 20, 21, 3, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 3, -19,
    'c', 17, -24, 20, -9, 6, -9,
    'c', 21, -9, 17, 7, 2, 2,
    'e',
   0x2084, # '₄'
    2, 15, 20, 20, 3, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 13, 3,
    'l', 13, -20,
    'l', 2, -3,
    'l', 15, -3,
    'e',
   0x2085, # '₅'
    2, 15, 20, 20, 4, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 14, -20,
    'l', 3, -20,
    'l', 2, -10,
    'c', 7, -12, 15, -10, 15, -4,
    'c', 15, 4, 4, 4, 2, 2,
    'e',
   0x2086, # '₆'
    2, 15, 20, 20, 3, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 14, -19,
    'c', 13, -20, 2, -23, 2, -7,
    'c', 2, 7, 15, 4, 15, -4,
    'c', 15, -11, 4, -14, 3, -4,
    'e',
   0x2087, # '₇'
    2, 15, 20, 20, 3, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 2, -20,
    'l', 15, -20,
    'l', 6, 3,
    'e',
   0x2088, # '₈'
    2, 15, 20, 21, 4, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 14, -15,
    'c', 14, -22, 3, -22, 3, -15,
    'c', 3, -9, 15, -9, 15, -2,
    'c', 15, 5, 2, 5, 2, -2,
    'c', 2, -9, 14, -9, 14, -15,
    'e',
   0x2089, # '₉'
    2, 15, 20, 20, 3, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 3, 2,
    'c', 5, 3, 15, 6, 15, -10,
    'c', 15, -24, 2, -21, 2, -13,
    'c', 2, -6, 13, -3, 15, -13,
    'e',
   0x208a, # '₊'
    2, 18, 20, 14, 2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 10, -14,
    'l', 10, 2,
    'm', 2, -6,
    'l', 18, -6,
    'e',
   0x208b, # '₋'
    2, 18, 20, 6, -6, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 2, -6,
    'l', 18, -6,
    'e',
   0x208c, # '₌'
    2, 18, 20, 10, -2, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 2, -10,
    'l', 18, -10,
    'm', 2, -2,
    'l', 18, -2,
    'e',
   0x208d, # '₍'
    3, 9, 12, 20, 9, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 9, -20,
    'c', 2, -11, 2, 0, 9, 9,
    'e',
   0x208e, # '₎'
    3, 9, 12, 20, 9, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 3, -20,
    'c', 10, -11, 10, 0, 3, 9,
    'e',
   0x2090, # 'ₐ'
    3, 16, 18, 13, 3, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 4, -11,
    'c', 9, -13, 16, -13, 16, -6,
    'l', 16, 3,
    'm', 16, -5,
    'c', 11, -6, 3, -6, 3, -1,
    'c', 3, 5, 16, 4, 16, -4,
    'e',
   0x2091, # 'ₑ'
    3, 16, 19, 13, 3, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 3, -5,
    'l', 16, -5,
    'c', 16, -15, 3, -15, 3, -5,
    'c', 3, 3, 11, 5, 16, 1,
    'e',
   0x2092, # 'ₒ'
    3, 18, 22, 14, 4, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 18, -5,
    'c', 18, -16, 3, -16, 3, -5,
    'c', 3, 6, 18, 6, 18, -5,
    'e',
   0x2093, # 'ₓ'
    3, 14, 17, 12, 3, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 3, -12,
    'l', 14, 3,
    'm', 14, -12,
    'l', 3, 3,
    'e',
   0x2094, # 'ₔ'
    3, 16, 19, 13, 3, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 16, -5,
    'l', 3, -5,
    'c', 3, 5, 16, 5, 16, -5,
    'c', 16, -13, 8, -15, 3, -11,
    'e',
   0x2095, # 'ₕ'
    4, 17, 21, 20, 3, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 4, -20,
    'l', 4, 3,
    'm', 4, -6,
    'c', 6, -13, 17, -15, 17, -6,
    'l', 17, 3,
    'e',
   0x2096, # 'ₖ'
    4, 16, 19, 20, 3, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 4, -20,
    'l', 4, 3,
    'm', 14, -13,
    'l', 4, -3,
    'm', 8, -6,
    'l', 16, 3,
    'e',
   0x2097, # 'ₗ'
    4, 4, 9, 20, 3, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 4, -20,
    'l', 4, 3,
    'e',
   0x2098, # 'ₘ'
    4, 27, 32, 13, 3, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 4, -12,
    'l', 4, 3,
    'm', 4, -6,
    'c', 6, -13, 15, -15, 15, -6,
    'l', 15, 3,
    'm', 15, -6,
    'c', 18, -13, 27, -15, 27, -6,
    'l', 27, 3,
    'e',
   0x2099, # 'ₙ'
    4, 17, 21, 13, 3, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 4, -12,
    'l', 4, 3,
    'm', 4, -6,
    'c', 6, -13, 17, -15, 17, -6,
    'l', 17, 3,
    'e',
   0x209a, # 'ₚ'
    4, 18, 22, 13, 11, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 4, 11,
    'l', 4, -12,
    'm', 4, -5,
    'c', 4, 5, 18, 5, 18, -5,
    'c', 18, -15, 4, -15, 4, -5,
    'e',
   0x209b, # 'ₛ'
    2, 10, 13, 12, 4, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 10, -11,
    'c', 9, -12, 2, -13, 2, -9,
    'c', 2, -5, 10, -5, 10, -1,
    'c', 10, 4, 5, 4, 2, 2,
    'e',
   0x209c, # 'ₜ'
    2, 11, 14, 18, 3, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 6, -18,
    'l', 6, -2,
    'c', 6, 2, 8, 4, 11, 2,
    'm', 2, -12,
    'l', 10, -12,
    'e',
   0x20ac, # '€'
    2, 35, 38, 42, 0, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 35, -40,
    'c', 23, -45, 7, -39, 7, -21,
    'c', 7, -3, 23, 3, 35, -2,
    'm', 30, -17,
    'l', 2, -17,
    'm', 2, -27,
    'l', 32, -27,
    'e',
   0x2212, # '−'
    4, 34, 38, 17, -17, 2, 2,
    0, 32, #  snap_x
    -42, 0, #  snap_y
    'm', 4, -17,
    'l', 34, -17,
    'e',
)

charmap = (
Charmap(page = 0x0000,
        offsets = (
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
   29,   39,   75,  101,  141,  188,  248,  306,
  326,  350,  374,  407,  435,  468,  489,  518,
  538,  570,  594,  631,  664,  692,  731,  771,
  795,  843,  883,  927,  975,  998, 1026, 1049,
 1097, 1151, 1181, 1229, 1261, 1295, 1329, 1360,
 1399, 1432, 1451, 1478, 1510, 1533, 1562, 1588,
 1620, 1655, 1693, 1734, 1773, 1801, 1831, 1854,
 1883, 1909, 1939, 1966, 1993, 2013, 2040, 2063,
 2083, 2103, 2148, 2186, 2218, 2256, 2292, 2328,
 2374, 2408, 2444, 2488, 2520, 2539, 2587, 2621,
 2653, 2691, 2729, 2760, 2799, 2834, 2867, 2890,
 2919, 2945, 2979, 3006, 3054, 3073, 3121,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
 3147, 3157, 3193, 3232, 3272, 3340, 3384, 3409,
 3472, 3517, 3594, 3638, 3670, 3691, 3701, 3773,
 3791, 3835, 3867, 3904, 3937, 3958, 4002, 4042,
 4072, 4100, 4124, 4156, 4189, 4231, 4281, 4331,
 4378, 4414, 4450, 4489, 4529, 4589, 4650, 4695,
 4740, 4779, 4818, 4860, 4923, 4950, 4977, 5007,
 5058, 5098, 5135, 5173, 5211, 5252, 5294, 5356,
 5383, 5421, 5458, 5495, 5535, 5596, 5632, 5669,
 5711, 5762, 5813, 5867, 5922, 5997, 6073, 6132,
 6177, 6218, 6259, 6303, 6368, 6395, 6422, 6452,
 6503, 6548, 6590, 6626, 6662, 6701, 6741, 6801,
 6850, 6886, 6924, 6962, 7003, 7065, 7103, 7153,
        )),
Charmap(page = 0x0001,
        offsets = (
 7217, 7251, 7300, 7338, 7391, 7429, 7482, 7518,
 7554, 7593, 7632, 7677, 7722, 7761, 7800, 7841,
 7883, 7921, 7963, 8000, 8039, 8080, 8123, 8169,
 8217, 8258, 8301, 8341, 8383, 8428, 8480, 8526,
 8579, 8630, 8688, 8730, 8779, 8819, 8860, 8897,
 8935, 8964, 8993, 9018, 9043, 9072, 9101, 9127,
 9171, 9205, 9224, 9256, 9318, 9353, 9388, 9425,
 9462, 9493, 9521, 9546, 9574, 9599, 9627, 9652,
 9689, 9723, 9751, 9776, 9807, 9845, 9876, 9914,
 9948, 9989, 10027, 10066, 10105, 10141, 10177, 10217,
 10257, 10299, 10341, 10389, 10439, 10483, 10518, 10562,
 10597, 10644, 10682, 10725, 10768, 10814, 10860, 10910,
 10960, 11006, 11052, 11090, 11135, 11169, 11207, 11238,
 11276, 11315, 11357, 11392, 11430, 11469, 11511, 11571,
 11634, 11675, 11719, 11758, 11800, 11837, 11874, 11911,
 11952, 12010, 12041, 12072, 12112, 12152, 12186, 12220,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
 12252, 12271, 12296, 12327, 12361, 12414, 12467, 12524,
 12559, 12609, 12656, 12694, 12747, 12807, 12844, 12896,
 12924, 12952, 12991, 13030, 13068,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
        )),
Charmap(page = 0x0002,
        offsets = (
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
 13109, 13132, 13160, 13204, 13227, 13250,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
        )),
Charmap(page = 0x0003,
        offsets = (
 13275, 13294, 13313, 13335, 13358,    1, 13377, 13400,
 13428,    1, 13471, 13515, 13540,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1, 13562,
 13581,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
 13604,    1,    1,    1,    1,    1,    1,    1,
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
 13623, 13642, 13661, 13680, 13699, 13718, 13737, 13762,
 13787, 13819, 13851, 13883, 13915, 13966, 14017, 14068,
 14119, 14144, 14175,    1,    1,    1, 14267,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
 14325,    1,    1,    1,    1,    1,    1,    1,
    1, 14395, 14417,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
 14439, 14469,    1,    1, 14503, 14528, 14564, 14601,
 14623, 14667, 14704, 14729, 14748, 14773, 14796, 14819,
 14851, 14881, 14903, 14936, 14966, 14991, 15027, 15064,
 15086, 15130, 15167, 15192, 15211, 15236, 15259,    1,
 15282, 15325, 15358, 15388, 15413, 15446, 15478, 15509,
 15528, 15573, 15605, 15641, 15678,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1, 15710,    1,    1,    1,
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
Charmap(page = 0x0022,
        offsets = (
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1,    1,    1,    1,    1,    1,    1,
    1,    1, 15752,    1,    1,    1,    1,    1,
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
)

default_font = Font(
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
    values: Values

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

    def __init__(self, f: Any, device: Device, values: Values, font: Font):
        self.f = f
        self.device = device
        self.values = values
        self.font = font
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
        self.font.text_path(s, draw)

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

        metrics = self.font.text_metrics(s)

        if self.values.font_height:
            ascent = metrics.font_ascent
            descent = metrics.font_descent
            text_x = 0;
            text_width = metrics.width
        else:
            ascent = metrics.ascent
            descent = metrics.descent
            text_x = metrics.left_side_bearing
            text_width = metrics.right_side_bearing - metrics.left_side_bearing

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
            text_off_x: float = 0
        elif self.values.align == 'center':
            text_off_x = (rect_width - text_width * scale) / 2
        else:
            text_off_x = text_width

        metrics_x_adjust = text_x * scale

        text_off_x = text_off_x - metrics_x_adjust

        text_x = text_off_x + r.top_left.x + self.values.border
        text_y = text_off_y + r.top_left.y + self.values.border
        text_x_span = text_width * scale
        text_y_span = text_height * scale

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
    parser.add_argument('--font', action='store', type=str,
                        help='SVG font file name',
                        default=None)
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
                        help='Use font metrics for strings instead of glyph metrics',
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

    if args.font:
        font = Font.svg_font(args.font)
    else:
        font = default_font

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

    gcode = GCode(output, device, values, font)
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
