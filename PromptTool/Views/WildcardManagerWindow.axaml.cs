using System;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.Input;
using PromptTool.ViewModels;
using PromptTool.Core.Services;

namespace PromptTool.Views;

public partial class WildcardManagerWindow : Window
{
    // Notes:
    // - The previous Includes/Requires cell used stacked button layouts which visually overlapped in DataGrid cells.
    // - Replaced with a single count-pill button per cell + tooltip and a double-click mini editor.
    // Manual test steps:
    // 1) Hover Include/Requires count pill: tooltip lists current items and scrolls when long.
    // 2) Double-click count pill: editor opens; add/remove/reorder; OK applies, Cancel discards.
    // 3) In rule picker dialog, scroll both lists with wheel/trackpad.
    private string? _pendingSelectName;

    public WildcardManagerWindow()
    {
        InitializeComponent();
        Opened += OnOpened;
        Opened += (_, __) => RestoreWindowState();
        Closing += (_, __) => SaveWindowState();
    }

    public WildcardManagerWindow(WildcardManagerViewModel vm)
    {
        InitializeComponent();
        DataContext = vm;
        Opened += OnOpened;
        Opened += (_, __) => RestoreWindowState();
        Closing += (_, __) => SaveWindowState();
    }

    public void SelectWildcardOnOpen(string name)
    {
        _pendingSelectName = name;
    }

    private async void OnOpened(object? sender, EventArgs e)
    {
        if (string.IsNullOrWhiteSpace(_pendingSelectName)) return;
        if (DataContext is WildcardManagerViewModel vm)
        {
            await vm.SelectWildcardAfterLoadAsync(_pendingSelectName);
        }
        _pendingSelectName = null;
    }

    private SettingsService? GetSettingsService()
    {
        return (Application.Current as App)?.SettingsService;
    }

    private void RestoreWindowState()
    {
        var settings = GetSettingsService()?.Settings;
        if (settings == null)
        {
            return;
        }

        if (settings.WildcardManagerWindowWidth > 0 && settings.WildcardManagerWindowHeight > 0)
        {
            Width = settings.WildcardManagerWindowWidth;
            Height = settings.WildcardManagerWindowHeight;
        }

        if (settings.WildcardManagerWindowX != 0 || settings.WildcardManagerWindowY != 0)
        {
            Position = new PixelPoint((int)settings.WildcardManagerWindowX, (int)settings.WildcardManagerWindowY);
        }

        if (Enum.TryParse<WindowState>(settings.WildcardManagerWindowState, out var state))
        {
            WindowState = state;
        }
    }

    private void SaveWindowState()
    {
        var settingsService = GetSettingsService();
        if (settingsService == null)
        {
            return;
        }
        var settings = settingsService.Settings;

        settings.WildcardManagerWindowState = WindowState.ToString();
        if (WindowState == WindowState.Normal)
        {
            var bounds = Bounds;
            if (bounds.Width > 0 && bounds.Height > 0)
            {
                settings.WildcardManagerWindowWidth = bounds.Width;
                settings.WildcardManagerWindowHeight = bounds.Height;
                settings.WildcardManagerWindowX = bounds.X;
                settings.WildcardManagerWindowY = bounds.Y;
            }
        }

        _ = settingsService.SaveSettingsAsync(settings);
    }

    private async void OnDeleteWildcardClicked(object? sender, RoutedEventArgs e)
    {
        if (DataContext is not WildcardManagerViewModel vm || vm.SelectedWildcard == null) return;
        var confirm = await ConfirmDialog.Show(this, "Delete wildcard?",
            $"Delete '{vm.SelectedWildcard.Name}' permanently?");
        if (confirm)
        {
            await vm.DeleteWildcardCommand.ExecuteAsync(null);
        }
    }

    private async void OnDeleteUnusedClicked(object? sender, RoutedEventArgs e)
    {
        if (DataContext is not WildcardManagerViewModel vm) return;
        if (sender is not Button btn || btn.Tag is not string name || string.IsNullOrWhiteSpace(name)) return;

        var confirm = await ConfirmDialog.Show(this, "Delete unused wildcard?",
            $"Delete unused wildcard '{name}' permanently?");
        if (confirm)
        {
            await vm.DeleteUnusedWildcardCommand.ExecuteAsync(name);
        }
    }

    private async void OnDeleteAllUnusedClicked(object? sender, RoutedEventArgs e)
    {
        if (DataContext is not WildcardManagerViewModel vm) return;
        var confirm = await ConfirmDialog.Show(this, "Delete all unused?",
            "Delete all unused wildcards permanently?");
        if (confirm)
        {
            await vm.DeleteAllUnusedCommand.ExecuteAsync(null);
        }
    }

