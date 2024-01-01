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
import os
import numbers
import csv
from io import StringIO
from typing import Any

class Values:
    def __init__(self):
        self.inch = True
        self.mm = False
        self.rect = False
        self.tesselate = False
        self.sheer = 0.1
        self.flatness = 0.001
        self.feed = 100
        self.speed = 100
        self.template = None
        self.device = None
        self.settings = None
        self.verbose = False
        self.config_dir = ["@CONFIG_DIRS@"]

    def handle_dict(self, d):
        values_vars = vars(self)
        for var in values_vars:
            if var in d and d[var] is not None:
                if var == "config_dir":
                    pass
                else:
                    values_vars[var] = d[var]

    def handle_args(self, args):
        self.handle_dict(vars(args))

    def config_open(self, name: str):
        if os.path.isabs(name):
            return open(name)
        failure = None
        for dir in ["."] + self.config_dir:
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
    feed: bool = True
    speed: bool = False
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
            elif key == "feed":
                self.feed = self.bool(value)
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
            reader = csv.reader(f, delimiter=",")
            setting_values = []
            for row in reader:
                setting_values = row
            for i in range(min(len(setting_values), len(self.setting_values))):
                self.setting_values[i] = setting_values[i]

    def set_json_file(self, json_file: str, values):
        with values.config_open(json_file) as file:
            self.set_values(json.load(file))


    @classmethod
    def args(cls, parser):
        parser.add_argument('--help', action='store_true',
                            help='Print usage and exit')
        parser.add_argument('-V', '--version', action='store_true',
                            help='Print version and exit')
        parser.add_argument('--verbose', action='store_true',
                            help='Print messages during processing')
        parser.add_argument('-i', '--inch', action='store_true',
                            help='Use inch units',
                            default=None)
        parser.add_argument('-m', '--mm', action='store_true',
                            help='Use millimeter units',
                            default=None)
        parser.add_argument('-f', '--flatness', action='store', type=float,
                            help='Spline decomposition tolerance')
        parser.add_argument('--tesselate', action='store_true',
                            help='Force tesselation of splines',
                            default=None)
        parser.add_argument('--feed', action='store', type=float,
                            help='Feed rate')
        parser.add_argument('--speed', action='store', type=float,
                            help='Spindle speed')
        parser.add_argument('-d', '--device', action='store',
                            help='Device config file')
        parser.add_argument('-S', '--settings', action='store',
                            help='Device-specific settings values')
        parser.add_argument('-o', '--output', action='store',
                            help='Output file name',
                            default='-')
        parser.add_argument('-C', '--config-dir', action='append',
                            help='Directory containing device configuration files')


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

    def union(self, r: Rect) -> Rect:
        return Rect(Point(min(self.top_left.x, r.top_left.x),
                          min(self.top_left.y, r.top_left.y)),
                    Point(max(self.bottom_right.x, r.bottom_right.x),
                          max(self.bottom_right.y, r.bottom_right.y)))


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

    def curve(
        self, x1: float, y1: float, x2: float, y2: float, x3: float, y3: float
    ) -> None:
        self.last_x = x3
        self.last_y = y3

    def curve2(self, x: float, y: float, x3: float, y3: float) -> None:
        x1 = self.last_x + 2 * (x - self.last_x) / 3
        y1 = self.last_y + 2 * (y - self.last_y) / 3
        x2 = x3 + 2 * (x - x3) / 3
        y2 = y3 + 2 * (y - y3) / 3
        self.curve(x1, y1, x2, y2, x3, y3)

    def rect(self, r: Rect) -> None:
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

    def curve(
        self, x1: float, y1: float, x2: float, y2: float, x3: float, y3: float
    ) -> None:
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

    def de_casteljau(self) -> tuple[Spline, Spline]:
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

    def curve(
        self, x1: float, y1: float, x2: float, y2: float, x3: float, y3: float
    ) -> None:
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

    def curve(
        self, x1: float, y1: float, x2: float, y2: float, x3: float, y3: float
    ) -> None:
        b = self.matrix.point(Point(x1, y1))
        c = self.matrix.point(Point(x2, y2))
        d = self.matrix.point(Point(x3, y3))
        self.chain.curve(b.x, b.y, c.x, c.y, d.x, d.y)
        super().curve(x1, y1, x2, y2, x3, y3)


class DebugDraw(Draw):
    def move(self, x: float, y: float) -> None:
        print("move %f %f" % (x, y))

    def draw(self, x: float, y: float) -> None:
        print("line %f %f" % (x, y))

    def curve(
        self, x1: float, y1: float, x2: float, y2: float, x3: float, y3: float
    ) -> None:
        print("curve %f %f %f %f %f %f" % (x1, y1, x2, y2, x3, y3))


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
        return "%f,%f - %f,%f" % (self.min_x, self.min_y, self.max_x, self.max_y)

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

    def curve(
        self, x1: float, y1: float, x2: float, y2: float, x3: float, y3: float
    ) -> None:
        s = Spline(
            Point(self.last_x, self.last_y), Point(x1, y1), Point(x2, y2), Point(x3, y3)
        )
        ps = s.decompose(self.tolerance)
        for p in ps[:-1]:
            self.point(p.x, p.y)
        self.draw(ps[-1].x, ps[-1].y)


from gcode_font import *

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
                self.device.settings % tuple(self.device.setting_values),
                file=self.f,
                end="",
            )
        if self.values.mm:
            print("%s" % self.device.mm, file=self.f, end="")
        else:
            print("%s" % self.device.inch, file=self.f, end="")

    def set_feed(self, feed: float) -> None:
        self.values.feed = feed
        
    def set_speed(self, speed: float) -> None:
        self.values.speed = speed
        
    def extra_params(self):
        extra = ()
        if self.device.feed:
            extra += (self.values.feed,)
        if self.device.speed:
            extra += (self.values.speed,)
        return extra

    def move(self, x: float, y: float):
        print(self.device.move % (x, y), file=self.f, end="")
        super().move(x, y)

    def draw(self, x: float, y: float):
        s = self.device.draw % ((x, y) + self.extra_params())
        print(s, file=self.f, end="")
        super().draw(x, y)

    def curve(self, x1: float, y1: float, x2: float, y2: float, x3: float, y3: float):
        s = self.device.curve % ((x1, y1, x2, y2, x3, y3) + self.extra_params())
        print(s, file=self.f, end="")
        super().curve(x1, y1, x2, y2, x3, y3)

    def stop(self):
        print("%s" % self.device.stop, file=self.f, end="")

    def get_draw(self):
        if self.device.curve == "" or self.values.tesselate:
            return LineDraw(self, self.values.flatness)
        return self

