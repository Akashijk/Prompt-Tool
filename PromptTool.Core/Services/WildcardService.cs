using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks; // Added
using PromptTool.Core.Models;

namespace PromptTool.Core.Services
{
    public class WildcardService
    {
        public record LegacyWildcardConversionResult(
            bool Converted,
            bool SkippedBecauseJsonExists,
            string? JsonPath,
            string? BackupPath,
            string? Error);

        public record LegacyWildcardBatchResult(
            int Converted,
            int SkippedExistingJson,
            int Failed,
            List<string> Errors);

        private readonly Dictionary<string, WildcardDefinition> _wildcards = new Dictionary<string, WildcardDefinition>();
        private readonly Dictionary<string, StructuredWildcard> _structuredWildcards = new();
        private readonly Random _random = new();
        private List<string> _wildcardsDirectories = new();
        private readonly SettingsService _settingsService;

        public WildcardService(string wildcardsDirectory, SettingsService settingsService)
            : this(new[] { wildcardsDirectory }, settingsService)
        {
            if (_settingsService.Settings.Verbose) Console.WriteLine("WildcardService: Single-string constructor finished.");
        }

        public WildcardService(IEnumerable<string> wildcardsDirectories, SettingsService settingsService)
        {
            _settingsService = settingsService;
            if (_settingsService.Settings.Verbose) Console.WriteLine("WildcardService: IEnumerable constructor started.");
            _wildcardsDirectories = wildcardsDirectories.Select(Path.GetFullPath).ToList();
            LoadWildcards();
            if (_settingsService.Settings.Verbose) Console.WriteLine("WildcardService: IEnumerable constructor finished.");
        }

        public void Reload(IEnumerable<string> wildcardsDirectories)
        {
            if (_settingsService.Settings.Verbose) Console.WriteLine("WildcardService: Reload started.");
            _wildcardsDirectories = wildcardsDirectories.Select(Path.GetFullPath).ToList();
            LoadWildcards();
            if (_settingsService.Settings.Verbose) Console.WriteLine("WildcardService: Reload finished.");
        }

        private void LoadWildcards()
        {
            if (_settingsService.Settings.Verbose) Console.WriteLine("WildcardService: LoadWildcards started.");
            _wildcards.Clear(); // Clear existing wildcards before reloading
            _structuredWildcards.Clear();
            InvalidateDependencyMap();

            var anyLoaded = false;
            var canonicalFiles = new Dictionary<string, (string Path, string Ext)>(StringComparer.OrdinalIgnoreCase);
            foreach (var dir in _wildcardsDirectories)
            {
                if (_settingsService.Settings.Verbose) Console.WriteLine($"WildcardService: Checking directory: {dir}");
                if (!Directory.Exists(dir))
                {
                    if (_settingsService.Settings.Verbose) Console.WriteLine($"WildcardService: Wildcards directory not found: {dir}");
                    continue;
                }

                foreach (var file in Directory.EnumerateFiles(dir, "*.*", SearchOption.AllDirectories))
                {
                    if (IsArchivedPath(file)) continue;
                    var ext = Path.GetExtension(file);
                    if (!ext.Equals(".json", StringComparison.OrdinalIgnoreCase) &&
                        !ext.Equals(".txt", StringComparison.OrdinalIgnoreCase))
                    {
                        continue;
                    }

                    var name = Path.GetFileNameWithoutExtension(file);
                    if (!canonicalFiles.TryGetValue(name, out var existing))
                    {
                        canonicalFiles[name] = (file, ext);
                        continue;
                    }

                    var isJson = ext.Equals(".json", StringComparison.OrdinalIgnoreCase);
                    var existingIsJson = existing.Ext.Equals(".json", StringComparison.OrdinalIgnoreCase);
                    if (isJson && !existingIsJson)
                    {
                        canonicalFiles[name] = (file, ext);
                        continue;
                    }
                    if (isJson == existingIsJson)
                    {
                        canonicalFiles[name] = (file, ext);
                    }
                }

                anyLoaded = true;
            }

            foreach (var file in canonicalFiles.Values.OrderBy(v => v.Path, StringComparer.OrdinalIgnoreCase))
            {
                if (file.Ext.Equals(".json", StringComparison.OrdinalIgnoreCase))
                {
                    LoadJsonWildcard(file.Path);
                }
                else
                {
                    LoadTextWildcard(file.Path);
                }
            }

            if (!anyLoaded)
            {
                if (_settingsService.Settings.Verbose) Console.WriteLine("WildcardService: No wildcard directories were found; using empty wildcard set.");
            }
            else
            {
                if (_settingsService.Settings.Verbose) Console.WriteLine($"WildcardService: Loaded {_wildcards.Count} wildcards.");
            }
            if (_settingsService.Settings.Verbose) Console.WriteLine("WildcardService: LoadWildcards finished.");
        }

