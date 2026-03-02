using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Interactivity;

namespace PromptTool.Views;

public partial class NegativePromptSaveDialog : Window
{
    public NegativePromptSaveDialog()
    {
        InitializeComponent();
    }

    public NegativePromptSaveDialog(string selectedPresetName)
    {
        InitializeComponent();
        MessageText.Text = string.IsNullOrWhiteSpace(selectedPresetName)
            ? "No preset is selected. You can save this as a new preset or skip saving."
            : $"Selected preset: {selectedPresetName}";
    }

    public static Task<NegativePromptSaveChoice> ShowAsync(Window owner, string selectedPresetName)
    {
        var dlg = new NegativePromptSaveDialog(selectedPresetName)
        {
            Topmost = true
        };
        dlg.Opened += (_, __) => dlg.Activate();
        return dlg.ShowDialog<NegativePromptSaveChoice>(owner);
    }

    private void OnOverwrite(object? sender, RoutedEventArgs e) => Close(NegativePromptSaveChoice.Overwrite);
    private void OnSaveAsNew(object? sender, RoutedEventArgs e) => Close(NegativePromptSaveChoice.SaveAsNew);
    private void OnSkip(object? sender, RoutedEventArgs e) => Close(NegativePromptSaveChoice.Skip);
    private void OnCancel(object? sender, RoutedEventArgs e) => Close(NegativePromptSaveChoice.Cancel);
}

public enum NegativePromptSaveChoice
{
    Overwrite,
    SaveAsNew,
    Skip,
    Cancel
}
