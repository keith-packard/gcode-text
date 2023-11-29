project('stroke-text',
	license : 'GPLv2',
	version: '0.1'
		 )

configure_file(input: 'stroke-text.5c',
	       output: 'stroke-text',
	       copy: true,
	       install_mode: 'rwxr-xr-x',
	       install_dir: get_option('bindir')
	      )

install_man('stroke-text.1')
