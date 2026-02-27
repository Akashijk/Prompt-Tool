using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using PromptTool.Core.Clients;
using PromptTool.Core.Services;
using PromptTool.ViewModels;

namespace PromptTool.Tests;

public static class Program
{
    public static async Task<int> Main()
    {
        var failures = new List<string>();

        await RunTestAsync(nameof(TestInsertReplacesExistingWildcard), TestInsertReplacesExistingWildcard, failures);
        await RunTestAsync(nameof(TestSelectingWildcardUpdatesOutput), TestSelectingWildcardUpdatesOutput, failures);
        await RunTestAsync(nameof(TestConvertTxtToJsonPreservesOrder), TestConvertTxtToJsonPreservesOrder, failures);
        await RunTestAsync(nameof(TestConvertCreatesBackup), TestConvertCreatesBackup, failures);
        await RunTestAsync(nameof(TestConvertSkipsWhenJsonExists), TestConvertSkipsWhenJsonExists, failures);

        if (failures.Count > 0)
        {
            Console.Error.WriteLine("Tests failed:");
            foreach (var failure in failures)
            {
                Console.Error.WriteLine($" - {failure}");
            }
            return 1;
        }

        Console.WriteLine("All PromptTool checks passed.");
        return 0;
    }

    private static async Task RunTestAsync(string name, Func<Task> test, List<string> failures)
    {
        try
        {
            await test();
        }
        catch (Exception ex)
        {
            failures.Add($"{name}: {ex.Message}");
        }
    }

    private static async Task TestInsertReplacesExistingWildcard()
    {
        var dir = CreateTempWildcards(new Dictionary<string, IReadOnlyList<string>>
        {
            { "color", new[] { "red" } },
            { "weather", new[] { "rain" } }
        });

        try
        {
            var (settings, wildcardService, vm) = BuildVm(dir);
            vm.PromptText = "A prompt with __color__ token.";

            var caretInside = vm.PromptText.IndexOf("__color__", StringComparison.Ordinal) + 3;
            var (updated, _) = vm.InsertOrReplaceWildcardAt("weather", caretInside, caretInside, caretInside);
            AssertEqual("A prompt with __weather__ token.", updated, "Caret inside wildcard should replace the whole token.");
        }
        finally
        {
            TryDelete(dir);
        }
    }

    private static async Task TestSelectingWildcardUpdatesOutput()
    {
        var dir = CreateTempWildcards(new Dictionary<string, IReadOnlyList<string>>
        {
            { "color", new[] { "red", "blue" } }
        });

        try
        {
            var (_, wildcardService, vm) = BuildVm(dir);
            vm.PromptText = "Color: __color__!";

            await vm.GenerateCommand.ExecuteAsync(null);

            var segment = vm.ProcessedPromptSegments.FirstOrDefault(s => s.IsWildcard)
                          ?? throw new InvalidOperationException("No wildcard segment produced.");

            await vm.ApplyWildcardChoiceAsync(segment, "blue");
            AssertEqual("Color: blue!", vm.OutputText, "Applying a new wildcard value should update the resolved output.");
        }
        finally
        {
            TryDelete(dir);
        }
    }

    private static (SettingsService settings, WildcardService wildcardService, MainWindowViewModel vm) BuildVm(string wildcardDir)
    {
        var settings = new SettingsService();
        settings.Settings.WildcardDir = wildcardDir;
        settings.SaveSettingsAsync(settings.Settings).GetAwaiter().GetResult();

        var wildcardService = new WildcardService(wildcardDir, settings);
        var processor = new PromptProcessorService(wildcardService);
        var templateService = new TemplateService(settings);
        var systemPrompts = new SystemPromptService(settings);
        var usageTracker = new ModelUsageTracker();
        var vm = new MainWindowViewModel(
            processor,
            wildcardService,
            settings,
            systemPrompts,
            new FakeOllamaClient(),
            new InvokeAIClient(new System.Net.Http.HttpClient(), settings),
            new HistoryManagerService(settings),
            new KpiStatsService(settings),
            templateService,
            usageTracker);
        return (settings, wildcardService, vm);
    }

    private sealed class FakeOllamaClient : OllamaClient
    {
        public FakeOllamaClient() : base(new System.Net.Http.HttpClient()) { }

        public override Task<IReadOnlyList<string>> GetModelNamesAsync(CancellationToken ct = default)
        {
            return Task.FromResult<IReadOnlyList<string>>(new List<string> { "test-model" });
        }

