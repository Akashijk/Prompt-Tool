using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Interactivity;

namespace PromptTool.Views;

public partial class ConfirmDialog : Window
{
    public ConfirmDialog()
    {
        InitializeComponent();
    }

    public ConfirmDialog(string title, string message)
    {
        InitializeComponent();
        Title = title;
        MessageText.Text = message;
    }

    public static Task<bool> Show(Window owner, string title, string message)
    {
        var dlg = new ConfirmDialog(title, message);
        return dlg.ShowDialog<bool>(owner);
    }

    private void OnYes(object? sender, RoutedEventArgs e) => Close(true);
    private void OnNo(object? sender, RoutedEventArgs e) => Close(false);
}
