using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Avalonia;
using Avalonia.Styling;
using Avalonia.Media;
using PromptTool.Core.Clients;
using PromptTool.Core.Config;
using PromptTool.Core.Models;
using PromptTool.Core.Services;
using PromptTool;
using System.Threading.Tasks;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Net.Http.Headers;
using PromptTool.Services;
using System.IO.Compression;
using System.Text.Json;
using System.Threading;
using System.ComponentModel;

namespace PromptTool.ViewModels;

public partial class SettingsViewModel : ObservableObject
{
    private readonly SettingsService _settingsService;
    private readonly OllamaClient _ollamaClient;
    private readonly InvokeAIClient? _invokeAiClient;
    private readonly NotificationService? _notifications;
    private readonly ImageCacheService _imageCacheService;
    private readonly ScoringCacheService _scoringCacheService = new();
    private readonly HttpClient _httpClient = new();
    private AppSettings _originalSettings;
    private Dictionary<string, GenerationDefaultsSettings> _workingDefaults = new();
    private List<ModelDefaults> _workingModelDefaults = new();
    private List<ModelDefaults> _workingLoraDefaults = new();
    private string _currentBaseModelType = "sdxl";

    public SettingsService SettingsService => _settingsService;
    public NotificationService? Notifications => _notifications;

    [ObservableProperty]
    private string _ollamaBaseUrl;

    [ObservableProperty]
    private string _invokeAIBaseUrl;

    [ObservableProperty]
    private string _templateBaseDir;

    [ObservableProperty]
    private string _wildcardDir;

    [ObservableProperty]
    private string _historyDir;

    [ObservableProperty]
    private string _systemPromptBaseDir;

    [ObservableProperty]
    private string _workflow;

    [ObservableProperty]
    private string? _defaultOllamaModel;

    [ObservableProperty]
    private string? _defaultScheduler;

    [ObservableProperty]
    private string _defaultNegativePrompt;

    [ObservableProperty] private string _defaultNegativePromptKey;
    [ObservableProperty] private int _invokeAITimeoutSeconds;
    [ObservableProperty] private string _theme;
    [ObservableProperty] private int _fontSize;

    [ObservableProperty]
    private int _defaultSteps;

    [ObservableProperty]
    private double _defaultCfgScale;

    [ObservableProperty]
    private double _defaultCfgRescaleMultiplier;

    [ObservableProperty]
    private int _defaultWidth;

    [ObservableProperty]
    private int _defaultHeight;

    [ObservableProperty]
    private bool _defaultSaveToGallery;

    [ObservableProperty]
    private string _defaultBaseModelType;

    [ObservableProperty]
    private bool _autoClearInvokeCacheBetweenModels;

    [ObservableProperty]
    private bool _serverSafetyModeEnabled;

    [ObservableProperty]
    private string _scoringCacheDir;

    [ObservableProperty]
    private string _aestheticModelsDir;

    [ObservableProperty]
    private string _imageCacheSizeLabel = string.Empty;

    [ObservableProperty]
    private string _clearImageCacheLabel = "Clear Image Cache";

    [ObservableProperty]
    private string _aestheticScoringBackend;

    public bool IsRemoteBackend => string.Equals(AestheticScoringBackend, "remote", StringComparison.OrdinalIgnoreCase);

    [ObservableProperty]
    private string _aestheticScoringRemoteUrl;

    [ObservableProperty]
    private string _settingsFilePath = string.Empty;

    [ObservableProperty]
    private bool _hasAutoBackups;

    public string AutoBackupDir => Path.Combine(_settingsService.ConfigDir, "backups");

    [ObservableProperty]
    private int _aestheticScoringRemoteBatchSize;

    [ObservableProperty]
    private string _huggingFaceApiKey;

    [ObservableProperty]
    private bool _verbose;
    [ObservableProperty]
    private bool _hasPendingChanges;
    public ObservableCollection<string> BaseModelTypes { get; } = new() { "sdxl", "sd-1.5" };
    public ObservableCollection<string> Themes { get; } = new() { "light", "dark", "system" };
    public ObservableCollection<string> AestheticScoringBackends { get; } = new() { "local", "remote" };
    [ObservableProperty] private ObservableCollection<string> _ollamaModels = new();
    public IReadOnlyList<string> Workflows { get; } = new[] { "sfw", "nsfw" };
    public ObservableCollection<NegativePresetItem> NegativePresets { get; } = new();
    [ObservableProperty] private NegativePresetItem? _selectedNegativePreset;
    [ObservableProperty] private string _editingPresetText = "";
    [ObservableProperty] private string _editingPresetName = "";

    [ObservableProperty]
    private bool? _dialogResult;

    public ObservableCollection<AestheticModelOption> AestheticModelCatalog { get; } = new();
    public ObservableCollection<AestheticModelOption> InstalledAestheticModels { get; } = new();
    [ObservableProperty] private AestheticModelOption? _selectedAestheticModel;
    public bool ShowAestheticModelDropdown => InstalledAestheticModels.Count > 1;
    [ObservableProperty] private bool _isAestheticDownloadActive;
    [ObservableProperty] private string _aestheticDownloadStatus = "";
    [ObservableProperty] private double _aestheticDownloadProgress;

    // Parameterless constructor for designer support
    public SettingsViewModel() : this(new SettingsService(), new OllamaClient(new System.Net.Http.HttpClient(), new SettingsService()), null, new ImageCacheService())
    {
    }

    public SettingsViewModel(
        SettingsService settingsService,
        OllamaClient ollamaClient,
        NotificationService? notifications = null,
        ImageCacheService? imageCacheService = null,
        InvokeAIClient? invokeAiClient = null)
    {
        _settingsService = settingsService;
        _ollamaClient = ollamaClient;
        _notifications = notifications;
        _imageCacheService = imageCacheService ?? new ImageCacheService();
        _invokeAiClient = invokeAiClient;
        var currentSettings = Clone(settingsService.Settings);
        _originalSettings = Clone(currentSettings);
        _workingDefaults = DeepCloneDefaults(settingsService.Settings.GenerationDefaults);
        _workingModelDefaults = CloneModelDefaults(settingsService.InvokeAIModelDefaults);
        _workingLoraDefaults = CloneModelDefaults(settingsService.InvokeAILoraDefaults);
        _ollamaBaseUrl = currentSettings.OllamaBaseUrl;
        _invokeAIBaseUrl = currentSettings.InvokeAIBaseUrl;
        _templateBaseDir = currentSettings.TemplateBaseDir;
        _wildcardDir = currentSettings.WildcardDir;
        _historyDir = currentSettings.HistoryDir;
        _systemPromptBaseDir = currentSettings.SystemPromptBaseDir;
        _workflow = currentSettings.Workflow;
        _defaultOllamaModel = currentSettings.DefaultOllamaModel;
        _defaultNegativePrompt = currentSettings.DefaultNegativePrompt;
        _defaultNegativePromptKey = currentSettings.DefaultNegativePromptKey;
        _invokeAITimeoutSeconds = currentSettings.InvokeAITimeoutSeconds;
        _theme = currentSettings.Theme;
        _fontSize = currentSettings.FontSize;
        _defaultBaseModelType = string.IsNullOrWhiteSpace(currentSettings.DefaultBaseModelType) ? "sdxl" : currentSettings.DefaultBaseModelType;
        _currentBaseModelType = _defaultBaseModelType;
        _autoClearInvokeCacheBetweenModels = currentSettings.AutoClearInvokeCacheBetweenModels;
        _serverSafetyModeEnabled = currentSettings.ServerSafetyModeEnabled;
        _aestheticScoringBackend = string.IsNullOrWhiteSpace(currentSettings.AestheticScoringBackend) ? "local" : currentSettings.AestheticScoringBackend;
        _aestheticScoringRemoteUrl = currentSettings.AestheticScoringRemoteUrl ?? string.Empty;
        _aestheticScoringRemoteBatchSize = currentSettings.AestheticScoringRemoteBatchSize <= 0 ? 8 : currentSettings.AestheticScoringRemoteBatchSize;
        _huggingFaceApiKey = currentSettings.HuggingFaceApiKey ?? string.Empty;
        _verbose = currentSettings.Verbose;
        _settingsFilePath = _settingsService.SettingsFileInUse;
        RefreshAutoBackups();
        _scoringCacheService.EnsureDirectories();
        _scoringCacheDir = _scoringCacheService.GetCacheDir();
        _aestheticModelsDir = _scoringCacheService.GetModelsDir();
        UpdateImageCacheLabels();
        InitializeAestheticModelCatalog();
        _ = RefreshAestheticModelListsAsync();
        NegativePresets.Clear();
        foreach (var kvp in currentSettings.NegativePromptPresets)
        {
            NegativePresets.Add(new NegativePresetItem(kvp.Key, kvp.Value));
        }
        SelectedNegativePreset = NegativePresets.FirstOrDefault(p => string.Equals(p.Key, _defaultNegativePromptKey, StringComparison.OrdinalIgnoreCase)) ?? NegativePresets.FirstOrDefault();
        if (SelectedNegativePreset != null) EditingPresetText = SelectedNegativePreset.Value;
        LoadDefaultsForBase(_defaultBaseModelType);
        UpdatePendingChanges();
    }

    [RelayCommand]
    private async Task Save()
    {
        var settingsToSave = BuildSettingsSnapshot();

        var hfKeyChanged = !string.Equals(settingsToSave.HuggingFaceApiKey, _originalSettings.HuggingFaceApiKey, StringComparison.Ordinal);
        if (hfKeyChanged && !await ValidateHuggingFaceKeyAsync(settingsToSave.HuggingFaceApiKey))
        {
            _notifications?.ShowError("Hugging Face API key validation failed. Please check the key and try again.", "Settings");
            return;
        }

        var defaultsChanged = !ModelDefaultsEqual(_workingModelDefaults, _settingsService.InvokeAIModelDefaults)
                              || !ModelDefaultsEqual(_workingLoraDefaults, _settingsService.InvokeAILoraDefaults);
        var changed = HasChanges(settingsToSave, _originalSettings) || defaultsChanged;
        var saved = await _settingsService.SaveSettingsAsync(settingsToSave);
        if (saved)
        {
            ApplyDefaultsToService(_settingsService.InvokeAIModelDefaults, _workingModelDefaults);
            ApplyDefaultsToService(_settingsService.InvokeAILoraDefaults, _workingLoraDefaults);
            var modelDefaultsSaved = _settingsService.SaveInvokeAIModelDefaults();
            var loraDefaultsSaved = _settingsService.SaveInvokeAILoraDefaults();
            if (!modelDefaultsSaved || !loraDefaultsSaved)
            {
                _notifications?.ShowError("Failed to save InvokeAI defaults. Your changes were not fully saved.", "Error");
                return;
            }

            _originalSettings = Clone(settingsToSave);
            ApplyThemeVariant(settingsToSave.Theme);
            if (hfKeyChanged && !string.IsNullOrWhiteSpace(settingsToSave.HuggingFaceApiKey))
            {
                _notifications?.ShowInfo("Hugging Face API key validated.", "Settings");
            }
            _notifications?.ShowInfo("Settings saved.", "Success");
            UpdatePendingChanges();
        }
        else
        {
            _notifications?.ShowError("Failed to save settings. Check logs for details.", "Error");
        }
        DialogResult = saved && changed;
    }

    public Task BackupHistoryAsync(string zipPath)
    {
        return BackupHistoryAsync(zipPath, null, CancellationToken.None);
    }

