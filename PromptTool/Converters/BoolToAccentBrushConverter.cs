using System;
using Avalonia;
using Avalonia.Data.Converters;
using Avalonia.Media;

namespace PromptTool.Converters;

public sealed class BoolToAccentBrushConverter : IValueConverter
{
    public object? Convert(object? value, Type targetType, object? parameter, System.Globalization.CultureInfo culture)
    {
        var resources = Application.Current?.Resources;
        var accent = resources?["AccentBrush"] as IBrush ?? Brushes.DodgerBlue;
        var primary = resources?["TextPrimaryBrush"] as IBrush ?? Brushes.White;

        return value is bool b && b ? accent : primary;
    }

    public object? ConvertBack(object? value, Type targetType, object? parameter, System.Globalization.CultureInfo culture)
    {
        throw new NotSupportedException();
    }
}
