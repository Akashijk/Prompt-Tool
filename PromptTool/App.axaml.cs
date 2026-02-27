using Avalonia;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Markup.Xaml;
using PromptTool.Core.Clients; // Added
using PromptTool.Core.Services;
using PromptTool.ViewModels;
using PromptTool.Views;
using System;
using System.IO;
using System.Net.Http; // Added
using Avalonia.Media;
using Avalonia.Platform;
using Avalonia.Controls;
using System.Linq; // Added
using PromptTool.Services;
using PromptTool.Core.Config;

namespace PromptTool
{
    public partial class App : Application
    {
        private static readonly ThemePalette DarkPalette = new()
        {
            BaseBackground = Color.Parse("#0E1524"),
            CardBackground = Color.Parse("#162035"),
            BorderColor = Color.Parse("#24304A"),
            AccentColor = Color.Parse("#4CC9F0"),
            TextPrimary = Color.Parse("#E8EDF5"),
            TextSecondary = Color.Parse("#A7B3C9")
        };

        private static readonly ThemePalette LightPalette = new()
        {
            BaseBackground = Color.Parse("#F4F6FB"),
            CardBackground = Color.Parse("#FFFFFF"),
            BorderColor = Color.Parse("#CCD3E2"),
            AccentColor = Color.Parse("#3366FF"),
            TextPrimary = Color.Parse("#0B1628"),
            TextSecondary = Color.Parse("#4A5B74")
        };

        public WildcardService? WildcardService { get; private set; }
        public PromptProcessorService? PromptProcessorService { get; private set; }
        public TemplateService? TemplateService { get; private set; }
        public ModelUsageTracker ModelUsageTracker { get; private set; } = new();
        public SystemPromptService? SystemPromptService { get; private set; }
        // Declare other services
        public SettingsService? SettingsService { get; private set; }
        public OllamaClient? OllamaClient { get; private set; }
        public InvokeAIClient? InvokeAIClient { get; private set; }
        public HistoryManagerService? HistoryManagerService { get; private set; }
        public KpiStatsService? KpiStatsService { get; private set; }
        public NotificationService NotificationService { get; private set; } = new();


        public override void Initialize()
        {
            AvaloniaXamlLoader.Load(this);
        }

