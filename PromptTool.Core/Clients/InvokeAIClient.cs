using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;
using System.Net.Http;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading;
using System.Threading.Tasks;
using PromptTool.Core.Clients.InvokeAI;
using PromptTool.Core.Models;
using PromptTool.Core.Services;

namespace PromptTool.Core.Clients;

public class InvokeAIClient
{
    private readonly HttpClient _http;
    private readonly SettingsService _settingsService;
    private string? _modelsEndpoint;
    private string _baseModelParamName = "base_models";
    private readonly SemaphoreSlim _initLock = new(1, 1);
    private List<string>? _schedulersCache;
    private readonly ConcurrentDictionary<string, object> _modelsCache = new();

        public InvokeAIClient(HttpClient httpClient, SettingsService settingsService)
        {
            _http = httpClient;
            _settingsService = settingsService;
        }


    public void UpdateBaseAddress(Uri baseAddress)
    {
        _http.BaseAddress = baseAddress;
    }

    public void ClearCache()
    {
        if (_settingsService.Settings.Verbose) Console.WriteLine("--- Clearing InvokeAIClient cache ---");
        _modelsCache.Clear();
        _schedulersCache = null;
    }

    public async Task<bool> EmptyModelCacheAsync(CancellationToken ct = default)
    {
        if (string.IsNullOrWhiteSpace(_modelsEndpoint))
        {
            var ok = await CheckServerCompatibilityAsync(ct);
            if (!ok || string.IsNullOrWhiteSpace(_modelsEndpoint))
            {
                return false;
            }
        }

        try
        {
            using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
            cts.CancelAfter(TimeSpan.FromSeconds(10));
            var resp = await _http.PostAsync($"{_modelsEndpoint}empty_model_cache", content: null, cts.Token);
            resp.EnsureSuccessStatusCode();
            return true;
        }
        catch
        {
            return false;
        }
    }

    public async Task<bool> CheckServerCompatibilityAsync(CancellationToken ct = default)
    {
        await _initLock.WaitAsync(ct);
        try
        {
            if (!string.IsNullOrWhiteSpace(_modelsEndpoint))
            {
                return true;
            }

            var versionResponse = await _http.GetAsync("/api/v1/app/version", ct);
            versionResponse.EnsureSuccessStatusCode();

            var endpointsToTry = new[] { "/api/v2/models/", "/api/v1/models/" };
            var paramNames = new[] { "base_models", "base_model" };

            foreach (var endpoint in endpointsToTry)
            {
                foreach (var paramName in paramNames)
                {
                    try
                    {
                        var url = $"{endpoint}?{paramName}=sdxl";
                        var resp = await _http.GetAsync(url, ct);

                        if (resp.IsSuccessStatusCode)
                        {
                            _modelsEndpoint = endpoint;
                            _baseModelParamName = paramName;
                            return true;
                        }
                    }
                    catch
                    {
                        // try next combination
                    }
                }
            }
            return false;
        }
        catch
        {
            return false;
        }
        finally
        {
            _initLock.Release();
        }
    }

