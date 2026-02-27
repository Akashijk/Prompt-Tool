using System;
using System.Runtime.InteropServices;
using Avalonia;
using Avalonia.Media.Imaging;

namespace PromptTool.Services;

public static class ScoringHelper
{
    public static double CalculateScore(Bitmap bitmap)
    {
        try
        {
            var width = bitmap.PixelSize.Width;
            var height = bitmap.PixelSize.Height;
            if (width == 0 || height == 0) return 0;

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
            double mean = 0;
            double m2 = 0;
            double edgeSum = 0;
            long count = 0;

            for (int y = 0; y < height - step; y += step)
            {
                var row = y * stride;
                var rowDown = (y + step) * stride;
                for (int x = 0; x < width - step; x += step)
                {
                    var idx = row + (x * 4);
                    var lum = Luminance(data, idx);
                    var idxR = row + ((x + step) * 4);
                    var idxD = rowDown + (x * 4);
                    var lumR = Luminance(data, idxR);
                    var lumD = Luminance(data, idxD);

                    var edge = Math.Abs(lum - lumR) + Math.Abs(lum - lumD);
                    edgeSum += edge;

                    count++;
                    var delta = lum - mean;
                    mean += delta / count;
                    var delta2 = lum - mean;
                    m2 += delta * delta2;
                }
            }

            if (count == 0) return 0;
            var variance = m2 / count;
            var stdDev = Math.Sqrt(variance);
            var edgeMean = edgeSum / count;

            var edgeNorm = Math.Min(1.0, edgeMean / 40.0);
            var contrastNorm = Math.Min(1.0, stdDev / 64.0);
            var score = (edgeNorm * 0.7 + contrastNorm * 0.3) * 100.0;
            return Math.Round(score, 1);
        }
        catch
        {
            return 0;
        }
    }

    public static double CalculateSharpnessScore(Bitmap bitmap)
    {
        try
        {
            var width = bitmap.PixelSize.Width;
            var height = bitmap.PixelSize.Height;
            if (width == 0 || height == 0) return 0;

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

            var step = Math.Max(1, Math.Min(width, height) / 300);
            double sum = 0;
            double sumSq = 0;
            long count = 0;

            for (int y = step; y < height - step; y += step)
            {
                var row = y * stride;
                var rowUp = (y - step) * stride;
                var rowDown = (y + step) * stride;
                for (int x = step; x < width - step; x += step)
                {
                    var idx = row + (x * 4);
                    var idxL = row + ((x - step) * 4);
                    var idxR = row + ((x + step) * 4);
                    var idxU = rowUp + (x * 4);
                    var idxD = rowDown + (x * 4);

                    var c = Luminance(data, idx);
                    var lap = (-4 * c)
                              + Luminance(data, idxL)
                              + Luminance(data, idxR)
                              + Luminance(data, idxU)
                              + Luminance(data, idxD);

                    sum += lap;
                    sumSq += lap * lap;
                    count++;
                }
            }

            if (count == 0) return 0;
            var mean = sum / count;
            var variance = (sumSq / count) - (mean * mean);
            var stdDev = Math.Sqrt(Math.Max(0, variance));

            var normalized = Math.Min(1.0, stdDev / 30.0) * 100.0;
            return Math.Round(normalized, 1);
        }
        catch
        {
            return 0;
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