        public override void OnFrameworkInitializationCompleted()
        {
            // Instantiating SettingsService early to be available for verbose checks.
            SettingsService = new SettingsService(); // Settings are loaded in the constructor
            var settings = SettingsService ?? throw new InvalidOperationException("SettingsService failed to initialize.");

            // Check for verbose command-line arguments
            var args = (ApplicationLifetime as IClassicDesktopStyleApplicationLifetime)?.Args;
            if (args != null && (args.Contains("--verbose", StringComparer.OrdinalIgnoreCase) || args.Contains("-v", StringComparer.OrdinalIgnoreCase)))
            {
                settings.Settings.Verbose = true;
            }
            PerfLogger.Enabled = settings.Settings.Verbose; // Set PerfLogger.Enabled based on potentially overridden verbose setting

            if (settings.Settings.Verbose) Console.WriteLine("App: OnFrameworkInitializationCompleted started.");

            // Determine the wildcards directory path
            var baseDirectory = AppContext.BaseDirectory;
            // For `dotnet run --project PromptTool/PromptTool.csproj`, baseDirectory is `PromptTool/`
            // We want `Prompt_Tool_CSharp/wildcards`
            // So, go up one level from PromptTool/ to Prompt_Tool_CSharp/, then into wildcards/
            string wildcardsDirectory = Path.Combine(baseDirectory, "..", "wildcards"); // Corrected path
            wildcardsDirectory = Path.GetFullPath(wildcardsDirectory); // Normalize the path

            if (!Directory.Exists(wildcardsDirectory))
            {
                if (settings.Settings.Verbose) Console.WriteLine($"App: Wildcards directory not found at resolved path: {wildcardsDirectory}");
            }
            else
            {
                if (settings.Settings.Verbose) Console.WriteLine($"App: Resolved wildcards directory: {wildcardsDirectory}");
            }

            // Apply theme preference
            var theme = string.IsNullOrWhiteSpace(settings.Settings.Theme)
                ? "dark"
                : settings.Settings.Theme.ToLowerInvariant();

            RequestedThemeVariant = theme switch
            {
                "dark" => Avalonia.Styling.ThemeVariant.Dark,
                "light" => Avalonia.Styling.ThemeVariant.Light,
                "system" => Avalonia.Styling.ThemeVariant.Default,
                _ => Avalonia.Styling.ThemeVariant.Dark
            };
            ApplyThemeResources(theme);

            // Use SettingsService to get the correct wildcard directories
            var wildcardDirs = settings.GetWildcardDirs();
            foreach(var dir in wildcardDirs)
            {
                if (!Directory.Exists(dir))
                {
                    if (settings.Settings.Verbose) Console.WriteLine($"App: Wildcards directory from settings not found: {dir}");
                }
                else
                {
                    if (settings.Settings.Verbose) Console.WriteLine($"App: Resolved wildcards directory from settings: {dir}");
                }
            }
            if (settings.Settings.Verbose) Console.WriteLine("App: Instantiating WildcardService...");
            WildcardService = new WildcardService(wildcardDirs, settings);
            if (settings.Settings.Verbose) Console.WriteLine("App: WildcardService instantiated.");

            if (settings.Settings.Verbose) Console.WriteLine("App: Instantiating PromptProcessorService...");
            PromptProcessorService = new PromptProcessorService(WildcardService, settings);
            if (settings.Settings.Verbose) Console.WriteLine("App: PromptProcessorService instantiated.");

            if (settings.Settings.Verbose) Console.WriteLine("App: Instantiating TemplateService...");
            TemplateService = new TemplateService(settings);
            if (settings.Settings.Verbose) Console.WriteLine("App: TemplateService instantiated.");

            if (settings.Settings.Verbose) Console.WriteLine("App: Instantiating SystemPromptService...");
            SystemPromptService = new SystemPromptService(settings);
            if (settings.Settings.Verbose) Console.WriteLine("App: SystemPromptService instantiated.");

            if (settings.Settings.Verbose) Console.WriteLine("App: Instantiating HttpClient...");
            var httpClient = new HttpClient();
            if (settings.Settings.InvokeAITimeoutSeconds > 0)
            {
                httpClient.Timeout = TimeSpan.FromSeconds(settings.Settings.InvokeAITimeoutSeconds);
            }
            if (settings.Settings.Verbose) Console.WriteLine("App: HttpClient instantiated.");

            if (settings.Settings.Verbose) Console.WriteLine("App: Instantiating OllamaClient...");
            OllamaClient = new OllamaClient(httpClient, settings); // Assuming HttpClient is sufficient
            // Configure BaseAddress for OllamaClient
            if (!string.IsNullOrWhiteSpace(settings.Settings.OllamaBaseUrl))
            {
                OllamaClient.UpdateBaseAddress(new Uri(settings.Settings.OllamaBaseUrl));
                if (settings.Settings.Verbose) Console.WriteLine($"App: OllamaClient BaseAddress set to {settings.Settings.OllamaBaseUrl}");
            }
            else
            {
                if (settings.Settings.Verbose) Console.WriteLine("App: OllamaBaseUrl is not configured in settings.");
            }
            if (settings.Settings.Verbose) Console.WriteLine("App: OllamaClient instantiated.");

            if (settings.Settings.Verbose) Console.WriteLine("App: Instantiating InvokeAIClient...");
            InvokeAIClient = new InvokeAIClient(httpClient, settings); // Assuming HttpClient is sufficient
            // Configure BaseAddress for InvokeAIClient as well
            if (!string.IsNullOrWhiteSpace(settings.Settings.InvokeAIBaseUrl))
            {
                InvokeAIClient.UpdateBaseAddress(new Uri(settings.Settings.InvokeAIBaseUrl));
                if (settings.Settings.Verbose) Console.WriteLine($"App: InvokeAIClient BaseAddress set to {settings.Settings.InvokeAIBaseUrl}");
            }
            else
            {
                if (settings.Settings.Verbose) Console.WriteLine("App: InvokeAIBaseUrl is not configured in settings.");
            }
            if (settings.Settings.Verbose) Console.WriteLine("App: InvokeAIClient instantiated.");

            if (settings.Settings.Verbose) Console.WriteLine("App: Instantiating HistoryManagerService...");
            HistoryManagerService = new HistoryManagerService(settings); // Needs SettingsService
            if (settings.Settings.Verbose) Console.WriteLine("App: HistoryManagerService instantiated.");

            if (settings.Settings.Verbose) Console.WriteLine("App: Instantiating KpiStatsService...");
            KpiStatsService = new KpiStatsService(settings);
            if (settings.Settings.Verbose) Console.WriteLine("App: KpiStatsService instantiated.");

            if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
            {
                if (settings.Settings.Verbose) Console.WriteLine("App: Setting up MainWindow (PromptWindow)...");
                var viewModel = new MainWindowViewModel(
                    PromptProcessorService,
                    WildcardService,
                    SettingsService,
                    SystemPromptService,
                    OllamaClient,
                    InvokeAIClient,
                    HistoryManagerService,
                    KpiStatsService,
                    TemplateService,
                    ModelUsageTracker,
                    NotificationService
                );
                var mainWindow = new PromptWindow(settings.Settings)
                {
                    DataContext = viewModel,
                    Icon = LoadAppIcon()
                };
                desktop.MainWindow = mainWindow;
                NotificationService.Attach(desktop.MainWindow);
                desktop.Exit += (_, __) =>
                {
                    viewModel.CancelActiveGeneration();
                    viewModel.DisposeCaches();
                };
                // Get the ViewModel instance and call its InitializeAsync method
                _ = viewModel.InitializeAsync(); // Fire and forget, or await if blocking is acceptable
                if (settings.Settings.Verbose) Console.WriteLine("App: MainWindow (PromptWindow) setup complete.");
            }

            base.OnFrameworkInitializationCompleted();
            if (settings.Settings.Verbose) Console.WriteLine("App: OnFrameworkInitializationCompleted finished.");
        }