    public async Task<IReadOnlyList<InvokeAIModel>> GetModelsAsync(string? baseModel = null, string? modelType = null, CancellationToken ct = default)
    {
        var cacheKey = $"{modelType ?? "any"}_{baseModel ?? "any"}";
        if (_modelsCache.TryGetValue(cacheKey, out var cachedModels) && cachedModels is IReadOnlyList<InvokeAIModel> models)
        {
            return models;
        }

        if (string.IsNullOrWhiteSpace(_modelsEndpoint))
        {
            var ok = await CheckServerCompatibilityAsync(ct);
            if (!ok || string.IsNullOrWhiteSpace(_modelsEndpoint))
            {
                return Array.Empty<InvokeAIModel>();
            }
        }

        var query = new Dictionary<string, string>();
        if (!string.IsNullOrEmpty(baseModel))
        {
            query[_baseModelParamName] = baseModel == "sd-1.5" ? "sd-1" : baseModel;
        }
        if (!string.IsNullOrEmpty(modelType))
        {
            query["model_type"] = modelType;
        }

        var queryString = string.Join("&", query.Select(kvp => $"{kvp.Key}={Uri.EscapeDataString(kvp.Value)}"));
        var url = $"{_modelsEndpoint}?{queryString}";

        try
        {
            var response = await _http.GetAsync(url, ct);
            response.EnsureSuccessStatusCode();

            var json = await response.Content.ReadFromJsonAsync<JsonNode>(cancellationToken: ct);
            JsonNode? modelsNode;
            if (json is JsonObject jsonObj && jsonObj.ContainsKey("models"))
            {
                modelsNode = jsonObj["models"];
            }
            else
            {
                modelsNode = json;
            }
            
            var result = modelsNode?.Deserialize<List<InvokeAIModel>>() ?? new List<InvokeAIModel>();

            // Ensure Type and Key are populated, mirroring Python's logic
            result = result.Select(m =>
            {
                var currentModel = m;
                if (!string.IsNullOrEmpty(modelType) && string.IsNullOrEmpty(currentModel.Type))
                {
                    currentModel = currentModel with { Type = modelType };
                }
                if (string.IsNullOrEmpty(currentModel.Key) && !string.IsNullOrEmpty(currentModel.Name))
                {
                    currentModel = currentModel with { Key = currentModel.Name };
                }
                return currentModel;
            }).ToList();

            _modelsCache.TryAdd(cacheKey, result);
            return result;
        }
        catch
        {
            return Array.Empty<InvokeAIModel>();
        }
    }


    public async Task<IReadOnlyList<string>> GetSchedulersAsync(CancellationToken ct = default)
    {
        if (_schedulersCache != null)
        {
            return _schedulersCache;
        }

        try
        {
            var response = await _http.GetAsync("/api/v1/schemas/scheduler", ct);
            if (response.IsSuccessStatusCode)
            {
                var schemaData = await response.Content.ReadFromJsonAsync<JsonNode>(cancellationToken: ct);
                var schedulers = ExtractSchedulerOptions(schemaData);
                if (schedulers.Count > 0)
                {
                    _schedulersCache = schedulers.OrderBy(s => s).ToList();
                    return _schedulersCache;
                }
            }
        }
        catch { /* Fallback */ }
        
        // Align with InvokeAI queue API accepted values.
        var fallbackSchedulers = new List<string>
        {
            "ddim", "ddpm", "deis", "deis_k", "lms", "lms_k", "pndm", "heun", "heun_k",
            "euler", "euler_k", "euler_a", "kdpm_2", "kdpm_2_k", "kdpm_2_a", "kdpm_2_a_k",
            "dpmpp_2s", "dpmpp_2s_k", "dpmpp_2m", "dpmpp_2m_k", "dpmpp_2m_sde", "dpmpp_2m_sde_k",
            "dpmpp_3m", "dpmpp_3m_k", "dpmpp_sde", "dpmpp_sde_k", "unipc", "unipc_k", "lcm", "tcd"
        };
        _schedulersCache = fallbackSchedulers.OrderBy(s => s).ToList();
        return _schedulersCache;
    }

    private static List<string> ExtractSchedulerOptions(JsonNode? node)
    {
        var results = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        void AddValue(JsonNode? value)
        {
            if (value is JsonValue jsonValue && jsonValue.TryGetValue<string>(out var str) && !string.IsNullOrWhiteSpace(str))
            {
                results.Add(str);
            }
        }

        void Walk(JsonNode? current)
        {
            if (current == null)
            {
                return;
            }

            if (current is JsonObject obj)
            {
                if (obj.TryGetPropertyValue("enum", out var enumNode) && enumNode is JsonArray enumArray)
                {
                    foreach (var item in enumArray)
                    {
                        AddValue(item);
                    }
                }

                if (obj.TryGetPropertyValue("const", out var constNode))
                {
                    AddValue(constNode);
                }

                if (obj.TryGetPropertyValue("anyOf", out var anyOfNode) && anyOfNode is JsonArray anyOfArray)
                {
                    foreach (var item in anyOfArray)
                    {
                        Walk(item);
                    }
                }

                if (obj.TryGetPropertyValue("oneOf", out var oneOfNode) && oneOfNode is JsonArray oneOfArray)
                {
                    foreach (var item in oneOfArray)
                    {
                        Walk(item);
                    }
                }

                if (obj.TryGetPropertyValue("items", out var itemsNode))
                {
                    Walk(itemsNode);
                }
            }
            else if (current is JsonArray array)
            {
                foreach (var item in array)
                {
                    Walk(item);
                }
            }
        }

        Walk(node);
        return results.OrderBy(s => s).ToList();
    }

