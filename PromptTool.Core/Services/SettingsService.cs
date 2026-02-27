using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using System.Threading.Tasks;
using System.Security.Cryptography;
using System.Text;
using PromptTool.Core.Config;
using PromptTool.Core.Models;
using PromptTool.Core.Clients.InvokeAI; // Added // Added

namespace PromptTool.Core.Services;

public class SettingsService
{
    private readonly string _configDir;
    private readonly string _settingsFilePath;
    private readonly string _pathsFilePath;
    private readonly string _invokeAIModelDefaultsFilePath;
    private readonly string _loraDefaultsFilePath;
    private readonly string _wildcardCacheFilePath;
    private readonly string _themeFilePath;
    private readonly string _hfKeyFilePath;
    private string _settingsFileInUse = string.Empty;
    public AppSettings Settings { get; private set; }
    public List<ModelDefaults> InvokeAIModelDefaults { get; private set; }
    public List<ModelDefaults> InvokeAILoraDefaults { get; private set; }
    public string ConfigDir => _configDir;
    public string SettingsFileInUse => _settingsFileInUse;
    public string PathsFilePath => _pathsFilePath;

    public SettingsService()
    {
        _configDir = ResolveConfigDir();
        Directory.CreateDirectory(_configDir);

        // Mirror the Qt app file set, but scoped to the C# directory for clean separation.
        _settingsFilePath = Path.Combine(_configDir, "settings.json");
        _pathsFilePath = Path.Combine(_configDir, "paths.json");
        _invokeAIModelDefaultsFilePath = Path.Combine(_configDir, "model_defaults.json");
        _loraDefaultsFilePath = Path.Combine(_configDir, "lora_defaults.json");
        _wildcardCacheFilePath = Path.Combine(_configDir, "wildcards.cache.json");
        _themeFilePath = Path.Combine(_configDir, "theme.json");
        _hfKeyFilePath = Path.Combine(_configDir, "hf_key.bin");
        Settings = LoadSettings();
        InvokeAIModelDefaults = LoadInvokeAIModelDefaults();
        InvokeAILoraDefaults = LoadInvokeAILoraDefaults();
        EnsureBaseDirectories();
    }

    private AppSettings LoadSettings()
    {
        // Prefer the unified names; fall back to the old C#-specific filenames to migrate users.
        var legacySettingsPath = Path.Combine(_configDir, "settings_csharp.json");
        var pathToUse = File.Exists(_settingsFilePath) ? _settingsFilePath : legacySettingsPath;

        if (File.Exists(pathToUse))
        {
            _settingsFileInUse = pathToUse;
            try
            {
                var json = File.ReadAllText(pathToUse);
                if (string.IsNullOrWhiteSpace(json))
                {
                    BackupCorruptSettings(pathToUse);
                    _settingsFileInUse = _settingsFilePath;
                    var emptyDefaults = ApplyDefaultPaths(new AppSettings());
                    emptyDefaults.Theme = LoadThemeValue(emptyDefaults.Theme);
                    SaveSettingsAsync(emptyDefaults).GetAwaiter().GetResult();
                    return emptyDefaults;
                }
                var loaded = JsonSerializer.Deserialize<AppSettings>(json) ?? new AppSettings();
                loaded.Theme = LoadThemeValue(loaded.Theme);
                loaded = ApplyDefaultPaths(loaded);
                TryDecryptHfKey(loaded);
                // Normalize DefaultScheduler after loading
                if (!string.IsNullOrWhiteSpace(loaded.DefaultScheduler))
                {
                    loaded.DefaultScheduler = GraphBuilder.NormalizeScheduler(loaded.DefaultScheduler);
                }
                var paths = LoadPathsSettings();
                if (paths != null)
                {
                    ApplyPaths(loaded, paths);
                }
                else if (HasExplicitPaths(loaded))
                {
                    SavePathsSettings(loaded);
                }
                return loaded;
            }
            catch (JsonException ex)
            {
                Console.Error.WriteLine($"Error loading settings: {ex.Message}");
                return ApplyDefaultPaths(new AppSettings());
            }
        }
        // Create default settings if none exist
        _settingsFileInUse = _settingsFilePath;
        var defaults = ApplyDefaultPaths(new AppSettings());
        defaults.Theme = LoadThemeValue(defaults.Theme);
        // Normalize DefaultScheduler before saving new defaults
        if (!string.IsNullOrWhiteSpace(defaults.DefaultScheduler))
        {
            defaults.DefaultScheduler = GraphBuilder.NormalizeScheduler(defaults.DefaultScheduler);
        }
        SaveSettingsAsync(defaults).GetAwaiter().GetResult();
        return defaults;
    }

