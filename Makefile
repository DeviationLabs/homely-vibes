ifneq (,$(wildcard ./.env))
	include .env
	export
endif

RED    := $(shell tput -Txterm setaf 1)
GREEN  := $(shell tput -Txterm setaf 2)
YELLOW := $(shell tput -Txterm setaf 3)
WHITE  := $(shell tput -Txterm setaf 7)
CYAN   := $(shell tput -Txterm setaf 6)
RESET  := $(shell tput -Txterm sgr0)

PYTHON_VERSION ?= 3.13.7

all: help

## Environment setup:
setup:
	@echo "🚀 Setting up the development environment with python $(PYTHON_VERSION)"
	@pyenv install $(PYTHON_VERSION) -s && pyenv local $(PYTHON_VERSION)  || (echo "🔴 Failed to run pyenv. Please review the README.md for setup instructions" && exit 1);
	@if [ "$$(python3 -V)" != "Python $(PYTHON_VERSION)" ]; then \
	    echo "Found python version: $$(python3 -V)"; \
		echo "${RED}Recommended python version not in path${RESET}\n${YELLOW}Please review the README.md for setup instructions${RESET}" && exit 1; \
	fi
	@brew upgrade
	@brew install libomp pre-commit yamllint -q
	@echo "📥 Installing project dependencies for $(PYTHON_VERSION)..."
	@uv sync --extra dev
	@echo "📦 Initializing Git submodules..."
	@git submodule update --init --recursive
	@echo "🔧 Setting up git hooks..."
	@make hooks
	@echo "${GREEN}✨ Done! Activating the virtual environment with: source .venv/bin/activate${RESET}"

colima: ## Start colima if not already running
	@echo "🐳 Checking colima status..."
	@if brew services list | grep -q "colima.*started"; then \
		echo "${GREEN}✅ Colima is already running${RESET}"; \
	else \
		echo "${YELLOW}🚀 Starting colima...${RESET}"; \
		brew services start colima; \
		echo "${GREEN}✅ Colima started successfully${RESET}"; \
	fi
	@echo "💾 Checking available disk space..."
	@DISK_INFO=$$(colima ssh -- df -h /usr/local 2>/dev/null | tail -n1); \
	if [ -n "$$DISK_INFO" ]; then \
		AVAILABLE_SPACE=$$(echo "$$DISK_INFO" | awk '{print $$4}'); \
		echo "📊 Available space: $$AVAILABLE_SPACE"; \
		SPACE_GB=$$(echo "$$AVAILABLE_SPACE" | sed 's/G//'); \
		if [ -n "$$SPACE_GB" ] && [ "$$SPACE_GB" -lt 20 ] 2>/dev/null; then \
			echo "${RED}⚠️  Low disk space detected (< 20GB)${RESET}"; \
			echo "${YELLOW}💡 Consider running: docker system prune -a${RESET}"; \
		else \
			echo "${GREEN}✅ Sufficient disk space available${RESET}"; \
		fi; \
	else \
		echo "${YELLOW}⚠️  Could not check disk space - colima may not be fully started${RESET}"; \
	fi

test: ## Run the tests
	@echo "🧪 Running the tests"
	@echo "📦 Running main test suite..."
	@uv run pytest Tesla RachioFlume August
	@echo "🔧 Running NodeCheck tests in isolation..."
	@uv run pytest NodeCheck
	@echo "${GREEN}All tests completed successfully.${RESET}"

coverage: ## Run the tests with coverage
	@echo "🧪 Running the tests with coverage"
	@coverage run --source=ml_etl --module pytest
	@coverage report -m
	@echo "${GREEN}Tests with coverage completed successfully.${RESET}"

coverage-lcov: coverage ## Run the tests with coverage and generate lcov report
	@echo "🧪 Generating lcov report"
	@coverage lcov
	@echo "${GREEN}Tests with coverage and lcov report completed successfully.${RESET}"

coverage-html: coverage ## Run the tests with coverage and generate HTML report
	@echo "🧪 Generating HTML report"
	@coverage html
	@open htmlcov/index.html
	@echo "${GREEN}Tests with coverage and HTML report completed successfully.${RESET}"

