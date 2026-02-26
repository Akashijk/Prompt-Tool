using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using PromptTool.Core.Config;
using PromptTool.Core.Models;

namespace PromptTool.Core.Services;

public class SystemPromptService
{
    private readonly SettingsService _settings;

    public SystemPromptService(SettingsService settings)
    {
        _settings = settings;
    }

    public async Task<string> LoadEnhancementPromptAsync(string? overridePrompt = null)
    {
        if (!string.IsNullOrWhiteSpace(overridePrompt))
        {
            return overridePrompt;
        }

        var searchPaths = GetEnhancementPromptPaths();
        foreach (var path in searchPaths)
        {
            if (File.Exists(path))
            {
                return await File.ReadAllTextAsync(path);
            }
        }

        return string.Empty;
    }

    public async Task<IReadOnlyList<VariationPrompt>> LoadVariationPromptsAsync()
    {
        EnsureVariationFiles();

        var results = new Dictionary<string, VariationPrompt>(StringComparer.OrdinalIgnoreCase);

        foreach (var dir in GetVariationDirectories())
        {
            if (!Directory.Exists(dir)) continue;

            foreach (var file in Directory.GetFiles(dir, "*.json"))
            {
                try
                {
                    var json = await File.ReadAllTextAsync(file);
                    var data = JsonSerializer.Deserialize<VariationFile>(json, new JsonSerializerOptions
                    {
                        PropertyNameCaseInsensitive = true
                    });
                    if (data?.Prompt == null) continue;
                    var variation = VariationPrompt.FromFileData(
                        Path.GetFileName(file) ?? Guid.NewGuid().ToString("N"),
                        data.Name,
                        data.Description,
                        data.Prompt);
                    results[variation.Key] = variation; // Later directories overwrite earlier ones
                }
                            catch (Exception ex)
                            {
                                if (_settings.Settings.Verbose) Console.WriteLine($"SystemPromptService: failed to load variation file {file}: {ex.Message}");
                            }            }
        }

        return results.Values
            .OrderBy(v => v.Name, StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    /// <summary>
    /// Ensures the user's workflow variations directory has content by copying bundled defaults if empty.
    /// This mirrors the Qt app behavior of seeding defaults on first run.
    /// </summary>
    private void EnsureVariationFiles()
    {
        try
        {
            var userWorkflowDir = _settings.GetSystemPromptDir();
            var userVarDir = Path.Combine(userWorkflowDir, "variations");
            Directory.CreateDirectory(userVarDir);

            var hasUserJson = Directory.EnumerateFiles(userVarDir, "*.json").Any();
            if (hasUserJson) return;

            var bundled = GetBundledWorkflowDir();
            if (string.IsNullOrWhiteSpace(bundled)) return;
            var bundledVarDir = Path.Combine(bundled, "variations");
            if (!Directory.Exists(bundledVarDir)) return;

            foreach (var file in Directory.EnumerateFiles(bundledVarDir, "*.json"))
            {
                var dest = Path.Combine(userVarDir, Path.GetFileName(file));
                if (!File.Exists(dest))
                {
                    File.Copy(file, dest, overwrite: false);
                }
            }
        }
                    catch (Exception ex)
                    {
                        if (_settings.Settings.Verbose) Console.WriteLine($"SystemPromptService: failed to seed variation files: {ex.Message}");
                    }    }

    private IEnumerable<string> GetEnhancementPromptPaths()
    {
        var workflowDir = _settings.GetSystemPromptDir();
        yield return Path.Combine(workflowDir, "enhancement.txt");

        var bundledWorkflowDir = GetBundledWorkflowDir();
        if (!string.IsNullOrWhiteSpace(bundledWorkflowDir))
        {
            yield return Path.Combine(bundledWorkflowDir, "enhancement.txt");
        }
    }

    private IEnumerable<string> GetVariationDirectories()
    {
        var workflowDir = _settings.GetSystemPromptDir();
        yield return Path.Combine(workflowDir, "variations");

        var bundledWorkflowDir = GetBundledWorkflowDir();
        if (!string.IsNullOrWhiteSpace(bundledWorkflowDir))
        {
            yield return Path.Combine(bundledWorkflowDir, "variations");
        }
    }

    private string? GetBundledWorkflowDir()
    {
        try
        {
            var workflow = _settings.Settings.Workflow ?? "sfw";
            var candidates = new[]
            {
                Path.Combine(AppContext.BaseDirectory, "system_prompts", workflow),
                Path.Combine(AppContext.BaseDirectory, "..", "system_prompts", workflow),
                Path.Combine(AppContext.BaseDirectory, "..", "..", "system_prompts", workflow),
                Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "system_prompts", workflow),
                Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "system_prompts", workflow)
            }
            .Select(Path.GetFullPath);

            return candidates.FirstOrDefault(Directory.Exists);
        }
        catch
        {
            return null;
        }
    }

    private sealed class VariationFile
    {
        public string? Name { get; set; }
        public string? Description { get; set; }
        public string? Prompt { get; set; }
    }
}