    public async Task BackupHistoryAsync(string zipPath, IProgress<BackupProgress>? progress, CancellationToken ct)
    {
        var historyDir = string.IsNullOrWhiteSpace(HistoryDir)
            ? _settingsService.Settings.HistoryDir
            : HistoryDir;

        if (string.IsNullOrWhiteSpace(historyDir) || !Directory.Exists(historyDir))
        {
            _notifications?.ShowWarning("History directory not found. Please check the History Directory setting.", "Backup");
            return;
        }

        try
        {
            var targetPath = zipPath;
            if (!targetPath.EndsWith(".zip", StringComparison.OrdinalIgnoreCase))
            {
                targetPath = $"{targetPath}.zip";
            }

            var historyFullPath = Path.GetFullPath(historyDir);
            var targetFullPath = Path.GetFullPath(targetPath);
            var tempPath = targetFullPath;

            if (targetFullPath.StartsWith(historyFullPath, StringComparison.OrdinalIgnoreCase))
            {
                tempPath = Path.Combine(Path.GetTempPath(), $"prompttool_history_{DateTime.Now:yyyyMMdd_HHmmss}.zip");
            }

            if (File.Exists(tempPath))
            {
                File.Delete(tempPath);
            }

            var total = CountFiles(historyFullPath, excludedDirs: null, excludedDirNames: new[] { ".thumbs" });
            var current = 0;
            progress?.Report(new BackupProgress("History", current, total, null));
            await Task.Run(() =>
            {
                using var archive = ZipFile.Open(tempPath, ZipArchiveMode.Create);
                AddDirectoryToZip(archive, historyFullPath, "history", progress, ref current, total, ct, "History", excludedDirs: null, excludedDirNames: new[] { ".thumbs" });
            }, ct);

            if (!string.Equals(tempPath, targetFullPath, StringComparison.OrdinalIgnoreCase))
            {
                if (File.Exists(targetFullPath))
                {
                    File.Delete(targetFullPath);
                }
                File.Move(tempPath, targetFullPath);
            }

            _notifications?.ShowInfo($"History backup created:\n{targetFullPath}", "Backup");
        }
        catch (Exception ex)
        {
            _notifications?.ShowError($"Failed to create history backup: {ex.Message}", "Backup");
        }
    }

    public Task BackupFullAsync(string configZipPath, string historyZipPath)
    {
        return BackupFullAsync(configZipPath, historyZipPath, null, CancellationToken.None);
    }

    public async Task BackupFullAsync(string configZipPath, string historyZipPath, IProgress<BackupProgress>? progress, CancellationToken ct)
    {
        await BackupConfigAsync(configZipPath, progress, ct);
        await BackupHistoryAsync(historyZipPath, progress, ct);
    }

    public Task BackupConfigAsync(string zipPath)
    {
        return BackupConfigAsync(zipPath, null, CancellationToken.None);
    }

    public async Task BackupConfigAsync(string zipPath, IProgress<BackupProgress>? progress, CancellationToken ct)
    {
        var configDir = _settingsService.ConfigDir;
        var templateDir = string.IsNullOrWhiteSpace(TemplateBaseDir) ? _settingsService.Settings.TemplateBaseDir : TemplateBaseDir;
        var wildcardDir = string.IsNullOrWhiteSpace(WildcardDir) ? _settingsService.Settings.WildcardDir : WildcardDir;
        var systemPromptsDir = string.IsNullOrWhiteSpace(SystemPromptBaseDir) ? _settingsService.Settings.SystemPromptBaseDir : SystemPromptBaseDir;
        var historyDir = string.IsNullOrWhiteSpace(HistoryDir) ? _settingsService.Settings.HistoryDir : HistoryDir;
        var scoringCacheDir = _scoringCacheService.GetCacheDir();
        var aestheticModelsDir = _scoringCacheService.GetModelsDir();

        try
        {
            var targetPath = EnsureZipPath(zipPath);
            var sourceRoots = new List<string>();
            AddIfExists(sourceRoots, configDir);
            AddIfExists(sourceRoots, templateDir);
            AddIfExists(sourceRoots, wildcardDir);
            AddIfExists(sourceRoots, systemPromptsDir);
            var excludedRoots = new List<string>();
            AddIfExists(excludedRoots, historyDir);
            AddIfExists(excludedRoots, AutoBackupDir);
            AddIfExists(excludedRoots, scoringCacheDir);
            AddIfExists(excludedRoots, aestheticModelsDir);
            if (excludedRoots.Count > 0)
            {
                var excludedCopy = excludedRoots.ToList();
                sourceRoots = sourceRoots
                    .Where(root => !excludedCopy.Any(exclude => IsSameOrUnder(root, exclude)))
                    .ToList();
            }

            if (sourceRoots.Count == 0)
            {
                _notifications?.ShowWarning("No config or content folders found to back up.", "Backup");
                return;
            }

            var tempPath = GetSafeTempZipPath(targetPath, sourceRoots);
            if (File.Exists(tempPath))
            {
                File.Delete(tempPath);
            }

            var total = sourceRoots.Sum(root => CountFiles(root, excludedRoots, excludedDirNames: new[] { ".thumbs" }));
            var current = 0;
            progress?.Report(new BackupProgress("Config", current, total, null));
            await Task.Run(() =>
            {
                using var archive = ZipFile.Open(tempPath, ZipArchiveMode.Create);
                AddDirectoryToZip(archive, configDir, "config", progress, ref current, total, ct, "Config", excludedRoots, excludedDirNames: new[] { ".thumbs" });
                AddDirectoryToZip(archive, templateDir, "templates", progress, ref current, total, ct, "Config", excludedRoots, excludedDirNames: new[] { ".thumbs" });
                AddDirectoryToZip(archive, wildcardDir, "wildcards", progress, ref current, total, ct, "Config", excludedRoots, excludedDirNames: new[] { ".thumbs" });
                AddDirectoryToZip(archive, systemPromptsDir, "system_prompts", progress, ref current, total, ct, "Config", excludedRoots, excludedDirNames: new[] { ".thumbs" });
            }, ct);

            if (!string.Equals(tempPath, targetPath, StringComparison.OrdinalIgnoreCase))
            {
                if (File.Exists(targetPath))
                {
                    File.Delete(targetPath);
                }
                File.Move(tempPath, targetPath);
            }

            _notifications?.ShowInfo($"Config backup created:\n{targetPath}", "Backup");
        }
        catch (Exception ex)
        {
            _notifications?.ShowError($"Failed to create config backup: {ex.Message}", "Backup");
        }
    }

    public async Task RestoreConfigAsync(string zipPath, bool overwriteExisting, bool restorePaths, CancellationToken ct)
    {
        if (!File.Exists(zipPath))
        {
            _notifications?.ShowWarning("Backup zip not found.", "Restore");
            return;
        }

        var configDir = _settingsService.ConfigDir;
        var templateDir = string.IsNullOrWhiteSpace(TemplateBaseDir) ? _settingsService.Settings.TemplateBaseDir : TemplateBaseDir;
        var wildcardDir = string.IsNullOrWhiteSpace(WildcardDir) ? _settingsService.Settings.WildcardDir : WildcardDir;
        var systemPromptsDir = string.IsNullOrWhiteSpace(SystemPromptBaseDir) ? _settingsService.Settings.SystemPromptBaseDir : SystemPromptBaseDir;

        try
        {
            await Task.Run(() =>
            {
                using var archive = ZipFile.OpenRead(zipPath);
                RestoreConfigFilesFromZip(archive, configDir, overwriteExisting, restorePaths);
                ExtractZipFolder(archive, "templates/", templateDir, overwriteExisting, ct);
                ExtractZipFolder(archive, "wildcards/", wildcardDir, overwriteExisting, ct);
                ExtractZipFolder(archive, "system_prompts/", systemPromptsDir, overwriteExisting, ct);
            }, ct);

            _settingsService.ReloadFromDisk();
            ReloadFromService();
            _notifications?.ShowInfo("Config/content restored and reloaded.", "Restore");
        }
        catch (Exception ex)
        {
            _notifications?.ShowError($"Failed to restore config: {ex.Message}", "Restore");
        }
    }

    public async Task RestoreHistoryAsync(string zipPath, bool overwriteExisting, CancellationToken ct)
    {
        if (!File.Exists(zipPath))
        {
            _notifications?.ShowWarning("Backup zip not found.", "Restore");
            return;
        }

        var historyDir = string.IsNullOrWhiteSpace(HistoryDir)
            ? _settingsService.Settings.HistoryDir
            : HistoryDir;

        if (string.IsNullOrWhiteSpace(historyDir))
        {
            _notifications?.ShowWarning("History directory not set.", "Restore");
            return;
        }

        try
        {
            await Task.Run(() =>
            {
                using var archive = ZipFile.OpenRead(zipPath);
                RestoreHistoryFromZip(archive, historyDir, overwriteExisting, ct);
            }, ct);

            _notifications?.ShowInfo("History restored.", "Restore");
        }
        catch (Exception ex)
        {
            _notifications?.ShowError($"Failed to restore history: {ex.Message}", "Restore");
        }
    }

    public BackupSections InspectBackupSections(string zipPath)
    {
        if (!File.Exists(zipPath))
        {
            return new BackupSections(false, false);
        }

        try
        {
            using var archive = ZipFile.OpenRead(zipPath);
            var hasConfig = archive.Entries.Any(e =>
                e.FullName.StartsWith("config/", StringComparison.OrdinalIgnoreCase) ||
                e.FullName.StartsWith("templates/", StringComparison.OrdinalIgnoreCase) ||
                e.FullName.StartsWith("wildcards/", StringComparison.OrdinalIgnoreCase) ||
                e.FullName.StartsWith("system_prompts/", StringComparison.OrdinalIgnoreCase));
            var hasHistory = archive.Entries.Any(e => e.FullName.StartsWith("history/", StringComparison.OrdinalIgnoreCase));
            return new BackupSections(hasConfig, hasHistory);
        }
        catch
        {
            return new BackupSections(false, false);
        }
    }

    public RestoreSummary BuildRestoreSummary(string zipPath, bool restoreConfig, bool restoreHistory, bool overwriteExisting)
    {
        var summary = new RestoreSummary
        {
            ZipPath = zipPath
        };
        if (!File.Exists(zipPath))
        {
            return summary;
        }

        var configDir = _settingsService.ConfigDir;
        var templateDir = string.IsNullOrWhiteSpace(TemplateBaseDir) ? _settingsService.Settings.TemplateBaseDir : TemplateBaseDir;
        var wildcardDir = string.IsNullOrWhiteSpace(WildcardDir) ? _settingsService.Settings.WildcardDir : WildcardDir;
        var systemPromptsDir = string.IsNullOrWhiteSpace(SystemPromptBaseDir) ? _settingsService.Settings.SystemPromptBaseDir : SystemPromptBaseDir;
        var historyDir = string.IsNullOrWhiteSpace(HistoryDir) ? _settingsService.Settings.HistoryDir : HistoryDir;

        using var archive = ZipFile.OpenRead(zipPath);
        foreach (var entry in archive.Entries)
        {
            if (entry.FullName.EndsWith("/", StringComparison.Ordinal))
            {
                continue;
            }

            summary.ArchiveFileCount++;

            if (restoreConfig && TryMapEntry(entry.FullName, "config/", configDir, out var configTarget))
            {
                summary.ConfigArchiveFiles++;
                UpdateSummary(summary, configTarget, overwriteExisting, isConfig: true);
                continue;
            }
            if (restoreConfig && TryMapEntry(entry.FullName, "templates/", templateDir, out var templateTarget))
            {
                summary.ConfigArchiveFiles++;
                UpdateSummary(summary, templateTarget, overwriteExisting, isConfig: true);
                continue;
            }
            if (restoreConfig && TryMapEntry(entry.FullName, "wildcards/", wildcardDir, out var wildcardTarget))
            {
                summary.ConfigArchiveFiles++;
                UpdateSummary(summary, wildcardTarget, overwriteExisting, isConfig: true);
                continue;
            }
            if (restoreConfig && TryMapEntry(entry.FullName, "system_prompts/", systemPromptsDir, out var systemTarget))
            {
                summary.ConfigArchiveFiles++;
                UpdateSummary(summary, systemTarget, overwriteExisting, isConfig: true);
                continue;
            }
            if (restoreHistory && TryMapEntry(entry.FullName, "history/", historyDir, out var historyTarget))
            {
                summary.HistoryArchiveFiles++;
                UpdateSummary(summary, historyTarget, overwriteExisting, isConfig: false);
                TrackHistoryLayout(summary, entry.FullName);
            }
        }

        summary.ConfigTargetDir = configDir;
        summary.TemplateTargetDir = templateDir;
        summary.WildcardTargetDir = wildcardDir;
        summary.SystemPromptsTargetDir = systemPromptsDir;
        summary.HistoryBaseTargetDir = historyDir;
        summary.ActiveWorkflow = string.IsNullOrWhiteSpace(_settingsService.Settings.Workflow) ? "sfw" : _settingsService.Settings.Workflow;
        summary.HistoryWorkflowTargetDir = Path.Combine(historyDir, summary.ActiveWorkflow);

        return summary;
    }

