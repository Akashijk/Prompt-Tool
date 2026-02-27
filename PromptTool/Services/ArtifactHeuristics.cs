using System;
using System.Runtime.InteropServices;
using Avalonia;
using Avalonia.Media.Imaging;

namespace PromptTool.Services;

public static class ArtifactHeuristics
{
    public static ArtifactFlags Evaluate(Bitmap bitmap)
    {
        try
        {
            var width = bitmap.PixelSize.Width;
            var height = bitmap.PixelSize.Height;
            if (width == 0 || height == 0) return default;

            var stride = width * 4;
            var data = new byte[stride * height];
            var handle = GCHandle.Alloc(data, GCHandleType.Pinned);
            try
            {
                bitmap.CopyPixels(new PixelRect(0, 0, width, height), handle.AddrOfPinnedObject(), data.Length, stride);
            }
            finally
            {
                handle.Free();
            }

            var step = Math.Max(1, Math.Min(width, height) / 200);
            var histogram = new int[256];
            double mean = 0;
            double m2 = 0;
            double edgeSum = 0;
            long count = 0;
            long edgeCount = 0;

            for (int y = 0; y < height - step; y += step)
            {
                var row = y * stride;
                var rowDown = (y + step) * stride;
                for (int x = 0; x < width - step; x += step)
                {
                    var idx = row + (x * 4);
                    var lum = Luminance(data, idx);
                    var bin = (int)Math.Clamp(Math.Round(lum), 0, 255);
                    histogram[bin]++;

                    var idxR = row + ((x + step) * 4);
                    var idxD = rowDown + (x * 4);
                    var lumR = Luminance(data, idxR);
                    var lumD = Luminance(data, idxD);

                    var edge = Math.Abs(lum - lumR) + Math.Abs(lum - lumD);
                    edgeSum += edge;
                    if (edge > 10) edgeCount++;

                    count++;
                    var delta = lum - mean;
                    mean += delta / count;
                    var delta2 = lum - mean;
                    m2 += delta * delta2;
                }
            }

            if (count == 0) return default;
            var variance = m2 / count;
            var stdDev = Math.Sqrt(variance);
            var edgeMean = edgeSum / count;
            var edgeDensity = edgeCount / (double)count;

            var maxBin = 0;
            var histTotal = 0;
            foreach (var value in histogram)
            {
                histTotal += value;
                if (value > maxBin) maxBin = value;
            }

            var maxBinRatio = histTotal > 0 ? maxBin / (double)histTotal : 0;

            var bandingRisk = maxBinRatio > 0.12 && stdDev < 18;
            var overSmoothRisk = edgeDensity < 0.02 || stdDev < 12;
            var warpRisk = edgeMean > 28 && stdDev < 20;

            return new ArtifactFlags(bandingRisk, overSmoothRisk, warpRisk);
        }
        catch
        {
            return default;
        }
    }

    private static double Luminance(byte[] data, int idx)
    {
        var b = data[idx];
        var g = data[idx + 1];
        var r = data[idx + 2];
        return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    }
}

public readonly record struct ArtifactFlags(bool BandingRisk, bool OverSmoothRisk, bool WarpRisk);
