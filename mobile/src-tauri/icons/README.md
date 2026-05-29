# Icons

`icon.png` is the source icon. The desktop project uses the same source image.
The platform icon bundle is generated with:

```sh
cd mobile/src-tauri && cargo tauri icon icons/icon.png
```

That command writes the desktop bundle formats (`32x32.png`, `128x128.png`,
`128x128@2x.png`, `icon.icns`, `icon.ico`) and mobile platform assets under
`icons/android/`. For iOS, Tauri/Xcode copies generated AppIcon assets into
`gen/apple/Assets.xcassets/AppIcon.appiconset/` during iOS project generation;
`gen/` remains a local build artifact.
