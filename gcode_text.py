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
from gcode_draw import *
from gcode_font import *

class TextValues(Values):

    def __init__(self):
        super().__init__()
        self.font = 'TwinSans.svg'
        self.oblique = False
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
        self.rects = None
        self.file = None


def Args():
    parser = argparse.ArgumentParser(
        add_help=False,
        description='Render stroked text'
        )
    Device.args(parser)
    parser.add_argument('-r', '--rect', action='store_true',
                        help='Draw bounding rectangles',
                        default=None)
    parser.add_argument('-O', '--oblique', action='store_true',
                        help='Draw the glyphs using a sheer transform',
                        default=None)
    parser.add_argument('--sheer', action='store', type=float,
                        help='Oblique sheer amount')
    parser.add_argument('-f', '--flatness', action='store', type=float,
                        help='Spline decomposition tolerance')
    parser.add_argument('--font', action='store', type=str,
                        help='SVG font file name',
                        default=None)
    parser.add_argument('-t', '--template', action='store',
                        help='Template file name',
                        default=None)
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

    with values.config_open(template_file) as file:
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
    values = TextValues()
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
