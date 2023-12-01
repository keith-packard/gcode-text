project('gcode-text',
	license : 'GPLv2',
	version: '0.4'
       )

share_dir = get_option('prefix') / get_option('datadir') / meson.project_name()

message('share_dir is ' + share_dir)

dirs_data = configuration_data()
dirs_data.set('SHARE_DIR', share_dir)
dirs_data.set('VERSION', meson.project_version())

configure_file(input: 'gcode-text.5c',
	       output: 'gcode-text',
	       configuration: dirs_data,
	       install_mode: 'rwxr-xr-x',
	       install_dir: get_option('bindir')
	      )

install_man('gcode-text.1')

device_files = [
  'device-default.json',
  'svg.json'
  ]

install_data(device_files)