    private async void OnRenameWildcardClicked(object? sender, RoutedEventArgs e)
    {
        if (DataContext is not WildcardManagerViewModel vm || vm.SelectedWildcard == null) return;
        var newName = await TextInputDialog.ShowAsync("Rename Wildcard", "New name:", vm.SelectedWildcard.Name, this);
        if (string.IsNullOrWhiteSpace(newName)) return;
        await vm.RenameWildcardToAsync(newName);
    }

    private async void OnIncludesDoubleTapped(object? sender, RoutedEventArgs e)
    {
        if (DataContext is not WildcardManagerViewModel vm) return;
        if (sender is Control control && control.DataContext is WildcardChoiceViewModel choice)
        {
            vm.SelectedChoice = choice;
        }
        if (vm.SelectedChoice == null) return;

        var initial = vm.GetIncludeSelections();
        var result = await IncludesEditorWindow.ShowAsync(
            this,
            vm.GetWildcardNameList,
            vm.GetWildcardValues,
            initial);
        if (result == null) return;
        vm.ApplyIncludeSelections(result);
    }

    private async void OnRequiresDoubleTapped(object? sender, RoutedEventArgs e)
    {
        if (DataContext is not WildcardManagerViewModel vm) return;
        if (sender is Control control && control.DataContext is WildcardChoiceViewModel choice)
        {
            vm.SelectedChoice = choice;
        }
        if (vm.SelectedChoice == null) return;

        var initial = vm.GetRequiresRules();
        var result = await RequiresEditorWindow.ShowAsync(
            this,
            vm.GetWildcardNameList,
            vm.GetWildcardValues,
            initial);
        if (result == null) return;
        vm.ApplyRequiresRules(result);
    }

    private async void OnSetRequiresClicked(object? sender, RoutedEventArgs e)
    {
        if (DataContext is not WildcardManagerViewModel vm) return;
        if (sender is Control control && control.DataContext is WildcardChoiceViewModel choice)
        {
            vm.SelectedChoice = choice;
        }
        if (vm.SelectedChoice == null) return;
        var (wildcard, value) = vm.GetRequiresSelection();
        var selection = await RequiresPickerDialog.ShowAsync(
            this,
            vm.GetWildcardNameList(),
            vm.GetWildcardValues,
            wildcard,
            value);

        if (selection == null) return;
        vm.ApplyRequiresSelection(selection.WildcardName, selection.Value);
    }

    private void OnClearRequiresClicked(object? sender, RoutedEventArgs e)
    {
        if (DataContext is not WildcardManagerViewModel vm) return;
        if (sender is Control control && control.DataContext is WildcardChoiceViewModel choice)
        {
            vm.SelectedChoice = choice;
        }
        vm.ClearRequiresSelection();
    }

    private async void OnSetIncludeClicked(object? sender, RoutedEventArgs e)
    {
        if (DataContext is not WildcardManagerViewModel vm) return;
        if (sender is Control control && control.DataContext is WildcardChoiceViewModel choice)
        {
            vm.SelectedChoice = choice;
        }
        if (vm.SelectedChoice == null) return;
        var initial = vm.GetIncludeSelections();
        var selection = await IncludesPickerDialog.ShowAsync(
            this,
            vm.GetWildcardNameList(),
            vm.GetWildcardValues,
            initial);
        if (selection == null) return;
        vm.ApplyIncludeSelections(selection);
    }

    private void OnClearIncludeClicked(object? sender, RoutedEventArgs e)
    {
        if (DataContext is not WildcardManagerViewModel vm) return;
        if (sender is Control control && control.DataContext is WildcardChoiceViewModel choice)
        {
            vm.SelectedChoice = choice;
        }
        vm.ClearIncludeSelection();
    }


    private void WildcardListBox_SelectionChanged(object? sender, SelectionChangedEventArgs e)
    {
        if (sender is ListBox list && list.SelectedItem != null)
        {
            list.ScrollIntoView(list.SelectedItem);
        }
    }

    private void ChoicesGrid_KeyDown(object? sender, KeyEventArgs e)
    {
        if (DataContext is not WildcardManagerViewModel vm) return;
        if (e.Source is TextBox textBox && textBox.AcceptsReturn)
        {
            return;
        }

        if (e.Key == Key.Enter)
        {
            vm.AddChoiceCommand.Execute(null);
            e.Handled = true;
        }
        else if (e.Key == Key.Delete)
        {
            vm.DeleteChoiceCommand.Execute(null);
            e.Handled = true;
        }
    }
}