    private static string ResolveConfigDir()
    {
        var baseDir = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        if (string.IsNullOrWhiteSpace(baseDir))
        {
            baseDir = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
        }
        if (string.IsNullOrWhiteSpace(baseDir))
        {
            var home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
            baseDir = string.IsNullOrWhiteSpace(home)
                ? Path.Combine(Path.GetTempPath(), "PromptTool")
                : Path.Combine(home, ".local", "share");
        }

        return Path.Combine(baseDir, "PromptTool");
    }


    private static void BackupCorruptSettings(string path)
    {
        try
        {
            var directory = Path.GetDirectoryName(path);
            if (string.IsNullOrWhiteSpace(directory))
            {
                return;
            }
            var timestamp = DateTime.Now.ToString("yyyyMMdd_HHmmss");
            var backupPath = Path.Combine(directory, $"settings.json.bak.{timestamp}");
            File.Copy(path, backupPath, overwrite: true);
        }
        catch
        {
            // Best-effort backup only.
        }
    }

    private List<ModelDefaults> LoadInvokeAIModelDefaults()
    {
        var legacyPath = Path.Combine(_configDir, "model_defaults_csharp.json");
        var pathToUse = File.Exists(_invokeAIModelDefaultsFilePath) ? _invokeAIModelDefaultsFilePath : legacyPath;
        if (File.Exists(pathToUse))
        {
            try
            {
                var json = File.ReadAllText(pathToUse);
                return ParseDefaultsJson(json, "models");
            }
            catch (JsonException ex)
            {
                if (Settings.Verbose) Console.Error.WriteLine($"Error loading InvokeAI model defaults: {ex.Message}");
                return new List<ModelDefaults>();
            }
        }
        return new List<ModelDefaults>();
    }

    private List<ModelDefaults> LoadInvokeAILoraDefaults()
    {
        var legacyPath = Path.Combine(_configDir, "lora_defaults_csharp.json");
        var pathToUse = File.Exists(_loraDefaultsFilePath) ? _loraDefaultsFilePath : legacyPath;
        if (File.Exists(pathToUse))
        {
            try
            {
                var json = File.ReadAllText(pathToUse);
                return ParseDefaultsJson(json, "loras");
            }
            catch (JsonException ex)
            {
                if (Settings.Verbose) Console.Error.WriteLine($"Error loading InvokeAI LoRA defaults: {ex.Message}");
                return new List<ModelDefaults>();
            }
        }
        return new List<ModelDefaults>();
    }

