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
setup-noshell:
	@echo "🚀 Setting up the development environment with python $(PYTHON_VERSION)"
	@pyenv install $(PYTHON_VERSION) -s && pyenv local $(PYTHON_VERSION)  || (echo "🔴 Failed to run pyenv. Please review the README.md for setup instructions" && exit 1);
	@if [ "$$(python3 -V)" != "Python $(PYTHON_VERSION)" ]; then \
	    echo "Found python version: $$(python3 -V)"; \
		echo "${RED}Recommended python version not in path${RESET}\n${YELLOW}Please review the README.md for setup instructions${RESET}" && exit 1; \
	fi
	@brew install libomp pre-commit yamllint -q
	@echo "📥 Installing project dependencies for $(PYTHON_VERSION)..."
	@poetry install
	@echo "🔧 Setting up git hooks..."
	@make hooks
	@poetry self add "poetry-plugin-shell[poetry-plugin]" # for backwards compatibility
	@echo "${GREEN}✨ Done! Activating the virtual environment with: poetry shell${RESET}"

## Environment setup:
setup: ## Setup the development environment
	@make setup-noshell
	@poetry shell

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
	@poetry run pytest
	@echo "${GREEN}Tests completed successfully.${RESET}"

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
	@make ruff-check
	@make mypy
	@make vulture
	@make semgrep
	@make codespell-check
	@make deptry
	@echo "${GREEN}All linters completed successfully.${RESET}"

lint-fix: ## Run all the linters and fix the issues
	@make ruff-format
	@make mypy
	@make vulture
	@make semgrep
	@make codespell
	@make deptry
	@make check-project-readmes
	@echo "${GREEN}All linters fixed successfully.${RESET}"

codespell: ## Run codespell against the project and fix any errors found
	@echo "📝 Running codespell"
	@poetry run codespell -w --skip="dist,docs"
	@echo "${GREEN}Codespell completed successfully.${RESET}"

codespell-check: ## Check codespell against the project
	@echo "📝 Running codespell"
	@poetry run codespell --skip="dist,docs"
	@echo "${GREEN}Codespell check completed successfully.${RESET}"

deptry: ## Run deptry on the project
	@echo "🔎 Running deptry"
	@poetry run deptry .

ruff: ## Use ruff on the project
	@echo "🔎 Performing static code analysis"
	@poetry run ruff check --fix
	@echo "${GREEN}Static code analysis completed successfully.${RESET}"

ruff-check: ## Check the project with ruff
	@echo "🔎 Checking the project with ruff"
	@poetry run ruff check
	@echo "${GREEN}Project checked with ruff successfully.${RESET}"


mypy: ## Run mypy on the project - TODO(AML-312): enable mypy for all modules
	@echo "🔎 Running dmypy"
	@poetry run dmypy run ml_etl/ || poetry run dmypy run ml_etl/ # try dmypy twice in case it fails the first time
	@echo "${GREEN}dmypy completed successfully.${RESET}"


vulture: ## Run vulture on the project to detect dead code
	@echo "🔎 Running vulture"
	@vulture
	@echo "${GREEN}vulture completed successfully.${RESET}"

semgrep: ## Run project-specific semgrep rules
	@echo "🔒 Running semgrep"
	@export PYTHONWARNINGS="ignore" \
		&& python3 scripts/semgrep/generate_multi_project_semgrep_rules.py \
		&& semgrep --quiet --config scripts/semgrep --metrics=off --error --test scripts/semgrep \
		&& semgrep --quiet --config scripts/semgrep --metrics=off --exclude scripts/semgrep \
		&& semgrep --quiet --config scripts/semgrep --metrics=off --severity ERROR --error --exclude scripts/semgrep \
		&& echo "${GREEN}semgrep completed successfully.${RESET}"

ruff-format: ## Format the code of the project
	@echo "✨ Applying code formatting with ruff"
	@poetry run ruff format
	@echo "${GREEN}Code formatted successfully.${RESET}"

ruff-format-check: ## Check the code formatting of the project
	@echo "🔍 Checking code formatting with ruff"
	@poetry run ruff format --check
	@echo "${GREEN}Code formatting check completed successfully.${RESET}"

## Hooks:
hooks: ## Set up all the hooks
	@echo "🔧 Setting up pre-commit hooks"
	@which pre-commit >/dev/null || (echo "${RED}pre-commit not found${RESET}\n${YELLOW}Please install with:${RESET}brew install pre-commit" && exit 1)
	@pre-commit install
	@echo "${GREEN}Pre-commit hooks set up successfully${RESET}"

clean: ## clean
	@echo "🧹 ${YELLOW} Cleaning up...${RESET}"
	@venv_dir="$(shell poetry env info -p)" && \
		if [ -d "$$venv_dir" ]; then echo "Purging venv_dir: $$venv_dir"; rm -rf "$${venv_dir}"; \
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

## Databricks:
start-sync-databricks:
	@echo "${RED} This command has been renamed to 'captain start-sync-databricks'.${RESET}"

yamllint:
	@echo "🔎 Running yamllint"
	@which yamllint > /dev/null 2>&1 \
	  || ( echo "${RED}❌ yamllint not found. Please install with: brew install yamllint${RESET}" && exit 1 )
	@yamllint .buildkite && echo "${GREEN}✅  YAML validation passed.${RESET}"  \
	  || (echo "${RED}❌ Please fix errors in buildkite yaml spec${RESET}" && exit 1)
    
validate-jobs-yaml:
	@echo "🔎 Running jobs yaml validation"
	@poetry run python ml_etl/scripts/validate_jobs_yaml.py \
	  && echo "${GREEN}✅  Jobs yaml validation passed.${RESET}" \
	  || (echo "${RED}❌ Please fix errors in jobs yaml${RESET}" && exit 1)

.PHONY: all \
	setup \
	test coverage coverage-lcov coverage-html \
    lint lint-fix codespell codespell-check deptry \
	ruff ruff-check mypy vulture \
    format ruff-format format-check ruff-format-check \
	hooks pre-commit clean \
	seed new-seed \
	schema-migration \
	colima \
	start-sync-databricks \
	yamllint jobs-yaml-validation \
	help