        private void LoadJsonWildcard(string filePath)
        {
            try
            {
                var jsonString = File.ReadAllText(filePath);
                var name = Path.GetFileNameWithoutExtension(filePath);
                var structured = ParseStructuredWildcard(name, jsonString, filePath);
                if (structured.Choices.Count == 0)
                {
                    if (_settingsService.Settings.Verbose) Console.WriteLine($"No usable values found in JSON wildcard {filePath}; skipping.");
                    return;
                }

                _structuredWildcards[name] = structured;
                _wildcards[name] = new WildcardDefinition(name, filePath, WildcardSourceType.Json,
                    structured.Choices.Select(c => c.Value).ToList());
                InvalidateDependencyMap();
            }
            catch (Exception ex)
            {
                if (_settingsService.Settings.Verbose) Console.WriteLine($"Error loading JSON wildcard {filePath}: {ex.Message}");
            }
        }

        private static List<string> ParseWildcardValues(string json)
        {
            try
            {
                // Accept either a raw array or an object with a "choices" array.
                using var doc = JsonDocument.Parse(json, new JsonDocumentOptions
                {
                    AllowTrailingCommas = true
                });

                JsonElement targetArray;
                if (doc.RootElement.ValueKind == JsonValueKind.Array)
                {
                    targetArray = doc.RootElement;
                }
                else if (doc.RootElement.ValueKind == JsonValueKind.Object &&
                         doc.RootElement.TryGetProperty("choices", out var choicesProp) &&
                         choicesProp.ValueKind == JsonValueKind.Array)
                {
                    targetArray = choicesProp;
                }
                else
                {
                    return new List<string>();
                }

                var results = new List<string>();
                foreach (var item in targetArray.EnumerateArray())
                {
                    switch (item.ValueKind)
                    {
                        case JsonValueKind.String:
                            var s = item.GetString();
                            if (!string.IsNullOrWhiteSpace(s))
                            {
                                results.Add(s.Trim());
                            }
                            break;
                        case JsonValueKind.Object:
                            if (item.TryGetProperty("value", out var valueProp) && valueProp.ValueKind == JsonValueKind.String)
                            {
                                var v = valueProp.GetString();
                                if (!string.IsNullOrWhiteSpace(v))
                                {
                                    results.Add(v.Trim());
                                }
                            }
                            else if (item.TryGetProperty("choice", out var choiceProp) && choiceProp.ValueKind == JsonValueKind.String)
                            {
                                var v = choiceProp.GetString();
                                if (!string.IsNullOrWhiteSpace(v))
                                {
                                    results.Add(v.Trim());
                                }
                            }
                            break;
                    }
                }

                return results;
            }
            catch
            {
                return new List<string>();
            }
        }

        private void LoadTextWildcard(string filePath)
        {
            try
            {
                var values = File.ReadAllLines(filePath)
                               .Where(line => !string.IsNullOrWhiteSpace(line))
                               .ToList();
                var name = Path.GetFileNameWithoutExtension(filePath);
                _wildcards[name] = new WildcardDefinition(name, filePath, WildcardSourceType.PlainText, values);
                _structuredWildcards[name] = new StructuredWildcard
                {
                    Name = name,
                    Choices = values.Select(v => new WildcardChoice { Value = v }).ToList()
                };
                InvalidateDependencyMap();
            }
            catch (Exception ex)
            {
                if (_settingsService.Settings.Verbose) Console.WriteLine($"Error loading TXT wildcard {filePath}: {ex.Message}");
            }
        }

        public string GetRandomValue(string wildcardName)
        {
            if (_structuredWildcards.TryGetValue(wildcardName, out var structured) && structured.Choices.Count > 0)
            {
                var choice = PickWeightedChoice(structured.Choices);
                if (choice != null)
                {
                    return choice.Value;
                }
            }

            if (_wildcards.TryGetValue(wildcardName, out var definition))
            {
                return definition.GetRandomValue();
            }
            return $"__{wildcardName}__"; // Return original format if not found
        }