        public static void ApplyThemeResources(string themeName)
        {
            var app = Current;
            if (app == null) return;
            var palette = (themeName ?? "").ToLowerInvariant() switch
            {
                "light" => LightPalette,
                _ => DarkPalette
            };

            app.Resources["BaseBackground"] = palette.BaseBackground;
            app.Resources["CardBackground"] = palette.CardBackground;
            app.Resources["BorderColor"] = palette.BorderColor;
            app.Resources["AccentColor"] = palette.AccentColor;
            app.Resources["TextPrimary"] = palette.TextPrimary;
            app.Resources["TextSecondary"] = palette.TextSecondary;

            app.Resources["BaseBackgroundBrush"] = new SolidColorBrush(palette.BaseBackground);
            app.Resources["CardBackgroundBrush"] = new SolidColorBrush(palette.CardBackground);
            app.Resources["BorderBrushStrong"] = new SolidColorBrush(palette.BorderColor);
            app.Resources["AccentBrush"] = new SolidColorBrush(palette.AccentColor);
            app.Resources["TextPrimaryBrush"] = new SolidColorBrush(palette.TextPrimary);
            app.Resources["TextSecondaryBrush"] = new SolidColorBrush(palette.TextSecondary);
        }

        private record ThemePalette
        {
            public Color BaseBackground { get; init; }
            public Color CardBackground { get; init; }
            public Color BorderColor { get; init; }
            public Color AccentColor { get; init; }
            public Color TextPrimary { get; init; }
            public Color TextSecondary { get; init; }
        }

        private WindowIcon? LoadAppIcon()
        {
            try
            {
                var uri = new Uri("avares://PromptTool/Assets/Icon.png");
                var stream = AssetLoader.Open(uri);
                return new WindowIcon(stream);
            }
            catch (Exception ex)
            {
                if (SettingsService?.Settings.Verbose == true) Console.WriteLine($"App: Failed to load icon: {ex.Message}");
                return null;
            }
        }
    }
}
