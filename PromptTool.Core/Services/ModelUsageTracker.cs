using System.Collections.Generic;

namespace PromptTool.Core.Services;

public class ModelUsageTracker
{
    private readonly Dictionary<string, int> _usage = new(StringComparer.OrdinalIgnoreCase);
    private readonly object _lock = new();

    public void Register(string? model)
    {
        if (string.IsNullOrWhiteSpace(model)) return;
        lock (_lock)
        {
            _usage[model] = _usage.TryGetValue(model, out var count) ? count + 1 : 1;
        }
    }

    public IReadOnlyList<string> Release(string? model)
    {
        if (string.IsNullOrWhiteSpace(model)) return Array.Empty<string>();
        lock (_lock)
        {
            if (!_usage.TryGetValue(model, out var count)) return Array.Empty<string>();
            count--;
            if (count <= 0)
            {
                _usage.Remove(model);
                return new[] { model };
            }
            _usage[model] = count;
        }
        return Array.Empty<string>();
    }

    public IReadOnlyList<string> ActiveModels()
    {
        lock (_lock)
        {
            return _usage.Keys.ToList();
        }
    }
}
