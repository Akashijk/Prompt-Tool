namespace PromptTool.Core.Config;

public class AppSettings
{
    public string OllamaBaseUrl { get; set; } = "http://localhost:11434";
    public string InvokeAIBaseUrl { get; set; } = "http://127.00.1:9090";

    // User-tunable workflow and UI preferences
    public string Workflow { get; set; } = "sfw";
    public string Theme { get; set; } = "dark";
    public int FontSize { get; set; } = 11;
    public int InvokeAITimeoutSeconds { get; set; } = 300;
    public string? DefaultOllamaModel { get; set; }
    public string AestheticScoringBackend { get; set; } = "local";
    public string AestheticScoringRemoteUrl { get; set; } = "";
    public int AestheticScoringRemoteBatchSize { get; set; } = 8;
    public string AestheticScoringModelPath { get; set; } = "";
    public string HuggingFaceApiKey { get; set; } = "";
    public string HuggingFaceApiKeyEncrypted { get; set; } = "";
    public bool EnableHeuristicScoring { get; set; } = false;
    public string DefaultNegativePrompt { get; set; } = "ugly, deformed, bad quality, cartoon, 3d, disfigured, bad anatomy";
    public Dictionary<string, string> NegativePromptPresets { get; set; } = new();
    public string DefaultNegativePromptKey { get; set; } = "standard";
    public string EnhancementSystemPrompt { get; set; } = "";
    public string? DefaultScheduler { get; set; } = "dpmpp_2m_k";
    public int DefaultSteps { get; set; } = 30;
    public double DefaultCfgScale { get; set; } = 7.5;
    public double DefaultCfgRescaleMultiplier { get; set; } = 0.0;
    public int DefaultWidth { get; set; } = 1024;
    public int DefaultHeight { get; set; } = 1024;
    public bool DefaultSaveToGallery { get; set; } = false;
    public string DefaultBaseModelType { get; set; } = "sdxl";
    public bool AutoClearInvokeCacheBetweenModels { get; set; } = true;
    public bool Verbose { get; set; } = false;
    public Dictionary<string, GenerationDefaultsSettings> GenerationDefaults { get; set; } = new();
    public Dictionary<string, ModelDefaultSettings> ModelDefaults { get; set; } = new();
    public Dictionary<string, ModelDefaultSettings> LoraDefaults { get; set; } = new();
    public double MainWindowWidth { get; set; }
    public double MainWindowHeight { get; set; }
    public double MainWindowX { get; set; }
    public double MainWindowY { get; set; }
    public string MainWindowState { get; set; } = "Normal";
    public double AnalyticsWindowWidth { get; set; }
    public double AnalyticsWindowHeight { get; set; }
    public double AnalyticsWindowX { get; set; }
    public double AnalyticsWindowY { get; set; }
    public string AnalyticsWindowState { get; set; } = "Normal";
    public double HistoryViewerWindowWidth { get; set; }
    public double HistoryViewerWindowHeight { get; set; }
    public double HistoryViewerWindowX { get; set; }
    public double HistoryViewerWindowY { get; set; }
    public string HistoryViewerWindowState { get; set; } = "Normal";
    public double FavoritesViewerWindowWidth { get; set; }
    public double FavoritesViewerWindowHeight { get; set; }
    public double FavoritesViewerWindowX { get; set; }
    public double FavoritesViewerWindowY { get; set; }
    public string FavoritesViewerWindowState { get; set; } = "Normal";
    public double ImageGenerationDialogWidth { get; set; }
    public double ImageGenerationDialogHeight { get; set; }
    public double ImageGenerationDialogX { get; set; }
    public double ImageGenerationDialogY { get; set; }
    public string ImageGenerationDialogState { get; set; } = "Normal";
    public double WildcardManagerWindowWidth { get; set; }
    public double WildcardManagerWindowHeight { get; set; }
    public double WildcardManagerWindowX { get; set; }
    public double WildcardManagerWindowY { get; set; }
    public string WildcardManagerWindowState { get; set; } = "Normal";

    // File system layout (populated with defaults by SettingsService if left blank)
    public string TemplateBaseDir { get; set; } = "";
    public string WildcardDir { get; set; } = "";
    public string HistoryDir { get; set; } = "";
    public string SystemPromptBaseDir { get; set; } = "";
    public string CacheDir { get; set; } = "";
}

public class GenerationDefaultsSettings
{
    public string Scheduler { get; set; } = "dpmpp_2m_k";
    public int Steps { get; set; } = 30;
    public double CfgScale { get; set; } = 7.5;
    public double CfgRescaleMultiplier { get; set; } = 0.0;
    public int Width { get; set; } = 1024;
    public int Height { get; set; } = 1024;
    public bool SaveToGallery { get; set; } = false;
}

public class ModelDefaultSettings
{
    public string ModelKey { get; set; } = "";
    public string ModelName { get; set; } = "";
    public string Scheduler { get; set; } = "dpmpp_2m_k";
    public int Steps { get; set; } = 30;
    public double CfgScale { get; set; } = 7.5;
    public double CfgRescaleMultiplier { get; set; } = 0.0;
    public int Width { get; set; } = 1024;
    public int Height { get; set; } = 1024;
    public string PositivePrefix { get; set; } = "";
    public string NegativePrefix { get; set; } = "";
}
