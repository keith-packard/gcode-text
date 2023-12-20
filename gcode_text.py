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
            self.point(p.x, p.y)
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
    width: float
    ascent: float
    descent: float

    def __init__(
        self,
        left_side_bearing: float = 0,
        right_side_bearing: float = 0,
        width: float = 0,
        ascent: float = 0,
        descent: float = 0,
    ):
        self.left_side_bearing = left_side_bearing
        self.right_side_bearing = right_side_bearing
        self.width = width
        self.ascent = ascent
        self.descent = descent

    def __str__(self):
        return "l %f r %f w %f a %f d %f" % (
            self.left_side_bearing,
            self.right_side_bearing,
            self.width,
            self.ascent,
            self.descent,
        )

    def copy(self):
        return TextMetrics(
            left_side_bearing = self.left_side_bearing,
            right_side_bearing = self.right_side_bearing,
            width = self.width,
            ascent = self.ascent,
            descent = self.descent)

svg_ns:str = '{http://www.w3.org/2000/svg}'

def svg_tag(tag: str) -> str:
    return svg_ns + tag

def chkfloat(f: float):
    i = int(f)
    if i == f:
        return i
    return f

def strtonum(s: str):
    return chkfloat(float(s))

class Glyph:
    ucs4: int
    metrics: TextMetrics
    outline: tuple[str|int|float]

    def __init__(self, ucs4: int, width: float, outline: tuple[str|int|float], flatness: float = 1e-6):
        self.ucs4 = ucs4
        self.outline = outline
        self.metrics = self.measure_ink(width, flatness)

    def gen_value(self):
        """Return the next element of the outlines array"""
        for value in self.outline:
            yield value

    #
    # Draw the glyph using the provide callbacks.
    #
    def path(self, calls: Draw) -> None:

        x1 = 0
        y1 = 0

        value = self.gen_value()

        prev_op = None
        while True:
            op = next(value)

            if op == "m":
                if prev_op == op:
                    print('Extra move in 0x%x' % self.ucs4)
                _x1 = next(value)
                _y1 = next(value)
                if _x1 == x1 and _y1 == y1:
                    print('gratuitous move in 0x%x to %f %f' % (self.ucs4, _x1, _y1))
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
                print("unknown font op %s in glyph %d" % (op, self.ucs4))
                raise ValueError
                return
            prev_op = op

    def measure_ink(self, width: float, flatness: float) -> TextMetrics:
        measure_calls = MeasureDraw(flatness)
        self.path(measure_calls)

        if measure_calls.min_x > measure_calls.max_x or measure_calls.min_y > measure_calls.max_y:
            measure_calls.min_x = 0
            measure_calls.max_x = 0
            measure_calls.min_y = 0
            measure_calls.max_y = 0

        return TextMetrics(
            left_side_bearing = chkfloat(math.floor(measure_calls.min_x)),
            right_side_bearing = chkfloat(math.ceil(measure_calls.max_x)),
            width = width,
            ascent = -chkfloat(math.floor(measure_calls.min_y)),
            descent = chkfloat(math.ceil(measure_calls.max_y)))