    /// <summary>
    /// Lightweight reachability check for InvokeAI.
    /// </summary>
    public async Task<bool> IsReachableAsync(CancellationToken ct = default)
    {
        try
        {
            using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
            cts.CancelAfter(TimeSpan.FromSeconds(12));
            var resp = await _http.GetAsync("/api/v1/app/version", cts.Token);
            return resp.IsSuccessStatusCode;
        }
        catch
        {
            return false;
        }
    }
    
    public async Task<InvokeAIGenerationResult> GenerateImageAsync(InvokeAIGenerationParams parameters, CancellationToken ct = default)    {
        if (parameters.Model == null)
        {
            throw new ArgumentNullException(nameof(parameters.Model), "A model must be selected for generation.");
        }
        
        var vaes = await GetModelsAsync(modelType: "vae", ct: ct);

        InvokeAIGraph graph;
        InvokeAIModel? vaeUsed;
        if (parameters.Model.Base == "sdxl")
        {
            (graph, vaeUsed) = GraphBuilder.BuildSdxlGraph(parameters, vaes);
        }
        else // Covers "sd-1.5" and "sd-1"
        {
            (graph, vaeUsed) = GraphBuilder.BuildSd15Graph(parameters, vaes);
        }
        
        var queueItem = await EnqueueBatchAsync(graph, ct);
        var itemId = queueItem["item_ids"]![0]!.GetValue<int>();

        var (imageBytes, imageName, jobInfo) = await WaitForResultWithCancellationCleanupAsync(itemId, parameters.SaveToGallery, ct);

        return new InvokeAIGenerationResult
        {
            ItemId = itemId,
            ImageBytes = imageBytes,
            ImageName = imageName,
            GenerationParams = new GenerationParams
            {
                Scheduler = parameters.Scheduler,
                Vae = vaeUsed
            },
            JobInfo = jobInfo
        };
    }

    public async Task<InvokeAIGenerationResult> GenerateImageFromGraphJsonAsync(JsonObject graph, bool saveToGallery, CancellationToken ct = default)
    {
        if (graph == null) throw new ArgumentNullException(nameof(graph));

        var queueItem = await EnqueueBatchJsonAsync(graph, ct);
        var itemId = queueItem["item_ids"]![0]!.GetValue<int>();

        var (imageBytes, imageName, jobInfo) = await WaitForResultWithCancellationCleanupAsync(itemId, saveToGallery, ct);

        return new InvokeAIGenerationResult
        {
            ItemId = itemId,
            ImageBytes = imageBytes,
            ImageName = imageName,
            JobInfo = jobInfo
        };
    }

    public async Task<InvokeAIGenerationResult> UpscaleImageAsync(
        byte[] imageBytes,
        string fileName,
        InvokeAIModel upscalerModel,
        double scale,
        int tileSize,
        bool fitToMultipleOf8,
        bool saveToGallery = false,
        CancellationToken ct = default)
    {
        var uploadedName = await UploadImageAsync(imageBytes, fileName, isIntermediate: !saveToGallery, ct);

        var graph = new InvokeAIGraph
        {
            Nodes = new Dictionary<string, IInvokeAINode>
            {
                ["spandrel_upscale"] = new SpandrelImageToImageAutoscaleNode
                {
                    Id = "spandrel_upscale",
                    Image = new InvokeAIImageField { ImageName = uploadedName },
                    ImageToImageModel = upscalerModel,
                    TileSize = tileSize,
                    Scale = scale,
                    FitToMultipleOf8 = fitToMultipleOf8
                },
                ["save_image"] = new SaveImageNode
                {
                    Id = "save_image",
                    IsIntermediate = !saveToGallery
                }
            },
            Edges = new List<InvokeAIEdge>
            {
                new()
                {
                    Source = new EdgePoint { NodeId = "spandrel_upscale", Field = "image" },
                    Destination = new EdgePoint { NodeId = "save_image", Field = "image" }
                }
            }
        };

        var queueItem = await EnqueueBatchAsync(graph, ct);
        var itemId = queueItem["item_ids"]![0]!.GetValue<int>();

        var (resultBytes, imageName, jobInfo) = await WaitForResultWithCancellationCleanupAsync(itemId, saveToGallery, ct);
        if (!saveToGallery)
        {
            await DeleteImageAsync(uploadedName, CancellationToken.None);
        }
        return new InvokeAIGenerationResult
        {
            ItemId = itemId,
            ImageBytes = resultBytes,
            ImageName = imageName,
            JobInfo = jobInfo
        };
    }

