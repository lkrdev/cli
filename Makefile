.PHONY: docs test-deps codemode-test codemode-start

docs:
	uv run typer lkr/main.py utils docs --output lkr.md

test-deps:
	python tests/test_dependency_resolution.py 

codemode-test:
	uv run pytest tests/test_codemode.py

schema-rs:
	cargo build --release --manifest-path lkr/schema/rust/Cargo.toml && cp lkr/schema/rust/target/release/lib_schema_rs.so lkr/schema/_schema_rs.so


download-swagger:
	uv run python lkr/codemode/download_swagger.py

codemode-start:
	@echo "Add this to your mcpServers config:"
	@echo "{"
	@echo "  \"mcpServers\": {"
	@echo "    \"lkr_codemode\": {"
	@echo "      \"command\": \"uvx\","
	@echo "      \"args\": [\"-q\", \"--from\", \"lkr-dev-cli[codemode]\", \"lkr\", \"code-mode\", \"run\"]"
	@echo "    }"
	@echo "  }"
	@echo "}"
	uv run -q lkr code-mode run