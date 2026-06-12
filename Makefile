.PHONY: test
test:
	uv run pytest -q
	ruff check
	ruff format --check
	ty check
	basedpyright
