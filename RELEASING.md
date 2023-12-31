# Releasing gcode-text

Here are the steps used to release a new version of gcode-text

 1. Update version in meson.build

 2. Commit

	$ git commit -s -m'Version <xxx>' meson.build

 3. Tag

	$ git tag -s -m'Version <xxx>' <xxx> main

 4. Build upstream release bits

	$ rm -rf build
	$ meson setup build
	$ cd build && ninja dist

 5. Merge to debian

	$ git checkout debian
	$ git merge <xxx>
	$ dch -v <xxx>-1 -D unstable
	$ git commit -s -m'debian: Version <xxx>-1' debian/changelog
	$ git tag -s -m'debian: Version <xxx>-1' <xxx>-1 debian

 6. Build debian bits

	$ 
