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
from gcode_draw import *

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
    def svg_font(cls, filename: str, values: TextValues) -> Font:
        with values.config_open(filename) as file:
            parser = etree.XMLParser(remove_comments=True, recover=True, resolve_entities=False)
            try:
                doc = etree.parse(file, parser=parser)
                svg_root = doc.getroot()
            except Exception as exc:
                print("Failed to load font (%s)" % exc)
                sys.exit(1)
            return Font.parse_svg_font(svg_root)