    private static List<ModelDefaults> ParseDefaultsJson(string json, string? rootKey)
    {
        if (string.IsNullOrWhiteSpace(json))
        {
            return new List<ModelDefaults>();
        }

        try
        {
            var list = JsonSerializer.Deserialize<List<ModelDefaults>>(json, new JsonSerializerOptions
            {
                PropertyNameCaseInsensitive = true
            });
            if (list != null && list.Count > 0)
            {
                return list;
            }
        }
        catch
        {
            // fall through to dictionary parsing
        }

        using var doc = JsonDocument.Parse(json);
        if (doc.RootElement.ValueKind != JsonValueKind.Object)
        {
            return new List<ModelDefaults>();
        }

        var root = doc.RootElement;
        if (!string.IsNullOrWhiteSpace(rootKey)
            && root.TryGetProperty(rootKey, out var subRoot)
            && subRoot.ValueKind == JsonValueKind.Object)
        {
            root = subRoot;
        }

        var results = new List<ModelDefaults>();
        foreach (var prop in root.EnumerateObject())
        {
            if (prop.Value.ValueKind != JsonValueKind.Object)
            {
                continue;
            }

            var item = new ModelDefaults { ModelName = prop.Name };
            foreach (var entry in prop.Value.EnumerateObject())
            {
                var key = entry.Name.Trim().ToLowerInvariant();
                switch (key)
                {
                    case "positive_prefix":
                    case "positive_prompt":
                    case "positive_prompt_prefix":
                    case "positiveprefix":
                        item.PositivePromptPrefix = entry.Value.GetString() ?? string.Empty;
                        break;
                    case "negative_prefix":
                    case "negative_prompt":
                    case "negative_prompt_prefix":
                    case "negativeprefix":
                        item.NegativePromptPrefix = entry.Value.GetString() ?? string.Empty;
                        break;
                    case "scheduler":
                    case "sampler":
                        item.Sampler = entry.Value.GetString() ?? string.Empty;
                        // Normalize sampler after loading
                        if (!string.IsNullOrWhiteSpace(item.Sampler))
                        {
                            item.Sampler = GraphBuilder.NormalizeScheduler(item.Sampler);
                        }
                        break;
                    case "steps":
                        if (entry.Value.ValueKind == JsonValueKind.Number && entry.Value.TryGetInt32(out var steps))
                        {
                            item.Steps = steps;
                        }
                        break;
                    case "cfg_scale":
                        if (entry.Value.ValueKind == JsonValueKind.Number)
                        {
                            item.CfgScale = entry.Value.GetDouble();
                        }
                        break;
                    case "cfg_rescale":
                    case "cfg_rescale_multiplier":
                        if (entry.Value.ValueKind == JsonValueKind.Number)
                        {
                            item.CfgRescaleMultiplier = entry.Value.GetDouble();
                        }
                        break;
                    case "size":
                        var size = entry.Value.GetString();
                        if (!string.IsNullOrWhiteSpace(size))
                        {
                            var parts = size.Split('x', 'X');
                            if (parts.Length == 2
                                && int.TryParse(parts[0].Trim(), out var w)
                                && int.TryParse(parts[1].Trim(), out var h))
                            {
                                item.Width = w;
                                item.Height = h;
                            }
                        }
                        break;
                }
            }
            results.Add(item);
        }

        return results;
    }

    public async Task<bool> SaveSettingsAsync(AppSettings newSettings)
    {
        try
        {
            Settings = ApplyDefaultPaths(newSettings); // Update the internal Settings property
            SaveThemeValue(Settings.Theme);
            var persisted = ApplyDefaultPaths(newSettings);
            if (!string.IsNullOrWhiteSpace(persisted.HuggingFaceApiKey))
            {
                persisted.HuggingFaceApiKeyEncrypted = EncryptHfKey(persisted.HuggingFaceApiKey);
                persisted.HuggingFaceApiKey = "";
            }
            SavePathsSettings(persisted);
            var settingsPayload = StripPaths(persisted);
            var options = new JsonSerializerOptions { WriteIndented = true };
            var json = JsonSerializer.Serialize(settingsPayload, options);
            await File.WriteAllTextAsync(_settingsFilePath, json); // Use async version
            EnsureBaseDirectories();
            return true;
        }
        catch (JsonException ex)
        {
            if (Settings.Verbose) Console.Error.WriteLine($"Error saving settings: {ex.Message}");
            return false;
        }
        catch (Exception ex)
        {
            if (Settings.Verbose) Console.Error.WriteLine($"Error saving settings: {ex.Message}");
            return false;
        }
    }

    private void TryDecryptHfKey(AppSettings settings)
    {
        if (!string.IsNullOrWhiteSpace(settings.HuggingFaceApiKey))
        {
            return;
        }
        if (string.IsNullOrWhiteSpace(settings.HuggingFaceApiKeyEncrypted))
        {
            return;
        }

        try
        {
            settings.HuggingFaceApiKey = DecryptHfKey(settings.HuggingFaceApiKeyEncrypted);
        }
        catch (Exception ex)
        {
            if (Settings.Verbose) Console.Error.WriteLine($"Error decrypting Hugging Face API key: {ex.Message}");
        }
    }

    private PathsSettings? LoadPathsSettings()
    {
        if (!File.Exists(_pathsFilePath))
        {
            return null;
        }

        try
        {
            var json = File.ReadAllText(_pathsFilePath);
            if (string.IsNullOrWhiteSpace(json)) return null;
            return JsonSerializer.Deserialize<PathsSettings>(json);
        }
        catch
        {
            return null;
        }
    }

    private void SavePathsSettings(AppSettings settings)
    {
        try
        {
            Directory.CreateDirectory(_configDir);
            var paths = new PathsSettings
            {
                TemplateBaseDir = settings.TemplateBaseDir,
                WildcardDir = settings.WildcardDir,
                HistoryDir = settings.HistoryDir,
                SystemPromptBaseDir = settings.SystemPromptBaseDir,
                CacheDir = settings.CacheDir
            };
            var json = JsonSerializer.Serialize(paths, new JsonSerializerOptions { WriteIndented = true });
            File.WriteAllText(_pathsFilePath, json);
        }
        catch
        {
            // Best effort only.
        }
    }

