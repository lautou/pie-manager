// Command gen-assets renders the MSIX Store logo assets for launcher.exe
// (Square44x44Logo.png, Square150x150Logo.png, StoreLogo.png) by bilinearly
// downsampling the existing 256x256 app icon. A hand-written resize avoids
// pulling in an image-processing dependency for this one build-time step.
package main

import (
	"fmt"
	"image"
	"image/color"
	"image/png"
	"math"
	"os"
	"path/filepath"
)

func loadPNG(path string) (image.Image, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	return png.Decode(f)
}

func clampInt(v, lo, hi int) int {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}

func nrgbaAt(img image.Image, x, y int) color.NRGBA {
	return color.NRGBAModel.Convert(img.At(x, y)).(color.NRGBA)
}

func lerp(a, b, t float64) float64 { return a + (b-a)*t }

// resizeBilinear scales src to a size x size image using bilinear
// interpolation — sufficient quality for a Store tile icon.
func resizeBilinear(src image.Image, size int) *image.NRGBA {
	bounds := src.Bounds()
	srcW, srcH := bounds.Dx(), bounds.Dy()
	dst := image.NewNRGBA(image.Rect(0, 0, size, size))

	scaleX := float64(srcW) / float64(size)
	scaleY := float64(srcH) / float64(size)

	for y := 0; y < size; y++ {
		srcY := (float64(y)+0.5)*scaleY - 0.5
		y0 := clampInt(int(math.Floor(srcY)), 0, srcH-1)
		y1 := clampInt(y0+1, 0, srcH-1)
		fy := srcY - math.Floor(srcY)

		for x := 0; x < size; x++ {
			srcX := (float64(x)+0.5)*scaleX - 0.5
			x0 := clampInt(int(math.Floor(srcX)), 0, srcW-1)
			x1 := clampInt(x0+1, 0, srcW-1)
			fx := srcX - math.Floor(srcX)

			c00 := nrgbaAt(src, bounds.Min.X+x0, bounds.Min.Y+y0)
			c10 := nrgbaAt(src, bounds.Min.X+x1, bounds.Min.Y+y0)
			c01 := nrgbaAt(src, bounds.Min.X+x0, bounds.Min.Y+y1)
			c11 := nrgbaAt(src, bounds.Min.X+x1, bounds.Min.Y+y1)

			r := lerp(lerp(float64(c00.R), float64(c10.R), fx), lerp(float64(c01.R), float64(c11.R), fx), fy)
			g := lerp(lerp(float64(c00.G), float64(c10.G), fx), lerp(float64(c01.G), float64(c11.G), fx), fy)
			b := lerp(lerp(float64(c00.B), float64(c10.B), fx), lerp(float64(c01.B), float64(c11.B), fx), fy)
			a := lerp(lerp(float64(c00.A), float64(c10.A), fx), lerp(float64(c01.A), float64(c11.A), fx), fy)

			dst.SetNRGBA(x, y, color.NRGBA{
				R: uint8(r + 0.5), G: uint8(g + 0.5), B: uint8(b + 0.5), A: uint8(a + 0.5),
			})
		}
	}
	return dst
}

func writeResized(src image.Image, size int, path string) error {
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()
	return png.Encode(f, resizeBilinear(src, size))
}

func main() {
	if len(os.Args) != 3 {
		fmt.Fprintln(os.Stderr, "usage: gen-assets <source-256x256.png> <output-dir>")
		os.Exit(1)
	}
	srcPath, outDir := os.Args[1], os.Args[2]

	src, err := loadPNG(srcPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	if err := os.MkdirAll(outDir, 0o755); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}

	targets := map[string]int{
		"Square44x44Logo.png":   44,
		"Square150x150Logo.png": 150,
		"StoreLogo.png":         50,
	}
	for name, size := range targets {
		if err := writeResized(src, size, filepath.Join(outDir, name)); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
	}
}
