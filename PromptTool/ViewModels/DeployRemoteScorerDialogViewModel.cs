using System;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using PromptTool.Core.Services;
using PromptTool.Services;
using Avalonia.Media;

namespace PromptTool.ViewModels;

public partial class DeployRemoteScorerDialogViewModel : ObservableObject
{
    private readonly SettingsService _settingsService;
    private readonly RemoteScorerDeploymentService _deploymentService;
    private readonly StringBuilder _logBuilder = new();
    private readonly object _logLock = new();
    private const int MaxLogLength = 20000;
    private CancellationTokenSource? _deployCts;

    [ObservableProperty] private string _host = "";
    [ObservableProperty] private int _port = 22;
    [ObservableProperty] private string _username = "";
    [ObservableProperty] private RemoteScorerDeploymentService.AuthType _authType = RemoteScorerDeploymentService.AuthType.KeyFile;
    [ObservableProperty] private string _keyFilePath = "";
    [ObservableProperty] private string _password = "";
    [ObservableProperty] private string _installDir = "~/prompttool-aesthetic";
    [ObservableProperty] private int _exposedPort = 7861;
    [ObservableProperty] private bool _enableRocm = true;
    [ObservableProperty] private string _outputLog = "";
    [ObservableProperty] private string _manualInstructions = "";
    [ObservableProperty] private string _statusMessage = "";
    [ObservableProperty] private IBrush _statusBrush = Brushes.Transparent;

    public bool IsKeyAuth => AuthType == RemoteScorerDeploymentService.AuthType.KeyFile;
    public bool IsPasswordAuth => AuthType == RemoteScorerDeploymentService.AuthType.Password;
    public Array AuthTypes => Enum.GetValues(typeof(RemoteScorerDeploymentService.AuthType));

    public IAsyncRelayCommand DeployCommand { get; }
    public IAsyncRelayCommand TestConnectionCommand { get; }
    public IRelayCommand CloseCommand { get; }
    public IAsyncRelayCommand CopyManualCommand { get; }

    public Func<string, Task>? CopyToClipboardAsync { get; set; }
    public event EventHandler<bool?>? RequestClose;

    public DeployRemoteScorerDialogViewModel(SettingsService settingsService, RemoteScorerDeploymentService deploymentService)
    {
        _settingsService = settingsService;
        _deploymentService = deploymentService;

        DeployCommand = new AsyncRelayCommand(DeployAsync);
        TestConnectionCommand = new AsyncRelayCommand(TestConnectionAsync);
        CloseCommand = new RelayCommand(() => RequestClose?.Invoke(this, false));
        CopyManualCommand = new AsyncRelayCommand(CopyManualAsync);

        RefreshManualInstructions();
    }

    partial void OnAuthTypeChanged(RemoteScorerDeploymentService.AuthType value)
    {
        OnPropertyChanged(nameof(IsKeyAuth));
        OnPropertyChanged(nameof(IsPasswordAuth));
    }

    partial void OnHostChanged(string value) => RefreshManualInstructions();
    partial void OnInstallDirChanged(string value) => RefreshManualInstructions();
    partial void OnExposedPortChanged(int value) => RefreshManualInstructions();
    partial void OnEnableRocmChanged(bool value) => RefreshManualInstructions();

