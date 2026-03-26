using System;
using System.Collections.Generic;

namespace PromptTool.Core.Models;

public class HistoryEntry
{
    public string Id { get; set; } = Guid.NewGuid().ToString();
    public DateTime Timestamp { get; set; } = DateTime.Now;
    public string OriginalPrompt { get; set; } = string.Empty;
    public string ProcessedPrompt { get; set; } = string.Empty; // The prompt sent to Ollama/InvokeAI
    public string OllamaModel { get; set; } = string.Empty; // The Ollama model used for text generation
    public string? TemplateName { get; set; }
    public byte[]? GeneratedImageBytes { get; set; } // For image generation results (transient, not persisted)
    public string? ImageFilePath { get; set; } // Path to image saved to disk (absolute or relative)
    public InvokeAIGenerationParams? ImageParameters { get; set; } // For image generation parameters
    public string? InvokeAIModel { get; set; } // The InvokeAI model used for image generation
    public Dictionary<string, string>? Context { get; set; } // Any other relevant context
    public bool IsFavorite { get; set; }

    // Legacy/compatibility fields from the Qt app
    public string? Status { get; set; }
    public string? EnhancedPrompt { get; set; }
    public Dictionary<string, string>? VariationPrompts { get; set; }
    public string? Workflow { get; set; }
    public string? CoverImagePath { get; set; }
    public bool IsExperimentRun { get; set; }
    public string? ExperimentType { get; set; }
    public string? ExperimentVariable { get; set; }
    public string? ExperimentHeaderPrompt { get; set; }
    public Dictionary<string, string>? ExperimentLockedChoices { get; set; }
    public int? ExperimentPlannedCount { get; set; }
    public string? ExperimentNotes { get; set; }
    public string? ParentEntryId { get; set; }
    public string? ParentImagePath { get; set; }
    public string? LineageRunId { get; set; }
    public string? LineageType { get; set; }

    // Aggregated images (original/enhanced/variations). Kept separate from ImageFilePath
    // to support multiple images per entry and the Qt JSONL history format.
    public List<HistoryImage> Images { get; set; } = new();
}

public class HistoryImage
{
    public string? ImagePath { get; set; } // Relative to history dir when possible
    public byte[]? ImageBytes { get; set; } // Transient
    public InvokeAIGenerationParams? GenerationParams { get; set; }
    public string? GenerationParamsJson { get; set; } // Raw JSON from legacy format
    public string? GenerationGraphJson { get; set; } // Raw InvokeAI graph JSON for exact replay
    public bool IsFavorite { get; set; }
    public string? PromptType { get; set; } // Original/Enhanced/Variation:Name/etc
    public string? PromptTypeSuffix { get; set; } // Upscale info or other annotation
    public string? Prompt { get; set; }
    public string? Workflow { get; set; }
    public double? AestheticScore { get; set; }
    public string? AestheticScoreModel { get; set; }
    public DateTime? AestheticScoreTimestamp { get; set; }
    public int? AestheticScoreMs { get; set; }
    public double? HeuristicScore { get; set; }
    public double? SharpnessScore { get; set; }
    public double? PromptMatchScore { get; set; }
    public double? CompositeScore { get; set; }
    public int? GenerationDurationMs { get; set; }
    public int? QueueWaitMs { get; set; }
    public int? TotalDurationMs { get; set; }
    public string? GenerationStatus { get; set; }
    public string? ErrorType { get; set; }
    public string? ErrorMessage { get; set; }
    public string? ErrorTraceback { get; set; }
    public string? UpscaleModel { get; set; }
    public double? UpscaleScale { get; set; }
    public int? UpscaleTileSize { get; set; }
    public bool? UpscaleFitToMultipleOf8 { get; set; }
    public string? UpscaleSourceImagePath { get; set; }
    public string? DerivedFromImagePath { get; set; }
    public string? ExperimentVariantLabel { get; set; }
    public string? ExperimentVariantValue { get; set; }
    public int? ExperimentVariantIndex { get; set; }
}
