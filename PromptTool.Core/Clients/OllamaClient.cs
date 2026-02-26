using System.Collections.Generic;
using System.Net.Http.Json;
using PromptTool.Core.Services;

namespace PromptTool.Core.Clients;

public class OllamaClient
{
    private readonly HttpClient _http;
    private readonly SettingsService _settingsService;
    private Uri? _base;

    public OllamaClient(HttpClient http, SettingsService settingsService)
    {
        _http = http;
        _settingsService = settingsService;
    }

    public Uri? BaseAddress => _base ?? _http.BaseAddress;

    public void UpdateBaseAddress(Uri baseAddress)
    {
        _base = baseAddress;
        if (_settingsService.Settings.Verbose) Console.WriteLine($"OllamaClient: BaseAddress set to {baseAddress}");
    }

    public virtual async Task<IReadOnlyList<string>> GetModelNamesAsync(CancellationToken ct = default)
        => await GetModelNamesAsync(null, ct);

    public virtual async Task<IReadOnlyList<string>> GetModelNamesAsync(Uri? baseOverride, CancellationToken ct = default)
    {
        var baseUri = baseOverride ?? _base ?? _http.BaseAddress;
        if (baseUri == null) throw new InvalidOperationException("Ollama base address is not configured.");

        using var resp = await _http.GetAsync(new Uri(baseUri, "/api/tags"), ct);
        if (!resp.IsSuccessStatusCode)
        {
            var body = await resp.Content.ReadAsStringAsync(ct);
            throw new HttpRequestException($"GET /api/tags failed with {(int)resp.StatusCode} {resp.ReasonPhrase}. Body: {body}");
        }

        var tags = await resp.Content.ReadFromJsonAsync<TagsResponse>(cancellationToken: ct);
        return tags?.models?
                   .Select(m => m.name)
                   .Where(n => !string.IsNullOrWhiteSpace(n))
                   .Distinct()
                   .OrderBy(n => n)
                   .ToList()
               ?? new List<string>();
    }

    public async Task<IReadOnlyList<string>> GetRunningModelsAsync(CancellationToken ct = default)
    {
        var baseUri = _base ?? _http.BaseAddress;
        if (baseUri == null) throw new InvalidOperationException("Ollama base address is not configured.");

        using var resp = await _http.GetAsync(new Uri(baseUri, "/api/ps"), ct);
        if (!resp.IsSuccessStatusCode)
        {
            var body = await resp.Content.ReadAsStringAsync(ct);
            throw new HttpRequestException($"GET /api/ps failed with {(int)resp.StatusCode} {resp.ReasonPhrase}. Body: {body}");
        }

        var ps = await resp.Content.ReadFromJsonAsync<PsResponse>(cancellationToken: ct);
        return ps?.models?.Select(m => m.name).Where(n => !string.IsNullOrWhiteSpace(n)).ToList() ?? new List<string>();
    }

    public async Task UnloadModelAsync(string model, CancellationToken ct = default)
    {
        var baseUri = _base ?? _http.BaseAddress;
        if (baseUri == null) throw new InvalidOperationException("Ollama base address is not configured.");

        var payload = new { model, prompt = "", keep_alive = 0 };
        using var resp = await _http.PostAsJsonAsync(new Uri(baseUri, "/api/generate"), payload, ct);
        if (!resp.IsSuccessStatusCode)
        {
            var body = await resp.Content.ReadAsStringAsync(ct);
            throw new HttpRequestException($"Unload model {model} failed with {(int)resp.StatusCode} {resp.ReasonPhrase}. Body: {body}");
        }
    }

    public async Task UnloadAllModelsAsync(CancellationToken ct = default)
    {
        IReadOnlyList<string> running;
        try
        {
            running = await GetRunningModelsAsync(ct);
        }
        catch (Exception ex)
        {
            if (_settingsService.Settings.Verbose) Console.WriteLine($"OllamaClient: unable to list running models for unload: {ex.Message}");
            return;
        }

        foreach (var model in running)
        {
            try
            {
                await UnloadModelAsync(model, ct);
                if (_settingsService.Settings.Verbose) Console.WriteLine($"OllamaClient: unloaded model '{model}'.");
            }
            catch (Exception ex)
            {
                if (_settingsService.Settings.Verbose) Console.WriteLine($"OllamaClient: failed to unload model '{model}': {ex.Message}");
            }
        }
    }

    public virtual async Task<string> GenerateAsync(string model, string prompt, CancellationToken ct = default, double? temperature = null, double? topP = null)
    {
        var baseUri = _base ?? _http.BaseAddress;
        if (baseUri == null) throw new InvalidOperationException("Ollama base address is not configured.");

        var req = new Dictionary<string, object>
        {
            ["model"] = model,
            ["prompt"] = prompt,
            ["stream"] = false
        };

        if (temperature.HasValue || topP.HasValue)
        {
            var options = new Dictionary<string, object>();
            if (temperature.HasValue) options["temperature"] = temperature.Value;
            if (topP.HasValue) options["top_p"] = topP.Value;
            if (options.Count > 0)
            {
                req["options"] = options;
            }
        }

        using var resp = await _http.PostAsJsonAsync(new Uri(baseUri, "/api/generate"), req, ct);
        resp.EnsureSuccessStatusCode();

        var json = await resp.Content.ReadFromJsonAsync<GenerateResponse>(cancellationToken: ct);
        return json?.response ?? "";
    }

    private sealed class GenerateResponse
    {
        public string? response { get; set; }
    }

    private sealed class TagsResponse
    {
        public List<TagModel> models { get; set; } = new();
    }

    private sealed class PsResponse
    {
        public List<TagModel> models { get; set; } = new();
    }

    private sealed class TagModel
    {
        public string name { get; set; } = "";
    }

}
