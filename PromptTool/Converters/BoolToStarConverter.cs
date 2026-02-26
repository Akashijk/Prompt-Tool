using System;
using Avalonia.Data.Converters;

namespace PromptTool.Converters;

public class BoolToStarConverter : IValueConverter
{
    public object? Convert(object? value, Type targetType, object? parameter, System.Globalization.CultureInfo culture)
    {
        if (value is bool b && b)
        {
            return "★";
        }
        return "☆";
    }

    public object? ConvertBack(object? value, Type targetType, object? parameter, System.Globalization.CultureInfo culture)
    {
        if (value is string s)
        {
            return s.Contains("★");
        }
        return false;
    }
}
