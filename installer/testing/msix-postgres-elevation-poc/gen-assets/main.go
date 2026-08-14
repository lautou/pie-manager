// Command gen-assets writes two minimal solid-color PNG placeholders required
// by makeappx.exe (Square44x44Logo.png, Square150x150Logo.png). This is a
// throwaway MSIX diagnostic build (see ../README.md) — no real icon needed.
package main

import (
	"fmt"
	"image"
	"image/color"
	"image/png"
	"os"
	"path/filepath"
)

func writeSquarePNG(path string, size int) error {
	img := image.NewRGBA(image.Rect(0, 0, size, size))
	fill := color.RGBA{R: 0x4a, G: 0x9e, B: 0xff, A: 0xff}
	for y := 0; y < size; y++ {
		for x := 0; x < size; x++ {
			img.Set(x, y, fill)
		}
	}
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()
	return png.Encode(f, img)
}

func main() {
	if len(os.Args) != 2 {
		fmt.Fprintln(os.Stderr, "usage: gen-assets <output-dir>")
		os.Exit(1)
	}
	dir := os.Args[1]
	if err := os.MkdirAll(dir, 0o755); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	if err := writeSquarePNG(filepath.Join(dir, "Square44x44Logo.png"), 44); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	if err := writeSquarePNG(filepath.Join(dir, "Square150x150Logo.png"), 150); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
