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

	usage: gcode-text [--help] [-V] [-i] [-m] [-r] [-O] [--tesselate] [--sheer SHEER] [-f FLATNESS]
			  [--font FONT] [-s SPEED] [-t TEMPLATE] [-d DEVICE] [-S SETTINGS] [-o OUTPUT]
			  [-b BORDER] [-x START_X] [-y START_Y] [-w WIDTH] [-h HEIGHT] [-X DELTA_X]
			  [-Y DELTA_Y] [-c COLUMNS] [-v VALUE] [-n NUMBER] [-T TEXT]
			  [-a {left,right,center}] [--font-height] [-C CONFIG_DIR]
			  [file ...]

	positional arguments:
	  file                  Text source files

	options:
	  --help                Print usage and exit
	  -V, --version         Print version and exit
	  -i, --inch            Use inch units
	  -m, --mm              Use millimeter units
	  -r, --rect            Draw bounding rectangles
	  -O, --oblique         Draw the glyphs using a sheer transform
	  --tesselate           Force tesselation of splines
	  --sheer SHEER         Oblique sheer amount
	  -f FLATNESS, --flatness FLATNESS
				Spline decomposition tolerance
	  --font FONT           SVG font file name
	  -s SPEED, --speed SPEED
				Feed rate
	  -t TEMPLATE, --template TEMPLATE
				Template file name
	  -d DEVICE, --device DEVICE
				Device config file
	  -S SETTINGS, --settings SETTINGS
				Device-specific settings values
	  -o OUTPUT, --output OUTPUT
				Output file name
	  -b BORDER, --border BORDER
				Border width
	  -x START_X, --start-x START_X
				Starting X for boxes
	  -y START_Y, --start-y START_Y
				Starting Y for boxes
	  -w WIDTH, --width WIDTH
				Box width
	  -h HEIGHT, --height HEIGHT
				Box height
	  -X DELTA_X, --delta-x DELTA_X
				X offset between boxes
	  -Y DELTA_Y, --delta-y DELTA_Y
				Y offset between boxes
	  -c COLUMNS, --columns COLUMNS
				Number of columns of boxes
	  -v VALUE, --value VALUE
				Initial text numeric value
	  -n NUMBER, --number NUMBER
				Number of numeric values
	  -T TEXT, --text TEXT  Text string
	  -a {left,right,center}, --align {left,right,center}
	  --font-metrics        Use font metrics for strings instead of glyph metrics
	  -C CONFIG_DIR, --config-dir CONFIG_DIR
				Directory containing device configuration files

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

	$ gcode-text -d svg.json -x 50 -y 0 -w 1600 -h 100 -X 0 -Y 100 -o charset.svg --settings 1600,2800,6 charset --font-metrics --align=left

![charset svg output](https://github.com/keith-packard/gcode-text/raw/main/charset.svg)

Draw some sample text:

	$ gcode-text -d svg.json -x 5 -y 0 -w 790 -h 24 -X 0 -Y 28 --border 0 --settings 800,352,2 lorum --font-metrics --align=left -o lorum-roman.svg

![lorum ipsem output](https://github.com/keith-packard/gcode-text/raw/main/lorum-roman.svg)
 
	$ gcode-text -d svg.json -x 5 -y 0 -w 790 -h 24 -X 0 -Y 28 --border 0 --settings 800,352,2 lorum --font-metrics --align=left --oblique -o lorum-oblique.svg

![lorum ipsem output](https://github.com/keith-packard/gcode-text/raw/main/lorum-oblique.svg)

	$ gcode-text -d svg.json -x 5 -y 0 -w 790 -h 24 -X 0 -Y 28 --border 0 --settings 800,352,3 lorum --font-metrics --align=left -o lorum-bold.svg

![lorum ipsem output](https://github.com/keith-packard/gcode-text/raw/main/lorum-bold.svg)
 
	$ gcode-text -d svg.json -x 5 -y 0 -w 790 -h 24 -X 0 -Y 28 --border 0 --settings 800,352,3 lorum --font-metrics --align=left --oblique -o lorum-bold-oblique.svg

![lorum ipsem output](https://github.com/keith-packard/gcode-text/raw/main/lorum-bold-oblique.svg)
 
Draw the same text using the Hershey Script font from inkscape:

	$ gcode-text -d svg.json -x 5 -y 0 -w 790 -h 24 -X 0 -Y 28 --border 0 --settings 800,352,2 lorum --font-metrics --align=left -o lorum-script.svg --font /usr/share/inkscape/extensions/svg_fonts/HersheyScript1.svg

![lorum ipsem script output](https://github.com/keith-packard/gcode-text/raw/main/lorum-script.svg)
