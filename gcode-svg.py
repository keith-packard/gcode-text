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
        self.bounds = (0, 0, 0, 0)

    def set_bounds(self, bounds: tuple[float, float, float, float]):
        self.bounds = bounds

class Param:
    order: int
    color: str
    feed: float
    speed: float
    name: str

    def __init__(self, order: int, color: str, feed: float, speed: float, name: str):
        self.order = order
        self.color = color
        self.feed = feed
        self.speed = speed
        self.name = name

class Params:

    params: dict[str, Param]
    default: Param

    def __init__(self, json_file: str, values: SvgValues):
        self.params = {}
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
                    name = param['name']
                    self.params[color] = Param(order, color, feed, speed, name)
            elif key == "default":
                order = value['order']
                feed = value['feed']
                speed = value['speed']
                self.default = Param(order, "default", feed, speed, "default")

    def get(self, color: str):
        if not color in self.params:
            print('unknown color %s' % color)
            return self.default
        return self.params[color]

def path_to_gcode(gcode: GCode, path: svgelements.Path, param: Param, matrix: Matrix):

    path.approximate_arcs_with_cubics()

    print('path using %s %f %f' % (param.name, param.feed, param.speed))
    gcode.set_feed(param.feed)
    gcode.set_speed(param.speed)

    draw = MatrixDraw(gcode.get_draw(), matrix)

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

    values.handle_args(args)

    if args.params:
        params = Params(args.params, values)

    device = Device(values)

    output = sys.stdout
    if args.output != '-':
        output = open(args.output, "w")

    svgs = ()
    for filename in args.file:
        with open(filename) as file:
            svgs += (SVG.parse(file),)

    print('computing bounds...')
    values.set_bounds(svgelements.Group.union_bbox(svgs))
    print('bounds: %s' % (values.bounds,))

    matrix = Matrix()

    if values.mm:
        units_per_inch = 25.4
    else:
        units_per_inch = 1
        
    matrix = matrix.scale(units_per_inch / values.ppi, units_per_inch / values.ppi)

    ul = Point(values.bounds[0], values.bounds[1])
    lr = Point(values.bounds[2], values.bounds[3])

    if device.y_invert:
        matrix = matrix.translate(0, values.bounds[3] + values.bounds[1]);
        matrix = matrix.scale(1, -1)

    print('ul %s -> %s' % (ul, matrix.point(ul)))
    print('lr %s -> %s' % (lr, matrix.point(lr)))

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
