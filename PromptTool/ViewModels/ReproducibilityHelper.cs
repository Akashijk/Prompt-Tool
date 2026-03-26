using System;
using PromptTool.Core.Models;

namespace PromptTool.ViewModels;

public static class ReproducibilityHelper
{
    public static string GetReplayHealth(HistoryImage? image)
    {
        if (HasUsableGraphJson(image?.GenerationGraphJson))
        {
            return "Exact";
        }

        if (HasGenerationParams(image))
        {
            return "Likely";
        }

        return "Risky";
    }

    public static string GetReplayHealthLabel(HistoryImage? image)
    {
        return $"Replay {GetReplayHealth(image)}";
    }

    public static bool HasUsableGraphJson(string? json)
    {
        if (string.IsNullOrWhiteSpace(json))
        {
            return false;
        }

        var trimmed = json.Trim();
        if (string.Equals(trimmed, "null", StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        return trimmed.StartsWith("{", StringComparison.Ordinal) &&
               trimmed.Contains("\"nodes\"", StringComparison.OrdinalIgnoreCase) &&
               trimmed.Contains("\"edges\"", StringComparison.OrdinalIgnoreCase);
    }

    public static bool HasGenerationParams(HistoryImage? image)
    {
        if (image?.GenerationParams != null)
        {
            return true;
        }

        if (string.IsNullOrWhiteSpace(image?.GenerationParamsJson))
        {
            return false;
        }

        return !string.Equals(image.GenerationParamsJson.Trim(), "null", StringComparison.OrdinalIgnoreCase);
    }
}
