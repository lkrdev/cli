.PHONY: docs test help

docs:
	typer lkr/main.py utils docs --output lkr.md 

test:
	@echo "Running tests..."
	pytest $(FILE)

help:
	@echo "Makefile for lkr project"
	@echo ""
	@echo "Usage:"
	@echo "  make <target> [VARIABLE=value]"
	@echo ""
	@echo "Targets:"
	@echo "  docs        Generate documentation using Typer."
	@echo "  test        Run Pytests. Use FILE=<path_to_test_file.py> to run a specific test file."
	@echo "  help        Show this help message."
	@echo ""