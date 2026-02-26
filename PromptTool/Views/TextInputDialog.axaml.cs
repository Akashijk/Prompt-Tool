using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Interactivity;

namespace PromptTool.Views;

public partial class TextInputDialog : Window
{
    public TextInputDialog()
    {
        InitializeComponent();
    }

    public TextInputDialog(string title, string message, string? defaultValue = null)
    {
        InitializeComponent();
        Title = title;
        MessageText.Text = message;
        InputBox.Text = defaultValue ?? string.Empty;
    }

    public static async Task<string?> ShowAsync(string title, string message, string? defaultValue, Window owner)
    {
        var dlg = new TextInputDialog(title, message, defaultValue);
        return await dlg.ShowDialog<string?>(owner);
    }

    private void OnOk(object? sender, RoutedEventArgs e) => Close(InputBox.Text);
    private void OnCancel(object? sender, RoutedEventArgs e) => Close(null);
}
