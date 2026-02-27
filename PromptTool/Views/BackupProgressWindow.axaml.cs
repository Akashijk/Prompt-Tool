using System;
using Avalonia.Controls;

namespace PromptTool.Views;

public partial class BackupProgressWindow : Window
{
    private bool _canClose;
    public Action? CancelRequested { get; set; }

    public BackupProgressWindow()
    {
        InitializeComponent();
        Closing += (_, e) =>
        {
            if (!_canClose)
            {
                e.Cancel = true;
            }
        };
    }

    public void UpdateProgress(string stage, int current, int total, string? item)
    {
        StageText.Text = stage;
        if (total <= 0)
        {
            ProgressBar.IsIndeterminate = true;
            DetailText.Text = "";
            return;
        }

        ProgressBar.IsIndeterminate = false;
        ProgressBar.Value = total == 0 ? 0 : (double)current / total;
        if (string.IsNullOrWhiteSpace(item))
        {
            DetailText.Text = $"{current:N0} / {total:N0}";
            return;
        }

        DetailText.Text = $"{current:N0} / {total:N0}  —  {item}";
    }

    private void OnCancelClick(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        CancelButton.IsEnabled = false;
        StageText.Text = "Canceling...";
        CancelRequested?.Invoke();
    }

    public void AllowClose()
    {
        _canClose = true;
    }
}
