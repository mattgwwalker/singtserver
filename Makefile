wheel:
	python setup.py build bdist_wheel

pex:
	pip freeze > pip_freeze.txt
	pex -o singt.pex -r pip_freeze.txt

clean:
	rm -f singt.pex
	rm -f pip_freeze.txt
	rm -rf dist

