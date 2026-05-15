# Icons

`icon.png` is the 1024×1024 source. The other PNG sizes (`32x32.png`,
`128x128.png`, `128x128@2x.png`) and the platform-specific bundles
(`icon.icns` for macOS, `icon.ico` for Windows) are generated from it by:

```sh
cd desktop/src-tauri && cargo tauri icon icons/icon.png
```

That command writes `icon.icns` and `icon.ico` alongside the existing PNGs.
The release CI runs it before packaging so committed binaries aren't needed.
