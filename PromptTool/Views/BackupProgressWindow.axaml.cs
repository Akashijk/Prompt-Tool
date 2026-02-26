using Avalonia.Controls;

namespace PromptTool.Views;

public partial class BackupProgressWindow : Window
{
    private bool _canClose;

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

    public void UpdateProgress(string stage, int current, int total)
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
        DetailText.Text = $"{current:N0} / {total:N0}";
    }

    public void AllowClose()
    {
        _canClose = true;
    }
}