class Font:
    name: str
    style: str
    metadata: tuple[str,...]
    glyphs: dict[int, Glyph]
    ascent: float
    descent: float
    units_per_em: float
    x_height: float
    cap_height: float

    def __init__(self, units_per_em = 64):
        self.glyphs = {}
        self.units_per_em = units_per_em

    def glyph(self, ucs4: int) -> Glyph:
        if ucs4 in self.glyphs:
            return self.glyphs[ucs4]
        return self.glyphs[0]

    #
    # Draw a single glyph using the provide callbacks.
    #
    def glyph_path(self, ucs4: int, calls: Draw) -> float:
        glyph = self.glyph(ucs4)
        glyph.path(calls)
        width = glyph.metrics.width
        return width

    #
    # Draw a sequence of glyphs using the provided callbacks,
    # stepping by the width of each glyph
    #

    def text_path(self, s: str, calls: Draw) -> float:
        l = len(s)
        glyph_calls = OffsetDraw(calls)

        for g in s:
            ucs4 = ord(g)
            width = self.glyph_path(ucs4, glyph_calls)
            glyph_calls.step(width, 0)

        return glyph_calls.offset_x

    def text_metrics(self, s: str) -> TextMetrics:
        x = 0.0
        ret = TextMetrics()
        started = False
        for g in s:
            glyph = self.glyph(ord(g))
            m = glyph.metrics
            if started:
                ret.left_side_bearing = min(
                    ret.left_side_bearing, m.left_side_bearing + x
                )
                ret.right_side_bearing = max(
                    ret.right_side_bearing, m.right_side_bearing + x
                )
                ret.ascent = max(ret.ascent, m.ascent)
                ret.descent = max(ret.descent, m.descent)
                ret.width = max(ret.width, m.width + x)
            else:
                ret = m.copy()
                started = True
            x += m.width
        return ret

    def set_svg_face(self, element):
        for name, value in sorted(element.items()):
            if name == 'ascent':
                self.ascent = strtonum(value)
            elif name == 'descent':
                self.descent = abs(strtonum(value))
            elif name == 'font-family':
                self.name = value
            elif name == 'units-per-em':
                self.units_per_em = strtonum(value)
            elif name == 'x-height':
                self.x_height = strtonum(value)
            elif name == 'cap-height':
                self.cap_height = strtonum(value)
            elif name == 'font-style':
                self.style = value

    def add_svg_glyph(self, element, missing) -> float:
        if missing:
            ucs4 = 0
        else:
            ucs4 = ord(element.get('unicode'))
        width = strtonum(element.get('horiz-adv-x'))
        cur_x = 0
        cur_y = 0
        mov_x = 0
        mov_y = 0
        outline: tuple[Any,...] = ()
        path_string = element.get('d')
        if path_string is not None:
            path = parse_path(path_string)
            for p in path:
                if p.start.real != cur_x or p.start.imag != cur_y:
                    outline += ('m', chkfloat(p.start.real), chkfloat(-p.start.imag))
                    mov_x = p.start.real
                    mov_y = p.start.imag
                if isinstance(p, Move):
                    pass
                elif isinstance(p, Line):
                    outline += ('l', chkfloat(p.end.real), chkfloat(-p.end.imag))
                elif isinstance(p, CubicBezier):
                    outline += ('c',
                                chkfloat(p.control1.real), chkfloat(-p.control1.imag),
                                chkfloat(p.control2.real), chkfloat(-p.control2.imag),
                                chkfloat(p.end.real), chkfloat(-p.end.imag))
                elif isinstance(p, Close):
                    if cur_x != mov_x or cur_y != mov_y:
                        outline += ('l', chkfloat(mov_x), chkfloat(mov_y))
                cur_x = p.end.real
                cur_y = p.end.imag
        
        outline += ('e',)

        self.glyphs[ucs4] = Glyph(ucs4, width, outline, flatness = self.units_per_em/1e5)

        return width

    def dump_stf(self, file) -> None:
        d = self.__dict__.copy()
        glyphs = d["glyphs"]
        d["glyphs"] = tuple([glyphs[k] for k in glyphs])
        json.dump(d, file, sort_keys=True, indent="\t", default=lambda o: o.__dict__)

    @classmethod
    def parse_svg_font(cls, node_list):
        metadata = ()
        font = None
        for node in node_list:
            if etree.iselement(node):
                if node.tag == svg_tag('defs'):
                    font = Font.parse_svg_font(node)
                elif node.tag == svg_tag('font'):
                    font = Font()
                    for element in node:
                        if element.tag == svg_tag('font-face'):
                            font.set_svg_face(element)
                        elif element.tag == svg_tag('missing-glyph'):
                            font.add_svg_glyph(element, True)
                        elif element.tag == svg_tag('glyph'):
                            font.add_svg_glyph(element, False)
                    break
                elif node.tag == svg_tag('metadata'):
                    metadata = node.text.strip('\n').splitlines()
        if font is not None:
            font.metadata = metadata
        return font
                
                    
    @classmethod
    def svg_font(cls, filename: str, values: Values) -> Font:
        with config_open(filename, values) as file:
            parser = etree.XMLParser(remove_comments=True, recover=True, resolve_entities=False)
            try:
                doc = etree.parse(file, parser=parser)
                svg_root = doc.getroot()
            except Exception as exc:
                print("Failed to load font (%s)" % exc)
                sys.exit(1)
            return Font.parse_svg_font(svg_root)

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
        self.font = 'TwinSans.svg'
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
        self.font_metrics = False
        self.config_dir = ["@CONFIG_DIRS@"]
        self.rects = None
        self.file = None

    def handle_dict(self, d):
        values_vars = vars(self)
        for var in values_vars:
            if var in d and d[var] is not None:
                if var == 'config_dir':
                    pass
                else:
                    values_vars[var] = d[var]
            
    def handle_args(self, args):
        self.handle_dict(vars(args))


def config_open(name: str, values: Values):
    if os.path.isabs(name):
        return open(name)
    failure = None
    for dir in ['.'] + values.config_dir:
        try:
            return open(os.path.join(dir, name))
        except FileNotFoundError:
            continue
    raise FileNotFoundError(name)

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

        if self.values.font_metrics:
            ascent = self.font.ascent
            descent = self.font.descent
            text_x: float = 0;
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
    parser.add_argument('--font-metrics', action='store_true',
                        help='Use font metrics for strings instead of glyph metrics',
                        default=None)
    parser.add_argument('-C', '--config-dir', action='append',
                        help='Directory containing device configuration files')
    parser.add_argument('--dump-stf', action='store',
                        help='Dump font in STF format',
                        default=None)
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

    if values.rects is None:
        return

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
        values.config_dir = args.config_dir + values.config_dir

    if args.template:
        load_template(args.template, values)

    values.handle_args(args)

    device = Device(values)

    font = Font.svg_font(values.font, values)

    if args.dump_stf:
        with open(args.dump_stf, "w") as file:
            font.dump_stf(file)
            print('', file=file)
        sys.exit(0)

    rect_gen = get_rect(values)
    line_gen = get_line(values)

    output = sys.stdout
    if args.output != '-':
        output = open(args.output, "w")

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
