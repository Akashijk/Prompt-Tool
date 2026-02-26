using System;
using System.Linq;
using System.Text.Json;
using System.Collections.Generic;
using System.Globalization;
using Avalonia.Data.Converters;
using PromptTool.ViewModels;

namespace PromptTool.Converters;

public class WildcardContentConverter : IMultiValueConverter
{
    public object? Convert(IList<object?> values, Type targetType, object? parameter, CultureInfo culture)
    {
        if (values.Count < 2)
        {
            return string.Empty;
        }

        var name = values[0] as string;
        var vm = values[1] as MainWindowViewModel;
        if (vm == null && values[1] is Avalonia.Controls.Window window)
        {
            vm = window.DataContext as MainWindowViewModel;
        }
        if (string.IsNullOrWhiteSpace(name) || vm == null)
        {
            return string.Empty;
        }

        //return vm.GetWildcardFileContent(name) ?? string.Empty;
        var content = vm.GetWildcardFileContent(name) ?? string.Empty;
        return FormatWildcardTooltip(content);

    }

    private static string FormatWildcardTooltip(string? content)
    {
        if (string.IsNullOrWhiteSpace(content))
            return string.Empty;

        try
        {
            using var doc = JsonDocument.Parse(content);
            var root = doc.RootElement;

            if (!root.TryGetProperty("choices", out var choices) || choices.ValueKind != JsonValueKind.Array)
                return content; // not the shape we expect

            var lines = new List<string>();

            foreach (var item in choices.EnumerateArray())
            {
                switch (item.ValueKind)
                {
                    case JsonValueKind.String:
                        lines.Add(item.GetString() ?? "");
                        break;

                    case JsonValueKind.Object:
                        if (item.TryGetProperty("value", out var v) && v.ValueKind == JsonValueKind.String)
                            lines.Add(v.GetString() ?? "");
                        break;
                }
            }

            // If we extracted anything, show it; otherwise fallback.
            lines = lines.Where(s => !string.IsNullOrWhiteSpace(s)).ToList();
            return lines.Count > 0 ? string.Join(Environment.NewLine, lines) : content;
        }
        catch (JsonException)
        {
            // Not valid JSON -> show raw text
            return content;
        }
    }

}