    private async Task<JsonObject> EnqueueBatchAsync(InvokeAIGraph graph, CancellationToken ct)    {
        var batch = new
        {
            batch = new
            {
                graph,
                runs = 1
            }
        };

                    if (_settingsService.Settings.Verbose)        {
            var jsonOptions = new JsonSerializerOptions { WriteIndented = true };
            Console.WriteLine("--- VERBOSE: InvokeAI Generation Graph ---");
            Console.WriteLine(JsonSerializer.Serialize(batch, jsonOptions));
            Console.WriteLine("------------------------------------------");
        }

        HttpResponseMessage response;
        try
        {
            response = await _http.PostAsJsonAsync("/api/v1/queue/default/enqueue_batch", batch, ct);
        }
        catch (HttpRequestException ex)
        {
            throw new HttpRequestException("Failed to enqueue batch.", ex);
        }
        
        if (response.StatusCode == System.Net.HttpStatusCode.UnprocessableEntity)
        {
            var errorContent = await response.Content.ReadAsStringAsync(ct);
            if (_settingsService.Settings.Verbose) Console.WriteLine($"--- InvokeAI 422 Error ---\n{errorContent}\n--------------------------");
            throw new HttpRequestException($"Failed to enqueue batch. Server returned 422 Unprocessable Entity. Details: {errorContent}");
        }
        
        response.EnsureSuccessStatusCode();
        
        return await response.Content.ReadFromJsonAsync<JsonObject>(cancellationToken: ct) ?? new JsonObject();
    }

    private async Task<JsonObject> EnqueueBatchJsonAsync(JsonObject graph, CancellationToken ct)
    {
        var batch = new JsonObject
        {
            ["batch"] = new JsonObject
            {
                ["graph"] = graph,
                ["runs"] = 1
            }
        };

        if (_settingsService.Settings.Verbose)
        {
            var jsonOptions = new JsonSerializerOptions { WriteIndented = true };
            Console.WriteLine("--- VERBOSE: InvokeAI Generation Graph (JSON) ---");
            Console.WriteLine(batch.ToJsonString(jsonOptions));
            Console.WriteLine("-------------------------------------------------");
        }

        HttpResponseMessage response;
        try
        {
            response = await _http.PostAsJsonAsync("/api/v1/queue/default/enqueue_batch", batch, ct);
        }
        catch (HttpRequestException ex)
        {
            throw new HttpRequestException("Failed to enqueue batch.", ex);
        }

        if (response.StatusCode == System.Net.HttpStatusCode.UnprocessableEntity)
        {
            var errorContent = await response.Content.ReadAsStringAsync(ct);
            if (_settingsService.Settings.Verbose) Console.WriteLine($"--- InvokeAI 422 Error ---\n{errorContent}\n--------------------------");
            throw new HttpRequestException($"Failed to enqueue batch. Server returned 422 Unprocessable Entity. Details: {errorContent}");
        }

        response.EnsureSuccessStatusCode();
        return await response.Content.ReadFromJsonAsync<JsonObject>(cancellationToken: ct) ?? new JsonObject();
    }
    
