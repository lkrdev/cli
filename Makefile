.PHONY: docs test-deps codemode-test codemode-start schema-rs test-rs coverage-py coverage-rs coverage

docs:
	uv run typer lkr/main.py utils docs --output lkr.md

test-deps:
	python tests/test_dependency_resolution.py 

codemode-test:
	uv run pytest tests/test_codemode.py

schema-rs:
	cargo build --release --manifest-path lkr/schema/rust/Cargo.toml && cp lkr/schema/rust/target/release/lib_schema_rs.so lkr/schema/_schema_rs.so

test-rs:
	cargo clippy --manifest-path lkr/schema/rust/Cargo.toml -- -D warnings
	cargo test --no-default-features --manifest-path lkr/schema/rust/Cargo.toml

coverage-py:
	uv run pytest tests/test_schema.py --cov=lkr.schema --cov=scripts.schema --cov-report=term-missing --cov-report=xml:coverage.xml

coverage-rs:
	RUSTFLAGS="-C instrument-coverage" LLVM_PROFILE_FILE="lkr/schema/rust/target/cov-%p-%m.profraw" cargo test --no-default-features --manifest-path lkr/schema/rust/Cargo.toml

coverage: test-rs coverage-py coverage-rs

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