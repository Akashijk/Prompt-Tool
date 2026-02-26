using System;
using Avalonia.Data.Converters;
using Avalonia.Media;

namespace PromptTool.Converters;

public class BoolToIncludeBrushConverter : IValueConverter
{
    public object? Convert(object? value, Type targetType, object? parameter, System.Globalization.CultureInfo culture)
    {
        if (value is bool b && b)
        {
            return new SolidColorBrush(Color.Parse("#1e3a2f"));
        }
        return Brushes.Transparent;
    }

    public object? ConvertBack(object? value, Type targetType, object? parameter, System.Globalization.CultureInfo culture)
    {
        throw new NotSupportedException();
    }
}