    private static void ApplyPaths(AppSettings settings, PathsSettings paths)
    {
        if (!string.IsNullOrWhiteSpace(paths.TemplateBaseDir)) settings.TemplateBaseDir = paths.TemplateBaseDir;
        if (!string.IsNullOrWhiteSpace(paths.WildcardDir)) settings.WildcardDir = paths.WildcardDir;
        if (!string.IsNullOrWhiteSpace(paths.HistoryDir)) settings.HistoryDir = paths.HistoryDir;
        if (!string.IsNullOrWhiteSpace(paths.SystemPromptBaseDir)) settings.SystemPromptBaseDir = paths.SystemPromptBaseDir;
        if (!string.IsNullOrWhiteSpace(paths.CacheDir)) settings.CacheDir = paths.CacheDir;
    }

    private static AppSettings StripPaths(AppSettings settings)
    {
        var clone = JsonSerializer.Deserialize<AppSettings>(
            JsonSerializer.Serialize(settings)) ?? settings;
        clone.TemplateBaseDir = "";
        clone.WildcardDir = "";
        clone.HistoryDir = "";
        clone.SystemPromptBaseDir = "";
        clone.CacheDir = "";
        return clone;
    }

    private static bool HasExplicitPaths(AppSettings settings)
    {
        return !string.IsNullOrWhiteSpace(settings.TemplateBaseDir)
               || !string.IsNullOrWhiteSpace(settings.WildcardDir)
               || !string.IsNullOrWhiteSpace(settings.HistoryDir)
               || !string.IsNullOrWhiteSpace(settings.SystemPromptBaseDir)
               || !string.IsNullOrWhiteSpace(settings.CacheDir);
    }

    private string EncryptHfKey(string plain)
    {
        var key = GetOrCreateHfEncryptionKey();
        var nonce = RandomNumberGenerator.GetBytes(12);
        var plaintext = Encoding.UTF8.GetBytes(plain);
        var ciphertext = new byte[plaintext.Length];
        var tag = new byte[16];

        using var aes = new AesGcm(key, 16);
        aes.Encrypt(nonce, plaintext, ciphertext, tag);

        var combined = new byte[nonce.Length + ciphertext.Length + tag.Length];
        Buffer.BlockCopy(nonce, 0, combined, 0, nonce.Length);
        Buffer.BlockCopy(ciphertext, 0, combined, nonce.Length, ciphertext.Length);
        Buffer.BlockCopy(tag, 0, combined, nonce.Length + ciphertext.Length, tag.Length);
        return Convert.ToBase64String(combined);
    }

    private string DecryptHfKey(string encoded)
    {
        var key = GetOrCreateHfEncryptionKey();
        var combined = Convert.FromBase64String(encoded);
        if (combined.Length < 12 + 16)
        {
            return "";
        }

        var nonce = new byte[12];
        var tag = new byte[16];
        var ciphertext = new byte[combined.Length - nonce.Length - tag.Length];
        Buffer.BlockCopy(combined, 0, nonce, 0, nonce.Length);
        Buffer.BlockCopy(combined, nonce.Length, ciphertext, 0, ciphertext.Length);
        Buffer.BlockCopy(combined, nonce.Length + ciphertext.Length, tag, 0, tag.Length);

        var plaintext = new byte[ciphertext.Length];
        using var aes = new AesGcm(key, 16);
        aes.Decrypt(nonce, ciphertext, tag, plaintext);
        return Encoding.UTF8.GetString(plaintext);
    }

    private byte[] GetOrCreateHfEncryptionKey()
    {
        if (File.Exists(_hfKeyFilePath))
        {
            return File.ReadAllBytes(_hfKeyFilePath);
        }

        var key = RandomNumberGenerator.GetBytes(32);
        File.WriteAllBytes(_hfKeyFilePath, key);
        TryRestrictPermissions(_hfKeyFilePath);
        return key;
    }

