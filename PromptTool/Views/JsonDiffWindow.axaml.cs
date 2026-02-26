using Avalonia.Controls;
using Avalonia.Markup.Xaml;
using PromptTool.ViewModels;

namespace PromptTool.Views;

public partial class JsonDiffWindow : Window
{
    private Grid? _jsonGrid;
    private Border? _leftPanel;
    private Border? _rightPanel;

    public JsonDiffWindow()
    {
        InitializeComponent();
    }

    public JsonDiffWindow(JsonDiffViewModel viewModel) : this()
    {
        DataContext = viewModel;
        ApplyLayout(viewModel);
    }

    private void InitializeComponent()
    {
        AvaloniaXamlLoader.Load(this);
        _jsonGrid = this.FindControl<Grid>("JsonGrid");
        _leftPanel = this.FindControl<Border>("LeftPanel");
        _rightPanel = this.FindControl<Border>("RightPanel");
    }

    private void ApplyLayout(JsonDiffViewModel viewModel)
    {
        if (_jsonGrid == null || _leftPanel == null)
        {
            return;
        }

        if (viewModel.HasRightJson)
        {
            _jsonGrid.ColumnDefinitions = new ColumnDefinitions("*,*");
            Grid.SetColumnSpan(_leftPanel, 1);
            if (_rightPanel != null)
            {
                _rightPanel.IsVisible = true;
            }
        }
        else
        {
            _jsonGrid.ColumnDefinitions = new ColumnDefinitions("*");
            Grid.SetColumnSpan(_leftPanel, 1);
            if (_rightPanel != null)
            {
                _rightPanel.IsVisible = false;
            }
        }
    }

    private void Close_Click(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        Close();
    }

    private async void CopyLeft_Click(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        if (DataContext is not JsonDiffViewModel vm)
        {
            return;
        }

        var clipboard = this.Clipboard;
        if (clipboard == null)
        {
            return;
        }

        await clipboard.SetTextAsync(vm.LeftJson);
    }

    private async void CopyRight_Click(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        if (DataContext is not JsonDiffViewModel vm)
        {
            return;
        }

        if (string.IsNullOrWhiteSpace(vm.RightJson))
        {
            return;
        }

        var clipboard = this.Clipboard;
        if (clipboard == null)
        {
            return;
        }

        await clipboard.SetTextAsync(vm.RightJson);
    }
}