## Linting:
lint: ## Run all the linters
	@make ruff
	@make mypy
	@make vulture
	@make semgrep
	@make codespell
	@make deptry
	@echo "${GREEN}All linters completed successfully.${RESET}"

codespell: ## Run codespell against the project and fix any errors found
	@echo "📝 Running codespell"
	@uv run codespell -w --skip="dist,docs,package-lock.json,node_modules"
	@echo "${GREEN}Codespell completed successfully.${RESET}"

deptry: ## Run deptry on the project
	@echo "🔎 Running deptry"
	@uv run deptry .
	@echo "${GREEN}deptry completed successfully.${RESET}"

ruff: ## Use ruff on the project
	@echo "🔎 Performing static code analysis"
	@uv run ruff check --fix
	@uv run ruff format
	@echo "${GREEN}Static code analysis completed successfully.${RESET}"

mypy: ## Run mypy on the project
	@echo "🔎 Running mypy"
	@uv run mypy .
	@echo "${GREEN}mypy completed successfully.${RESET}"

vulture: ## Run vulture on the project to detect dead code
	@echo "🔎 Running vulture"
	@uv run vulture . --min-confidence 95 --exclude=.venv
	@echo "${GREEN}vulture completed successfully.${RESET}"

semgrep: ## Run semgrep security analysis
	@echo "🔒 Running semgrep"
	@uv run semgrep --config=auto .
	@echo "${GREEN}semgrep completed successfully.${RESET}"

## Hooks:
hooks: ## Set up all the hooks
	@echo "🔧 Setting up pre-commit hooks"
	@which pre-commit >/dev/null || (echo "${RED}pre-commit not found${RESET}\n${YELLOW}Please install with:${RESET}brew install pre-commit" && exit 1)
	@pre-commit install
	@echo "${GREEN}Pre-commit hooks set up successfully${RESET}"

clean: ## clean
	@echo "🧹 ${YELLOW} Cleaning up...${RESET}"
	@if [ -d ".venv" ]; then echo "Purging .venv directory"; rm -rf ".venv"; \
		else echo "No virtual env found"; fi || true
	@git clean -dfx __pycache__/ *.pyc *.pyo *.pyd .pytest_cache/ .mypy_cache/ .ruff_cache/ .dmypy.json
	@echo "${GREEN}✅ Cleaned successfully.${RESET}"

help:
	@echo ''
	@echo 'Usage:'
	@echo '  ${YELLOW}make${RESET} ${GREEN}<target>${RESET}'
	@echo ''
	@echo 'Targets:'
	@awk 'BEGIN {FS = ":.*?## "} { \
		if (/^[a-zA-Z_-]+:.*?##.*$$/) {printf "    ${YELLOW}%-30s${GREEN}%s${RESET}\n", $$1, $$2} \
		else if (/^## .*$$/) {printf "  ${CYAN}%s${RESET}\n", substr($$1,4)} \
		}' $(MAKEFILE_LIST)


yamllint:
	@echo "🔎 Running yamllint"
	@which yamllint > /dev/null 2>&1 \
	  || ( echo "${RED}❌ yamllint not found. Please install with: brew install yamllint${RESET}" && exit 1 )
	@yamllint .buildkite && echo "${GREEN}✅  YAML validation passed.${RESET}"  \
	  || (echo "${RED}❌ Please fix errors in buildkite yaml spec${RESET}" && exit 1)
    
validate-jobs-yaml:
	@echo "🔎 Running jobs yaml validation"
	@uv run python ml_etl/scripts/validate_jobs_yaml.py \
	  && echo "${GREEN}✅  Jobs yaml validation passed.${RESET}" \
	  || (echo "${RED}❌ Please fix errors in jobs yaml${RESET}" && exit 1)

.PHONY: all \
	setup \
	test coverage coverage-lcov coverage-html \
	lint lint-fix codespell deptry \
	ruff mypy vulture semgrep \
	hooks clean \
	colima \
	yamllint validate-jobs-yaml \
	help