        public List<string> GetAllValues(string wildcardName)
        {
            if (_structuredWildcards.TryGetValue(wildcardName, out var structured) && structured.Choices.Count > 0)
            {
                return structured.Choices.Select(c => c.Value).ToList();
            }
            if (_wildcards.TryGetValue(wildcardName, out var definition))
            {
                return definition.Values;
            }
            return new List<string>();
        }

        public string GetWildcardFileContent(string wildcardName)
        {
            if (_wildcards.TryGetValue(wildcardName, out var definition))
            {
                try
                {
                    return File.ReadAllText(definition.FilePath);
                }
                catch (Exception ex)
                {
                    if (_settingsService.Settings.Verbose) Console.WriteLine($"Error reading wildcard file content for {wildcardName}: {ex.Message}");
                    return $"Error reading file: {ex.Message}";
                }
            }
            return $"Wildcard '{wildcardName}' not found.";
        }

        public bool WildcardExists(string wildcardName)
        {
            return _wildcards.ContainsKey(wildcardName);
        }

        public async Task<IEnumerable<WildcardFileEntry>> GetAllWildcardFileEntries()
        {
            return await GetWildcardFileEntries(includeArchived: false);
        }

        public async Task<IEnumerable<WildcardFileEntry>> GetWildcardFileEntries(bool includeArchived)
        {
            var entries = new List<WildcardFileEntry>();
            var candidates = EnumerateWildcardFiles(includeArchived)
                .OrderBy(f => f.Name, StringComparer.OrdinalIgnoreCase)
                .ToList();

            foreach (var candidate in candidates)
            {
                try
                {
                    var content = await File.ReadAllTextAsync(candidate.Path);
                    entries.Add(new WildcardFileEntry(candidate.Name, candidate.Path, content, candidate.IsArchived));
                }
                catch (Exception ex)
                {
                    if (_settingsService.Settings.Verbose) Console.WriteLine($"Error reading content for wildcard file {candidate.Path}: {ex.Message}");
                    entries.Add(new WildcardFileEntry(candidate.Name, candidate.Path, $"Error reading file: {ex.Message}", candidate.IsArchived));
                }
            }

            return entries;
        }

        public async Task SaveWildcardFileContent(string wildcardName, string content)
        {
            if (_wildcards.TryGetValue(wildcardName, out var definition))
            {
                try
                {
                    if (definition.SourceType == WildcardSourceType.PlainText)
                    {
                        var conversion = await ConvertLegacyTextWildcardAsync(definition.FilePath);
                        if ((conversion.Converted || conversion.SkippedBecauseJsonExists) && conversion.JsonPath != null)
                        {
                            definition = new WildcardDefinition(wildcardName, conversion.JsonPath, WildcardSourceType.Json);
                        }
                    }

                    var targetPath = definition.FilePath;
                    if (!targetPath.EndsWith(".json", StringComparison.OrdinalIgnoreCase))
                    {
                        var dir = Path.GetDirectoryName(targetPath) ?? Directory.GetCurrentDirectory();
                        targetPath = Path.Combine(dir, $"{wildcardName}.json");
                    }

                    await File.WriteAllTextAsync(targetPath, content);
                    // After saving, reload the specific wildcard to update its values in memory
                    if (definition.SourceType == WildcardSourceType.Json)
                    {
                        LoadJsonWildcard(targetPath);
                    }
                    else if (definition.SourceType == WildcardSourceType.PlainText)
                    {
                        LoadTextWildcard(definition.FilePath);
                    }
                    InvalidateDependencyMap();
                }
                catch (Exception ex)
                {
                    if (_settingsService.Settings.Verbose) Console.WriteLine($"Error saving wildcard file content for {wildcardName}: {ex.Message}");
                    throw; // Re-throw to inform the caller
                }
            }
            else
            {
                // If the wildcard doesn't exist, create a new file based on the name.
                // Assuming JSON type for new files for now, or could determine from content.
                // For simplicity, let's assume it's always creating a JSON file.
                // This might need more sophisticated handling based on user intent (e.g., text vs json)
                var targetRoot = _wildcardsDirectories.FirstOrDefault() ?? Directory.GetCurrentDirectory();
                var newFilePath = Path.Combine(targetRoot, $"{wildcardName}.json"); // Default to JSON
                try
                {
                    await File.WriteAllTextAsync(newFilePath, content);
                    LoadJsonWildcard(newFilePath); // Load the newly created wildcard
                }
                catch (Exception ex)
                {
                    if (_settingsService.Settings.Verbose) Console.WriteLine($"Error creating new wildcard file {newFilePath}: {ex.Message}");
                    throw;
                }
            }
        }

