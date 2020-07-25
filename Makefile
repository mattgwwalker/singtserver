singt.pex:
	pip freeze > pip_freeze.txt
	pex -o singt.pex -r pip_freeze.txt

clean:
	rm singt.pex
	rm pip_freeze.txt

