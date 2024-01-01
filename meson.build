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
project('gcode-text',
	license : 'GPLv2',
	version: '0.6'
       )

fs = import('fs')

share_dir = get_option('prefix') / get_option('datadir') / meson.project_name()

dirs_data = configuration_data()
dirs_data.set('SHARE_DIR', share_dir)
dirs_data.set('VERSION', meson.project_version())

font_dir_list = get_option('font-dirs')

config_dirs = ''

foreach config_dir : [share_dir] + font_dir_list
  if config_dirs == ''
    config_dirs = config_dir
  else
    config_dirs = config_dirs + '", "' + config_dir
  endif
endforeach

dirs_data.set('SHARE_DIR', share_dir)
dirs_data.set('CONFIG_DIRS', config_dirs)

mypy = find_program('mypy')

python = find_program('python3')

nickle = find_program('nickle')

gcode_text = configure_file(input: 'gcode-text.py',
			    output: '@BASENAME@',
			    configuration: dirs_data,
			    install_mode: 'rwxr-xr-x',
			    install_dir: get_option('bindir'))

gcode_svg = configure_file(input: 'gcode-svg.py',
			    output: '@BASENAME@',
			    configuration: dirs_data,
			    install_mode: 'rwxr-xr-x',
			    install_dir: get_option('bindir'))

gcode_edit_font = configure_file(input: 'gcode-edit-font.5c',
			    output: '@BASENAME@',
			    configuration: dirs_data,
			    install_mode: 'rwxr-xr-x',
			    install_dir: get_option('bindir'))

fonts = [
  'TwinSans.stf',
  'TwinScript.stf',
  ]

foreach font : fonts
  font_svg = fs.replace_suffix(font, '.svg')
  font_target = custom_target(font_svg,
			      output: font_svg,
			      input: font,
			      command: [nickle, gcode_edit_font,
					'--glyphlist', '@CURRENT_SOURCE_DIR@' / 'glyphlist.txt',
					'--svg', '@OUTPUT@', '@INPUT@'
				       ],
			      install: true,
			      install_dir: share_dir)
  if font == 'TwinSans.stf'
    twin_sans_svg = font_target
  endif
endforeach

python_env = environment({'PYTHONPATH': meson.build_root(), 'GCODE_SKIP_PATH': 'true'})

gcode_draw = configure_file(input: 'gcode_draw.py',
			    output: 'gcode_draw.py',
			    configuration: dirs_data,
			    install_dir: share_dir)

gcode_font = configure_file(input: 'gcode_font.py',
			    output: 'gcode_font.py',
			    configuration: dirs_data,
			    install_dir: share_dir)

foreach py : [gcode_text, gcode_svg]
  test('mypy',
       mypy,
       args: py
      )

  test('python',
       python,
       env: python_env,
       args: [py, '--version']
      )
endforeach

install_man('gcode-text.1')
install_man('gcode-edit-font.1')
install_man('gcode-svg.1')

device_files = [
  'device-default.json',
  'laser-grbl.json',
  'svg.json'
  ]

install_data(device_files)

param_files = [
  'cut-etch.json',
  ]

install_data(param_files)

template_files = [
  'sample-template.json',
  ]

install_data(template_files)

install_data(fonts)
