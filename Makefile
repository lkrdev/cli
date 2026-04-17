.PHONY: docs test-deps codemode-test codemode-start

docs:
	typer lkr/main.py utils docs --output lkr.md

test-deps:
	python tests/test_dependency_resolution.py 

codemode-test:
	uv run python tests/test_codemode.py

codemode-start:
	uv run lkr code-mode run