    private async Task<(byte[] imageBytes, string imageName, GenerationJobInfo jobInfo)> WaitForResultAsync(int itemId, bool saveToGallery, CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            var response = await _http.GetAsync($"/api/v1/queue/default/i/{itemId}", ct);
            response.EnsureSuccessStatusCode();
            var statusData = await response.Content.ReadFromJsonAsync<JsonObject>(cancellationToken: ct);
            var jobInfo = BuildJobInfo(statusData);

            switch (statusData?["status"]?.GetValue<string>())
            {
                case "completed":
                    var imageNames = ExtractImageNames(statusData);
                    if (imageNames.Count == 0)
                    {
                        throw new InvalidOperationException("Could not parse image name from completed job.");
                    }

                    byte[]? imageBytes = null;
                    string? resolvedName = null;
                    foreach (var name in imageNames)
                    {
                        try
                        {
                            var imageResponse = await _http.GetAsync($"/api/v1/images/i/{name}/full", ct);
                            imageResponse.EnsureSuccessStatusCode();
                            imageBytes = await imageResponse.Content.ReadAsByteArrayAsync(ct);
                            resolvedName = name;
                            break;
                        }
                        catch
                        {
                            // try next image
                        }
                    }

                    if (imageBytes == null || string.IsNullOrWhiteSpace(resolvedName))
                    {
                        throw new InvalidOperationException("Failed to fetch any images from completed job.");
                    }

                    if (!saveToGallery)
                    {
                        // Delete all images produced by this job to mirror Python behavior.
                        foreach (var name in imageNames)
                        {
                            await DeleteImageAsync(name, CancellationToken.None);
                        }
                    }

                    return (imageBytes, resolvedName, jobInfo);

                case "failed":
                case "canceled":
                    if (_settingsService.Settings.Verbose) Console.WriteLine($"--- InvokeAI Job Failed/Canceled ---\n{JsonSerializer.Serialize(statusData, new JsonSerializerOptions { WriteIndented = true })}\n------------------------------------");
                    string errorMsg = "Unknown error.";
                    try
                    {
                        if (statusData.TryGetPropertyValue("session", out var sessionNode) && sessionNode is JsonObject sessionObj)
                        {
                            if (sessionObj.TryGetPropertyValue("results", out var resultsNode) && resultsNode is JsonObject resultsObj)
                            {
                                foreach (var property in resultsObj.AsObject()) // Corrected: Iterate over properties of JsonObject
                                {
                                    if (property.Value is JsonObject nodeOutputObj && 
                                        nodeOutputObj.TryGetPropertyValue("type", out var typeNode) && 
                                        typeNode?.GetValue<string>() == "execution_error" &&
                                        nodeOutputObj.TryGetPropertyValue("error", out var errorNode))
                                    {
                                        errorMsg = errorNode?.GetValue<string>() ?? errorMsg;
                                        break;
                                    }
                                }
                            }
                        }
                    }
                    catch (Exception)
                    {
                        // Fallback to original error message
                    }
                    throw new InvokeAIJobFailedException($"Image generation failed or was canceled: {errorMsg}", jobInfo);

                default:
                    await Task.Delay(1000, ct);
                    break;
            }
        }

