using Avalonia.Controls;
using PromptTool.ViewModels;
using System.ComponentModel;
using System.Threading.Tasks;
using PromptTool.Core.Clients;
using System.Net.Http;
using System;
using System.Linq;
using PromptTool.Services;
using PromptTool.Views;
using Avalonia;
using Avalonia.Layout;
using Avalonia.Threading;
using CommunityToolkit.Mvvm.Input;
using Avalonia.Platform.Storage;
using PromptTool.Helpers;
using System.Collections.Generic;
using System.IO;
using System.Threading;

namespace PromptTool.Views;

public partial class SettingsWindow : Window
{
    private bool _closePromptActive;

    public SettingsWindow()
    {
        InitializeComponent();
        HookDialogCloseFromDataContext();
        Closing += OnClosing;
    }

    public SettingsWindow(SettingsViewModel viewModel)
    {
        InitializeComponent();
        DataContext = viewModel;
        HookDialogClose(viewModel);
        Closing += OnClosing;
    }

    public void NavigateToGenerationSection(string sectionKey)
    {
        var tabs = this.FindControl<TabControl>("SettingsTabs");
        var generationTab = this.FindControl<TabItem>("GenerationTab");
        if (tabs != null && generationTab != null)
        {
            tabs.SelectedItem = generationTab;
        }

        Dispatcher.UIThread.Post(() =>
        {
            var target = sectionKey switch
            {
                "SystemPrompts" => this.FindControl<Control>("SystemPromptsSection"),
                "InvokeAIModelDefaults" => this.FindControl<Control>("InvokeAIModelDefaultsSection"),
                "InvokeAILoraDefaults" => this.FindControl<Control>("InvokeAILoraDefaultsSection"),
                _ => this.FindControl<Control>("GenerationDefaultsSection")
            };
            target?.BringIntoView();
        }, DispatcherPriority.Background);
    }

    private void HookDialogCloseFromDataContext()
    {
        this.DataContextChanged += (_, _) =>
        {
            if (DataContext is SettingsViewModel vm)
            {
                HookDialogClose(vm);
            }
        };
    }

    private void HookDialogClose(SettingsViewModel viewModel)
    {
        viewModel.PropertyChanged += OnViewModelPropertyChanged;
    }