        public override Task<string> GenerateAsync(string model, string prompt, CancellationToken ct = default, double? temperature = null, double? topP = null)
        {
            return Task.FromResult($"{prompt} [enhanced by {model}]");
        }
    }

    private static void AssertEqual(string expected, string actual, string message)
    {
        if (!string.Equals(expected, actual, StringComparison.Ordinal))
        {
            throw new InvalidOperationException($"{message} Expected '{expected}', got '{actual}'.");
        }
    }

    private static string CreateTempWildcards(IDictionary<string, IReadOnlyList<string>> definitions)
    {
        var dir = Path.Combine(Path.GetTempPath(), "prompttool_tests_" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        foreach (var kvp in definitions)
        {
            File.WriteAllLines(Path.Combine(dir, $"{kvp.Key}.txt"), kvp.Value);
        }
        return dir;
    }

    private static async Task TestConvertTxtToJsonPreservesOrder()
    {
        var dir = Path.Combine(Path.GetTempPath(), "prompttool_tests_" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        var txtPath = Path.Combine(dir, "colors.txt");
        await File.WriteAllLinesAsync(txtPath, new[] { "red", "blue", "green" });

        try
        {
            var settings = new SettingsService();
            settings.Settings.WildcardDir = dir;
            settings.SaveSettingsAsync(settings.Settings).GetAwaiter().GetResult();
            var service = new WildcardService(dir, settings);

            var result = await service.ConvertLegacyTextWildcardAsync(txtPath);
            if (!result.Converted || result.JsonPath == null) throw new InvalidOperationException("Conversion failed.");

            var json = await File.ReadAllTextAsync(result.JsonPath);
            using var doc = System.Text.Json.JsonDocument.Parse(json);
            var choices = doc.RootElement.GetProperty("choices").EnumerateArray().Select(e => e.GetString()).ToList();
            AssertEqual("red", choices[0], "First choice should preserve order.");
            AssertEqual("blue", choices[1], "Second choice should preserve order.");
            AssertEqual("green", choices[2], "Third choice should preserve order.");
        }
        finally
        {
            TryDelete(dir);
        }
    }

    private static async Task TestConvertCreatesBackup()
    {
        var dir = Path.Combine(Path.GetTempPath(), "prompttool_tests_" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        var txtPath = Path.Combine(dir, "animals.txt");
        await File.WriteAllLinesAsync(txtPath, new[] { "cat", "dog" });

        try
        {
            var settings = new SettingsService();
            settings.Settings.WildcardDir = dir;
            settings.SaveSettingsAsync(settings.Settings).GetAwaiter().GetResult();
            var service = new WildcardService(dir, settings);

            var result = await service.ConvertLegacyTextWildcardAsync(txtPath);
            if (!result.Converted || result.BackupPath == null) throw new InvalidOperationException("Conversion did not create backup.");
            if (!File.Exists(result.BackupPath)) throw new InvalidOperationException("Backup file missing.");
            if (File.Exists(txtPath)) throw new InvalidOperationException("Original TXT should be moved to backup.");
        }
        finally
        {
            TryDelete(dir);
        }
    }

    private static async Task TestConvertSkipsWhenJsonExists()
    {
        var dir = Path.Combine(Path.GetTempPath(), "prompttool_tests_" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        var txtPath = Path.Combine(dir, "mood.txt");
        var jsonPath = Path.Combine(dir, "mood.json");
        await File.WriteAllLinesAsync(txtPath, new[] { "happy" });
        await File.WriteAllTextAsync(jsonPath, "{ \"choices\": [\"calm\"] }");

        try
        {
            var settings = new SettingsService();
            settings.Settings.WildcardDir = dir;
            settings.SaveSettingsAsync(settings.Settings).GetAwaiter().GetResult();
            var service = new WildcardService(dir, settings);

            var originalJson = await File.ReadAllTextAsync(jsonPath);
            var result = await service.ConvertLegacyTextWildcardAsync(txtPath);
            if (!result.SkippedBecauseJsonExists) throw new InvalidOperationException("Conversion should skip when JSON exists.");
            var afterJson = await File.ReadAllTextAsync(jsonPath);
            AssertEqual(originalJson, afterJson, "Existing JSON should not be overwritten.");
            if (!File.Exists(txtPath)) throw new InvalidOperationException("Original TXT should remain when JSON exists.");
        }
        finally
        {
            TryDelete(dir);
        }
    }

    private static void TryDelete(string path)
    {
        try
        {
            if (Directory.Exists(path))
            {
                Directory.Delete(path, true);
            }
        }
        catch
        {
            // best-effort cleanup
        }
    }
}