    private void TryRestrictPermissions(string path)
    {
        try
        {
            if (OperatingSystem.IsWindows())
            {
                return;
            }

            File.SetUnixFileMode(path, UnixFileMode.UserRead | UnixFileMode.UserWrite);
        }
        catch
        {
            // ignore permission hardening failures
        }
    }

    public bool SaveInvokeAIModelDefaults()
    {
        try
        {
            var options = new JsonSerializerOptions { WriteIndented = true };
            var json = JsonSerializer.Serialize(InvokeAIModelDefaults, options);
            File.WriteAllText(_invokeAIModelDefaultsFilePath, json);
            return true;
        }
        catch (JsonException ex)
        {
            if (Settings.Verbose) Console.Error.WriteLine($"Error saving InvokeAI model defaults: {ex.Message}");
            return false;
        }
        catch (Exception ex)
        {
            if (Settings.Verbose) Console.Error.WriteLine($"Error saving InvokeAI model defaults: {ex.Message}");
            return false;
        }
    }

    public bool SaveInvokeAILoraDefaults()
    {
        try
        {
            var options = new JsonSerializerOptions { WriteIndented = true };
            var json = JsonSerializer.Serialize(InvokeAILoraDefaults, options);
            File.WriteAllText(_loraDefaultsFilePath, json);
            return true;
        }
        catch (JsonException ex)
        {
            if (Settings.Verbose) Console.Error.WriteLine($"Error saving InvokeAI LoRA defaults: {ex.Message}");
            return false;
        }
        catch (Exception ex)
        {
            if (Settings.Verbose) Console.Error.WriteLine($"Error saving InvokeAI LoRA defaults: {ex.Message}");
            return false;
        }
    }

    public void ExportInvokeAIDefaults(string path)
    {
        var package = new
        {
            models = InvokeAIModelDefaults,
            loras = InvokeAILoraDefaults
        };
        var options = new JsonSerializerOptions { WriteIndented = true };
        File.WriteAllText(path, JsonSerializer.Serialize(package, options));
    }

    public bool ImportInvokeAIDefaults(string path)
    {
        try
        {
            var json = File.ReadAllText(path);
            var doc = JsonSerializer.Deserialize<JsonElement>(json);
            if (doc.ValueKind != JsonValueKind.Object) return false;

            if (doc.TryGetProperty("models", out var modelsElem))
            {
                var models = modelsElem.Deserialize<List<ModelDefaults>>() ?? new List<ModelDefaults>();
                InvokeAIModelDefaults = models;
                SaveInvokeAIModelDefaults();
            }
            if (doc.TryGetProperty("loras", out var lorasElem))
            {
                var loras = lorasElem.Deserialize<List<ModelDefaults>>() ?? new List<ModelDefaults>();
                InvokeAILoraDefaults = loras;
                SaveInvokeAILoraDefaults();
            }
            return true;
        }
        catch (Exception ex)
        {
            if (Settings.Verbose) Console.Error.WriteLine($"Error importing InvokeAI defaults: {ex.Message}");
            return false;
        }
    }

    public string ConfigDirectory => _configDir;
    public string WildcardCacheFilePath => _wildcardCacheFilePath;
    public string ThemeFilePath => _themeFilePath;
    public string ModelDefaultsFilePath => _invokeAIModelDefaultsFilePath;
    public string LoraDefaultsFilePath => _loraDefaultsFilePath;

    public string GetTemplateDir()
    {
        return Path.Combine(Settings.TemplateBaseDir, Settings.Workflow ?? "sfw");
    }

    public IReadOnlyList<string> GetWildcardDirs()
    {
        // Workflow-specific wildcards override shared ones by being loaded later
        if (string.Equals(Settings.Workflow, "nsfw", StringComparison.OrdinalIgnoreCase))
        {
            return new[] { Path.Combine(Settings.WildcardDir, "nsfw"), Settings.WildcardDir };
        }
        return new[] { Settings.WildcardDir };
    }

    public string GetHistoryDir()
    {
        return Path.Combine(Settings.HistoryDir, Settings.Workflow ?? "sfw");
    }

    public string GetHistoryImagesDir()
    {
        return Path.Combine(GetHistoryDir(), "images");
    }

    public string GetSystemPromptDir()
    {
        return Path.Combine(Settings.SystemPromptBaseDir, Settings.Workflow ?? "sfw");
    }

    private AppSettings ApplyDefaultPaths(AppSettings settings)
    {
        var appRoot = _configDir.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);

