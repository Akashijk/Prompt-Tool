using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using PromptTool.Core.Config;

namespace PromptTool.Core.Services;

public class TemplateService
{
    private readonly SettingsService _settingsService;

    public TemplateService(SettingsService settingsService)
    {
        _settingsService = settingsService;
    }

    private string GetTemplateDirectory(string? workflow = null)
    {
        var resolved = string.IsNullOrWhiteSpace(workflow)
            ? _settingsService.Settings.Workflow ?? "sfw"
            : workflow;
        return Path.Combine(_settingsService.Settings.TemplateBaseDir, resolved);
    }

    public Task<List<string>> GetTemplateNamesAsync()
    {
        var directory = GetTemplateDirectory();
        return GetTemplateNamesFromDirectoryAsync(directory);
    }

    public Task<List<string>> GetTemplateNamesAsync(string? workflow)
    {
        var directory = GetTemplateDirectory(workflow);
        return GetTemplateNamesFromDirectoryAsync(directory);
    }

    private static Task<List<string>> GetTemplateNamesFromDirectoryAsync(string directory)
    {
        if (!Directory.Exists(directory))
        {
            return Task.FromResult(new List<string>());
        }

        var templateFiles = Directory.GetFiles(directory, "*.txt")
            .Select(Path.GetFileNameWithoutExtension)
            .Where(name => name != null)
            .ToList();
            
        return Task.FromResult(templateFiles)!;
    }
    
    public async Task<string> LoadTemplateAsync(string templateName)
    {
        var directory = GetTemplateDirectory();
        var filePath = Path.Combine(directory, $"{templateName}.txt");

        if (!File.Exists(filePath))
        {
            return string.Empty;
        }

        return await File.ReadAllTextAsync(filePath);
    }
}
