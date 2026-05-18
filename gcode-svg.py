#!/usr/bin/python3
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
import json
import math
import sys
import argparse
import os
import numbers
import re
from typing import Any
import svgelements # type: ignore
from svgelements import * # type: ignore

if not os.getenv('GCODE_SKIP_PATH'):
    sys.path = ['@SHARE_DIR@'] + sys.path

from gcode_draw import *
from gcode_font import *

class SvgValues(Values):

    def __init__(self):
        super().__init__()
        self.ppi = 96.0
        self.bounds = Rect(Point(0, 0), Point(0, 0))

    def set_bounds(self, bounds: Rect) -> None:
        self.bounds = bounds

class SvgColor:
    red: int
    green: int
    blue: int
    alpha: float

    names = {
        "black": "#000000",
        "silver": "#C0C0C0",
        "gray": "#808080",
        "white": "#FFFFFF",
        "maroon": "#800000",
        "red": "#FF0000",
        "purple": "#800080",
        "fuchsia": "#FF00FF",
        "green": "#008000",
        "lime": "#00FF00",
        "olive": "#808000",
        "yellow": "#FFFF00",
        "navy": "#000080",
        "blue": "#0000FF",
        "teal": "#008080",
        "aqua": "#00FFFF",
    }

    def float_value(self, text):
        return float(text)

    def decimal_value(self, text):
        if text.endswith('%'):
            return int(round(int(text[:-1]) * 255 / 100))
        else:
            return int(text)

    def hex_value(self, text):
        if len(text) == 1:
            return int(text, 16) * 17
        return int(text, 16)

    def __init__(self, text: str):
        if text in self.names:
            text = self.names[text]
        m = re.fullmatch(r"#([0-9a-fA-F])([0-9a-fA-F])([0-9a-fA-F])", text)
        if m:
            self.red = self.hex_value(m.group(1))
            self.green = self.hex_value(m.group(1))
            self.blue = self.hex_value(m.group(1))
            self.alpha = 1
            return

        m = re.fullmatch(r"#([0-9a-fA-F]{2})([0-9a-fA-F]{2})([0-9a-fA-F]{2})", text)
        if m:
            self.red = self.hex_value(m.group(1))
            self.green = self.hex_value(m.group(2))
            self.blue = self.hex_value(m.group(3))
            self.alpha = 1
            return

        m = re.fullmatch(r"rgb *\( *([0-9][0-9]*%?) *, *([0-9][0-9]*%?) *, *([0-9][0-9]*%?) *\)", text)
        if m:
            self.red = self.decimal_value(m.group(1))
            self.green = self.decimal_value(m.group(2))
            self.blue = self.decimal_value(m.group(3))
            self.alpha = 1
            return

        m = re.fullmatch(r"rgba *\( *([0-9][0-9]*%?) *, *([0-9][0-9]*%?) *, *([0-9][0-9]*%?) *, *([0-9][0-9]*%?) *\)", text)
        if m:
            self.red = self.decimal_value(m.group(1))
            self.green = self.decimal_value(m.group(2))
            self.blue = self.decimal_value(m.group(3))
            self.alpha = self.float_value(m.group(4))
            return

    def __eq__(self, other):
        return (self.red == other.red and
                self.green == other.green and
                self.blue == other.blue and
                self.alpha == other.alpha)

    def __str__(self):
        if self.alpha < 1:
            return "rgba(%d, %d, %d, %f)" % (self.red, self.green, self.blue, self.alpha)
        else:
            return "rgb(%d, %d, %d)" % (self.red, self.green, self.blue)

    def __hash__(self):
        return hash(str(self))

class Param:
    order: int
    color: SvgColor
    feed: float
    speed: float
    passes: int
    name: str
    step: float

    def __init__(self, order: int, color: str | SvgColor, feed: float, speed: float, passes: int, name: str, step: float):
        self.order = order
        if isinstance(color, str):
            color = SvgColor(color)
        self.color = color
        self.feed = feed
        self.speed = speed
        self.passes = passes
        self.name = name
        self.step = step

