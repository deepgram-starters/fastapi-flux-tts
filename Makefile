# FastAPI Flux TTS Makefile

PYTHON := python3
PIP := pip

.PHONY: help check check-prereqs init install start start-backend start-frontend test update clean status eject-frontend

help:
	@echo "FastAPI Flux TTS - Available Commands"
	@echo "====================================="
	@echo "  make check-prereqs   Check required tools are installed"
	@echo "  make init            Install dependencies"
	@echo "  make install         Install Python dependencies"
	@echo "  make start           Start the backend (port 8081)"
	@echo "  make clean           Remove caches and build artifacts"
	@echo ""
	@echo ""

check-prereqs:
	@command -v git >/dev/null 2>&1 || { echo "git is required"; exit 1; }
	@command -v $(PYTHON) >/dev/null 2>&1 || { echo "python3 is required"; exit 1; }
	@echo "✓ Prerequisites installed"

check: check-prereqs

init: check-prereqs install

install:
	@echo "==> Installing Python dependencies..."
	$(PIP) install -r requirements.txt

start:
	@if [ -d "frontend" ] && [ -n "$$(ls -A frontend 2>/dev/null)" ]; then \
		$(MAKE) start-backend & $(MAKE) start-frontend & wait; \
	else \
		$(MAKE) start-backend; \
	fi

start-backend:
	@if [ ! -f ".env" ]; then \
		echo "Error: .env not found. Run: cp sample.env .env"; \
		exit 1; \
	fi
	@echo "==> Starting backend on http://localhost:8081"
	$(PYTHON) app.py

start-frontend:
	@if [ ! -d "frontend" ] || [ -z "$$(ls -A frontend 2>/dev/null)" ]; then \
		echo "Error: Frontend submodule not present yet (flux-tts-html)."; \
		exit 1; \
	fi
	@echo "==> Starting frontend on http://localhost:8080"
	cd frontend && pnpm run dev -- --port 8080 --no-open

test:
	@if [ ! -f "contracts/tests/run-flux-tts-app.sh" ]; then \
		echo "Contract test not present yet (contracts/tests/run-flux-tts-app.sh)."; \
		exit 1; \
	fi
	cd contracts && ./tests/run-flux-tts-app.sh

update:
	git submodule update --remote --merge

clean:
	rm -rf __pycache__ */__pycache__
	rm -rf frontend/node_modules frontend/.vite frontend/dist

status:
	@git status --short
	@git submodule status || echo "(no submodules yet)"

eject-frontend:
	@echo ""
	@echo "⚠️  This will:"
	@echo "   1. Copy frontend submodule files into a regular 'frontend/' directory"
	@echo "   2. Remove the frontend git submodule configuration"
	@echo "   3. Remove the contracts git submodule"
	@echo "   4. Remove .gitmodules file"
	@echo ""
	@echo "   After ejecting, frontend changes can be committed directly"
	@echo "   with your backend changes. This cannot be undone."
	@echo ""
	@read -p "   Continue? [Y/n] " confirm; \
	if [ "$$confirm" != "Y" ] && [ "$$confirm" != "y" ] && [ -n "$$confirm" ]; then \
		echo "   Cancelled."; \
		exit 1; \
	fi
	@echo ""
	@echo "==> Ejecting frontend submodule..."
	@FRONTEND_TMP=$$(mktemp -d); \
	cp -r frontend/. "$$FRONTEND_TMP/"; \
	git submodule deinit -f frontend; \
	git rm -f frontend; \
	rm -rf .git/modules/frontend; \
	mkdir -p frontend; \
	cp -r "$$FRONTEND_TMP/." frontend/; \
	rm -rf "$$FRONTEND_TMP"; \
	rm -rf frontend/.git; \
	echo "   ✅ Frontend ejected to regular directory"
	@echo "==> Removing contracts submodule..."
	@if git config --file .gitmodules submodule.contracts.url > /dev/null 2>&1; then \
		git submodule deinit -f contracts; \
		git rm -f contracts; \
		rm -rf .git/modules/contracts; \
		echo "   ✅ Contracts submodule removed"; \
	else \
		echo "   ℹ️  No contracts submodule found"; \
	fi
	@if [ -f .gitmodules ] && [ ! -s .gitmodules ]; then \
		git rm -f .gitmodules; \
		echo "   ✅ Empty .gitmodules removed"; \
	fi
	@echo ""
	@echo "✅ Eject complete! Frontend files are now regular tracked files."
	@echo "   Run 'git add . && git commit' to save the changes."
