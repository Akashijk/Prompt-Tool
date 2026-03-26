using System.Threading.Tasks;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;

namespace PromptTool.Views;

public enum WindowCloseChoice
{
    Save,
    Discard,
    Cancel
}

public static class WindowClosePrompt
{
    public static Task<WindowCloseChoice> ShowAsync(
        Window owner,
        string title,
        string message,
        string applyLabel = "Save")
    {
        var dialog = new Window
        {
            Title = title,
            WindowStartupLocation = WindowStartupLocation.CenterOwner,
            SizeToContent = SizeToContent.WidthAndHeight,
            CanResize = false
        };

        var text = new TextBlock
        {
            Text = message,
            TextWrapping = Avalonia.Media.TextWrapping.Wrap,
            Margin = new Thickness(0, 0, 0, 12)
        };

        var saveButton = new Button { Content = applyLabel, MinWidth = 80 };
        var discardButton = new Button { Content = "Discard", MinWidth = 80 };
        var cancelButton = new Button { Content = "Cancel", MinWidth = 80, IsCancel = true };

        var buttons = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            HorizontalAlignment = HorizontalAlignment.Right,
            Spacing = 8,
            Children = { saveButton, discardButton, cancelButton }
        };

        var panel = new StackPanel
        {
            Margin = new Thickness(12),
            Children = { text, buttons }
        };

        dialog.Content = panel;

        saveButton.Click += (_, _) => dialog.Close(WindowCloseChoice.Save);
        discardButton.Click += (_, _) => dialog.Close(WindowCloseChoice.Discard);
        cancelButton.Click += (_, _) => dialog.Close(WindowCloseChoice.Cancel);

        return dialog.ShowDialog<WindowCloseChoice>(owner);
    }
}
