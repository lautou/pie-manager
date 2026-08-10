// Command gen-assets renders the MSIX Store logo assets for launcher.exe
// (Square44x44Logo.png, Square150x150Logo.png, StoreLogo.png) by bilinearly
// downsampling the largest frame embedded in pie-manager.ico. A hand-written
// resize avoids pulling in an image-processing dependency for this one
// build-time step, and reading directly from the .ico avoids depending on
// installer/launcher/*.png — those are gitignored, local-only extraction
// artifacts (see .gitignore), not committed source assets.
package main

import (
	"bytes"
	"encoding/binary"
	"fmt"
	"image"
	"image/color"
	"image/png"
	"math"
	"os"
	"path/filepath"
)

var pngMagic = []byte{0x89, 'P', 'N', 'G', '\r', '\n', 0x1a, '\n'}

// loadLargestPNGFrame extracts the largest PNG-encoded frame embedded in a
// Windows .ico file. Modern icon tooling stores large (>=256x256) frames as
// PNG data inside the ICO container rather than raw DIB — confirmed for this
// app's own pie-manager.ico by inspecting its directory entries — so no
// third-party ICO decoder is needed here, just Go's stdlib PNG decoder
// pointed at the right byte range.
func loadLargestPNGFrame(path string) (image.Image, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	if len(data) < 6 || binary.LittleEndian.Uint16(data[2:4]) != 1 {
		return nil, fmt.Errorf("%s is not a valid ICO file", path)
	}
	count := int(binary.LittleEndian.Uint16(data[4:6]))

	bestArea := -1
	var bestFrame []byte
	for i := 0; i < count; i++ {
		off := 6 + i*16
		if off+16 > len(data) {
			break
		}
		w, h := int(data[off]), int(data[off+1])
		if w == 0 {
			w = 256
		}
		if h == 0 {
			h = 256
		}
		bytesInRes := int(binary.LittleEndian.Uint32(data[off+8 : off+12]))
		imageOffset := int(binary.LittleEndian.Uint32(data[off+12 : off+16]))
		end := imageOffset + bytesInRes
		if imageOffset < 0 || end > len(data) || !bytes.HasPrefix(data[imageOffset:], pngMagic) {
			continue // not a decodable PNG-in-ICO frame — skip
		}
		if area := w * h; area > bestArea {
			bestArea = area
			bestFrame = data[imageOffset:end]
		}
	}
	if bestFrame == nil {
		return nil, fmt.Errorf("%s has no PNG-encoded frame to decode", path)
	}
	return png.Decode(bytes.NewReader(bestFrame))
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
		fmt.Fprintln(os.Stderr, "usage: gen-assets <source.ico> <output-dir>")
		os.Exit(1)
	}
	srcPath, outDir := os.Args[1], os.Args[2]

	src, err := loadLargestPNGFrame(srcPath)
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
