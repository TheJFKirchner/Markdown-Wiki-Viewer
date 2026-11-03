# Draws the app icon (a small graph on a dark tile) and writes app.ico with all the
# sizes Windows uses. Edit the colors/shapes below and run build.cmd to apply it.
# To use your own artwork instead, just replace app.ico with any .ico file.

Add-Type -AssemblyName System.Drawing

$out = Join-Path $PSScriptRoot 'app.ico'
$sizes = 16, 24, 32, 48, 64, 256

$bgTop    = [System.Drawing.Color]::FromArgb(255, 52, 44, 78)
$bgBottom = [System.Drawing.Color]::FromArgb(255, 24, 21, 34)
$accent   = [System.Drawing.Color]::FromArgb(255, 167, 139, 250)
$edge     = [System.Drawing.Color]::FromArgb(200, 196, 181, 253)

# Layout on a 256x256 canvas: [x, y, radius]
$nodes = @(
    @(128, 128, 28),
    @(62, 72, 18),
    @(192, 64, 20),
    @(198, 184, 18),
    @(70, 192, 20)
)
$edges = @(@(0, 1), @(0, 2), @(0, 3), @(0, 4), @(1, 4), @(2, 3))

function Draw-Icon([int]$size) {
    $bmp = New-Object System.Drawing.Bitmap $size, $size, ([System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.Clear([System.Drawing.Color]::Transparent)
    $s = $size / 256.0

    # Rounded tile
    $r = 56 * $s; $d = $r * 2; $w = $size - 1
    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $path.AddArc(0, 0, $d, $d, 180, 90)
    $path.AddArc($w - $d, 0, $d, $d, 270, 90)
    $path.AddArc($w - $d, $w - $d, $d, $d, 0, 90)
    $path.AddArc(0, $w - $d, $d, $d, 90, 90)
    $path.CloseFigure()
    $rect = New-Object System.Drawing.RectangleF 0, 0, $size, $size
    $brush = New-Object System.Drawing.Drawing2D.LinearGradientBrush $rect, $bgTop, $bgBottom, 90
    $g.FillPath($brush, $path)

    # Edges, then nodes on top
    $pen = New-Object System.Drawing.Pen $edge, ([Math]::Max(1.0, 9 * $s))
    foreach ($e in $edges) {
        $a = $nodes[$e[0]]; $b = $nodes[$e[1]]
        $g.DrawLine($pen, [float]($a[0] * $s), [float]($a[1] * $s), [float]($b[0] * $s), [float]($b[1] * $s))
    }
    $fill = New-Object System.Drawing.SolidBrush $accent
    foreach ($n in $nodes) {
        $nr = [Math]::Max(1.5, $n[2] * $s)
        $g.FillEllipse($fill, [float]($n[0] * $s - $nr), [float]($n[1] * $s - $nr), [float]($nr * 2), [float]($nr * 2))
    }
    $g.Dispose()
    return $bmp
}

# Classic DIB entry (32-bit BGRA, bottom-up, plus an empty AND mask) for small sizes.
function Get-DibBytes($bmp) {
    $w = $bmp.Width; $h = $bmp.Height
    $ms = New-Object System.IO.MemoryStream
    $bw = New-Object System.IO.BinaryWriter $ms
    $maskRow = [int]([Math]::Floor(($w + 31) / 32) * 4)
    $bw.Write([int]40); $bw.Write([int]$w); $bw.Write([int]($h * 2))
    $bw.Write([int16]1); $bw.Write([int16]32); $bw.Write([int]0)
    $bw.Write([int]($w * $h * 4 + $maskRow * $h))
    $bw.Write([int]0); $bw.Write([int]0); $bw.Write([int]0); $bw.Write([int]0)
    for ($y = $h - 1; $y -ge 0; $y--) {
        for ($x = 0; $x -lt $w; $x++) {
            $c = $bmp.GetPixel($x, $y)
            $bw.Write([byte]$c.B); $bw.Write([byte]$c.G); $bw.Write([byte]$c.R); $bw.Write([byte]$c.A)
        }
    }
    $bw.Write((New-Object byte[] ($maskRow * $h)))
    $bw.Flush()
    return $ms.ToArray()
}

$images = foreach ($size in $sizes) {
    $bmp = Draw-Icon $size
    if ($size -ge 256) {
        $ms = New-Object System.IO.MemoryStream
        $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
        $bytes = $ms.ToArray()
    } else {
        $bytes = Get-DibBytes $bmp
    }
    $bmp.Dispose()
    ,@($size, $bytes)
}

$fs = [System.IO.File]::Create($out)
$bw = New-Object System.IO.BinaryWriter $fs
$bw.Write([int16]0); $bw.Write([int16]1); $bw.Write([int16]$images.Count)
$offset = 6 + 16 * $images.Count
foreach ($img in $images) {
    $dim = if ($img[0] -ge 256) { 0 } else { $img[0] }
    $bw.Write([byte]$dim); $bw.Write([byte]$dim); $bw.Write([byte]0); $bw.Write([byte]0)
    $bw.Write([int16]1); $bw.Write([int16]32)
    $bw.Write([int]$img[1].Length); $bw.Write([int]$offset)
    $offset += $img[1].Length
}
foreach ($img in $images) { $bw.Write([byte[]]$img[1]) }
$bw.Close()
Write-Host "Wrote $out"
