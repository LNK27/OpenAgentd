.PHONY: dev ios-init ios-dev ios-build build clean

dev: ## Run the mobile shell against the web Vite dev server
	cd src-tauri && cargo tauri dev

ios-init: ## Initialize Tauri iOS project files
	cd src-tauri && cargo tauri ios init

ios-dev: ## Run on an iOS simulator/device
	cd src-tauri && cargo tauri ios dev

ios-build: ## Build the iOS app
	cd src-tauri && cargo tauri ios build

build: ## Build the mobile Tauri app bundle
	cd src-tauri && cargo tauri build

clean: ## Remove mobile build artifacts
	rm -rf src-tauri/target src-tauri/gen src-tauri/ios
