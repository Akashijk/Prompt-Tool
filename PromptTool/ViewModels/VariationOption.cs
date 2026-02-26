using CommunityToolkit.Mvvm.ComponentModel;
using PromptTool.Core.Models;

namespace PromptTool.ViewModels;

public partial class VariationOption : ObservableObject
{
    public VariationPrompt Definition { get; }

    [ObservableProperty] private bool _isSelected = true;

    public string Key => Definition.Key;
    public string Name => Definition.Name;
    public string Description => Definition.Description;

    public VariationOption(VariationPrompt definition)
    {
        Definition = definition;
    }
}
