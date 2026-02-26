using System;
using System.Collections.Concurrent;
using System.Diagnostics;
using System.Threading;

namespace PromptTool.Services;

public static class PerfLogger
{
    public static bool Enabled { get; set; } = true;

    private static readonly ConcurrentDictionary<string, long> Counters = new(StringComparer.OrdinalIgnoreCase);
    private static readonly ConcurrentDictionary<string, Timing> Timings = new(StringComparer.OrdinalIgnoreCase);

    public static IDisposable Time(string label)
    {
        return new LogScope(label);
    }

    public static IDisposable Measure(string key)
    {
        return new MeasureScope(key);
    }

    public static void Count(string key, long delta = 1)
    {
        if (!Enabled) return;
        Counters.AddOrUpdate(key, delta, (_, current) => current + delta);
    }

    public static void ResetCounters(params string[] keys)
    {
        if (!Enabled) return;
        foreach (var key in keys)
        {
            Counters[key] = 0;
        }
    }

    public static void ResetTimings(params string[] keys)
    {
        if (!Enabled) return;
        foreach (var key in keys)
        {
            Timings[key] = new Timing();
        }
    }

    public static void AddDuration(string key, long ticks)
    {
        if (!Enabled) return;
        var timing = Timings.GetOrAdd(key, _ => new Timing());
        Interlocked.Increment(ref timing.Count);
        Interlocked.Add(ref timing.TotalTicks, ticks);
    }

    public static long GetCount(string key)
    {
        return Counters.TryGetValue(key, out var value) ? value : 0;
    }

    public static void LogSummary(string label, params string[] timingKeys)
    {
        if (!Enabled) return;
        foreach (var key in timingKeys)
        {
            if (!Timings.TryGetValue(key, out var timing) || timing.Count == 0)
            {
                Log($"{label}: {key} count=0");
                continue;
            }

            var avgMs = timing.TotalTicks * 1000.0 / Stopwatch.Frequency / timing.Count;
            Log($"{label}: {key} count={timing.Count} avg={avgMs:0.0}ms");
        }
    }

    public static void Log(string message)
    {
        if (!Enabled) return;
        Console.WriteLine($"[perf] {message}");
    }

    private sealed class Timing
    {
        public long Count;
        public long TotalTicks;
    }

    private sealed class LogScope : IDisposable
    {
        private readonly string _label;
        private readonly long _start;
        private bool _disposed;

        public LogScope(string label)
        {
            _label = label;
            _start = Stopwatch.GetTimestamp();
        }

        public void Dispose()
        {
            if (_disposed || !Enabled) return;
            _disposed = true;
            var elapsedMs = (Stopwatch.GetTimestamp() - _start) * 1000.0 / Stopwatch.Frequency;
            Log($"{_label} took {elapsedMs:0.0}ms");
        }
    }

    private sealed class MeasureScope : IDisposable
    {
        private readonly string _key;
        private readonly long _start;
        private bool _disposed;

        public MeasureScope(string key)
        {
            _key = key;
            _start = Stopwatch.GetTimestamp();
        }

        public void Dispose()
        {
            if (_disposed || !Enabled) return;
            _disposed = true;
            AddDuration(_key, Stopwatch.GetTimestamp() - _start);
        }
    }
}
