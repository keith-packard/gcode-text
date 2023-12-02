project('gcode-text',
	license : 'GPLv2',
	version: '0.4'
       )

share_dir = get_option('prefix') / get_option('datadir') / meson.project_name()

message('share_dir is ' + share_dir)

dirs_data = configuration_data()
dirs_data.set('SHARE_DIR', share_dir)
dirs_data.set('VERSION', meson.project_version())


nickle_exe = configure_file(input: 'gcode-text.5c',
			    output: 'gcode-text',
			    configuration: dirs_data,
			    install_mode: 'rwxr-xr-x',
			    install_dir: get_option('bindir')
			   )

python_exe = configure_file(input: 'gcode_text.py',
			    output: 'gcode_text',
			    configuration: dirs_data,
			    install_mode: 'rwxr-xr-x',
			    install_dir: get_option('bindir'))

mypy = find_program('mypy')

python = find_program('python3')

nickle = find_program('nickle')

test('mypy',
     mypy,
     args: python_exe
    )

test('python',
     python,
     args: [python_exe, '--version']
    )

test('nickle',
     nickle,
     args: [nickle_exe, '--version']
    )

install_man('gcode-text.1')

device_files = [
  'device-default.json',
  'svg.json'
  ]

install_data(device_files)

template_files = [
  'sample-template.json',
  ]

install_data(template_files)
