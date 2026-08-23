// SPDX-License-Identifier: AGPL-3.0-or-later

// Command gen-assets renders the real "PIE Manager" brand icon (the same 256x256 PNG
// embedded in launcher.exe/pie-manager.exe via winres, see ../256x256.png) down to the
// sizes required by AppxManifest.xml (Square44x44Logo, Square150x150Logo).
package main

import (
	"fmt"
	"image"
	"image/color"
	"image/png"
	"os"
	"path/filepath"
)

// resize downsamples src to a size x size square using an area-average (box) filter:
// every destination pixel is the average of all source pixels that fall under it. This
// is the correct approach for shrinking an image (as opposed to point-sampling or naive
// nearest-neighbor), since it avoids aliasing on the icon's fine details (grid lines,
// text) — appropriate here because every target size (150, 44) is smaller than the
// 256x256 source, i.e. always downsampling, never upsampling.
func resize(src image.Image, size int) *image.RGBA {
	bounds := src.Bounds()
	srcW, srcH := bounds.Dx(), bounds.Dy()
	dst := image.NewRGBA(image.Rect(0, 0, size, size))
	for y := 0; y < size; y++ {
		srcY0 := y * srcH / size
		srcY1 := (y + 1) * srcH / size
		if srcY1 <= srcY0 {
			srcY1 = srcY0 + 1
		}
		for x := 0; x < size; x++ {
			srcX0 := x * srcW / size
			srcX1 := (x + 1) * srcW / size
			if srcX1 <= srcX0 {
				srcX1 = srcX0 + 1
			}
			var r, g, b, a, n uint64
			for sy := srcY0; sy < srcY1; sy++ {
				for sx := srcX0; sx < srcX1; sx++ {
					pr, pg, pb, pa := src.At(bounds.Min.X+sx, bounds.Min.Y+sy).RGBA()
					r += uint64(pr)
					g += uint64(pg)
					b += uint64(pb)
					a += uint64(pa)
					n++
				}
			}
			dst.Set(x, y, color.RGBA64{
				R: uint16(r / n),
				G: uint16(g / n),
				B: uint16(b / n),
				A: uint16(a / n),
			})
		}
	}
	return dst
}

func writeResizedPNG(src image.Image, path string, size int) error {
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()
	return png.Encode(f, resize(src, size))
}

func loadSource(path string) (image.Image, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	return png.Decode(f)
}

func main() {
	if len(os.Args) != 3 {
		fmt.Fprintln(os.Stderr, "usage: gen-assets <source-icon.png> <output-dir>")
		os.Exit(1)
	}
	sourcePath, dir := os.Args[1], os.Args[2]

	src, err := loadSource(sourcePath)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}

	if err := os.MkdirAll(dir, 0o755); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	if err := writeResizedPNG(src, filepath.Join(dir, "Square44x44Logo.png"), 44); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	if err := writeResizedPNG(src, filepath.Join(dir, "Square150x150Logo.png"), 150); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