        public async Task DeleteWildcardFile(string wildcardName)
        {
            if (_wildcards.TryGetValue(wildcardName, out var definition))
            {
                try
                {
                    await Task.Run(() => File.Delete(definition.FilePath)); // Use Task.Run for synchronous File.Delete
                    _wildcards.Remove(wildcardName); // Remove from in-memory cache
                    _structuredWildcards.Remove(wildcardName);
                    InvalidateDependencyMap();
                }
                catch (Exception ex)
                {
                    if (_settingsService.Settings.Verbose) Console.WriteLine($"Error deleting wildcard file for {wildcardName}: {ex.Message}");
                    throw; // Re-throw to inform the caller
                }
            }
            else
            {
                throw new ArgumentException($"Wildcard '{wildcardName}' not found for deletion.");
            }
        }

        public async Task DeleteWildcardFileByPath(string filePath)
        {
            if (string.IsNullOrWhiteSpace(filePath) || !File.Exists(filePath))
            {
                throw new FileNotFoundException("Wildcard file not found.", filePath);
            }

            var name = Path.GetFileNameWithoutExtension(filePath);
            try
            {
                await Task.Run(() => File.Delete(filePath));
                _wildcards.Remove(name);
                _structuredWildcards.Remove(name);
                InvalidateDependencyMap();
            }
            catch (Exception ex)
            {
                if (_settingsService.Settings.Verbose) Console.WriteLine($"Error deleting wildcard file {filePath}: {ex.Message}");
                throw;
            }
        }

        public Task RenameWildcardFileAsync(string filePath, string newName)
        {
            if (string.IsNullOrWhiteSpace(filePath) || !File.Exists(filePath))
            {
                throw new FileNotFoundException("Wildcard file not found.", filePath);
            }
            if (string.IsNullOrWhiteSpace(newName))
            {
                throw new ArgumentException("New name is required.", nameof(newName));
            }

            var dir = Path.GetDirectoryName(filePath) ?? Directory.GetCurrentDirectory();
            var ext = Path.GetExtension(filePath);
            var targetPath = Path.Combine(dir, $"{newName}{ext}");
            if (File.Exists(targetPath))
            {
                throw new IOException($"A file named '{newName}{ext}' already exists.");
            }

            File.Move(filePath, targetPath);
            LoadWildcards();
            return Task.CompletedTask;
        }

        public Task ArchiveWildcardFileAsync(string filePath)
        {
            MoveWildcardFileAsync(filePath, "archive");
            return Task.CompletedTask;
        }