class Params:

    params: dict[SvgColor, Param]
    default: Param

    def __init__(self, json_file: str, values: SvgValues):
        self.params = {}
        self.default = Param(1, "default", 1, 1, 0, "default", .1)
        if json_file is not None:
            with values.config_open(json_file) as file:
                self.set_params(json.load(file), values)

    def set_params(self, json, values: SvgValues):
        values.handle_dict(json)
        for key, value in json.items():
            if key == "params":
                for param in value:
                    order = param['order']
                    color = SvgColor(param['color'])
                    feed = param['feed']
                    speed = param['speed']
                    passes = param['passes']
                    name = param['name']
                    if 'step' in param:
                        step = param['step']
                    else:
                        step = .1
                    self.params[color] = Param(order, color, feed, speed, passes, name, step)
            elif key == "default":
                order = value['order']
                feed = value['feed']
                speed = value['speed']
                passes = value['passes']
                self.default = Param(order, "default", feed, speed, passes, "default", .1)

    def get(self, color: str | SvgColor):
        if isinstance(color, str):
            color = SvgColor(color)
        if not color in self.params:
            print('unknown color %s' % color)
            return self.default
        return self.params[color]

def stroke_to_gcode(gcode: GCode, path: svgelements.Path, param: Param, matrix: Matrix):

    if gcode.values.verbose:
        print('path using "%s" feed %f speed %f passes %d' % (param.name, param.feed, param.speed, param.passes))
    gcode.set_feed(param.feed)
    gcode.set_speed(param.speed)

    draw = MatrixDraw(gcode.get_draw(), matrix)

    for i in range(param.passes):
        for seg in path:
            if isinstance(seg, svgelements.Move):
                if seg.end is not None:
                    draw.move(seg.end.x, seg.end.y)
            elif isinstance(seg, svgelements.Close):
                start: svgelements.Point = seg.end
                draw.draw(start.x, start.y)
            elif isinstance(seg, svgelements.Line):
                draw.draw(seg.end.x, seg.end.y)
            elif isinstance(seg, svgelements.QuadraticBezier):
                draw.curve2(seg.control.x, seg.control.y,
                             seg.end.x, seg.end.y)
            elif isinstance(seg, svgelements.CubicBezier):
                draw.curve(seg.control1.x, seg.control1.y,
                           seg.control2.x, seg.control2.y,
                           seg.end.x, seg.end.y)
            elif isinstance(seg, svgelements.Arc):
                print('arc')

class Intercept:

    x: float
    winding: bool

    def __init__(self, x, winding):
        self.x = x
        self.winding = winding

    def __str__(self):
        return "(%f %r)" % (self.x, self.winding)

    def __lt__(self, other):
        if self.x < other.x:
            return True
        if self.x > other.x:
            return False
        if self.winding and not other.winding:
            return True
        return False

class Edge:

    x1: float
    y1: float
    x2: float
    y2: float
    winding: bool

    def __init__(self, x1, y1, x2, y2):
        assert (y1 != y2)
        self.winding = y1 > y2
        if y1 > y2:
            t = x1
            x1 = x2
            x2 = t
            t = y1
            y1 = y2
            y2 = t
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2

    def x(self, y):
        if y < self.y1 or self.y2 <= y:
            return None

        y_off = self.y1
        slope = (self.x2 - self.x1) / (self.y2 - self.y1)
        x_off = self.x1
        x = (y - y_off) * slope + x_off

        return Intercept(x, self.winding)
        
    def __str__(self):
        return "(%f %f) (%f %f)" % (self.x1, self.y1, self.x2, self.y2)

    def __lt__(self, other):
        if self.y1 < other.y1:
            return True
        if self.y1 > other.y1:
            return False

        if self.x1 < other.x1:
            return True
        if self.x1 > other.x1:
            return False

        if self.y2 < other.y2:
            return True
        if self.y2 > other.y2:
            return False
        
        if self.x2 < other.x2:
            return True
        return False

    def __eq__(self, other):
        if self.x1 != other.x1:
            return False
        if self.y1 != other.y1:
            return False
        if self.x2 != other.x2:
            return False
        if self.y2 != other.y2:
            return False
        return True

class EdgeDraw(Draw):

    edges: list[Edge]

    def __init__(self):
        super().__init__()
        self.edges = []

    def start(self):
        print("EdgeDraw start")
        pass

    def draw(self, x: float, y: float):
        if y != self.last_y:
            edge = Edge(x, y, self.last_x, self.last_y)
            self.edges += [edge]
        super().draw(x, y)

    def spans(self, y):
        xs = []
        for edge in self.edges:
            x = edge.x(y)
            if x is not None:
                xs += [x]
        xs.sort()
        return xs