    private async Task DeployAsync()
    {
        StatusMessage = "";
        StatusBrush = Brushes.Transparent;
        _deployCts?.Cancel();
        _deployCts = new CancellationTokenSource();
        var options = BuildOptions();

        if (string.IsNullOrWhiteSpace(options.Host) || string.IsNullOrWhiteSpace(options.Username))
        {
            StatusMessage = "Host and Username are required.";
            StatusBrush = Brushes.Tomato;
            return;
        }

        if (options.AuthType == RemoteScorerDeploymentService.AuthType.KeyFile && string.IsNullOrWhiteSpace(options.KeyFilePath))
        {
            StatusMessage = "Key file path is required for key authentication.";
            StatusBrush = Brushes.Tomato;
            return;
        }

        if (options.AuthType == RemoteScorerDeploymentService.AuthType.Password && string.IsNullOrWhiteSpace(options.Password))
        {
            StatusMessage = "Password is required for password authentication.";
            StatusBrush = Brushes.Tomato;
            return;
        }

        try
        {
            AppendLog("Starting deployment...");
            await Task.Run(() => _deploymentService.DeployAsync(options, CreateLogger(), _deployCts.Token));
            _settingsService.Settings.AestheticScoringBackend = "remote";
            _settingsService.Settings.AestheticScoringRemoteUrl = $"http://{options.Host}:{options.ExposedPort}";
            await _settingsService.SaveSettingsAsync(_settingsService.Settings);
            AppendLog("Settings updated for remote scoring.");
            StatusMessage = "Deployment succeeded. Remote scoring enabled.";
            StatusBrush = Brushes.SeaGreen;
        }
        catch (Exception ex)
        {
            AppendLog($"Error: {ex.Message}");
            StatusMessage = ex.Message;
            StatusBrush = Brushes.Tomato;
        }
    }

    private async Task TestConnectionAsync()
    {
        StatusMessage = "";
        StatusBrush = Brushes.Transparent;
        _deployCts?.Cancel();
        _deployCts = new CancellationTokenSource();
        var options = BuildOptions();
        if (string.IsNullOrWhiteSpace(options.Host) || string.IsNullOrWhiteSpace(options.Username))
        {
            StatusMessage = "Host and Username are required.";
            StatusBrush = Brushes.Tomato;
            return;
        }
        if (options.AuthType == RemoteScorerDeploymentService.AuthType.KeyFile && string.IsNullOrWhiteSpace(options.KeyFilePath))
        {
            StatusMessage = "Key file path is required for key authentication.";
            StatusBrush = Brushes.Tomato;
            return;
        }
        if (options.AuthType == RemoteScorerDeploymentService.AuthType.Password && string.IsNullOrWhiteSpace(options.Password))
        {
            StatusMessage = "Password is required for password authentication.";
            StatusBrush = Brushes.Tomato;
            return;
        }
        try
        {
            AppendLog("Testing SSH connection...");
            await Task.Run(() => _deploymentService.TestConnectionAsync(options, CreateLogger(), _deployCts.Token));
            StatusMessage = "Connection successful.";
            StatusBrush = Brushes.SeaGreen;
        }
        catch (Exception ex)
        {
            AppendLog($"Error: {ex.Message}");
            StatusMessage = ex.Message;
            StatusBrush = Brushes.Tomato;
        }
    }

    private async Task CopyManualAsync()
    {
        if (CopyToClipboardAsync == null) return;
        await CopyToClipboardAsync(ManualInstructions);
    }

    private RemoteScorerDeploymentService.DeployOptions BuildOptions()
    {
        return new RemoteScorerDeploymentService.DeployOptions
        {
            Host = Host.Trim(),
            Port = Port,
            Username = Username.Trim(),
            AuthType = AuthType,
            KeyFilePath = KeyFilePath,
            Password = Password,
            InstallDir = string.IsNullOrWhiteSpace(InstallDir) ? "~/prompttool-aesthetic" : InstallDir.Trim(),
            ExposedPort = ExposedPort,
            EnableRocm = EnableRocm
        };
    }

    private void RefreshManualInstructions()
    {
        ManualInstructions = _deploymentService.BuildManualInstructions(BuildOptions());
    }

    private IProgress<string> CreateLogger()
    {
        return new Progress<string>(AppendLog);
    }

    private void AppendLog(string message)
    {
        lock (_logLock)
        {
            _logBuilder.AppendLine(message);
            if (_logBuilder.Length > MaxLogLength)
            {
                _logBuilder.Remove(0, _logBuilder.Length - MaxLogLength);
            }
            OutputLog = _logBuilder.ToString();
        }
    }
}