        public Task UnarchiveWildcardFileAsync(string filePath)
        {
            var dir = Path.GetDirectoryName(filePath) ?? Directory.GetCurrentDirectory();
            var parent = Directory.GetParent(dir);
            if (parent == null || !dir.EndsWith($"{Path.DirectorySeparatorChar}archive", StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidOperationException("Wildcard is not in an archive folder.");
            }

            var targetPath = Path.Combine(parent.FullName, Path.GetFileName(filePath));
            if (File.Exists(targetPath))
            {
                throw new IOException($"A file named '{Path.GetFileName(filePath)}' already exists in the target folder.");
            }

            File.Move(filePath, targetPath);
            LoadWildcards();
            return Task.CompletedTask;
        }

        private void MoveWildcardFileAsync(string filePath, string targetFolderName)
        {
            if (string.IsNullOrWhiteSpace(filePath) || !File.Exists(filePath))
            {
                throw new FileNotFoundException("Wildcard file not found.", filePath);
            }

            var dir = Path.GetDirectoryName(filePath) ?? Directory.GetCurrentDirectory();
            var targetDir = Path.Combine(dir, targetFolderName);
            Directory.CreateDirectory(targetDir);

            var targetPath = Path.Combine(targetDir, Path.GetFileName(filePath));
            if (File.Exists(targetPath))
            {
                throw new IOException($"A file named '{Path.GetFileName(filePath)}' already exists in '{targetFolderName}'.");
            }

            File.Move(filePath, targetPath);
            LoadWildcards();
        }

        public async Task<LegacyWildcardConversionResult> ConvertLegacyTextWildcardAsync(string txtPath)
        {
            if (string.IsNullOrWhiteSpace(txtPath) || !File.Exists(txtPath))
            {
                return new LegacyWildcardConversionResult(false, false, null, null, "TXT file not found.");
            }

            if (!txtPath.EndsWith(".txt", StringComparison.OrdinalIgnoreCase))
            {
                return new LegacyWildcardConversionResult(false, false, null, null, "File is not a .txt wildcard.");
            }

            var name = Path.GetFileNameWithoutExtension(txtPath);
            var existingJsonPath = FindExistingJsonPath(name);
            if (!string.IsNullOrWhiteSpace(existingJsonPath))
            {
                return new LegacyWildcardConversionResult(false, true, existingJsonPath, null, null);
            }

            var dir = Path.GetDirectoryName(txtPath) ?? Directory.GetCurrentDirectory();
            var jsonPath = Path.Combine(dir, $"{name}.json");
            var backupPath = $"{txtPath}.bak.{DateTime.UtcNow:yyyyMMdd_HHmmss}";

            try
            {
                var lines = await File.ReadAllLinesAsync(txtPath);
                var values = lines
                    .Select(line => line.Trim())
                    .Where(line => !string.IsNullOrWhiteSpace(line))
                    .Where(line => !line.StartsWith("#", StringComparison.Ordinal) && !line.StartsWith("//", StringComparison.Ordinal))
                    .ToList();

                var payload = new
                {
                    description = $"Legacy wildcard imported from {Path.GetFileName(txtPath)}.",
                    choices = values
                };

                File.Move(txtPath, backupPath);
                var json = JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true });
                await File.WriteAllTextAsync(jsonPath, json);

                LoadJsonWildcard(jsonPath);
                InvalidateDependencyMap();
                return new LegacyWildcardConversionResult(true, false, jsonPath, backupPath, null);
            }
            catch (Exception ex)
            {
                try
                {
                    if (File.Exists(backupPath) && !File.Exists(txtPath))
                    {
                        File.Move(backupPath, txtPath);
                    }
                    if (File.Exists(jsonPath))
                    {
                        File.Delete(jsonPath);
                    }
                }
                catch
                {
                    // best-effort rollback
                }

                return new LegacyWildcardConversionResult(false, false, null, null, ex.Message);
            }
        }

        public async Task<LegacyWildcardBatchResult> ConvertAllLegacyTextWildcardsAsync()
        {
            var converted = 0;
            var skipped = 0;
            var failed = 0;
            var errors = new List<string>();

            var candidates = EnumerateWildcardFiles(includeArchived: false)
                .Where(c => c.Path.EndsWith(".txt", StringComparison.OrdinalIgnoreCase))
                .ToList();

            foreach (var candidate in candidates)
            {
                var result = await ConvertLegacyTextWildcardAsync(candidate.Path);
                if (result.Converted) converted++;
                else if (result.SkippedBecauseJsonExists) skipped++;
                else
                {
                    failed++;
                    if (!string.IsNullOrWhiteSpace(result.Error))
                    {
                        errors.Add($"{candidate.Name}: {result.Error}");
                    }
                }
            }

            LoadWildcards();
            return new LegacyWildcardBatchResult(converted, skipped, failed, errors);
        }

        public StructuredWildcard ParseStructuredContent(string name, string content)
        {
            return ParseStructuredWildcard(name, content, name);
        }

        private Dictionary<string, DependencyNode>? _dependencyMap;
        public IReadOnlyDictionary<string, StructuredWildcard> GetStructuredWildcards() => _structuredWildcards;
        public IEnumerable<string> GetWildcardNames() => _structuredWildcards.Keys.OrderBy(k => k, StringComparer.OrdinalIgnoreCase);

        private void InvalidateDependencyMap()
        {
            _dependencyMap = null;
        }

        public IReadOnlyList<DependencyNode> GetDependencies()
        {
            if (_dependencyMap == null)
            {
                BuildDependencyMap();
            }
            return _dependencyMap!.Values
                .OrderBy(n => n.Name, StringComparer.OrdinalIgnoreCase)
                .ToList();
        }

