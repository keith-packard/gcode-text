project('gcode-text',
	license : 'GPLv2',
	version: '0.5'
       )

share_dir = get_option('prefix') / get_option('datadir') / meson.project_name()

dirs_data = configuration_data()
dirs_data.set('SHARE_DIR', share_dir)
dirs_data.set('VERSION', meson.project_version())

font_dir_list = get_option('font-dirs')

font_dirs = ''

foreach font_dir : font_dir_list
  font_dirs = font_dirs + '"' + font_dir + '", '
endforeach

dirs_data.set('FONT_DIRS', font_dirs)

mypy = find_program('mypy')

python = find_program('python3')

nickle = find_program('nickle')

python_exe = configure_file(input: 'gcode_text.py',
			    output: 'gcode-text',
			    configuration: dirs_data,
			    install_mode: 'rwxr-xr-x',
			    install_dir: get_option('bindir'))

nickle_exe = configure_file(input: 'edit-font.5c',
			    output: 'gcode-edit-font',
			    configuration: dirs_data,
			    install_mode: 'rwxr-xr-x',
			    install_dir: get_option('bindir'))

font_filename = 'twin-sans.svg'

twin_sans_svg = custom_target(font_filename,
			      output: font_filename,
			      input: 'font',
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
  'font',
  ]

install_data(font_files)
