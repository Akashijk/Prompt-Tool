using System;
using System.Globalization;
using Avalonia.Data.Converters;

namespace PromptTool.Converters;

public class IntToBoolConverter : IValueConverter
{
    public object? Convert(object? value, Type targetType, object? parameter, CultureInfo culture)
    {
        if (value is int intValue && targetType == typeof(bool))
        {
            return intValue > 0;
        }
        // Fallback for cases where value is null or not an int, or targetType is not bool
        return false;
    }

    public object? ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture)
    {
        throw new NotImplementedException();
    }
}
