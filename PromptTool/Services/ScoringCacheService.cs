using System;
using System.IO;

namespace PromptTool.Services;

public class ScoringCacheService
{
    private const string CacheFolderName = "scoring";
    private const string ModelsFolderName = "models";
    private const string AppFolderName = "PromptTool";

    public string GetCacheDir()
    {
        var baseDir = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        if (string.IsNullOrWhiteSpace(baseDir))
        {
            baseDir = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
        }
        if (string.IsNullOrWhiteSpace(baseDir))
        {
            baseDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".prompttool");
        }

        return Path.Combine(baseDir, AppFolderName, CacheFolderName);
    }

    public string GetModelsDir()
    {
        return Path.Combine(GetCacheDir(), ModelsFolderName);
    }

    public void EnsureDirectories()
    {
        Directory.CreateDirectory(GetCacheDir());
        Directory.CreateDirectory(GetModelsDir());
    }
}
