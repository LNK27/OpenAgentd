.PHONY: dev ios-init ios-dev ios-dev-device ios-build ios-clean build clean

IOS_DEVICE ?= 00008110-001455560199801E

dev: ## Run the mobile shell against the web Vite dev server
	cd src-tauri && cargo tauri dev

ios-init: ## Initialize Tauri iOS project files
	cd src-tauri && cargo tauri ios init

ios-dev: ## Run on an iOS simulator/device
	cd src-tauri && cargo tauri ios dev --host

ios-dev-device: ## Run on the known physical iPhone
	cd src-tauri && cargo tauri ios dev --host --device $(IOS_DEVICE)

ios-build: ## Build the iOS app
	cd src-tauri && cargo tauri ios build

ios-clean: ## Remove generated iOS/Xcode state
	rm -rf src-tauri/gen ~/Library/Developer/Xcode/DerivedData/openagentd-mobile-*

build: ## Build the mobile Tauri app bundle
	cd src-tauri && cargo tauri build

clean: ## Remove mobile build artifacts
	rm -rf src-tauri/target src-tauri/gen src-tauri/ios
