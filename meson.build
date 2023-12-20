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
	version: '0.5'
       )

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

dirs_data.set('CONFIG_DIRS', config_dirs)

mypy = find_program('mypy')

python = find_program('python3')

nickle = find_program('nickle')

python_exe = configure_file(input: 'gcode_text.py',
			    output: 'gcode-text',
			    configuration: dirs_data,
			    install_mode: 'rwxr-xr-x',
			    install_dir: get_option('bindir'))

nickle_exe = configure_file(input: 'gcode-edit-font.5c',
			    output: 'gcode-edit-font',
			    configuration: dirs_data,
			    install_mode: 'rwxr-xr-x',
			    install_dir: get_option('bindir'))

font_filename = 'TwinSans.svg'
font_source = 'TwinSans.stf'

twin_sans_svg = custom_target(font_filename,
			      output: font_filename,
			      input: font_source,
			      command: [nickle, nickle_exe,
					'--glyphlist', '@CURRENT_SOURCE_DIR@' / 'glyphlist.txt',
					'--svg', '@OUTPUT@', '@INPUT@'
				       ],
			      install: true,
			      install_dir: share_dir)

test('mypy',
     mypy,
     args: python_exe
    )

test('python',
     python,
     args: [python_exe, '--version']
    )

install_man('gcode-text.1')
install_man('gcode-edit-font.1')

device_files = [
  'device-default.json',
  'laser-grbl.json',
  'svg.json'
  ]

install_data(device_files)

template_files = [
  'sample-template.json',
  ]

install_data(template_files)

font_files = [
  font_source,
  ]

install_data(font_files)
