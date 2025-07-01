.PHONY: docs test-deps

docs:
	typer lkr/main.py utils docs --output lkr.md

test-deps:
	python tests/test_dependency_resolution.py 