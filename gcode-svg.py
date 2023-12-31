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
from typing import Any
import svgelements # type: ignore
from svgelements import * # type: ignore

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

class Param:
    order: int
    color: str
    feed: float
    speed: float
    passes: int
    name: str

    def __init__(self, order: int, color: str, feed: float, speed: float, passes: int, name: str):
        self.order = order
        self.color = color
        self.feed = feed
        self.speed = speed
        self.passes = passes
        self.name = name

class Params:

    params: dict[str, Param]
    default: Param

    def __init__(self, json_file: str, values: SvgValues):
        self.params = {}
        self.default = Param(1, "default", 1, 1, 0, "default")
        if json_file is not None:
            with values.config_open(json_file) as file:
                self.set_params(json.load(file), values)

    def set_params(self, json, values: SvgValues):
        values.handle_dict(json)
        for key, value in json.items():
            if key == "params":
                for param in value:
                    order = param['order']
                    color = param['color']
                    feed = param['feed']
                    speed = param['speed']
                    passes = param['passes']
                    name = param['name']
                    self.params[color] = Param(order, color, feed, speed, passes, name)
            elif key == "default":
                order = value['order']
                feed = value['feed']
                speed = value['speed']
                passes = value['passes']
                self.default = Param(order, "default", feed, speed, passes, "default")

    def get(self, color: str):
        if not color in self.params:
            print('unknown color %s' % color)
            return self.default
        return self.params[color]

def path_to_gcode(gcode: GCode, path: svgelements.Path, param: Param, matrix: Matrix):

    path.approximate_arcs_with_cubics()

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
                start: svgelements.Point = path.first_point
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

    paths=[]
    for svg in svgs:
        for e in svg.elements():
            stroke = e.values['stroke']
            if (isinstance(e, svgelements.Rect) or
                isinstance(e, svgelements.Circle) or
                isinstance(e, svgelements.Ellipse)):
                e = svgelements.Path(e.segments())
            if isinstance(e, svgelements.Path):
                param = params.get(stroke)
                paths += [(e, param)]
    
    paths.sort(key = key_svg_entry)

    for p in paths:
        path_to_gcode(gcode, p[0], p[1], matrix)

    gcode.stop()

main()