    public BackupVerifyResult VerifyBackupZip(string zipPath)
    {
        if (!File.Exists(zipPath))
        {
            return new BackupVerifyResult(false, "Backup zip not found.");
        }

        try
        {
            using var archive = ZipFile.OpenRead(zipPath);
            var fileCount = archive.Entries.Count(e => !e.FullName.EndsWith("/", StringComparison.Ordinal));
            if (fileCount == 0)
            {
                return new BackupVerifyResult(false, "Backup zip is empty.");
            }

            var hasConfig = archive.Entries.Any(e => e.FullName.StartsWith("config/", StringComparison.OrdinalIgnoreCase));
            var hasTemplates = archive.Entries.Any(e => e.FullName.StartsWith("templates/", StringComparison.OrdinalIgnoreCase));
            var hasWildcards = archive.Entries.Any(e => e.FullName.StartsWith("wildcards/", StringComparison.OrdinalIgnoreCase));
            var hasSystemPrompts = archive.Entries.Any(e => e.FullName.StartsWith("system_prompts/", StringComparison.OrdinalIgnoreCase));
            var hasHistory = archive.Entries.Any(e => e.FullName.StartsWith("history/", StringComparison.OrdinalIgnoreCase));

            var parts = new List<string> { $"Files: {fileCount}" };
            if (hasConfig) parts.Add("Config");
            if (hasTemplates) parts.Add("Templates");
            if (hasWildcards) parts.Add("Wildcards");
            if (hasSystemPrompts) parts.Add("System Prompts");
            if (hasHistory) parts.Add("History");

            if (!hasConfig && !hasTemplates && !hasWildcards && !hasSystemPrompts && !hasHistory)
            {
                return new BackupVerifyResult(false, "Backup zip does not contain known sections (config/templates/wildcards/system_prompts/history).");
            }

            return new BackupVerifyResult(true, $"Backup looks valid. Sections: {string.Join(", ", parts)}");
        }
        catch (Exception ex)
        {
            return new BackupVerifyResult(false, $"Failed to read backup zip: {ex.Message}");
        }
    }

