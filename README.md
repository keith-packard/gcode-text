# Gcode-text
Copyright © 2023 Keith Packard

Gcode-text renders text to gcode. The user defines a set of
rectangular regions, either on the command line or as a JSON template
file. Each rectangle is then filled with text, either read from files
or provided as command line arguments.

## License

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 2 of the License, or
(at your option) any later version.

## Usage

	gcode-text: usage: gcode-text <options> [--] file ...
	    -V,--version		Print version and exit
	    -i,--inch			Use inch units
	    -m,--mm			Use millimeter units
	    -r,--rect			Draw bounding rectangles
	    -O,--oblique		Draw the glyphs using a sheer transform
	    -f,--flatness <flatness>	Spline decomposition tolerance
	    -s,--speed <speed>		Feed rate
	    -t,--template <template>	Template file name
	    -d,--device <device-file>   Device config file
	    -S,--settings <value,...>   Device-specific settings values
	    -o,--output <output>	Output file name
	    -b,--border <border>	Border width
	    -x,--start-x <start-x>	Starting X for boxes
	    -y,--start-y <start-y>	Starting Y for boxes
	    -w,--width <width>		Box width
	    -h,--height <height>	Box height
	    -X,--delta-x <delta-x>	X offset between boxes
	    -Y,--delta-y <delta-y>	Y offset between boxes
	    -c,--columns <columns>	Number of columns of boxes
	    -v,--value <value>		Initial text numeric value
	    -n,--number <number>	Number of numeric values
	    -T,--text <string>		Text string
	    -C,--config-dir <dir>	Directory containing device configuration files

## Examples

Draw "hello world" into a 4"x1" box at 1"x1"

	$ gcode-text -o output.gcode -T "hello world" -w 4 -h 1 -x 1 -y 1

Draw numbers starting at 1 using the sample template

	$ gcode-text -o output.gcode -v 1 -t sample-template.json

Draw 10 numbers from 10232 to 10241 in a 2x5 grid of 0.25"x0.1" boxes
spaced 4"x1.5" apart and offset by 1.5"x1" from the origin with a
border of 0.01" around the text:

	$ gcode-text -o output.gcode -v 10232 -n 10 -c 2 -x 1.5 -y 1 -w .25 -h .1 -X 4 -Y 1.5 -b 0.01

Draw the sample below

	$ gcode-text -o gcode-text.gcode -T "Gcode-text" -x 0 -y 0 -w 6 -h 1 -r -b 0.1

![sample gcode output](https://github.com/keith-packard/gcode-text/raw/main/gcode-text.png)
 
Draw the SVG sample below

	$ gcode-text -o gcode-text.svg -d svg.json -T "Gcode-text (SVG)" -x 0 -y 0 -w 640 -h 100 -b 10 -S "640,100,5"

![sample svg output](https://github.com/keith-packard/gcode-text/raw/main/gcode-text.svg)

Draw all of the characters available:

	$ gcode-text -d svg.json -x 50 -y 0 -w 1600 -h 100 -X 0 -Y 100 -o charset.svg --settings 1600,2800,6 charset --font-height --align=left

![charset svg output](https://github.com/keith-packard/gcode-text/raw/main/charset.svg)

Draw some sample text:

	$ gcode-text -d svg.json -x 5 -y 0 -w 790 -h 24 -X 0 -Y 28 --border 0 --settings 800,352,2 lorum --font-height --align=left -o lorum-roman.svg

![lorum ipsem output](https://github.com/keith-packard/gcode-text/raw/main/lorum-roman.svg)
 
	$ gcode-text -d svg.json -x 5 -y 0 -w 790 -h 24 -X 0 -Y 28 --border 0 --settings 800,352,2 lorum --font-height --align=left --oblique -o lorum-oblique.svg

![lorum ipsem output](https://github.com/keith-packard/gcode-text/raw/main/lorum-oblique.svg)

	$ gcode-text -d svg.json -x 5 -y 0 -w 790 -h 24 -X 0 -Y 28 --border 0 --settings 800,352,3 lorum --font-height --align=left -o lorum-bold.svg

![lorum ipsem output](https://github.com/keith-packard/gcode-text/raw/main/lorum-bold.svg)
 
	$ gcode-text -d svg.json -x 5 -y 0 -w 790 -h 24 -X 0 -Y 28 --border 0 --settings 800,352,3 lorum --font-height --align=left --oblique -o lorum-bold-oblique.svg

![lorum ipsem output](https://github.com/keith-packard/gcode-text/raw/main/lorum-bold-oblique.svg)
 
