all: run_tests report
	open htmlcov/index.html

run_tests:
	coverage run --branch --source=../singtserver -m pytest

report:
	coverage html