    private void OnViewModelPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(SettingsViewModel.DialogResult) && sender is SettingsViewModel vm && vm.DialogResult.HasValue)
        {
            Close(vm.DialogResult.Value);
        }
    }

    private async void OnClosing(object? sender, WindowClosingEventArgs e)
    {
        if (_closePromptActive) return;
        if (DataContext is not SettingsViewModel vm) return;
        if (vm.DialogResult.HasValue) return;
        if (!vm.HasPendingChanges()) return;

        e.Cancel = true;
        _closePromptActive = true;
        var choice = await ShowUnsavedChangesPromptAsync(
            "Unsaved settings",
            "You have unsaved changes. Save them before closing?");
        _closePromptActive = false;

        switch (choice)
        {
            case CloseChoice.Save:
                if (vm.SaveCommand is IAsyncRelayCommand asyncCmd)
                {
                    await asyncCmd.ExecuteAsync(null);
                }
                else
                {
                    vm.SaveCommand.Execute(null);
                }
                break;
            case CloseChoice.Discard:
                Close(false);
                break;
            case CloseChoice.Cancel:
                break;
        }
    }

    private enum CloseChoice
    {
        Save,
        Discard,
        Cancel
    }

    private async Task<CloseChoice> ShowUnsavedChangesPromptAsync(string title, string message)
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

        var saveButton = new Button { Content = "Save", MinWidth = 80 };
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

        saveButton.Click += (_, _) => dialog.Close(CloseChoice.Save);
        discardButton.Click += (_, _) => dialog.Close(CloseChoice.Discard);
        cancelButton.Click += (_, _) => dialog.Close(CloseChoice.Cancel);

        var result = await dialog.ShowDialog<CloseChoice>(this);
        return result;
    }

    private async void OpenGenerationDefaults(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        if (DataContext is not SettingsViewModel vm)
        {
            return;
        }

        var defaultsVm = new GenerationDefaultsViewModel
        {
        };

        try
        {
            var invokeClient = new InvokeAIClient(new HttpClient(), vm.SettingsService);
            if (Uri.TryCreate(vm.InvokeAIBaseUrl, UriKind.Absolute, out var uri))
            {
                invokeClient.UpdateBaseAddress(uri);
            }
            var schedulers = await invokeClient.GetSchedulersAsync();
            defaultsVm.SetSchedulers(schedulers, vm.DefaultScheduler ?? "dpmpp_2m_k");
        }
        catch
        {
            defaultsVm.SetSchedulers(new[] { vm.DefaultScheduler ?? "dpmpp_2m_k" }, vm.DefaultScheduler ?? "dpmpp_2m_k");
        }
        defaultsVm.SetDefaults(vm.GetDefaultsSnapshot(), vm.DefaultBaseModelType);
        var dialog = new GenerationDefaultsWindow { DataContext = defaultsVm };
        var result = await dialog.ShowDialog<bool?>(this);
        if (result == true)
        {
            vm.ApplyDefaultsSnapshot(defaultsVm.GetDefaultsSnapshot(), defaultsVm.CurrentBaseModelType);
        }
    }

    private async void BackupHistory_Click(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        if (DataContext is not SettingsViewModel vm)
        {
            return;
        }

        var provider = StorageProvider;
        if (provider == null)
        {
            return;
        }

        var folder = await PickBackupFolderAsync(provider, "Backup History");
        if (string.IsNullOrWhiteSpace(folder))
        {
            return;
        }

        var path = BuildBackupPath(folder, "prompttool_history");
        await RunBackupWithProgressAsync(ct => vm.BackupHistoryAsync(path, CreateProgress(), ct), "History");
    }

    private async void BackupConfig_Click(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        if (DataContext is not SettingsViewModel vm)
        {
            return;
        }

        var provider = StorageProvider;
        if (provider == null)
        {
            return;
        }

        var folder = await PickBackupFolderAsync(provider, "Backup Config/Content");
        if (string.IsNullOrWhiteSpace(folder))
        {
            return;
        }

        var path = BuildBackupPath(folder, "prompttool_config");
        await RunBackupWithProgressAsync(ct => vm.BackupConfigAsync(path, CreateProgress(), ct), "Config");
    }

    private async void BackupFull_Click(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        if (DataContext is not SettingsViewModel vm)
        {
            return;
        }

        var provider = StorageProvider;
        if (provider == null)
        {
            return;
        }

        var folder = await PickBackupFolderAsync(provider, "Full Backup");
        if (string.IsNullOrWhiteSpace(folder))
        {
            return;
        }

        var timestamp = DateTime.Now.ToString("yyyyMMdd_HHmmss");
        var configPath = Path.Combine(folder, $"prompttool_config_{timestamp}.zip");
        var historyPath = Path.Combine(folder, $"prompttool_history_{timestamp}.zip");

        await RunBackupWithProgressAsync(ct => vm.BackupFullAsync(configPath, historyPath, CreateProgress(), ct), "Full");
    }

    private async void RestoreBackup_Click(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        if (DataContext is not SettingsViewModel vm)
        {
            return;
        }

        var provider = StorageProvider;
        if (provider == null)
        {
            return;
        }

        var priorCursor = Cursor;
        Cursor = new Avalonia.Input.Cursor(Avalonia.Input.StandardCursorType.Wait);
        await Task.Yield();
        var zipPath = await PickZipFileAsync(provider, "Restore from Backup Zip");
        Cursor = priorCursor;
        if (string.IsNullOrWhiteSpace(zipPath))
        {
            return;
        }

        var sections = vm.InspectBackupSections(zipPath);
        if (!sections.HasConfig && !sections.HasHistory)
        {
            await ShowInfoAsync("Restore", "No matching entries found in the selected backup.");
            return;
        }

        var overwriteExisting = await ShowRestoreModeAsync();
        if (overwriteExisting == null)
        {
            return;
        }

        var summary = vm.BuildRestoreSummary(zipPath, sections.HasConfig, sections.HasHistory, overwriteExisting.Value);
        if (summary.TotalAdd + summary.TotalOverwrite + summary.TotalSkip == 0)
        {
            await ShowInfoAsync("Restore", "No matching entries found in the selected backup.");
            return;
        }

        var proceed = await ShowRestoreSummaryAsync(summary, overwriteExisting.Value);
        if (!proceed)
        {
            return;
        }

        await RunBackupWithProgressAsync(async ct =>
        {
            await vm.CreateAutoBackupAsync(sections.HasConfig, sections.HasHistory, ct);
            if (sections.HasConfig)
            {
                await vm.RestoreConfigAsync(zipPath, overwriteExisting.Value, ct);
            }
            if (sections.HasHistory)
            {
                await vm.RestoreHistoryAsync(zipPath, overwriteExisting.Value, ct);
            }
        }, "Restore");
    }

    private async void VerifyBackup_Click(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        if (DataContext is not SettingsViewModel vm)
        {
            return;
        }

        var provider = StorageProvider;
        if (provider == null)
        {
            return;
        }

        var zipPath = await PickZipFileAsync(provider, "Verify Backup Zip");
        if (string.IsNullOrWhiteSpace(zipPath))
        {
            return;
        }

        var result = vm.VerifyBackupZip(zipPath);
        var title = result.IsValid ? "Backup Verified" : "Backup Issue";
        await ShowInfoAsync(title, result.Message);
    }

    private void DeleteAutoBackups_Click(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        if (DataContext is not SettingsViewModel vm)
        {
            return;
        }

        vm.DeleteAutoBackups();
    }

    private async void PickTemplateDir_Click(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        await PickPathAsync("Select Template Base Directory", (vm, path) => vm.TemplateBaseDir = path, vm => vm.TemplateBaseDir);
    }

    private async void PickWildcardDir_Click(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        await PickPathAsync("Select Wildcard Directory", (vm, path) => vm.WildcardDir = path, vm => vm.WildcardDir);
    }

    private async void PickHistoryDir_Click(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        await PickPathAsync("Select History Directory", (vm, path) => vm.HistoryDir = path, vm => vm.HistoryDir);
    }

    private async void PickSystemPromptsDir_Click(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        await PickPathAsync("Select System Prompts Directory", (vm, path) => vm.SystemPromptBaseDir = path, vm => vm.SystemPromptBaseDir);
    }

    private async Task PickPathAsync(
        string title,
        Action<SettingsViewModel, string> apply,
        Func<SettingsViewModel, string?> current)
    {
        if (DataContext is not SettingsViewModel vm)
        {
            return;
        }

        var provider = StorageProvider;
        if (provider == null)
        {
            return;
        }

        var options = new FolderPickerOpenOptions
        {
            Title = title,
            AllowMultiple = false
        };
        var picked = await FilePickerHelper.PickFolderAsync(provider, options);
        if (string.IsNullOrWhiteSpace(picked))
        {
            return;
        }

        apply(vm, picked);
    }

    private static async Task<string?> PickBackupFolderAsync(IStorageProvider provider, string title)
    {
        var options = new FolderPickerOpenOptions
        {
            Title = title,
            AllowMultiple = false
        };
        return await FilePickerHelper.PickFolderAsync(provider, options);
    }

    private static string BuildBackupPath(string folder, string baseName)
    {
        var timestamp = DateTime.Now.ToString("yyyyMMdd_HHmmss");
        return Path.Combine(folder, $"{baseName}_{timestamp}.zip");
    }

    private static async Task<string?> PickZipFileAsync(IStorageProvider provider, string title)
    {
        var options = new FilePickerOpenOptions
        {
            Title = title,
            AllowMultiple = false,
            FileTypeFilter = new List<FilePickerFileType>
            {
                new FilePickerFileType("Zip archive") { Patterns = new[] { "*.zip" } }
            }
        };
        return await FilePickerHelper.PickOpenFileAsync(provider, options);
    }

    private async Task<bool?> ShowRestoreModeAsync()
    {
        var tcs = new TaskCompletionSource<bool?>();
        var overwriteCheck = new CheckBox { Content = "Overwrite existing files (recommended for full restore)", IsChecked = false };

        var dialog = new Window
        {
            Width = 420,
            Height = 200,
            WindowStartupLocation = WindowStartupLocation.CenterOwner,
            Title = "Restore Mode",
            Content = new StackPanel
            {
                Margin = new Thickness(12),
                Spacing = 12,
                Children =
                {
                    new TextBlock
                    {
                        Text = "Choose how to apply the backup.",
                        TextWrapping = Avalonia.Media.TextWrapping.Wrap
                    },
                    overwriteCheck,
                    new StackPanel
                    {
                        Orientation = Orientation.Horizontal,
                        HorizontalAlignment = HorizontalAlignment.Right,
                        Spacing = 8,
                        Children =
                        {
                            new Button { Content = "Cancel", IsCancel = true },
                            new Button { Content = "Restore", IsDefault = true }
                        }
                    }
                }
            }
        };

        var buttons = ((dialog.Content as StackPanel)?.Children.LastOrDefault() as StackPanel)?.Children;
        var cancel = buttons?.OfType<Button>().FirstOrDefault(b => string.Equals(b.Content?.ToString(), "Cancel", StringComparison.OrdinalIgnoreCase));
        var ok = buttons?.OfType<Button>().FirstOrDefault(b => string.Equals(b.Content?.ToString(), "Restore", StringComparison.OrdinalIgnoreCase));

        if (cancel != null)
        {
            cancel.Click += (_, __) =>
            {
                tcs.TrySetResult(null);
                dialog.Close();
            };
        }

        if (ok != null)
        {
            ok.Click += (_, __) =>
            {
                tcs.TrySetResult(overwriteCheck.IsChecked == true);
                dialog.Close();
            };
        }

        dialog.Closed += (_, __) =>
        {
            if (!tcs.Task.IsCompleted)
            {
                tcs.TrySetResult(null);
            }
        };

        await dialog.ShowDialog(this);
        return await tcs.Task;
    }

    private async Task<bool> ShowRestoreSummaryAsync(SettingsViewModel.RestoreSummary summary, bool overwriteExisting)
    {
        var tcs = new TaskCompletionSource<bool>();
        var overwriteLabel = overwriteExisting ? "Overwrite existing: ON" : "Overwrite existing: OFF (merge-only)";
        var message =
            $"Config: add {summary.ConfigAdd}, overwrite {summary.ConfigOverwrite}, skip {summary.ConfigSkip}\n" +
            $"History: add {summary.HistoryAdd}, overwrite {summary.HistoryOverwrite}, skip {summary.HistorySkip}\n\n" +
            $"{overwriteLabel}\n\nProceed with restore?";

        var dialog = new Window
        {
            Width = 420,
            Height = 240,
            WindowStartupLocation = WindowStartupLocation.CenterOwner,
            Title = "Restore Summary",
            Content = new StackPanel
            {
                Margin = new Thickness(12),
                Spacing = 12,
                Children =
                {
                    new TextBlock { Text = message, TextWrapping = Avalonia.Media.TextWrapping.Wrap },
                    new StackPanel
                    {
                        Orientation = Orientation.Horizontal,
                        HorizontalAlignment = HorizontalAlignment.Right,
                        Spacing = 8,
                        Children =
                        {
                            new Button { Content = "Cancel", IsCancel = true },
                            new Button { Content = "Restore", IsDefault = true }
                        }
                    }
                }
            }
        };

        var buttons = ((dialog.Content as StackPanel)?.Children.LastOrDefault() as StackPanel)?.Children;
        var cancel = buttons?.OfType<Button>().FirstOrDefault(b => string.Equals(b.Content?.ToString(), "Cancel", StringComparison.OrdinalIgnoreCase));
        var ok = buttons?.OfType<Button>().FirstOrDefault(b => string.Equals(b.Content?.ToString(), "Restore", StringComparison.OrdinalIgnoreCase));

        if (cancel != null)
        {
            cancel.Click += (_, __) =>
            {
                tcs.TrySetResult(false);
                dialog.Close();
            };
        }

        if (ok != null)
        {
            ok.Click += (_, __) =>
            {
                tcs.TrySetResult(true);
                dialog.Close();
            };
        }

        dialog.Closed += (_, __) =>
        {
            if (!tcs.Task.IsCompleted)
            {
                tcs.TrySetResult(false);
            }
        };

        await dialog.ShowDialog(this);
        return await tcs.Task;
    }

    private BackupProgressWindow? _backupProgressWindow;

    private IProgress<SettingsViewModel.BackupProgress> CreateProgress()
    {
        return new Progress<SettingsViewModel.BackupProgress>(p =>
        {
            _backupProgressWindow?.UpdateProgress($"{p.Stage} backup", p.Current, p.Total, p.Item);
        });
    }

    private async Task RunBackupWithProgressAsync(Func<CancellationToken, Task> runBackup, string title)
    {
        using var cts = new CancellationTokenSource();
        _backupProgressWindow = new BackupProgressWindow
        {
            Title = $"{title} Backup"
        };
        _backupProgressWindow.ShowInTaskbar = false;
        _backupProgressWindow.WindowStartupLocation = WindowStartupLocation.CenterOwner;
        _backupProgressWindow.CancelRequested = () => cts.Cancel();
        _backupProgressWindow.Show(this);
        _backupProgressWindow.UpdateProgress("Preparing backup...", 0, 0, null);

        try
        {
            await runBackup(cts.Token);
        }
        catch (OperationCanceledException)
        {
            await ShowInfoAsync("Backup", $"{title} backup canceled.");
        }
        finally
        {
            _backupProgressWindow.AllowClose();
            _backupProgressWindow.Close();
            _backupProgressWindow = null;
        }
    }

    private async void DeployScoringAgent_Click(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        if (DataContext is not SettingsViewModel vm)
        {
            return;
        }

        var service = new RemoteScorerDeploymentService();
        var dialogVm = new DeployRemoteScorerDialogViewModel(vm.SettingsService, service);
        var dialog = new DeployRemoteScorerDialog(dialogVm);
        await dialog.ShowDialog<bool?>(this);
    }

    private async void RemoveScoringAgent_Click(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        var script = RemoteScoringAgentService.BuildRemoveScript("$HOME/prompttool-aesthetic");
        await ShowScriptDialogAsync("Remove Remote Scoring Agent", script);
    }

    private async Task ShowScriptDialogAsync(string title, string script)
    {
        var dialog = new Window
        {
            Title = title,
            Width = 640,
            Height = 420,
            WindowStartupLocation = WindowStartupLocation.CenterOwner
        };

        var scriptBox = new TextBox
        {
            Text = script,
            AcceptsReturn = true,
            TextWrapping = Avalonia.Media.TextWrapping.NoWrap,
            IsReadOnly = true
        };
        var scroll = new ScrollViewer
        {
            Content = scriptBox,
            VerticalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Auto,
            HorizontalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Auto
        };

        var copyButton = new Button { Content = "Copy Script" };
        copyButton.Click += async (_, __) =>
        {
            if (dialog.Clipboard != null)
            {
                await dialog.Clipboard.SetTextAsync(script);
            }
        };
        var closeButton = new Button { Content = "Close" };
        closeButton.Click += (_, __) => dialog.Close();

        var actions = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            HorizontalAlignment = HorizontalAlignment.Right,
            Spacing = 8,
            Margin = new Thickness(0, 8, 0, 0),
            Children = { copyButton, closeButton }
        };
        var grid = new Grid
        {
            RowDefinitions = new RowDefinitions("*,Auto"),
            Children =
            {
                scroll,
                actions
            }
        };
        Grid.SetRow(scroll, 0);
        Grid.SetRow(actions, 1);
        dialog.Content = grid;

        await dialog.ShowDialog(this);
    }

    private async void OpenSystemPrompts_Click(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        if (DataContext is not SettingsViewModel vm) return;
        var editorVm = new SystemPromptEditorViewModel(vm.SettingsService);
        var win = new SystemPromptEditorWindow { DataContext = editorVm };
        win.Show(this);
        await Task.CompletedTask;
    }

    private async void OpenInvokeAIModelDefaults_Click(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        if (DataContext is not SettingsViewModel vm) return;
        var client = CreateInvokeClient(vm);
        if (!await client.CheckServerCompatibilityAsync())
        {
            await ShowInfoAsync("InvokeAI Offline", "InvokeAI server could not be reached. Check the base URL in Settings > Connections.");
            return;
        }
        var defaultsVm = new InvokeAIModelDefaultsViewModel(
            vm.SettingsService,
            client,
            vm.Notifications,
            vm.GetInvokeAIModelDefaultsSnapshot(),
            deferPersist: true);
        var win = new InvokeAIModelDefaultsWindow { DataContext = defaultsVm };
        var result = await win.ShowDialog<bool?>(this);
        if (result == true)
        {
            vm.ApplyInvokeAIModelDefaultsSnapshot(defaultsVm.GetDefaultsSnapshot());
        }
    }

    private async void OpenInvokeAILoraDefaults_Click(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        if (DataContext is not SettingsViewModel vm) return;
        var client = CreateInvokeClient(vm);
        if (!await client.CheckServerCompatibilityAsync())
        {
            await ShowInfoAsync("InvokeAI Offline", "InvokeAI server could not be reached. Check the base URL in Settings > Connections.");
            return;
        }
        var defaultsVm = new InvokeAILoraDefaultsViewModel(
            vm.SettingsService,
            client,
            vm.Notifications,
            vm.GetInvokeAILoraDefaultsSnapshot(),
            deferPersist: true);
        var win = new InvokeAILoraDefaultsWindow { DataContext = defaultsVm };
        var result = await win.ShowDialog<bool?>(this);
        if (result == true)
        {
            vm.ApplyInvokeAILoraDefaultsSnapshot(defaultsVm.GetDefaultsSnapshot());
        }
    }

            private InvokeAIClient CreateInvokeClient(SettingsViewModel vm)
            {
                var invokeClient = new InvokeAIClient(new HttpClient(), vm.SettingsService);        if (Uri.TryCreate(vm.InvokeAIBaseUrl, UriKind.Absolute, out var uri))
        {
            invokeClient.UpdateBaseAddress(uri);
        }
        return invokeClient;
    }

    private async Task ShowInfoAsync(string title, string message)
    {
        var tcs = new TaskCompletionSource<bool>();
        var dialog = new Window
        {
            Width = 420,
            Height = 180,
            WindowStartupLocation = WindowStartupLocation.CenterOwner,
            Title = title,
            Content = new StackPanel
            {
                Margin = new Thickness(12),
                Spacing = 12,
                Children =
                {
                    new TextBlock { Text = message, TextWrapping = Avalonia.Media.TextWrapping.Wrap },
                    new StackPanel
                    {
                        Orientation = Orientation.Horizontal,
                        HorizontalAlignment = HorizontalAlignment.Right,
                        Spacing = 8,
                        Children =
                        {
                            new Button { Content = "OK" }
                        }
                    }
                }
            }
        };

        var ok = ((dialog.Content as StackPanel)?.Children.LastOrDefault() as StackPanel)?.Children.FirstOrDefault() as Button;
        if (ok != null)
        {
            ok.Click += (_, __) =>
            {
                tcs.TrySetResult(true);
                dialog.Close();
            };
        }

        dialog.Closed += (_, __) =>
        {
            if (!tcs.Task.IsCompleted)
            {
                tcs.TrySetResult(true);
            }
        };

        dialog.Show(this);
        await tcs.Task;
    }
}