        await CancelAndCleanupItemAsync(itemId, saveToGallery, CancellationToken.None);
        throw new TaskCanceledException("Image generation was canceled by the user.");
    }

    private async Task<(byte[] imageBytes, string imageName, GenerationJobInfo jobInfo)> WaitForResultWithCancellationCleanupAsync(
        int itemId,
        bool saveToGallery,
        CancellationToken ct)
    {
        try
        {
            return await WaitForResultAsync(itemId, saveToGallery, ct);
        }
        catch (OperationCanceledException) when (ct.IsCancellationRequested)
        {
            await CancelAndCleanupItemAsync(itemId, saveToGallery, CancellationToken.None);
            throw;
        }
    }

    private static GenerationJobInfo BuildJobInfo(JsonObject? statusData)
    {
        if (statusData == null)
        {
            return new GenerationJobInfo();
        }

        var status = statusData["status"]?.GetValue<string>() ?? string.Empty;
        var errorType = statusData["error_type"]?.GetValue<string>();
        var errorMessage = statusData["error_message"]?.GetValue<string>();
        var errorTraceback = statusData["error_traceback"]?.GetValue<string>();

        var created = TryParseDateTimeOffset(statusData["created_at"]);
        var started = TryParseDateTimeOffset(statusData["started_at"]);
        var completed = TryParseDateTimeOffset(statusData["completed_at"]);

        int? queueWaitMs = null;
        int? totalMs = null;
        int? durationMs = null;

        if (created.HasValue && started.HasValue)
        {
            queueWaitMs = (int)Math.Round((started.Value - created.Value).TotalMilliseconds);
        }

        if (created.HasValue && completed.HasValue)
        {
            totalMs = (int)Math.Round((completed.Value - created.Value).TotalMilliseconds);
        }

        if (statusData["duration"] is JsonValue durationVal)
        {
            if (durationVal.TryGetValue(out double durationSeconds))
            {
                durationMs = (int)Math.Round(durationSeconds * 1000.0);
            }
            else if (durationVal.TryGetValue(out float durationFloat))
            {
                durationMs = (int)Math.Round(durationFloat * 1000.0);
            }
        }

        if (!durationMs.HasValue && started.HasValue && completed.HasValue)
        {
            durationMs = (int)Math.Round((completed.Value - started.Value).TotalMilliseconds);
        }

        return new GenerationJobInfo
        {
            Status = status,
            ErrorType = errorType,
            ErrorMessage = errorMessage,
            ErrorTraceback = errorTraceback,
            GenerationDurationMs = durationMs,
            QueueWaitMs = queueWaitMs,
            TotalDurationMs = totalMs
        };
    }

    private static DateTimeOffset? TryParseDateTimeOffset(JsonNode? node)
    {
        if (node is not JsonValue value) return null;
        if (!value.TryGetValue(out string? raw) || string.IsNullOrWhiteSpace(raw)) return null;
        return DateTimeOffset.TryParse(raw, out var dt) ? dt : null;
    }
    
    public async Task CancelAndCleanupItemAsync(int itemId, bool saveToGallery, CancellationToken ct)
    {
        try
        {
            await _http.PutAsync($"/api/v1/queue/default/i/{itemId}/cancel", null, ct);
            
            // Poll for final status to get image names for cleanup
            if (!saveToGallery)
            {
                // Simplified cleanup: does not poll for result, just assumes cancellation worked.
                // For a full implementation, one would poll for the final "canceled" state
                // to get any created image names and then delete them.
            }
        }
        catch (HttpRequestException)
        {
            // Ignore errors on cancellation
        }
    }

    private async Task<string> UploadImageAsync(byte[] imageBytes, string fileName, bool isIntermediate, CancellationToken ct)
    {
        using var content = new MultipartFormDataContent();
        var imageContent = new ByteArrayContent(imageBytes);
        imageContent.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue("image/png");
        content.Add(imageContent, "file", fileName);

        var url = $"/api/v1/images/upload?image_category=general&is_intermediate={isIntermediate.ToString().ToLowerInvariant()}";
        var resp = await _http.PostAsync(url, content, ct);
        resp.EnsureSuccessStatusCode();

        var json = await resp.Content.ReadFromJsonAsync<JsonObject>(cancellationToken: ct);
        var name = json?["image_name"]?.GetValue<string>();
        if (string.IsNullOrWhiteSpace(name))
        {
            throw new InvalidOperationException("InvokeAI upload did not return an image name.");
        }
        return name!;
    }

    private async Task DeleteImageAsync(string imageName, CancellationToken ct)
    {
        try
        {
            await _http.DeleteAsync($"/api/v1/images/i/{imageName}", ct);
        }
        catch (HttpRequestException)
        {
            // Log deletion error
        }
    }

    private static List<string> ExtractImageNames(JsonObject? statusJson)
    {
        var names = new List<string>();
        if (statusJson?["session"] is not JsonObject sessionObj) return names;

        var resultsNode = sessionObj["results"];

        void ProcessNode(JsonObject? node)
        {
            if (node is null) return;
            var imagesNode = node["images"] ?? node["image"];

            if (imagesNode is JsonObject singleObj)
            {
                var name = singleObj["image_name"]?.GetValue<string>()
                           ?? singleObj["name"]?.GetValue<string>();
                if (!string.IsNullOrWhiteSpace(name))
                {
                    names.Add(name!);
                }
                return;
            }

            if (imagesNode is JsonArray arr)
            {
                foreach (var img in arr.OfType<JsonObject>())
                {
                    var name = img["image_name"]?.GetValue<string>()
                               ?? img["name"]?.GetValue<string>();
                    if (!string.IsNullOrWhiteSpace(name))
                    {
                        names.Add(name!);
                    }
                }
            }
        }

        if (resultsNode is JsonObject resultsObj)
        {
            foreach (var kvp in resultsObj)
            {
                ProcessNode(kvp.Value as JsonObject);
            }
        }
        else if (resultsNode is JsonArray resultsArr)
        {
            foreach (var item in resultsArr.OfType<JsonObject>())
            {
                ProcessNode(item);
            }
        }

        return names;
    }
}
