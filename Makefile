.PHONY: docs test-deps codemode-test codemode-start

docs:
	uv run typer lkr/main.py utils docs --output lkr.md

test-deps:
	python tests/test_dependency_resolution.py 

codemode-test:
	uv run python tests/test_codemode.py

codemode-start:
	@echo "Add this to your mcpServers config:"
	@echo "{"
	@echo "  \"mcpServers\": {"
	@echo "    \"lkr-codemode\": {"
	@echo "      \"command\": \"uv\","
	@echo "      \"args\": [\"--directory\", \"/Users/bryanweber/projects/lkr/cli\", \"run\", \"lkr\", \"code-mode\", \"run\"]"
	@echo "    }"
	@echo "  }"
	@echo "}"
	uv run lkr code-mode run