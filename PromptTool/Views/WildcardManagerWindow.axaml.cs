using System;
using System.Text.Json;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.Input;
using Avalonia.Controls.ApplicationLifetimes;
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
    private bool _stateRestored;

    public WildcardManagerWindow()
    {
        InitializeComponent();
        Opened += OnOpened;
        Closing += (_, __) => SaveWindowState();
        RestoreWindowState();
    }

    public WildcardManagerWindow(WildcardManagerViewModel vm)
    {
        InitializeComponent();
        DataContext = vm;
        Opened += OnOpened;
        Closing += (_, __) => SaveWindowState();
        RestoreWindowState();
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
        if (_stateRestored)
        {
            return;
        }
        _stateRestored = true;

        var settings = GetSettingsService()?.Settings;
        if (settings == null)
        {
            return;
        }

        if (Enum.TryParse<WindowState>(settings.WildcardManagerWindowState, out var state) && state != WindowState.Normal)
        {
            WindowState = state;
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

        WindowState = WindowState.Normal;
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

    private async void OnNewWildcardClicked(object? sender, RoutedEventArgs e)
    {
        if (DataContext is not WildcardManagerViewModel vm)
        {
            return;
        }

        var suggested = string.IsNullOrWhiteSpace(vm.CurrentWildcardName) ? "new_wildcard" : vm.CurrentWildcardName;
        var name = await TextInputDialog.ShowAsync("New Wildcard", "Wildcard name:", suggested, this);
        if (string.IsNullOrWhiteSpace(name))
        {
            return;
        }

        var mainVm = (Application.Current?.ApplicationLifetime as IClassicDesktopStyleApplicationLifetime)?.MainWindow?.DataContext as MainWindowViewModel;
        if (mainVm != null)
        {
            await mainVm.CreateWildcardWithOptionalAiAsync(name, this, vm);
            return;
        }

        vm.NewWildcardCommand.Execute(null);
    }

    private async void OnDedupeWildcardsClicked(object? sender, RoutedEventArgs e)
    {
        if (DataContext is not WildcardManagerViewModel vm)
        {
            return;
        }

        var dedupeVm = new WildcardDedupeViewModel(vm.WildcardService, vm.TemplateService);
        var win = new WildcardDedupeWindow(dedupeVm);
        await win.ShowDialog(this);

        await vm.LoadWildcardsCommand.ExecuteAsync(null);
        if (!string.IsNullOrWhiteSpace(dedupeVm.LastMergedName))
        {
            vm.SelectWildcardByNameCommand.Execute(dedupeVm.LastMergedName);
        }
    }

    private async void OnMergeSimilarClicked(object? sender, RoutedEventArgs e)
    {
        if (DataContext is not WildcardManagerViewModel vm || sender is not Button button || button.Tag is not string sourceName)
        {
            return;
        }

        var targetName = vm.CurrentWildcardName?.Trim();
        if (string.IsNullOrWhiteSpace(targetName))
        {
            return;
        }

        var confirm = await ConfirmDialog.Show(
            this,
            "Merge similar wildcard?",
            $"Merge '{sourceName}' into '{targetName}'?\n\nThis will combine overlapping choices, update template references, and delete '{sourceName}'.");

        if (!confirm)
        {
            return;
        }

        await vm.MergeWildcardIntoCurrentAsync(sourceName);
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

    private async void OnBulkAddChoicesClicked(object? sender, RoutedEventArgs e)
    {
        if (DataContext is not WildcardManagerViewModel vm)
        {
            return;
        }

        var raw = await MultiLineTextInputDialog.ShowAsync(
            "Add Multiple Entries",
            "Paste or type one entry per line. Blank lines are ignored, and leading bullets like '-', '*', or '•' are stripped.",
            null,
            this);

        if (string.IsNullOrWhiteSpace(raw))
        {
            return;
        }

        vm.AddChoicesFromLines(raw);
    }

    private async void OnAiSuggestChoicesClicked(object? sender, RoutedEventArgs e)
    {
        if (DataContext is not WildcardManagerViewModel vm || string.IsNullOrWhiteSpace(vm.CurrentWildcardName))
        {
            return;
        }

        var mainVm = (Application.Current?.ApplicationLifetime as IClassicDesktopStyleApplicationLifetime)?.MainWindow?.DataContext as MainWindowViewModel;
        if (mainVm == null)
        {
            vm.SetStatusMessage("AI suggestions are unavailable because the main window model could not be found.");
            return;
        }

        var description = await TextInputDialog.ShowAsync(
            "AI Suggest Entries",
            $"Describe what kinds of choices should be added to '{vm.CurrentWildcardName}'. AI may also suggest tags, includes, and requires when useful.",
            $"Add more high-quality {vm.CurrentWildcardName.Replace('_', ' ')} entries",
            this);

        if (string.IsNullOrWhiteSpace(description))
        {
            return;
        }

        try
        {
            vm.SetStatusMessage("AI is generating entry suggestions...");
            var generatedJson = await mainVm.GenerateWildcardSuggestionsForEditorAsync(vm.CurrentWildcardName, description.Trim());

            // Ensure the response is at least valid JSON before handing it to the editor append flow.
            _ = JsonDocument.Parse(generatedJson);

            var added = vm.AppendChoicesFromWildcardJson(generatedJson);
            if (added == 0)
            {
                vm.SetStatusMessage("AI returned suggestions, but no usable choices were found.");
            }
        }
        catch (Exception ex)
        {
            vm.SetStatusMessage($"AI suggestions failed: {ex.Message}");
        }
    }

    private void OnSortChoicesByValueClicked(object? sender, RoutedEventArgs e)
    {
        if (DataContext is not WildcardManagerViewModel vm)
        {
            return;
        }

        vm.SortChoicesCommand.Execute(null);
        e.Handled = true;
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
