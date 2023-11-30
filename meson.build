project('gcode-text',
	license : 'GPLv2',
	version: '0.1'
		 )

configure_file(input: 'gcode-text.5c',
	       output: 'gcode-text',
	       copy: true,
	       install_mode: 'rwxr-xr-x',
	       install_dir: get_option('bindir')
	      )

install_man('gcode-text.1')

install_data('device-default.json')
