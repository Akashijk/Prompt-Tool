using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Interactivity;

namespace PromptTool.Views;

public partial class ConfirmDialog : Window
{
    private const string DefaultConfirmText = "Delete";
    private const string DefaultCancelText = "Cancel";

    public ConfirmDialog()
    {
        InitializeComponent();
    }

    public ConfirmDialog(string title, string message, string confirmText = DefaultConfirmText, string cancelText = DefaultCancelText)
    {
        InitializeComponent();
        Title = title;
        MessageText.Text = message;
        YesButton.Content = string.IsNullOrWhiteSpace(confirmText) ? DefaultConfirmText : confirmText;
        NoButton.Content = string.IsNullOrWhiteSpace(cancelText) ? DefaultCancelText : cancelText;
    }

    public static Task<bool> Show(Window owner, string title, string message)
    {
        var dlg = new ConfirmDialog(title, message);
        return dlg.ShowDialog<bool>(owner);
    }

    public static Task<bool> Show(Window owner, string title, string message, string confirmText, string cancelText)
    {
        var dlg = new ConfirmDialog(title, message, confirmText, cancelText);
        return dlg.ShowDialog<bool>(owner);
    }

    private void OnYes(object? sender, RoutedEventArgs e) => Close(true);
    private void OnNo(object? sender, RoutedEventArgs e) => Close(false);
}