def scan_to_gcode(gcode: GCode, paths: list[svgelements.Path], param: Param, matrix: Matrix):
    
    edge_draw = EdgeDraw()

    line_draw = LineDraw(edge_draw, gcode.values.flatness)

    edraw = MatrixDraw(line_draw, matrix)

    for path in paths:
        for seg in path:
            if isinstance(seg, svgelements.Move):
                if seg.end is not None:
                    edraw.move(seg.end.x, seg.end.y)
            elif isinstance(seg, svgelements.Close):
                start: svgelements.Point = seg.end
                edraw.draw(start.x, start.y)
            elif isinstance(seg, svgelements.Line):
                edraw.draw(seg.end.x, seg.end.y)
            elif isinstance(seg, svgelements.QuadraticBezier):
                edraw.curve2(seg.control.x, seg.control.y,
                             seg.end.x, seg.end.y)
            elif isinstance(seg, svgelements.CubicBezier):
                edraw.curve(seg.control1.x, seg.control1.y,
                           seg.control2.x, seg.control2.y,
                           seg.end.x, seg.end.y)
            elif isinstance(seg, svgelements.Arc):
                print('arc')
            else:
                print('skipping %r' % seg)
        

    if gcode.values.verbose:
        print('path using "%s" feed %f speed %f passes %d step %f' % (param.name, param.feed, param.speed, param.passes, param.step))
    gcode.set_feed(param.feed)
    gcode.set_speed(param.speed)

    draw = gcode.get_draw()

    values = gcode.values

    bounds = values.bounds

    for i in range(param.passes):
        y = values.bounds.top_left.y
        while y <= bounds.bottom_right.y:
            spans = edge_draw.spans(y)
            if spans:
                spans.sort()
                winding = 0
                x = 0
                for span in spans:
                    if winding != 0 and x != span.x:
                        draw.move(x, y)
                        draw.draw(span.x, y)
                    x = span.x
                    if span.winding:
                        winding += 1
                    else:
                        winding -= 1
            y = y + param.step

def Args():
    parser = argparse.ArgumentParser(
        add_help=False,
        description='Convert SVG to Gcode'
        )
    Device.args(parser)
    parser.add_argument('-p', '--params', action='store',
                        help='Parameter file name',
                        default=None)
    parser.add_argument('file', nargs='*',
                        help='SVG input files')

    args = parser.parse_args()

    if args.help:
        parser.print_help()
        sys.exit(0)

    if args.version:
        print("%s" % '@VERSION@')
        sys.exit(0)

    return args
    
def key_svg_entry(e: tuple[Param, svgelements.Path]) -> int:
    return e[1].order

def main():

    values = SvgValues()

    args = Args()

    if args.config_dir:
        values.config_dir = args.config_dir + values.config_dir

    params = Params(args.params, values)

    values.handle_args(args)

    device = Device(values)

    output = sys.stdout
    if args.output != '-':
        output = open(args.output, "w")

    svgs = ()
    for filename in args.file:
        with open(filename) as file:
            svgs += (SVG.parse(file),)

    bounds = None
    for svg in svgs:
        x = svg.implicit_x
        y = svg.implicit_y
        w = svg.implicit_width
        h = svg.implicit_height
        this_bounds = Rect(Point(x, y), Point(x + w, y + h))
        if bounds is None:
            bounds = this_bounds
        else:
            bounds = bounds.union(this_bounds)
    values.set_bounds(bounds)

    matrix = Matrix()

    if values.mm:
        units_per_inch = 25.4
    else:
        units_per_inch = 1
        
    matrix = matrix.scale(units_per_inch / values.ppi, units_per_inch / values.ppi)

    if device.y_invert:
        matrix = matrix.translate(0, values.bounds.bottom_right.y + values.bounds.top_left.y);
        matrix = matrix.scale(1, -1)

    gcode = GCode(output, device, values, None)

    gcode.start()

    strokes=[]
    fills={}
    
    for svg in svgs:
        for e in svg.elements():
            stroke = e.values['stroke']
            fill = e.values['fill']
            if (isinstance(e, svgelements.Rect) or
                isinstance(e, svgelements.Circle) or
                isinstance(e, svgelements.Ellipse)):
                e = svgelements.Path(e.segments())

            if isinstance(e, svgelements.Path):
                e.approximate_arcs_with_cubics()
                if stroke != 'none':
                    param = params.get(stroke)
                    strokes += [(e, param)]
                if fill != 'none':
                    param = params.get(fill)
                    if param in fills:
                        fills[param] += [e]
                    else:
                        fills[param] = [e]
    
    strokes.sort(key = key_svg_entry)

    for stroke in strokes:
        stroke_to_gcode(gcode, stroke[0], stroke[1], matrix)

    if fills:
        for param in fills:
            paths = fills[param]
            scan_to_gcode(gcode, paths, param, matrix)

    gcode.stop()

main()