        settings.TemplateBaseDir = string.IsNullOrWhiteSpace(settings.TemplateBaseDir)
            ? Path.Combine(appRoot, "templates")
            : settings.TemplateBaseDir;

        settings.WildcardDir = string.IsNullOrWhiteSpace(settings.WildcardDir)
            ? Path.Combine(appRoot, "wildcards")
            : settings.WildcardDir;

        settings.HistoryDir = string.IsNullOrWhiteSpace(settings.HistoryDir)
            ? Path.Combine(appRoot, "history")
            : settings.HistoryDir;

        settings.SystemPromptBaseDir = string.IsNullOrWhiteSpace(settings.SystemPromptBaseDir)
            ? Path.Combine(appRoot, "system_prompts")
            : settings.SystemPromptBaseDir;

        settings.CacheDir = string.IsNullOrWhiteSpace(settings.CacheDir)
            ? Path.Combine(appRoot, "cache")
            : settings.CacheDir;

        settings.Workflow = string.IsNullOrWhiteSpace(settings.Workflow) ? "sfw" : settings.Workflow;
        settings.Theme = string.IsNullOrWhiteSpace(settings.Theme) ? "light" : settings.Theme;
        settings.FontSize = settings.FontSize <= 0 ? 11 : settings.FontSize;
        settings.InvokeAITimeoutSeconds = settings.InvokeAITimeoutSeconds <= 0 ? 300 : settings.InvokeAITimeoutSeconds;
        settings.EnhancementSystemPrompt ??= "";
        settings.DefaultScheduler = string.IsNullOrWhiteSpace(settings.DefaultScheduler) ? "dpmpp_2m_k" : settings.DefaultScheduler;
        settings.DefaultSteps = settings.DefaultSteps <= 0 ? 30 : settings.DefaultSteps;
        settings.DefaultCfgScale = settings.DefaultCfgScale <= 0 ? 7.5 : settings.DefaultCfgScale;
        settings.DefaultCfgRescaleMultiplier = settings.DefaultCfgRescaleMultiplier < 0 ? 0.0 : settings.DefaultCfgRescaleMultiplier;
        settings.DefaultWidth = settings.DefaultWidth <= 0 ? 1024 : settings.DefaultWidth;
        settings.DefaultHeight = settings.DefaultHeight <= 0 ? 1024 : settings.DefaultHeight;
        settings.DefaultSaveToGallery = settings.DefaultSaveToGallery;
        settings.DefaultBaseModelType = string.IsNullOrWhiteSpace(settings.DefaultBaseModelType) ? "sdxl" : settings.DefaultBaseModelType;
        settings.AutoClearInvokeCacheBetweenModels = settings.AutoClearInvokeCacheBetweenModels;
        settings.Verbose = settings.Verbose;
        settings.GenerationDefaults ??= new Dictionary<string, GenerationDefaultsSettings>();
        settings.AestheticScoringBackend = string.IsNullOrWhiteSpace(settings.AestheticScoringBackend)
            ? "local"
            : settings.AestheticScoringBackend;
        settings.AestheticScoringRemoteUrl ??= "";
        settings.HuggingFaceApiKey ??= "";
        settings.NegativePromptPresets ??= new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        if (settings.NegativePromptPresets.Count == 0)
        {
            settings.NegativePromptPresets["standard"] = settings.DefaultNegativePrompt;
        }
        if (!settings.NegativePromptPresets.ContainsKey(settings.DefaultNegativePromptKey))
        {
            settings.DefaultNegativePromptKey = settings.NegativePromptPresets.Keys.First();
        }
        SeedGenerationDefaults(settings, "sdxl");
        SeedGenerationDefaults(settings, "sd-1.5", defaultWidth: 512, defaultHeight: 512);