        public IReadOnlyList<string> FindUnusedWildcards()
        {
            if (_dependencyMap == null)
            {
                BuildDependencyMap();
            }

            return _dependencyMap!.Values
                .Where(n => n.RequiredBy.Count == 0)
                .Select(n => n.Name)
                .OrderBy(n => n, StringComparer.OrdinalIgnoreCase)
                .ToList();
        }

        private void BuildDependencyMap()
        {
            _dependencyMap = new Dictionary<string, DependencyNode>(StringComparer.OrdinalIgnoreCase);
            foreach (var kvp in _structuredWildcards)
            {
                var node = GetOrCreate(kvp.Key);
                var wildcard = kvp.Value;
                if (wildcard.Includes != null)
                {
                    foreach (var inc in FlattenIncludes(wildcard.Includes))
                    {
                        var incNode = GetOrCreate(inc);
                        node.Includes.Add(inc);
                        incNode.RequiredBy.Add(kvp.Key);
                    }
                }
                foreach (var choice in wildcard.Choices)
                {
                    if (choice.Includes != null)
                    {
                        foreach (var inc in FlattenIncludes(choice.Includes))
                        {
                            var incNode = GetOrCreate(inc);
                            node.Includes.Add(inc);
                            incNode.RequiredBy.Add(kvp.Key);
                        }
                    }
                }
            }

            DependencyNode GetOrCreate(string name)
            {
                if (!_dependencyMap!.TryGetValue(name, out var n))
                {
                    n = new DependencyNode(name);
                    _dependencyMap[name] = n;
                }
                return n;
            }

            static IEnumerable<string> FlattenIncludes(object includes)
            {
                switch (includes)
                {
                    case string s when !string.IsNullOrWhiteSpace(s):
                        return new[] { s.Trim() };
                    case IEnumerable<string> arr:
                        return arr.Where(x => !string.IsNullOrWhiteSpace(x)).Select(x => x.Trim());
                    default:
                        return Array.Empty<string>();
                }
            }
        }

