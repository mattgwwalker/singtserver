wheel:
	python setup.py build bdist_wheel

clean:
	rm -rf dist
	rm -rf build
	rm -rf singtserver.egg-info

cloc:
	cloc --exclude-list-file=exclude-list.txt singtserver
