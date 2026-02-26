using Avalonia.Controls;
using Avalonia.Data.Converters;
using Avalonia.Input;
using System;
using System.Globalization;

namespace PromptTool.Converters
{
    public class BoolToHandCursorConverter : IValueConverter
    {
        public object? Convert(object? value, Type targetType, object? parameter, CultureInfo culture)
        {
            if (value is bool b)
            {
                return b ? new Cursor(StandardCursorType.Hand) : new Cursor(StandardCursorType.Arrow);
            }
            return new Cursor(StandardCursorType.Arrow);
        }

        public object? ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture)
        {
            throw new NotSupportedException();
        }
    }
}