        return settings;
    }

    private static void SeedGenerationDefaults(AppSettings settings, string baseType, int? defaultWidth = null, int? defaultHeight = null)
    {
        if (!settings.GenerationDefaults.TryGetValue(baseType, out var existing) || existing == null)
        {
            settings.GenerationDefaults[baseType] = new GenerationDefaultsSettings
            {
                Scheduler = settings.DefaultScheduler ?? "dpmpp_2m_k",
                Steps = settings.DefaultSteps > 0 ? settings.DefaultSteps : 30,
                CfgScale = settings.DefaultCfgScale > 0 ? settings.DefaultCfgScale : 7.5,
                CfgRescaleMultiplier = settings.DefaultCfgRescaleMultiplier >= 0 ? settings.DefaultCfgRescaleMultiplier : 0,
                Width = defaultWidth ?? settings.DefaultWidth,
                Height = defaultHeight ?? settings.DefaultHeight,
                SaveToGallery = settings.DefaultSaveToGallery
            };
        }
        else
        {
            if (existing.Width <= 0) existing.Width = defaultWidth ?? settings.DefaultWidth;
            if (existing.Height <= 0) existing.Height = defaultHeight ?? settings.DefaultHeight;
            if (string.IsNullOrWhiteSpace(existing.Scheduler)) existing.Scheduler = settings.DefaultScheduler ?? "dpmpp_2m_k";
            if (existing.Steps <= 0) existing.Steps = settings.DefaultSteps > 0 ? settings.DefaultSteps : 30;
            if (existing.CfgScale <= 0) existing.CfgScale = settings.DefaultCfgScale > 0 ? settings.DefaultCfgScale : 7.5;
            if (existing.CfgRescaleMultiplier < 0) existing.CfgRescaleMultiplier = 0;
        }
    }

    private void EnsureBaseDirectories()
    {
        Directory.CreateDirectory(Settings.TemplateBaseDir);
        Directory.CreateDirectory(Path.Combine(Settings.TemplateBaseDir, "sfw"));
        Directory.CreateDirectory(Path.Combine(Settings.TemplateBaseDir, "nsfw"));

        Directory.CreateDirectory(Settings.WildcardDir);
        Directory.CreateDirectory(Path.Combine(Settings.WildcardDir, "nsfw"));

        Directory.CreateDirectory(Settings.HistoryDir);
        Directory.CreateDirectory(Path.Combine(Settings.HistoryDir, "sfw"));
        Directory.CreateDirectory(Path.Combine(Settings.HistoryDir, "sfw", "images"));
        Directory.CreateDirectory(Path.Combine(Settings.HistoryDir, "nsfw"));
        Directory.CreateDirectory(Path.Combine(Settings.HistoryDir, "nsfw", "images"));

        Directory.CreateDirectory(Settings.SystemPromptBaseDir);
        Directory.CreateDirectory(Path.Combine(Settings.SystemPromptBaseDir, "sfw"));
        Directory.CreateDirectory(Path.Combine(Settings.SystemPromptBaseDir, "nsfw"));
        Directory.CreateDirectory(Path.Combine(Settings.SystemPromptBaseDir, "sfw", "variations"));
        Directory.CreateDirectory(Path.Combine(Settings.SystemPromptBaseDir, "nsfw", "variations"));
        Directory.CreateDirectory(Path.Combine(Settings.SystemPromptBaseDir, "sfw", "negative_prompts"));
        Directory.CreateDirectory(Path.Combine(Settings.SystemPromptBaseDir, "nsfw", "negative_prompts"));

        Directory.CreateDirectory(Settings.CacheDir);
    }

    private string LoadThemeValue(string? fallback)
    {
        try
        {
            var legacyPath = Path.Combine(_configDir, "theme_csharp.json");
            var pathToUse = File.Exists(_themeFilePath) ? _themeFilePath : legacyPath;
            if (!File.Exists(pathToUse)) return fallback ?? "dark";
            var json = File.ReadAllText(pathToUse);
            var doc = JsonSerializer.Deserialize<JsonElement>(json);
            if (doc.ValueKind == JsonValueKind.String)
            {
                return doc.GetString() ?? fallback ?? "dark";
            }
            if (doc.ValueKind == JsonValueKind.Object && doc.TryGetProperty("theme", out var t) && t.ValueKind == JsonValueKind.String)
            {
                return t.GetString() ?? fallback ?? "dark";
            }
        }
        catch (Exception ex)
        {
            if (Settings.Verbose) Console.Error.WriteLine($"Error loading theme: {ex.Message}");
        }
        return fallback ?? "dark";
    }

    private void SaveThemeValue(string? theme)
    {
        try
        {
            var payload = string.IsNullOrWhiteSpace(theme)
                ? "\"dark\""
                : JsonSerializer.Serialize(theme);
            File.WriteAllText(_themeFilePath, payload);
        }
        catch (Exception ex)
        {
            if (Settings.Verbose) Console.Error.WriteLine($"Error saving theme: {ex.Message}");
        }
    }
}