        private StructuredWildcard ParseStructuredWildcard(string name, string jsonString, string filePath)
        {
            var result = new StructuredWildcard { Name = name };
            try
            {
                using var doc = JsonDocument.Parse(jsonString, new JsonDocumentOptions { AllowTrailingCommas = true });
                var root = doc.RootElement;
                if (root.ValueKind == JsonValueKind.Array)
                {
                    result.Choices = root.EnumerateArray()
                        .Where(e => e.ValueKind == JsonValueKind.String)
                        .Select(e => new WildcardChoice { Value = e.GetString() ?? string.Empty })
                        .Where(c => !string.IsNullOrWhiteSpace(c.Value))
                        .ToList();
                    return result;
                }

                if (root.ValueKind != JsonValueKind.Object)
                {
                    return result;
                }

                if (root.TryGetProperty("description", out var desc) && desc.ValueKind == JsonValueKind.String)
                {
                    result.Description = desc.GetString();
                }
                if (root.TryGetProperty("includes", out var inc))
                {
                    result.Includes = ParseIncludes(inc);
                }
                if (root.TryGetProperty("choices", out var choicesElem) && choicesElem.ValueKind == JsonValueKind.Array)
                {
                    foreach (var choiceElem in choicesElem.EnumerateArray())
                    {
                        if (choiceElem.ValueKind == JsonValueKind.String)
                        {
                            var val = choiceElem.GetString();
                            if (!string.IsNullOrWhiteSpace(val))
                            {
                                result.Choices.Add(new WildcardChoice { Value = val.Trim() });
                            }
                        }
                        else if (choiceElem.ValueKind == JsonValueKind.Object)
                        {
                            if (!choiceElem.TryGetProperty("value", out var valueProp) || valueProp.ValueKind != JsonValueKind.String)
                            {
                                continue;
                            }

                            var choice = new WildcardChoice
                            {
                                Value = valueProp.GetString() ?? string.Empty,
                                Weight = choiceElem.TryGetProperty("weight", out var weightProp) && weightProp.TryGetDouble(out var w) ? w : 1,
                                RequiresJson = choiceElem.TryGetProperty("requires", out var requiresProp) ? requiresProp.GetRawText() : null
                            };

                            if (choiceElem.TryGetProperty("tags", out var tagsProp) && tagsProp.ValueKind == JsonValueKind.Array)
                            {
                                foreach (var t in tagsProp.EnumerateArray())
                                {
                                    if (t.ValueKind == JsonValueKind.String)
                                    {
                                        var tag = t.GetString();
                                        if (!string.IsNullOrWhiteSpace(tag))
                                        {
                                            choice.Tags.Add(tag);
                                        }
                                    }
                                }
                            }

                            if (choiceElem.TryGetProperty("includes", out var choiceIncludes))
                            {
                                choice.Includes = ParseIncludes(choiceIncludes);
                            }

                            if (!string.IsNullOrWhiteSpace(choice.Value))
                            {
                                result.Choices.Add(choice);
                            }
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                if (_settingsService.Settings.Verbose) Console.WriteLine($"Error parsing structured wildcard {filePath}: {ex.Message}");
            }

            return result;
        }

        private static object? ParseIncludes(JsonElement element)
        {
            if (element.ValueKind == JsonValueKind.String)
            {
                var s = element.GetString();
                return string.IsNullOrWhiteSpace(s) ? null : s;
            }

            if (element.ValueKind == JsonValueKind.Array)
            {
                var items = element.EnumerateArray()
                    .Where(e => e.ValueKind == JsonValueKind.String)
                    .Select(e => e.GetString())
                    .Where(s => !string.IsNullOrWhiteSpace(s))
                    .Select(s => s!.Trim())
                    .ToList();
                return items.Count == 0 ? null : items;
            }

            return null;
        }

        private WildcardChoice? PickWeightedChoice(List<WildcardChoice> choices)
        {
            var pool = choices.Where(c => !string.IsNullOrWhiteSpace(c.Value)).ToList();
            if (pool.Count == 0) return null;
            var totalWeight = pool.Sum(c => c.Weight <= 0 ? 1 : c.Weight);
            var roll = _random.NextDouble() * totalWeight;
            var cumulative = 0.0;
            foreach (var choice in pool)
            {
                cumulative += choice.Weight <= 0 ? 1 : choice.Weight;
                if (roll <= cumulative)
                {
                    return choice;
                }
            }

            return pool.Last();
        }

        private IEnumerable<(string Name, string Path, bool IsArchived)> EnumerateWildcardFiles(bool includeArchived)
        {
            var canonical = new Dictionary<string, (string Path, string Ext, bool IsArchived)>(StringComparer.OrdinalIgnoreCase);

            foreach (var dir in _wildcardsDirectories)
            {
                if (!Directory.Exists(dir)) continue;
                foreach (var file in Directory.EnumerateFiles(dir, "*.*", SearchOption.AllDirectories))
                {
                    var ext = Path.GetExtension(file);
                    if (!ext.Equals(".json", StringComparison.OrdinalIgnoreCase) &&
                        !ext.Equals(".txt", StringComparison.OrdinalIgnoreCase))
                    {
                        continue;
                    }

                    var archived = IsArchivedPath(file);
                    if (archived && !includeArchived) continue;

                    var name = Path.GetFileNameWithoutExtension(file);
                    if (!canonical.TryGetValue(name, out var existing))
                    {
                        canonical[name] = (file, ext, archived);
                        continue;
                    }

                    var isJson = ext.Equals(".json", StringComparison.OrdinalIgnoreCase);
                    var existingIsJson = existing.Ext.Equals(".json", StringComparison.OrdinalIgnoreCase);
                    if (!existing.IsArchived && archived)
                    {
                        continue;
                    }
                    if (existing.IsArchived && !archived)
                    {
                        canonical[name] = (file, ext, archived);
                        continue;
                    }
                    if (isJson && !existingIsJson)
                    {
                        canonical[name] = (file, ext, archived);
                        continue;
                    }
                    if (isJson == existingIsJson)
                    {
                        canonical[name] = (file, ext, archived);
                    }
                }
            }

            return canonical.Select(kvp => (kvp.Key, kvp.Value.Path, kvp.Value.IsArchived));
        }

        private static bool IsArchivedPath(string path)
        {
            var parts = path.Split(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            return parts.Any(p => p.Equals("archive", StringComparison.OrdinalIgnoreCase));
        }

        private string? FindExistingJsonPath(string name)
        {
            foreach (var dir in _wildcardsDirectories)
            {
                if (!Directory.Exists(dir)) continue;
                foreach (var file in Directory.EnumerateFiles(dir, $"{name}.json", SearchOption.AllDirectories))
                {
                    if (!IsArchivedPath(file))
                    {
                        return file;
                    }
                }
            }

            return null;
        }
    }
}