    private void RestoreHistoryFromZip(ZipArchive archive, string historyDir, bool overwriteExisting, CancellationToken ct)
    {
        var stagingDir = Path.Combine(Path.GetTempPath(), $"prompttool_restore_{DateTime.Now:yyyyMMdd_HHmmss}");
        Directory.CreateDirectory(stagingDir);

        try
        {
            ExtractZipFolder(archive, "history/", stagingDir, overwriteExisting: true, ct);

            foreach (var file in Directory.EnumerateFiles(stagingDir, "*", SearchOption.AllDirectories))
            {
                var fileName = Path.GetFileName(file);
                if (fileName.Equals("history.json", StringComparison.OrdinalIgnoreCase) ||
                    fileName.Equals("history.jsonl", StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                var relative = Path.GetRelativePath(stagingDir, file);
                var targetPath = Path.Combine(historyDir, relative);
                Directory.CreateDirectory(Path.GetDirectoryName(targetPath) ?? historyDir);

                if (overwriteExisting)
                {
                    ReplaceFileWithRetry(file, targetPath);
                }
                else if (!File.Exists(targetPath))
                {
                    ReplaceFileWithRetry(file, targetPath);
                }
            }

            MergeHistoryIndexes(stagingDir, historyDir, overwriteExisting);
        }
        finally
        {
            try
            {
                Directory.Delete(stagingDir, recursive: true);
            }
            catch
            {
                // Best effort cleanup.
            }
        }
    }

    private static void RestoreConfigFilesFromZip(ZipArchive archive, string configDir, bool overwriteExisting, bool restorePaths)
    {
        foreach (var entry in archive.Entries)
        {
            if (!entry.FullName.StartsWith("config/", StringComparison.OrdinalIgnoreCase) ||
                entry.FullName.EndsWith("/", StringComparison.Ordinal))
            {
                continue;
            }

            var name = entry.FullName.Substring("config/".Length);
            if (string.IsNullOrWhiteSpace(name))
            {
                continue;
            }

            Directory.CreateDirectory(configDir);
            var targetPath = Path.Combine(configDir, name);
            var targetDir = Path.GetDirectoryName(targetPath);
            if (!string.IsNullOrWhiteSpace(targetDir))
            {
                Directory.CreateDirectory(targetDir);
            }
            if (!restorePaths && name.Equals("paths.json", StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            if (name.Equals("settings.json", StringComparison.OrdinalIgnoreCase))
            {
                RestoreSettingsFile(entry, targetPath, overwriteExisting);
                continue;
            }

            if (File.Exists(targetPath) && !overwriteExisting)
            {
                continue;
            }

            var tempPath = Path.Combine(configDir, $"{name}.tmp");
            var tempDir = Path.GetDirectoryName(tempPath);
            if (!string.IsNullOrWhiteSpace(tempDir))
            {
                Directory.CreateDirectory(tempDir);
            }
            entry.ExtractToFile(tempPath, overwrite: true);
            ReplaceFileWithRetry(tempPath, targetPath);
        }
    }

    private static void RestoreSettingsFile(ZipArchiveEntry entry, string targetPath, bool overwriteExisting)
    {
        var targetDir = Path.GetDirectoryName(targetPath);
        if (!string.IsNullOrWhiteSpace(targetDir))
        {
            Directory.CreateDirectory(targetDir);
        }

        var tempPath = $"{targetPath}.tmp";
        entry.ExtractToFile(tempPath, overwrite: true);

        if (!File.Exists(targetPath) || overwriteExisting)
        {
            ReplaceFileWithRetry(tempPath, targetPath);
            return;
        }

        try
        {
            var current = LoadSettingsFromFile(targetPath);
            var backup = LoadSettingsFromFile(tempPath);
            var merged = MergeRestoredSettings(current, backup);
            var json = JsonSerializer.Serialize(merged, new JsonSerializerOptions { WriteIndented = true });
            File.WriteAllText(tempPath, json);
            ReplaceFileWithRetry(tempPath, targetPath);
        }
        catch
        {
            File.Delete(tempPath);
        }
    }

    private static AppSettings LoadSettingsFromFile(string path)
    {
        if (!File.Exists(path))
        {
            return new AppSettings();
        }

        var json = File.ReadAllText(path);
        if (string.IsNullOrWhiteSpace(json))
        {
            return new AppSettings();
        }

        return JsonSerializer.Deserialize<AppSettings>(json) ?? new AppSettings();
    }

    private static AppSettings MergeRestoredSettings(AppSettings current, AppSettings backup)
    {
        current.NegativePromptPresets ??= new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        backup.NegativePromptPresets ??= new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

        foreach (var preset in backup.NegativePromptPresets)
        {
            if (!current.NegativePromptPresets.ContainsKey(preset.Key))
            {
                current.NegativePromptPresets[preset.Key] = preset.Value;
            }
        }

        if (string.IsNullOrWhiteSpace(current.DefaultNegativePrompt) &&
            !string.IsNullOrWhiteSpace(backup.DefaultNegativePrompt))
        {
            current.DefaultNegativePrompt = backup.DefaultNegativePrompt;
        }

        var currentDefaultKey = current.DefaultNegativePromptKey;
        if (string.IsNullOrWhiteSpace(currentDefaultKey) ||
            !current.NegativePromptPresets.ContainsKey(currentDefaultKey))
        {
            var backupDefaultKey = backup.DefaultNegativePromptKey;
            if (!string.IsNullOrWhiteSpace(backupDefaultKey) &&
                current.NegativePromptPresets.ContainsKey(backupDefaultKey))
            {
                current.DefaultNegativePromptKey = backupDefaultKey;
            }
            else if (current.NegativePromptPresets.Count > 0)
            {
                current.DefaultNegativePromptKey = current.NegativePromptPresets.Keys.First();
            }
        }

        if (string.IsNullOrWhiteSpace(current.DefaultNegativePrompt) &&
            !string.IsNullOrWhiteSpace(current.DefaultNegativePromptKey) &&
            current.NegativePromptPresets.TryGetValue(current.DefaultNegativePromptKey, out var presetValue))
        {
            current.DefaultNegativePrompt = presetValue;
        }

        return current;
    }

    private void ReloadFromService()
    {
        var currentSettings = Clone(_settingsService.Settings);
        _originalSettings = Clone(currentSettings);
        _workingDefaults = DeepCloneDefaults(currentSettings.GenerationDefaults);
        _workingModelDefaults = CloneModelDefaults(_settingsService.InvokeAIModelDefaults);
        _workingLoraDefaults = CloneModelDefaults(_settingsService.InvokeAILoraDefaults);

        OllamaBaseUrl = currentSettings.OllamaBaseUrl;
        InvokeAIBaseUrl = currentSettings.InvokeAIBaseUrl;
        TemplateBaseDir = currentSettings.TemplateBaseDir;
        WildcardDir = currentSettings.WildcardDir;
        HistoryDir = currentSettings.HistoryDir;
        SystemPromptBaseDir = currentSettings.SystemPromptBaseDir;
        Workflow = currentSettings.Workflow;
        DefaultOllamaModel = currentSettings.DefaultOllamaModel;
        DefaultNegativePrompt = currentSettings.DefaultNegativePrompt;
        DefaultNegativePromptKey = currentSettings.DefaultNegativePromptKey;
        InvokeAITimeoutSeconds = currentSettings.InvokeAITimeoutSeconds;
        Theme = currentSettings.Theme;
        FontSize = currentSettings.FontSize;
        DefaultBaseModelType = string.IsNullOrWhiteSpace(currentSettings.DefaultBaseModelType) ? "sdxl" : currentSettings.DefaultBaseModelType;
        _currentBaseModelType = DefaultBaseModelType;
        AutoClearInvokeCacheBetweenModels = currentSettings.AutoClearInvokeCacheBetweenModels;
        ServerSafetyModeEnabled = currentSettings.ServerSafetyModeEnabled;
        AestheticScoringBackend = string.IsNullOrWhiteSpace(currentSettings.AestheticScoringBackend) ? "local" : currentSettings.AestheticScoringBackend;
        AestheticScoringRemoteUrl = currentSettings.AestheticScoringRemoteUrl ?? string.Empty;
        AestheticScoringRemoteBatchSize = currentSettings.AestheticScoringRemoteBatchSize <= 0 ? 8 : currentSettings.AestheticScoringRemoteBatchSize;
        HuggingFaceApiKey = currentSettings.HuggingFaceApiKey ?? string.Empty;
        Verbose = currentSettings.Verbose;
        SettingsFilePath = _settingsService.SettingsFileInUse;

        NegativePresets.Clear();
        foreach (var kvp in currentSettings.NegativePromptPresets)
        {
            NegativePresets.Add(new NegativePresetItem(kvp.Key, kvp.Value));
        }

        SelectedNegativePreset = NegativePresets.FirstOrDefault(p => string.Equals(p.Key, DefaultNegativePromptKey, StringComparison.OrdinalIgnoreCase))
            ?? NegativePresets.FirstOrDefault();
        EditingPresetText = SelectedNegativePreset?.Value ?? string.Empty;
        EditingPresetName = SelectedNegativePreset?.Key ?? string.Empty;

        LoadDefaultsForBase(DefaultBaseModelType);
        ApplyThemeVariant(currentSettings.Theme);
        RefreshAutoBackups();
        UpdatePendingChanges();
    }

    private void MergeHistoryIndexes(string stagingDir, string historyDir, bool overwriteExisting)
    {
        var activeWorkflow = string.IsNullOrWhiteSpace(_settingsService.Settings.Workflow)
            ? "sfw"
            : _settingsService.Settings.Workflow;
        var activeWorkflowDir = Path.Combine(historyDir, activeWorkflow);

        var rootBackupEntries = ReadHistoryEntriesFromFile(Path.Combine(stagingDir, "history.json"));
        rootBackupEntries.AddRange(ReadHistoryEntriesFromFile(Path.Combine(stagingDir, "history.jsonl")));
        if (rootBackupEntries.Count > 0)
        {
            PromoteLegacyRootHistoryFiles(historyDir, activeWorkflowDir, overwriteExisting);
            MergeHistoryIndex(stagingDir, activeWorkflowDir, overwriteExisting);
        }

        foreach (var dir in Directory.EnumerateDirectories(stagingDir))
        {
            var workflow = Path.GetFileName(dir);
            if (string.IsNullOrWhiteSpace(workflow))
            {
                continue;
            }

            var targetDir = Path.Combine(historyDir, workflow);
            MergeHistoryIndex(dir, targetDir, overwriteExisting);
        }
    }

    private static void PromoteLegacyRootHistoryFiles(string sourceDir, string workflowDir, bool overwriteExisting)
    {
        var workflowSegment = Path.GetFileName(workflowDir.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar));
        foreach (var file in Directory.EnumerateFiles(sourceDir, "*", SearchOption.AllDirectories).ToList())
        {
            var relative = Path.GetRelativePath(sourceDir, file);
            if (string.IsNullOrWhiteSpace(relative))
            {
                continue;
            }

            var normalizedRelative = relative.Replace(Path.AltDirectorySeparatorChar, Path.DirectorySeparatorChar);
            var firstSegment = normalizedRelative.Split(Path.DirectorySeparatorChar, StringSplitOptions.RemoveEmptyEntries)
                .FirstOrDefault();

            if (string.IsNullOrWhiteSpace(firstSegment) ||
                firstSegment.Equals(workflowSegment, StringComparison.OrdinalIgnoreCase) ||
                firstSegment.Equals("sfw", StringComparison.OrdinalIgnoreCase) ||
                firstSegment.Equals("nsfw", StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            var fileName = Path.GetFileName(file);
            if (fileName.Equals("history.json", StringComparison.OrdinalIgnoreCase) ||
                fileName.Equals("history.jsonl", StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            var targetPath = Path.Combine(workflowDir, normalizedRelative);
            Directory.CreateDirectory(Path.GetDirectoryName(targetPath) ?? workflowDir);

            if (overwriteExisting)
            {
                ReplaceFileWithRetry(file, targetPath);
            }
            else if (!File.Exists(targetPath))
            {
                ReplaceFileWithRetry(file, targetPath);
            }
        }
    }

    private static void MergeHistoryIndex(string sourceDir, string targetDir, bool overwriteExisting)
    {
        var backupEntries = ReadHistoryEntriesFromFile(Path.Combine(sourceDir, "history.json"));
        backupEntries.AddRange(ReadHistoryEntriesFromFile(Path.Combine(sourceDir, "history.jsonl")));

        if (backupEntries.Count == 0)
        {
            return;
        }

        Directory.CreateDirectory(targetDir);

        var existingEntries = overwriteExisting
            ? new List<JsonElement>()
            : ReadHistoryEntriesFromFile(Path.Combine(targetDir, "history.json"))
                .Concat(ReadHistoryEntriesFromFile(Path.Combine(targetDir, "history.jsonl")))
                .ToList();

        var merged = MergeHistoryById(existingEntries, backupEntries);
        WriteHistoryJson(Path.Combine(targetDir, "history.json"), merged);
        var jsonlPath = Path.Combine(targetDir, "history.jsonl");
        if (File.Exists(jsonlPath))
        {
            File.Delete(jsonlPath);
        }
    }

    private static List<JsonElement> ReadHistoryEntriesFromFile(string path)
    {
        if (!File.Exists(path))
        {
            return new List<JsonElement>();
        }

        try
        {
            using var stream = OpenReadShared(path);
            if (path.EndsWith(".jsonl", StringComparison.OrdinalIgnoreCase))
            {
                using var reader = new StreamReader(stream);
                var entries = new List<JsonElement>();
                while (!reader.EndOfStream)
                {
                    var line = reader.ReadLine();
                    if (string.IsNullOrWhiteSpace(line))
                    {
                        continue;
                    }

                    using var doc = JsonDocument.Parse(line);
                    entries.Add(doc.RootElement.Clone());
                }

                return entries;
            }

            using var docArray = JsonDocument.Parse(stream);
            if (docArray.RootElement.ValueKind != JsonValueKind.Array)
            {
                return new List<JsonElement>();
            }

            return docArray.RootElement.EnumerateArray().Select(e => e.Clone()).ToList();
        }
        catch
        {
            return new List<JsonElement>();
        }
    }

    private static void WriteHistoryJson(string targetPath, IReadOnlyList<JsonElement> entries)
    {
        var tempPath = Path.Combine(Path.GetDirectoryName(targetPath) ?? Path.GetTempPath(), $"{Path.GetFileName(targetPath)}.tmp");
        using (var output = File.Create(tempPath))
        using (var writer = new Utf8JsonWriter(output, new JsonWriterOptions { Indented = true }))
        {
            writer.WriteStartArray();
            foreach (var entry in entries)
            {
                entry.WriteTo(writer);
            }
            writer.WriteEndArray();
        }
        ReplaceFileWithRetry(tempPath, targetPath);
    }

    private static void WriteHistoryJsonl(string targetPath, IReadOnlyList<JsonElement> entries)
    {
        var tempPath = Path.Combine(Path.GetDirectoryName(targetPath) ?? Path.GetTempPath(), $"{Path.GetFileName(targetPath)}.tmp");
        using (var output = File.Create(tempPath))
        using (var writer = new StreamWriter(output))
        {
            foreach (var entry in entries)
            {
                writer.WriteLine(entry.GetRawText());
            }
        }
        ReplaceFileWithRetry(tempPath, targetPath);
    }

    private static List<JsonElement> ReadHistoryJson(Stream stream)
    {
        using var doc = JsonDocument.Parse(stream);
        if (doc.RootElement.ValueKind != JsonValueKind.Array)
        {
            return new List<JsonElement>();
        }
        return doc.RootElement.EnumerateArray().Select(e => e.Clone()).ToList();
    }

    private static List<string> ReadHistoryJsonl(Stream stream)
    {
        using var reader = new StreamReader(stream);
        var lines = new List<string>();
        while (!reader.EndOfStream)
        {
            var line = reader.ReadLine();
            if (string.IsNullOrWhiteSpace(line)) continue;
            lines.Add(line);
        }
        return lines;
    }

    private static FileStream OpenReadShared(string path)
    {
        return new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
    }

    private static void ReplaceFileWithRetry(string sourcePath, string targetPath)
    {
        const int maxAttempts = 5;
        var delayMs = 150;
        for (int attempt = 1; attempt <= maxAttempts; attempt++)
        {
            try
            {
                if (File.Exists(targetPath))
                {
                    File.Replace(sourcePath, targetPath, null);
                }
                else
                {
                    File.Move(sourcePath, targetPath, overwrite: true);
                }
                return;
            }
            catch (IOException) when (attempt < maxAttempts)
            {
                Thread.Sleep(delayMs);
                delayMs *= 2;
            }
        }
        if (File.Exists(targetPath))
        {
            File.Replace(sourcePath, targetPath, null);
        }
        else
        {
            File.Move(sourcePath, targetPath, overwrite: true);
        }
    }

    private static List<JsonElement> MergeHistoryById(List<JsonElement> existingEntries, List<JsonElement> backupEntries)
    {
        var map = new Dictionary<string, JsonElement>(StringComparer.OrdinalIgnoreCase);
        foreach (var entry in existingEntries)
        {
            var id = GetHistoryId(entry);
            if (!string.IsNullOrWhiteSpace(id))
            {
                map[id] = entry;
            }
        }
        foreach (var entry in backupEntries)
        {
            var id = GetHistoryId(entry);
            if (!string.IsNullOrWhiteSpace(id) && !map.ContainsKey(id))
            {
                map[id] = entry;
            }
        }
        return map.Values.ToList();
    }

    private static List<string> MergeHistoryJsonlById(List<string> existing, List<string> backup)
    {
        var map = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var line in existing)
        {
            var id = GetHistoryId(line);
            if (!string.IsNullOrWhiteSpace(id) && !map.ContainsKey(id))
            {
                map[id] = line;
            }
        }
        foreach (var line in backup)
        {
            var id = GetHistoryId(line);
            if (!string.IsNullOrWhiteSpace(id) && !map.ContainsKey(id))
            {
                map[id] = line;
            }
        }
        return map.Values.ToList();
    }

    private static string? GetHistoryId(JsonElement entry)
    {
        if (entry.ValueKind != JsonValueKind.Object) return null;
        if (entry.TryGetProperty("Id", out var idProp) && idProp.ValueKind == JsonValueKind.String)
        {
            return idProp.GetString();
        }
        if (entry.TryGetProperty("id", out var idLower) && idLower.ValueKind == JsonValueKind.String)
        {
            return idLower.GetString();
        }
        return null;
    }

    private static string? GetHistoryId(string jsonLine)
    {
        try
        {
            using var doc = JsonDocument.Parse(jsonLine);
            return GetHistoryId(doc.RootElement);
        }
        catch
        {
            return null;
        }
    }

    private static string EnsureZipPath(string path)
    {
        return path.EndsWith(".zip", StringComparison.OrdinalIgnoreCase) ? path : $"{path}.zip";
    }

    private static void AddIfExists(List<string> roots, string? dir)
    {
        if (!string.IsNullOrWhiteSpace(dir) && Directory.Exists(dir))
        {
            roots.Add(Path.GetFullPath(dir));
        }
    }

    private static string GetSafeTempZipPath(string targetPath, List<string> sourceRoots)
    {
        var targetFullPath = Path.GetFullPath(targetPath);
        foreach (var root in sourceRoots)
        {
            if (targetFullPath.StartsWith(root, StringComparison.OrdinalIgnoreCase))
            {
                return Path.Combine(Path.GetTempPath(), $"prompttool_backup_{DateTime.Now:yyyyMMdd_HHmmss}.zip");
            }
        }
        return targetFullPath;
    }

    private static int CountFiles(
        string directory,
        IReadOnlyList<string>? excludedDirs = null,
        IReadOnlyList<string>? excludedDirNames = null)
    {
        if (!Directory.Exists(directory))
        {
            return 0;
        }
        if ((excludedDirs == null || excludedDirs.Count == 0) &&
            (excludedDirNames == null || excludedDirNames.Count == 0))
        {
            return Directory.EnumerateFiles(directory, "*", SearchOption.AllDirectories)
                .Count(file => !IsExcludedFileName(file));
        }

        var excluded = NormalizeExcludeDirs(excludedDirs);
        return Directory.EnumerateFiles(directory, "*", SearchOption.AllDirectories)
            .Count(file => !IsExcluded(file, excluded, excludedDirNames) && !IsExcludedFileName(file));
    }

    private static void ExtractZipFolder(ZipArchive archive, string prefix, string targetDir, bool overwriteExisting, CancellationToken ct)
    {
        if (string.IsNullOrWhiteSpace(targetDir))
        {
            return;
        }

        var basePath = Path.GetFullPath(targetDir);
        Directory.CreateDirectory(basePath);

        foreach (var entry in archive.Entries)
        {
            ct.ThrowIfCancellationRequested();
            if (!entry.FullName.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            var relative = entry.FullName.Substring(prefix.Length);
            if (string.IsNullOrWhiteSpace(relative))
            {
                continue;
            }

            var destinationPath = Path.GetFullPath(Path.Combine(basePath, relative));
            if (!destinationPath.StartsWith(basePath, StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            var directory = Path.GetDirectoryName(destinationPath);
            if (!string.IsNullOrWhiteSpace(directory))
            {
                Directory.CreateDirectory(directory);
            }

            if (entry.FullName.EndsWith("/", StringComparison.Ordinal))
            {
                continue;
            }

            if (File.Exists(destinationPath) && !overwriteExisting)
            {
                continue;
            }

            entry.ExtractToFile(destinationPath, overwrite: true);
        }
    }

    private static bool TryMapEntry(string entryName, string prefix, string targetDir, out string targetPath)
    {
        targetPath = string.Empty;
        if (string.IsNullOrWhiteSpace(targetDir))
        {
            return false;
        }
        if (!entryName.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        var relative = entryName.Substring(prefix.Length);
        if (string.IsNullOrWhiteSpace(relative))
        {
            return false;
        }

        var basePath = Path.GetFullPath(targetDir);
        targetPath = Path.GetFullPath(Path.Combine(basePath, relative));
        return targetPath.StartsWith(basePath, StringComparison.OrdinalIgnoreCase);
    }

    private static void UpdateSummary(RestoreSummary summary, string targetPath, bool overwriteExisting, bool isConfig)
    {
        var exists = File.Exists(targetPath);
        if (isConfig)
        {
            if (!exists)
            {
                summary.ConfigAdd++;
            }
            else if (overwriteExisting)
            {
                summary.ConfigOverwrite++;
            }
            else
            {
                summary.ConfigSkip++;
            }
        }
        else
        {
            if (!exists)
            {
                summary.HistoryAdd++;
            }
            else if (overwriteExisting)
            {
                summary.HistoryOverwrite++;
            }
            else
            {
                summary.HistorySkip++;
            }
        }
    }

    public sealed class RestoreSummary
    {
        public string ZipPath { get; set; } = string.Empty;
        public int ArchiveFileCount { get; set; }
        public int ConfigArchiveFiles { get; set; }
        public int HistoryArchiveFiles { get; set; }
        public int ConfigAdd { get; set; }
        public int ConfigOverwrite { get; set; }
        public int ConfigSkip { get; set; }
        public int HistoryAdd { get; set; }
        public int HistoryOverwrite { get; set; }
        public int HistorySkip { get; set; }
        public bool HasLegacyRootHistory { get; set; }
        public bool HasRootHistoryMetadata { get; set; }
        public bool HasRootHistoryImages { get; set; }
        public HashSet<string> HistoryWorkflowFolders { get; } = new(StringComparer.OrdinalIgnoreCase);
        public string ConfigTargetDir { get; set; } = string.Empty;
        public string TemplateTargetDir { get; set; } = string.Empty;
        public string WildcardTargetDir { get; set; } = string.Empty;
        public string SystemPromptsTargetDir { get; set; } = string.Empty;
        public string HistoryBaseTargetDir { get; set; } = string.Empty;
        public string ActiveWorkflow { get; set; } = "sfw";
        public string HistoryWorkflowTargetDir { get; set; } = string.Empty;
        public int TotalAdd => ConfigAdd + HistoryAdd;
        public int TotalOverwrite => ConfigOverwrite + HistoryOverwrite;
        public int TotalSkip => ConfigSkip + HistorySkip;
    }

    public sealed record BackupVerifyResult(bool IsValid, string Message);
    public sealed record BackupSections(bool HasConfig, bool HasHistory);

    public async Task CreateAutoBackupAsync(bool includeConfig, bool includeHistory, CancellationToken ct)
    {
        if (!includeConfig && !includeHistory)
        {
            return;
        }

        try
        {
            Directory.CreateDirectory(AutoBackupDir);
            var timestamp = DateTime.Now.ToString("yyyyMMdd_HHmmss");
            if (includeConfig)
            {
                var configZip = Path.Combine(AutoBackupDir, $"auto_config_{timestamp}.zip");
                await BackupConfigAsync(configZip, null, ct);
            }
            if (includeHistory)
            {
                var historyZip = Path.Combine(AutoBackupDir, $"auto_history_{timestamp}.zip");
                await BackupHistoryAsync(historyZip, null, ct);
            }
            RefreshAutoBackups();
        }
        catch (Exception ex)
        {
            _notifications?.ShowError($"Failed to create auto backup: {ex.Message}", "Restore");
        }
    }

    public void DeleteAutoBackups()
    {
        try
        {
            if (Directory.Exists(AutoBackupDir))
            {
                foreach (var file in Directory.EnumerateFiles(AutoBackupDir, "*.zip"))
                {
                    File.Delete(file);
                }
            }
        }
        catch (Exception ex)
        {
            _notifications?.ShowError($"Failed to delete auto backups: {ex.Message}", "Backup");
        }
        finally
        {
            RefreshAutoBackups();
        }
    }

    public void RefreshAutoBackups()
    {
        HasAutoBackups = Directory.Exists(AutoBackupDir)
            && Directory.EnumerateFiles(AutoBackupDir, "*.zip").Any();
    }

    private static void TrackHistoryLayout(RestoreSummary summary, string entryName)
    {
        var relative = entryName["history/".Length..].Replace('\\', '/');
        if (string.IsNullOrWhiteSpace(relative))
        {
            return;
        }

        var segments = relative.Split('/', StringSplitOptions.RemoveEmptyEntries);
        if (segments.Length == 0)
        {
            return;
        }

        var first = segments[0];
        if (first.Equals("sfw", StringComparison.OrdinalIgnoreCase) ||
            first.Equals("nsfw", StringComparison.OrdinalIgnoreCase))
        {
            summary.HistoryWorkflowFolders.Add(first.ToLowerInvariant());
            return;
        }

        summary.HasLegacyRootHistory = true;
        if (first.Equals("history.json", StringComparison.OrdinalIgnoreCase) ||
            first.Equals("history.jsonl", StringComparison.OrdinalIgnoreCase))
        {
            summary.HasRootHistoryMetadata = true;
            return;
        }

        if (first.Equals("images", StringComparison.OrdinalIgnoreCase))
        {
            summary.HasRootHistoryImages = true;
        }
    }

    private static void AddDirectoryToZip(
        ZipArchive archive,
        string? directory,
        string prefix,
        IProgress<BackupProgress>? progress,
        ref int current,
        int total,
        CancellationToken ct,
        string stage,
        IReadOnlyList<string>? excludedDirs = null,
        IReadOnlyList<string>? excludedDirNames = null)
    {
        if (string.IsNullOrWhiteSpace(directory) || !Directory.Exists(directory))
        {
            return;
        }

        var basePath = Path.GetFullPath(directory);
        var excluded = NormalizeExcludeDirs(excludedDirs);
        foreach (var file in Directory.EnumerateFiles(basePath, "*", SearchOption.AllDirectories))
        {
            ct.ThrowIfCancellationRequested();
            if (IsExcluded(file, excluded, excludedDirNames) || IsExcludedFileName(file))
            {
                continue;
            }
            var relative = Path.GetRelativePath(basePath, file);
            var entryName = Path.Combine(prefix, relative).Replace('\\', '/');
            archive.CreateEntryFromFile(file, entryName, CompressionLevel.Optimal);
            current++;
            progress?.Report(new BackupProgress(stage, current, total, relative));
        }
    }

    private static IReadOnlyList<string> NormalizeExcludeDirs(IReadOnlyList<string>? excludedDirs)
    {
        if (excludedDirs == null || excludedDirs.Count == 0)
        {
            return Array.Empty<string>();
        }

        var list = new List<string>(excludedDirs.Count);
        foreach (var dir in excludedDirs)
        {
            if (string.IsNullOrWhiteSpace(dir))
            {
                continue;
            }
            list.Add(NormalizeDir(dir));
        }
        return list;
    }

    private static string NormalizeDir(string dir)
    {
        var full = Path.GetFullPath(dir);
        return full.EndsWith(Path.DirectorySeparatorChar)
            ? full
            : full + Path.DirectorySeparatorChar;
    }

    private static bool IsExcluded(
        string filePath,
        IReadOnlyList<string> excludedDirs,
        IReadOnlyList<string>? excludedDirNames)
    {
        if (excludedDirs.Count == 0 && (excludedDirNames == null || excludedDirNames.Count == 0))
        {
            return false;
        }

        var full = Path.GetFullPath(filePath);
        foreach (var exclude in excludedDirs)
        {
            if (full.StartsWith(exclude, StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }
        }

        if (excludedDirNames != null && excludedDirNames.Count > 0)
        {
            if (ContainsPathSegment(full, excludedDirNames))
            {
                return true;
            }
        }
        return false;
    }

    private static bool IsExcludedFileName(string filePath)
    {
        var name = Path.GetFileName(filePath);
        if (string.IsNullOrWhiteSpace(name)) return false;
        return name.Equals(".DS_Store", StringComparison.OrdinalIgnoreCase)
               || name.Equals("Thumbs.db", StringComparison.OrdinalIgnoreCase)
               || name.Equals("desktop.ini", StringComparison.OrdinalIgnoreCase)
               || name.Equals(".Trash", StringComparison.OrdinalIgnoreCase)
               || name.Equals(".localized", StringComparison.OrdinalIgnoreCase);
    }

    private static bool ContainsPathSegment(string fullPath, IReadOnlyList<string> names)
    {
        var separators = new[] { Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar };
        foreach (var part in fullPath.Split(separators, StringSplitOptions.RemoveEmptyEntries))
        {
            foreach (var name in names)
            {
                if (string.Equals(part, name, StringComparison.OrdinalIgnoreCase))
                {
                    return true;
                }
            }
        }
        return false;
    }

    private static bool IsSameOrUnder(string path, string root)
    {
        var fullPath = NormalizeDir(path);
        var fullRoot = NormalizeDir(root);
        return fullPath.StartsWith(fullRoot, StringComparison.OrdinalIgnoreCase);
    }

    public sealed class BackupProgress
    {
        public BackupProgress(string stage, int current, int total, string? item)
        {
            Stage = stage;
            Current = current;
            Total = total;
            Item = item;
        }

        public string Stage { get; }
        public int Current { get; }
        public int Total { get; }
        public string? Item { get; }
    }

    public bool ComputeHasPendingChanges()
    {
        var settingsToCheck = BuildSettingsSnapshot();
        var defaultsChanged = !ModelDefaultsEqual(_workingModelDefaults, _settingsService.InvokeAIModelDefaults)
                              || !ModelDefaultsEqual(_workingLoraDefaults, _settingsService.InvokeAILoraDefaults);
        return HasChanges(settingsToCheck, _originalSettings) || defaultsChanged;
    }

    public string CancelLabel => HasPendingChanges ? "Cancel" : "Close";

    partial void OnHasPendingChangesChanged(bool value)
    {
        OnPropertyChanged(nameof(CancelLabel));
    }

    protected override void OnPropertyChanged(PropertyChangedEventArgs e)
    {
        base.OnPropertyChanged(e);
        if (e.PropertyName == nameof(HasPendingChanges) || e.PropertyName == nameof(CancelLabel))
        {
            return;
        }
        UpdatePendingChanges();
    }

    private void UpdatePendingChanges()
    {
        HasPendingChanges = ComputeHasPendingChanges();
    }

    [RelayCommand]
    private void Cancel()
    {
        DialogResult = false;
    }

    public List<ModelDefaults> GetInvokeAIModelDefaultsSnapshot() => CloneModelDefaults(_workingModelDefaults);

    public void ApplyInvokeAIModelDefaultsSnapshot(IEnumerable<ModelDefaults> defaults)
    {
        _workingModelDefaults = CloneModelDefaults(defaults);
    }

    public List<ModelDefaults> GetInvokeAILoraDefaultsSnapshot() => CloneModelDefaults(_workingLoraDefaults);

    public void ApplyInvokeAILoraDefaultsSnapshot(IEnumerable<ModelDefaults> defaults)
    {
        _workingLoraDefaults = CloneModelDefaults(defaults);
    }

    [RelayCommand]
    private void OpenScoringCache()
    {
        var dir = ScoringCacheDir;
        if (string.IsNullOrWhiteSpace(dir)) return;
        try
        {
            if (!Directory.Exists(dir))
            {
                _notifications?.ShowError($"Scoring cache folder does not exist yet: {dir}", "Scoring");
                return;
            }

            if (OperatingSystem.IsMacOS())
            {
                var startInfo = new System.Diagnostics.ProcessStartInfo("open");
                startInfo.ArgumentList.Add(dir);
                System.Diagnostics.Process.Start(startInfo);
            }
            else if (OperatingSystem.IsWindows())
            {
                var startInfo = new System.Diagnostics.ProcessStartInfo("explorer.exe");
                startInfo.ArgumentList.Add(dir);
                System.Diagnostics.Process.Start(startInfo);
            }
            else
            {
                var startInfo = new System.Diagnostics.ProcessStartInfo("xdg-open");
                startInfo.ArgumentList.Add(dir);
                System.Diagnostics.Process.Start(startInfo);
            }
        }
        catch (Exception ex)
        {
            _notifications?.ShowError($"Failed to open scoring cache: {ex.Message}", "Error");
        }
    }

    [RelayCommand]
    private void ClearScoringCache()
    {
        var dir = ScoringCacheDir;
        if (string.IsNullOrWhiteSpace(dir)) return;

        try
        {
            if (Directory.Exists(dir))
            {
                Directory.Delete(dir, true);
            }
            _scoringCacheService.EnsureDirectories();
            _notifications?.ShowInfo("Scoring cache cleared.", "Scoring");
        }
        catch (Exception ex)
        {
            _notifications?.ShowError($"Failed to clear scoring cache: {ex.Message}", "Error");
        }
    }

    [RelayCommand]
    private void ClearImageCache()
    {
        _imageCacheService.Clear();
        _imageCacheService.ClearDiskCache();
        UpdateImageCacheLabels();
        _notifications?.ShowInfo("Image cache cleared.", "Settings");
    }

    [RelayCommand]
    private async Task ClearInvokeCache()
    {
        if (_invokeAiClient == null)
        {
            _notifications?.ShowWarning("InvokeAI cache clearing is not available in this context.", "Settings");
            return;
        }
        try
        {
            var ok = await _invokeAiClient.EmptyModelCacheAsync();
            if (ok)
            {
                _notifications?.ShowInfo("InvokeAI model cache cleared.", "Settings");
            }
            else
            {
                _notifications?.ShowWarning("InvokeAI did not confirm cache clear.", "Settings");
            }
        }
        catch (Exception ex)
        {
            _notifications?.ShowError($"Failed to clear InvokeAI cache: {ex.Message}", "Settings");
        }
    }

    private void UpdateImageCacheLabels()
    {
        var ramSize = FormatBytes(_imageCacheService.CurrentBytes);
        var diskSize = FormatBytes(_imageCacheService.GetDiskCacheBytes());
        ImageCacheSizeLabel = $"RAM: {ramSize} · Disk: {diskSize}";
        ClearImageCacheLabel = $"Clear Image Cache ({diskSize})";
    }

    private static string FormatBytes(long bytes)
    {
        const double scale = 1024.0;
        if (bytes < scale) return $"{bytes} B";
        var kb = bytes / scale;
        if (kb < scale) return $"{kb:0.##} KB";
        var mb = kb / scale;
        if (mb < scale) return $"{mb:0.##} MB";
        var gb = mb / scale;
        return $"{gb:0.##} GB";
    }

    [RelayCommand]
    private async Task LoadOllamaModelsAsync()
    {
        try
        {
            if (Uri.TryCreate(OllamaBaseUrl, UriKind.Absolute, out var uri))
            {
                _ollamaClient.UpdateBaseAddress(uri);
            }
            var models = await _ollamaClient.GetModelNamesAsync();
            OllamaModels = new ObservableCollection<string>(models);
        }
                    catch (Exception ex)
                    {
                        if (_settingsService.Settings.Verbose) Console.WriteLine($"Failed to load Ollama models: {ex.Message}");
                    }    }

    partial void OnDefaultBaseModelTypeChanged(string value)
    {
        // Preserve current edits before switching
        StoreDefaultsForBase(_currentBaseModelType);
        _currentBaseModelType = string.IsNullOrWhiteSpace(value) ? "sdxl" : value;
        LoadDefaultsForBase(_currentBaseModelType);
    }

    private void LoadDefaultsForBase(string baseType)
    {
        var key = string.IsNullOrWhiteSpace(baseType) ? "sdxl" : baseType;
        if (!_workingDefaults.TryGetValue(key, out var defaults))
        {
            defaults = new GenerationDefaultsSettings();
            _workingDefaults[key] = defaults;
        }
        if (key.Equals("sd-1.5", StringComparison.OrdinalIgnoreCase) && defaults.Width == 1024 && defaults.Height == 1024)
        {
            defaults.Width = 512;
            defaults.Height = 512;
        }

        DefaultScheduler = defaults.Scheduler;
        DefaultSteps = defaults.Steps;
        DefaultCfgScale = defaults.CfgScale;
        DefaultCfgRescaleMultiplier = defaults.CfgRescaleMultiplier;
        DefaultWidth = defaults.Width;
        DefaultHeight = defaults.Height;
        DefaultSaveToGallery = defaults.SaveToGallery;
    }

    private void StoreDefaultsForBase(string baseType)
    {
        var key = string.IsNullOrWhiteSpace(baseType) ? "sdxl" : baseType;
        _workingDefaults[key] = new GenerationDefaultsSettings
        {
            Scheduler = DefaultScheduler ?? "dpmpp_2m_k",
            Steps = DefaultSteps <= 0 ? 30 : DefaultSteps,
            CfgScale = DefaultCfgScale <= 0 ? 7.5 : DefaultCfgScale,
            CfgRescaleMultiplier = DefaultCfgRescaleMultiplier < 0 ? 0 : DefaultCfgRescaleMultiplier,
            Width = DefaultWidth <= 0 ? 1024 : DefaultWidth,
            Height = DefaultHeight <= 0 ? 1024 : DefaultHeight,
            SaveToGallery = DefaultSaveToGallery
        };
    }

    public Dictionary<string, GenerationDefaultsSettings> GetDefaultsSnapshot() => DeepCloneDefaults(_workingDefaults);

    public void ApplyDefaultsSnapshot(Dictionary<string, GenerationDefaultsSettings> map, string currentBase)
    {
        _workingDefaults = DeepCloneDefaults(map);
        DefaultBaseModelType = string.IsNullOrWhiteSpace(currentBase) ? "sdxl" : currentBase;
        _currentBaseModelType = DefaultBaseModelType;
        LoadDefaultsForBase(DefaultBaseModelType);
    }

    private static void ApplyThemeVariant(string? theme)
    {
        var variant = (theme ?? "").ToLowerInvariant() switch
        {
            "light" => ThemeVariant.Light,
            "system" => ThemeVariant.Default,
            _ => ThemeVariant.Dark
        };
        if (Application.Current != null)
        {
            Application.Current.RequestedThemeVariant = variant;
            App.ApplyThemeResources(theme ?? "dark");
        }
    }

    partial void OnThemeChanged(string value)
    {
        ApplyThemeVariant(value);
    }

    private static AppSettings Clone(AppSettings settings)
    {
        return new AppSettings
        {
            OllamaBaseUrl = settings.OllamaBaseUrl,
            InvokeAIBaseUrl = settings.InvokeAIBaseUrl,
            TemplateBaseDir = settings.TemplateBaseDir,
            WildcardDir = settings.WildcardDir,
            HistoryDir = settings.HistoryDir,
            SystemPromptBaseDir = settings.SystemPromptBaseDir,
            Workflow = settings.Workflow,
            Theme = settings.Theme,
            FontSize = settings.FontSize,
            DefaultOllamaModel = settings.DefaultOllamaModel,
            DefaultNegativePrompt = settings.DefaultNegativePrompt,
            DefaultNegativePromptKey = settings.DefaultNegativePromptKey,
            NegativePromptPresets = new Dictionary<string, string>(settings.NegativePromptPresets, StringComparer.OrdinalIgnoreCase),
            InvokeAITimeoutSeconds = settings.InvokeAITimeoutSeconds,
            CacheDir = settings.CacheDir,
            DefaultScheduler = settings.DefaultScheduler,
            DefaultSteps = settings.DefaultSteps,
            DefaultCfgScale = settings.DefaultCfgScale,
            DefaultCfgRescaleMultiplier = settings.DefaultCfgRescaleMultiplier,
            DefaultWidth = settings.DefaultWidth,
            DefaultHeight = settings.DefaultHeight,
            DefaultSaveToGallery = settings.DefaultSaveToGallery,
            DefaultBaseModelType = settings.DefaultBaseModelType,
            AutoClearInvokeCacheBetweenModels = settings.AutoClearInvokeCacheBetweenModels,
            ServerSafetyModeEnabled = settings.ServerSafetyModeEnabled,
            Verbose = settings.Verbose,
            AestheticScoringBackend = settings.AestheticScoringBackend,
            AestheticScoringRemoteUrl = settings.AestheticScoringRemoteUrl,
            AestheticScoringRemoteBatchSize = settings.AestheticScoringRemoteBatchSize,
            AestheticScoringModelPath = settings.AestheticScoringModelPath,
            HuggingFaceApiKey = settings.HuggingFaceApiKey,
            HuggingFaceApiKeyEncrypted = settings.HuggingFaceApiKeyEncrypted,
            GenerationDefaults = DeepCloneDefaults(settings.GenerationDefaults)
        };
    }

    private static bool HasChanges(AppSettings current, AppSettings original)
    {
        return !string.Equals(current.OllamaBaseUrl, original.OllamaBaseUrl, StringComparison.OrdinalIgnoreCase)
               || !string.Equals(current.InvokeAIBaseUrl, original.InvokeAIBaseUrl, StringComparison.OrdinalIgnoreCase)
               || !string.Equals(current.TemplateBaseDir, original.TemplateBaseDir, StringComparison.OrdinalIgnoreCase)
               || !string.Equals(current.WildcardDir, original.WildcardDir, StringComparison.OrdinalIgnoreCase)
               || !string.Equals(current.HistoryDir, original.HistoryDir, StringComparison.OrdinalIgnoreCase)
               || !string.Equals(current.SystemPromptBaseDir, original.SystemPromptBaseDir, StringComparison.OrdinalIgnoreCase)
               || !string.Equals(current.Workflow, original.Workflow, StringComparison.OrdinalIgnoreCase)
               || !string.Equals(current.DefaultOllamaModel, original.DefaultOllamaModel, StringComparison.OrdinalIgnoreCase)
               || !string.Equals(current.DefaultNegativePrompt, original.DefaultNegativePrompt, StringComparison.Ordinal)
               || !string.Equals(current.DefaultNegativePromptKey, original.DefaultNegativePromptKey, StringComparison.OrdinalIgnoreCase)
               || current.InvokeAITimeoutSeconds != original.InvokeAITimeoutSeconds
               || !string.Equals(current.Theme, original.Theme, StringComparison.OrdinalIgnoreCase)
               || current.FontSize != original.FontSize
               || !NegativePresetsEqual(current.NegativePromptPresets, original.NegativePromptPresets)
               || !string.Equals(current.DefaultScheduler, original.DefaultScheduler, StringComparison.OrdinalIgnoreCase)
               || current.DefaultSteps != original.DefaultSteps
               || Math.Abs(current.DefaultCfgScale - original.DefaultCfgScale) > 0.0001
               || Math.Abs(current.DefaultCfgRescaleMultiplier - original.DefaultCfgRescaleMultiplier) > 0.0001
               || current.DefaultWidth != original.DefaultWidth
               || current.DefaultHeight != original.DefaultHeight
               || current.DefaultSaveToGallery != original.DefaultSaveToGallery
               || !string.Equals(current.DefaultBaseModelType, original.DefaultBaseModelType, StringComparison.OrdinalIgnoreCase)
               || current.AutoClearInvokeCacheBetweenModels != original.AutoClearInvokeCacheBetweenModels
               || current.ServerSafetyModeEnabled != original.ServerSafetyModeEnabled
               || !string.Equals(current.AestheticScoringBackend, original.AestheticScoringBackend, StringComparison.OrdinalIgnoreCase)
               || !string.Equals(current.AestheticScoringRemoteUrl, original.AestheticScoringRemoteUrl, StringComparison.OrdinalIgnoreCase)
               || current.AestheticScoringRemoteBatchSize != original.AestheticScoringRemoteBatchSize
               || !string.Equals(current.AestheticScoringModelPath, original.AestheticScoringModelPath, StringComparison.OrdinalIgnoreCase)
               || !string.Equals(current.HuggingFaceApiKey, original.HuggingFaceApiKey, StringComparison.OrdinalIgnoreCase)
               || current.Verbose != original.Verbose
               || !DefaultsEqual(current.GenerationDefaults, original.GenerationDefaults);
    }

    private static Dictionary<string, GenerationDefaultsSettings> DeepCloneDefaults(Dictionary<string, GenerationDefaultsSettings>? source)
    {
        var result = new Dictionary<string, GenerationDefaultsSettings>(StringComparer.OrdinalIgnoreCase);
        if (source == null) return result;
        foreach (var kvp in source)
        {
            if (kvp.Value == null) continue;
            result[kvp.Key] = new GenerationDefaultsSettings
            {
                Scheduler = kvp.Value.Scheduler,
                Steps = kvp.Value.Steps,
                CfgScale = kvp.Value.CfgScale,
                CfgRescaleMultiplier = kvp.Value.CfgRescaleMultiplier,
                Width = kvp.Value.Width,
                Height = kvp.Value.Height,
                SaveToGallery = kvp.Value.SaveToGallery
            };
        }
        return result;
    }

    private AppSettings BuildSettingsSnapshot()
    {
        StoreDefaultsForBase(DefaultBaseModelType);
        var settingsToSave = Clone(_settingsService.Settings);
        settingsToSave.OllamaBaseUrl = OllamaBaseUrl;
        settingsToSave.InvokeAIBaseUrl = InvokeAIBaseUrl;
        settingsToSave.TemplateBaseDir = TemplateBaseDir;
        settingsToSave.WildcardDir = WildcardDir;
        settingsToSave.HistoryDir = HistoryDir;
        settingsToSave.SystemPromptBaseDir = SystemPromptBaseDir;
        settingsToSave.Workflow = string.IsNullOrWhiteSpace(Workflow) ? "sfw" : Workflow;
        settingsToSave.DefaultOllamaModel = DefaultOllamaModel;
        CommitNegativePresetEdits();
        settingsToSave.DefaultNegativePrompt = SelectedNegativePreset?.Value ?? DefaultNegativePrompt ?? string.Empty;
        settingsToSave.DefaultNegativePromptKey = SelectedNegativePreset?.Key ?? (string.IsNullOrWhiteSpace(DefaultNegativePromptKey) ? "standard" : DefaultNegativePromptKey);
        settingsToSave.InvokeAITimeoutSeconds = InvokeAITimeoutSeconds <= 0 ? 300 : InvokeAITimeoutSeconds;
        settingsToSave.Theme = string.IsNullOrWhiteSpace(Theme) ? "light" : Theme;
        settingsToSave.FontSize = FontSize <= 0 ? 11 : FontSize;
        settingsToSave.DefaultBaseModelType = string.IsNullOrWhiteSpace(DefaultBaseModelType) ? "sdxl" : DefaultBaseModelType;
        settingsToSave.AutoClearInvokeCacheBetweenModels = AutoClearInvokeCacheBetweenModels;
        settingsToSave.ServerSafetyModeEnabled = ServerSafetyModeEnabled;
        settingsToSave.Verbose = Verbose;
        settingsToSave.AestheticScoringBackend = string.IsNullOrWhiteSpace(AestheticScoringBackend) ? "local" : AestheticScoringBackend;
        settingsToSave.AestheticScoringRemoteUrl = AestheticScoringRemoteUrl ?? string.Empty;
        settingsToSave.AestheticScoringRemoteBatchSize = AestheticScoringRemoteBatchSize <= 0 ? 8 : AestheticScoringRemoteBatchSize;
        settingsToSave.AestheticScoringModelPath = SelectedAestheticModel?.LocalPath ?? string.Empty;
        settingsToSave.HuggingFaceApiKey = HuggingFaceApiKey ?? string.Empty;
        settingsToSave.NegativePromptPresets = NegativePresets.ToDictionary(p => p.Key, p => p.Value, StringComparer.OrdinalIgnoreCase);

        settingsToSave.GenerationDefaults = DeepCloneDefaults(_workingDefaults);

        var activeDefaults = _workingDefaults.GetValueOrDefault(settingsToSave.DefaultBaseModelType) ?? new GenerationDefaultsSettings();
        settingsToSave.DefaultScheduler = activeDefaults.Scheduler;
        settingsToSave.DefaultSteps = activeDefaults.Steps;
        settingsToSave.DefaultCfgScale = activeDefaults.CfgScale;
        settingsToSave.DefaultCfgRescaleMultiplier = activeDefaults.CfgRescaleMultiplier;
        settingsToSave.DefaultWidth = activeDefaults.Width;
        settingsToSave.DefaultHeight = activeDefaults.Height;
        settingsToSave.DefaultSaveToGallery = activeDefaults.SaveToGallery;

        return settingsToSave;
    }

    private static List<ModelDefaults> CloneModelDefaults(IEnumerable<ModelDefaults> source)
    {
        var list = new List<ModelDefaults>();
        foreach (var item in source)
        {
            list.Add(new ModelDefaults
            {
                ModelName = item.ModelName,
                Sampler = item.Sampler,
                Steps = item.Steps,
                CfgScale = item.CfgScale,
                CfgRescaleMultiplier = item.CfgRescaleMultiplier,
                Width = item.Width,
                Height = item.Height,
                PositivePromptPrefix = item.PositivePromptPrefix,
                NegativePromptPrefix = item.NegativePromptPrefix
            });
        }
        return list;
    }

    private static void ApplyDefaultsToService(List<ModelDefaults> target, IEnumerable<ModelDefaults> source)
    {
        target.Clear();
        target.AddRange(CloneModelDefaults(source));
    }

    private static bool ModelDefaultsEqual(IEnumerable<ModelDefaults> a, IEnumerable<ModelDefaults> b)
    {
        var mapA = a.ToDictionary(x => x.ModelName, StringComparer.OrdinalIgnoreCase);
        var mapB = b.ToDictionary(x => x.ModelName, StringComparer.OrdinalIgnoreCase);
        if (mapA.Count != mapB.Count) return false;
        foreach (var kvp in mapA)
        {
            if (!mapB.TryGetValue(kvp.Key, out var other)) return false;
            var current = kvp.Value;
            if (!string.Equals(current.Sampler, other.Sampler, StringComparison.OrdinalIgnoreCase)) return false;
            if (current.Steps != other.Steps) return false;
            if (Math.Abs(current.CfgScale - other.CfgScale) > 0.0001) return false;
            if (Math.Abs(current.CfgRescaleMultiplier - other.CfgRescaleMultiplier) > 0.0001) return false;
            if (current.Width != other.Width || current.Height != other.Height) return false;
            if (!string.Equals(current.PositivePromptPrefix, other.PositivePromptPrefix, StringComparison.Ordinal)) return false;
            if (!string.Equals(current.NegativePromptPrefix, other.NegativePromptPrefix, StringComparison.Ordinal)) return false;
        }
        return true;
    }

    private static bool DefaultsEqual(Dictionary<string, GenerationDefaultsSettings>? a, Dictionary<string, GenerationDefaultsSettings>? b)
    {
        a ??= new Dictionary<string, GenerationDefaultsSettings>(StringComparer.OrdinalIgnoreCase);
        b ??= new Dictionary<string, GenerationDefaultsSettings>(StringComparer.OrdinalIgnoreCase);
        if (a.Count != b.Count) return false;
        foreach (var kvp in a)
        {
            if (!b.TryGetValue(kvp.Key, out var other) || kvp.Value == null || other == null) return false;
            if (!string.Equals(kvp.Value.Scheduler, other.Scheduler, StringComparison.OrdinalIgnoreCase)) return false;
            if (kvp.Value.Steps != other.Steps) return false;
            if (Math.Abs(kvp.Value.CfgScale - other.CfgScale) > 0.0001) return false;
            if (Math.Abs(kvp.Value.CfgRescaleMultiplier - other.CfgRescaleMultiplier) > 0.0001) return false;
            if (kvp.Value.Width != other.Width || kvp.Value.Height != other.Height) return false;
            if (kvp.Value.SaveToGallery != other.SaveToGallery) return false;
        }
        return true;
    }

    private static bool NegativePresetsEqual(Dictionary<string, string>? a, Dictionary<string, string>? b)
    {
        a ??= new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        b ??= new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        if (a.Count != b.Count) return false;
        foreach (var kvp in a)
        {
            if (!b.TryGetValue(kvp.Key, out var val) || !string.Equals(kvp.Value, val, StringComparison.Ordinal)) return false;
        }
        return true;
    }

    partial void OnSelectedNegativePresetChanged(NegativePresetItem? value)
    {
        if (value != null)
        {
            EditingPresetText = value.Value;
            DefaultNegativePromptKey = value.Key;
            DefaultNegativePrompt = value.Value;
            EditingPresetName = value.Key;
        }
    }

    partial void OnAestheticScoringBackendChanged(string value)
    {
        OnPropertyChanged(nameof(IsRemoteBackend));
    }

    private async Task<bool> ValidateHuggingFaceKeyAsync(string? key)
    {
        if (string.IsNullOrWhiteSpace(key))
        {
            return true;
        }

        try
        {
            using var request = new HttpRequestMessage(HttpMethod.Get, "https://huggingface.co/api/whoami-v2");
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", key.Trim());
            using var response = await _httpClient.SendAsync(request);
            return response.IsSuccessStatusCode;
        }
        catch
        {
            return false;
        }
    }

    partial void OnSelectedAestheticModelChanged(AestheticModelOption? value)
    {
        OnPropertyChanged(nameof(ShowAestheticModelDropdown));
    }

    private void InitializeAestheticModelCatalog()
    {
        AestheticModelCatalog.Clear();

        var aestheticName = "Aesthetic Predictor v2.5 (fsw)";
        var aestheticUrl = "https://huggingface.co/fsw/aesthetic-predictor-v2-5_onnx/resolve/main/aesthetic_predictor_v2_5.onnx";
        var aestheticPath = Path.Combine(AestheticModelsDir, "fsw_aesthetic_predictor_v2_5.onnx");
        AestheticModelCatalog.Add(new AestheticModelOption(aestheticName, aestheticUrl, aestheticPath, true, true));
    }

    [RelayCommand]
    private async Task RefreshAestheticModelListsAsync()
    {
        foreach (var entry in AestheticModelCatalog)
        {
            entry.RefreshFromDisk();
            if (!entry.SizeBytes.HasValue)
            {
                await TryPopulateRemoteSizeAsync(entry);
            }
        }

        InstalledAestheticModels.Clear();
        foreach (var entry in AestheticModelCatalog.Where(e => e.IsDownloaded))
        {
            InstalledAestheticModels.Add(entry);
        }

        if (Directory.Exists(AestheticModelsDir))
        {
            foreach (var file in Directory.EnumerateFiles(AestheticModelsDir, "*.onnx"))
            {
                if (AestheticModelCatalog.Any(e => string.Equals(e.LocalPath, file, StringComparison.OrdinalIgnoreCase)))
                {
                    continue;
                }

                if (string.Equals(Path.GetFileName(file), "clip_vision.onnx", StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                var name = Path.GetFileNameWithoutExtension(file);
                var option = new AestheticModelOption(name, null, file, false, false);
                option.RefreshFromDisk();
                InstalledAestheticModels.Add(option);
            }
        }

        var savedPath = _settingsService.Settings.AestheticScoringModelPath;
        SelectedAestheticModel = InstalledAestheticModels.FirstOrDefault(m =>
            !string.IsNullOrWhiteSpace(savedPath) &&
            string.Equals(m.LocalPath, savedPath, StringComparison.OrdinalIgnoreCase))
            ?? InstalledAestheticModels.FirstOrDefault();

        OnPropertyChanged(nameof(ShowAestheticModelDropdown));
    }

    [RelayCommand]
    private async Task DownloadAestheticModelAsync(AestheticModelOption? model)
    {
        if (model == null || string.IsNullOrWhiteSpace(model.Url))
        {
            return;
        }
        if (model.IsDownloaded)
        {
            _notifications?.ShowInfo($"{model.Name} is already downloaded.", "Aesthetic Scoring");
            return;
        }

        try
        {
            _scoringCacheService.EnsureDirectories();
            IsAestheticDownloadActive = true;
            AestheticDownloadProgress = 0;
            AestheticDownloadStatus = $"Downloading {model.Name}...";

            await DownloadFileAsync(model.Url, model.LocalPath, model.Name);

            model.RefreshFromDisk();
            if (!InstalledAestheticModels.Contains(model))
            {
                InstalledAestheticModels.Add(model);
            }
            SelectedAestheticModel ??= model;
            if (model.RequiresClip)
            {
                await EnsureClipModelAsync();
            }
            _notifications?.ShowInfo($"Downloaded {model.Name}.", "Aesthetic Scoring");
            OnPropertyChanged(nameof(ShowAestheticModelDropdown));
        }
        catch (Exception ex)
        {
            _notifications?.ShowError($"Failed to download {model.Name}: {ex.Message}", "Aesthetic Scoring");
        }
        finally
        {
            IsAestheticDownloadActive = false;
            AestheticDownloadStatus = "";
            AestheticDownloadProgress = 0;
        }
    }

    [RelayCommand]
    private void OpenAestheticModelsFolder()
    {
        var dir = AestheticModelsDir;
        if (string.IsNullOrWhiteSpace(dir)) return;
        try
        {
            if (!Directory.Exists(dir))
            {
                _notifications?.ShowError($"Aesthetic models folder does not exist yet: {dir}", "Aesthetic Scoring");
                return;
            }

            if (OperatingSystem.IsMacOS())
            {
                var startInfo = new System.Diagnostics.ProcessStartInfo("open");
                startInfo.ArgumentList.Add(dir);
                System.Diagnostics.Process.Start(startInfo);
            }
            else if (OperatingSystem.IsWindows())
            {
                var startInfo = new System.Diagnostics.ProcessStartInfo("explorer.exe");
                startInfo.ArgumentList.Add(dir);
                System.Diagnostics.Process.Start(startInfo);
            }
            else
            {
                var startInfo = new System.Diagnostics.ProcessStartInfo("xdg-open");
                startInfo.ArgumentList.Add(dir);
                System.Diagnostics.Process.Start(startInfo);
            }
        }
        catch (Exception ex)
        {
            _notifications?.ShowError($"Failed to open aesthetic models folder: {ex.Message}", "Aesthetic Scoring");
        }
    }

    private async Task TryPopulateRemoteSizeAsync(AestheticModelOption model)
    {
        if (string.IsNullOrWhiteSpace(model.Url) || model.SizeBytes.HasValue) return;
        try
        {
            using var request = new HttpRequestMessage(HttpMethod.Head, model.Url);
            if (!string.IsNullOrWhiteSpace(HuggingFaceApiKey))
            {
                request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", HuggingFaceApiKey.Trim());
            }
            using var response = await _httpClient.SendAsync(request);
            if (response.IsSuccessStatusCode)
            {
                model.SizeBytes = response.Content.Headers.ContentLength;
            }
        }
        catch
        {
            // ignore size fetch failures
        }
    }

    private async Task EnsureClipModelAsync()
    {
        var manifest = ModelManifest.CreateDefault();
        var clipPath = Path.Combine(AestheticModelsDir, "clip_vision.onnx");
        if (File.Exists(clipPath))
        {
            return;
        }

        var url = manifest.GetClipModelUrls().FirstOrDefault();
        if (string.IsNullOrWhiteSpace(url))
        {
            return;
        }

        IsAestheticDownloadActive = true;
        AestheticDownloadProgress = 0;
        AestheticDownloadStatus = "Downloading CLIP model...";
        await DownloadFileAsync(url, clipPath, "CLIP model");
    }

    private async Task DownloadFileAsync(string url, string outputPath, string label)
    {
        using var request = new HttpRequestMessage(HttpMethod.Get, url);
        if (!string.IsNullOrWhiteSpace(HuggingFaceApiKey))
        {
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", HuggingFaceApiKey.Trim());
        }

        using var response = await _httpClient.SendAsync(request, HttpCompletionOption.ResponseHeadersRead);
        response.EnsureSuccessStatusCode();

        var total = response.Content.Headers.ContentLength;
        await using var output = File.Create(outputPath);
        await using var input = await response.Content.ReadAsStreamAsync();
        var buffer = new byte[1024 * 1024];
        long readTotal = 0;
        int read;
        while ((read = await input.ReadAsync(buffer.AsMemory(0, buffer.Length))) > 0)
        {
            await output.WriteAsync(buffer.AsMemory(0, read));
            readTotal += read;
            if (total.HasValue && total.Value > 0)
            {
                AestheticDownloadProgress = readTotal / (double)total.Value;
                AestheticDownloadStatus = $"{label} {readTotal / 1024 / 1024}MB / {total.Value / 1024 / 1024}MB";
            }
            else
            {
                AestheticDownloadStatus = $"{label} {readTotal / 1024 / 1024}MB";
            }
        }
    }

    [RelayCommand]
    private void AddNegativePreset()
    {
        var key = GetNextPresetKey();
        NegativePresets.Add(new NegativePresetItem(key, string.Empty));
        SelectedNegativePreset = NegativePresets.LastOrDefault();
        EditingPresetText = string.Empty;
    }

    [RelayCommand]
    private void RemoveNegativePreset()
    {
        if (SelectedNegativePreset == null) return;
        NegativePresets.Remove(SelectedNegativePreset);
        if (NegativePresets.Count == 0)
        {
            var fallbackKey = GetNextPresetKey(preferred: "standard");
            NegativePresets.Add(new NegativePresetItem(fallbackKey, string.Empty));
        }
        SelectedNegativePreset = NegativePresets.FirstOrDefault();
    }

    [RelayCommand]
    private void SaveNegativePreset()
    {
        CommitNegativePresetEdits();
    }

    [RelayCommand]
    private void RenameNegativePreset()
    {
        if (SelectedNegativePreset == null) return;
        var proposed = (EditingPresetName ?? string.Empty).Trim();
        if (string.IsNullOrWhiteSpace(proposed)) return;

        if (NegativePresets.Any(p =>
                !ReferenceEquals(p, SelectedNegativePreset) &&
                string.Equals(p.Key, proposed, StringComparison.OrdinalIgnoreCase)))
        {
            _notifications?.ShowWarning("A preset with that name already exists.", "Rename preset");
            return;
        }

        var oldKey = SelectedNegativePreset.Key;
        SelectedNegativePreset.Key = proposed;
        if (string.Equals(DefaultNegativePromptKey, oldKey, StringComparison.OrdinalIgnoreCase))
        {
            DefaultNegativePromptKey = proposed;
        }
    }

    private void CommitNegativePresetEdits()
    {
        if (SelectedNegativePreset == null) return;
        SelectedNegativePreset.Value = EditingPresetText;
        DefaultNegativePrompt = SelectedNegativePreset.Value;
        DefaultNegativePromptKey = SelectedNegativePreset.Key;
    }

    private string GetNextPresetKey(string? preferred = null)
    {
        if (!string.IsNullOrWhiteSpace(preferred) &&
            !NegativePresets.Any(p => string.Equals(p.Key, preferred, StringComparison.OrdinalIgnoreCase)))
        {
            return preferred;
        }

        var index = 1;
        while (true)
        {
            var key = $"Preset {index}";
            if (!NegativePresets.Any(p => string.Equals(p.Key, key, StringComparison.OrdinalIgnoreCase)))
            {
                return key;
            }
            index++;
        }
    }

    public sealed partial class NegativePresetItem : ObservableObject
    {
        public NegativePresetItem(string key, string value)
        {
            _key = key;
            _value = value;
        }

        [ObservableProperty] private string _key;
        [ObservableProperty] private string _value;
    }
}
