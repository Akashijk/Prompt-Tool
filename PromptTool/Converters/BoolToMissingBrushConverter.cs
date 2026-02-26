using System;
using Avalonia.Data.Converters;
using Avalonia.Media;

namespace PromptTool.Converters;

public class BoolToMissingBrushConverter : IValueConverter
{
    public object? Convert(object? value, Type targetType, object? parameter, System.Globalization.CultureInfo culture)
    {
        if (value is bool b && b)
        {
            return Brushes.DarkOrange;
        }
        return Brushes.Gray;
    }

    public object? ConvertBack(object? value, Type targetType, object? parameter, System.Globalization.CultureInfo culture)
    {
        throw new NotSupportedException();
    }
}
